"""Measure Synapt retrieval with precision@k, recall@k, hit@k, MRR and nDCG@k.

    python scripts/evaluate_retrieval.py --output artifacts/evaluation/retrieval-2026-10-13.json

Read-only against the configured provider (passage search, graph search and walk, and `trident_query` with
`ticket_mode="only"`, which runs no model and records no episode). Three parts, defined in claims.evaluation.retrieval:

1. Procedures. For each hand-labelled query (RETRIEVAL_QUERIES) the two standard procedure reads an investigation makes: the
   passage search (`adapter.retrieve`) and the knowledge-graph lookup (`adapter.retrieve_graph`). Results are graded at document
   level against the SOPs the claim needs; a graph procedure counts as the SOP whose passage it was extracted from. The model
   follow-ups of a live investigation are not included: they only add to these.
2. Similar claims for the same queries. They are written for this test, so none is in the ticket store: precision@k is the
   share of returned past claims of the same claim type, nDCG is graded by banded attribute agreement.
3. Known item. Tickets from the uploaded workbook are sent back as queries: is each its own nearest neighbour (hit@1, MRR)?
   With the ticket itself removed, the rest are graded like part 2.
"""

import argparse
import asyncio
import json
import random
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.agents import access
from claims.core.schemas import ClaimInput
from claims.core.settings import Settings
from claims.corpus.builder import SOPS
from claims.corpus.cards import claim_alias
from claims.corpus.procedures import PROCEDURES
from claims.evaluation import retrieval as rm
from claims.synapt import knowledge_graph
from claims.synapt.adapter import LiveSynaptAdapter, ticket_examples

WORKBOOK = ROOT / "artifacts/synapt/ticketing-capstone1/claims_tickets_capstone1.xlsx"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
BATCH = 25  # the tool accepts at most 50 tickets per call
EMBEDDED = ("title", "description", "category", "region")


def read_workbook(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as z:
        shared = [si.find("m:t", NS).text or "" for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS)]
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = [
        [shared[int(c.find("m:v", NS).text)] if c.get("t") == "s" else float(c.find("m:v", NS).text) for c in row.findall("m:c", NS)]
        for row in sheet.find("m:sheetData", NS).findall("m:row", NS)
    ]
    return [dict(zip(rows[0], values, strict=True)) for values in rows[1:]]


def chunk_map(adapter: LiveSynaptAdapter) -> dict[str, str]:
    """Synapt chunk ID -> SOP, by searching for every SOP's title and reading the source_id header of what comes back."""
    found: dict[str, str] = {}
    titles = [title for _, title, _ in SOPS] + [p[1] for p in PROCEDURES]
    with access.acting_as("passage_retriever"):
        for title in titles:
            for item in adapter.passage_search(title, top_k=5):
                sop = rm.sop_in_text(item.text)
                if sop:
                    found[item.source_id] = sop
    return found


def hold_out_share(adapter: LiveSynaptAdapter) -> float | None:
    """The share of the ticket store Synapt keeps out of the neighbour pool, from `trident_get_stats`."""

    async def read():
        async with adapter._session() as session:
            result = await session.call_tool("trident_get_stats", arguments={"provider_id": adapter.settings.synapt_provider_id})
            return knowledge_graph.decode(result, adapter._redact)

    mining = (asyncio.run(read()) or {}).get("ticket_mining") or {}
    tickets, held = mining.get("tickets"), mining.get("held_out")
    return round(held / tickets, 4) if isinstance(tickets, int) and tickets and isinstance(held, int) else None


def mean_of(rows: list[dict], key: str):
    return rm.mean(r.get(key) for r in rows)


def summary(rows: list[dict], keys: tuple[str, ...]) -> dict:
    return {key: mean_of(rows, key) for key in keys}


def procedures_and_neighbours(adapter, chunks, by_alias):
    per_query = []
    for query in rm.RETRIEVAL_QUERIES:
        claim = ClaimInput.model_validate(query["claim"])
        needs = frozenset(query["needs"])
        started = time.perf_counter()
        bundle = adapter.retrieve(claim)
        graph = adapter.retrieve_graph(claim)
        seconds = round(time.perf_counter() - started, 1)
        passages = rm.dedupe(rm.sop_in_text(e.text) or chunks.get(e.source_id) for e in bundle.evidence)
        # What the brief receives: the passages behind a claim-specific graph procedure (claims.retrieval.graph.assemble_evidence).
        backed = knowledge_graph.backed_passages(graph["procedures"])
        in_evidence = rm.dedupe(
            rm.sop_in_text(e.text) or chunks.get(e.source_id)
            for e in bundle.evidence
            if not graph["procedures"] or e.source_id in backed
        )
        procedures = rm.dedupe(
            next((chunks[c] for c in record["source_chunk_ids"] if c in chunks), None) for record in graph["procedures"]
        )
        combined = set(in_evidence) | set(procedures)
        profile = rm.claim_profile(query["claim"])
        neighbours = [by_alias.get(claim_alias(cid)) for cid in bundle.semantic_claim_ids]
        neighbour_k = max(1, len(neighbours))
        per_query.append({
            "id": query["id"],
            "seconds": seconds,
            "passages": rm.score_sops(passages, needs),
            "passages_in_evidence": rm.score_sops(in_evidence, needs),
            "graph": rm.score_sops(procedures, needs) | {"graph_procedures": [r["name"] for r in graph["procedures"]]},
            "combined": {
                "recall": rm.recall_at_k(sorted(combined, key=str), needs, None),
                "precision": round(sum(rm.sop_grade(s, needs) > 0 for s in combined) / len(combined), 4) if combined else 0.0,
                "missed": sorted(needs - combined),
            },
            "similar_claims": rm.score_neighbours(profile, [None if n is None else rm.workbook_profile(n) for n in neighbours],
                                                  neighbour_k)
            | {"ids": bundle.semantic_claim_ids},
            "warnings": bundle.warnings,
        })
        print(f"{query['id']:<28} passages recall {per_query[-1]['passages']['recall']:.2f}  graph recall "
              f"{per_query[-1]['graph']['recall']:.2f}  similar same-type {per_query[-1]['similar_claims']['same_type_share']}"
              f"  ({seconds}s)")
    return per_query


async def known_items(adapter, sample: list[dict], by_alias) -> list[dict]:
    results = []
    async with adapter._session() as session:
        for start in range(0, len(sample), BATCH):
            batch = sample[start:start + BATCH]
            arguments = {
                "provider_id": adapter.settings.synapt_provider_id,
                "question": "Past claims like this one",
                "ticket_mode": "only",
                "tickets": [{key: row[key] for key in EMBEDDED} for row in batch],
            }
            for attempt in range(3):
                result = await session.call_tool("trident_query", arguments=arguments)
                try:
                    labels = knowledge_graph.decode(result, adapter._redact).get("ticket_labels")
                except (knowledge_graph.GraphError, AttributeError):
                    labels = None
                if isinstance(labels, list) and len(labels) == len(batch):
                    break
                print(f"batch {start}: attempt {attempt + 1} returned no usable ticket_labels")
            else:
                raise SystemExit("Synapt failed three times for one batch; nothing was measured")
            for row, item in zip(batch, labels, strict=True):
                ranked = ticket_examples(item) if isinstance(item, dict) and not item.get("error") else []
                others = [by_alias.get(alias) for alias in ranked if alias != row["ticket_id"]]
                profile = rm.workbook_profile(row)
                results.append({
                    "ticket_id": row["ticket_id"],
                    "category": row["category"],
                    "returned": ranked,
                    **rm.score_known_item(row["ticket_id"], ranked),
                    "others": rm.score_neighbours(profile, [None if o is None else rm.workbook_profile(o) for o in others],
                                                  max(1, len(others))),
                })
            print(f"known items {start + len(batch)}/{len(sample)}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--known-per-type", type=int, default=10, help="workbook tickets per claim type sent back as queries")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--skip-known-items", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    adapter = LiveSynaptAdapter(settings)
    workbook = read_workbook(WORKBOOK)
    by_alias = {row["ticket_id"]: row for row in workbook}
    started = datetime.now(UTC)

    chunks = chunk_map(adapter)
    print(f"mapped {len(chunks)} chunks to {len(set(chunks.values()))} of {len(rm.ALL_SOPS)} SOPs")
    per_query = procedures_and_neighbours(adapter, chunks, by_alias)

    known = []
    if not args.skip_known_items:
        rng = random.Random(args.seed)
        sample = []
        for kind in sorted({row["category"] for row in workbook}):
            of_kind = [row for row in workbook if row["category"] == kind]
            sample += rng.sample(of_kind, min(args.known_per_type, len(of_kind)))
        known = asyncio.run(known_items(adapter, sample, by_alias))

    sop_keys = (f"precision@{rm.K}", "precision", f"recall@{rm.K}", "recall", f"hit@{rm.K}", "mrr", f"ndcg@{rm.K}")
    report = {
        "generated_at": started.isoformat(),
        "provider": settings.synapt_provider_id,
        "k": rm.K,
        "synapt_top_k": settings.synapt_top_k,
        "queries": len(per_query),
        "mapped_chunks": len(chunks),
        "summary": {
            "procedures": {
                "passage_search": summary([q["passages"] for q in per_query], sop_keys),
                "passages_in_evidence": summary([q["passages_in_evidence"] for q in per_query], sop_keys),
                "knowledge_graph": summary([q["graph"] for q in per_query], sop_keys),
                "combined": summary([q["combined"] for q in per_query], ("precision", "recall")),
            },
            "similar_claims_new": summary(
                [q["similar_claims"] for q in per_query], ("returned", "same_type_share", "mean_agreement", "ndcg")
            ),
            "known_item": {
                "tickets": len(known),
                "hit@1": mean_of(known, "hit@1"),
                "found": rm.mean(float(r["found"]) for r in known),
                "mrr": mean_of(known, "rr"),
                "hit@1_when_found": mean_of([r for r in known if r["found"]], "hit@1"),
                "store_hold_out_share": hold_out_share(adapter),
                "others_same_type_share": mean_of([r["others"] for r in known], "same_type_share"),
                "others_mean_agreement": mean_of([r["others"] for r in known], "mean_agreement"),
                "others_ndcg": mean_of([r["others"] for r in known], "ndcg"),
            }
            if known
            else None,
        },
        "per_query": per_query,
        "known_items": known,
        "notes": [
            (
                "Procedure relevance is hand-labelled per query (claims.evaluation.retrieval.RETRIEVAL_QUERIES), not derived from "
                "the application's own applicability rule. Grade 2 = needed, 1 = general handling, 0 = another claim's procedure."
            ),
            (
                "precision@k divides by k, so a leg that returns fewer than k documents is penalised for the empty slots; "
                "'precision' is over what was returned."
            ),
            "The ticket leg returns one example per label value of each label field, not a top-k list, so its k is what it returned.",
            (
                "Synapt holds part of the ticket store out for its own accuracy scoring (store_hold_out_share). A held-out ticket "
                "is not a neighbour, so it cannot find itself: compare 'found' with 1 - store_hold_out_share, and read "
                "hit@1_when_found as the known-item score for tickets in the neighbour pool. Which tickets are held out is not exposed."
            ),
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
