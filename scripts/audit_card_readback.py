"""Read uploaded claim cards back from Synapt and compare each with the card text we sent.

The graph check in `claims.synapt.inventory` cannot see Synapt's PII masking: lengths are recorded before
masking, so a card whose region token was rewritten still "verifies". Only reading a chunk back shows
what Synapt actually stored. This script does that: it queries the provider, finds every card body in the
returned chunks, and compares it with the local card (whitespace-normalised).

    SYNAPT_PROVIDER_ID=<provider> python scripts/audit_card_readback.py --corpus <dir> --cards 500

`--cards N` limits the audit to the first N cards of the corpus (a pilot). A store that holds only a few
hundred chunks returns everything for one query; a larger store is swept by querying with cards that have
not been read back yet. Read-only: nothing is written to Synapt.
"""

import argparse
import collections
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import duckdb

from claims.agents import access
from claims.core.settings import Settings
from claims.corpus.cards import claim_card_text, is_card_chunk
from claims.synapt.adapter import LiveSynaptAdapter, SynaptError

BODY = re.compile(r"claim_ref: (claimref_[a-j]+)\n(.*?)(?=\n\s*#{2,3} history:|\Z)", re.DOTALL)
MASK = re.compile(r"\[[A-Z_]+_[0-9a-f]{6,}\]")
REGION = re.compile(r"claim in (regionkey_\S+?)\.")


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def local_cards(corpus: Path, limit: int | None) -> list[dict]:
    cursor = duckdb.connect().execute(
        "SELECT * FROM read_parquet(?)", [str(corpus / "claim_cards.parquet")]
    )
    names = [d[0] for d in cursor.description]
    rows = [dict(zip(names, values)) for values in cursor.fetchall()]
    return rows[:limit] if limit else rows


def classify(stored: str, local: str) -> str:
    if stored == local:
        return "identical"
    if MASK.search(stored) and not MASK.search(local):
        region = REGION.search(stored)
        return "region_token_masked" if region is None or "[" in region.group(1) else "other_masked"
    if local.startswith(stored) and len(stored) < len(local):
        return "truncated"
    return "different"


async def chunks_for(adapter, provider, query, top_k):
    payload = await adapter.call_read_tool(
        "trident_get_chunks",
        {"provider_id": provider, "query": query, "top_k": top_k},
        max_response_chars=20_000_000,
    )
    raw = payload.get("result", payload)
    data = json.loads(raw) if isinstance(raw, str) else raw
    return data if isinstance(data, list) else data.get("chunks", [])


async def main(args):
    settings = Settings()
    provider = settings.synapt_provider_id
    print(f"provider: {provider}", flush=True)
    adapter = LiveSynaptAdapter(settings)
    rows = local_cards(args.corpus, args.cards)
    by_ref = {r["claim_ref"]: r for r in rows}
    payload = await adapter.call_read_tool("trident_get_stats", {"provider_id": provider})
    result = payload.get("result", payload)
    stats = json.loads(result) if isinstance(result, str) else result
    chunks_in_store = stats.get("chunks", 0)
    top_k = min(args.top_k, chunks_in_store + 100)
    print(f"local cards: {len(rows):,}; chunks in the store: {chunks_in_store:,}; top_k per query: {top_k:,}", flush=True)

    seen: dict[str, str] = {}
    stray: set[str] = set()
    outcomes = collections.Counter()
    examples = collections.defaultdict(list)
    rng = random.Random(args.seed)
    started, queries, failed, stalled = time.monotonic(), 0, 0, 0
    pending_query = "Historical claim card."
    while queries < args.max_queries and stalled < 5 and len(seen) < len(rows):
        try:
            chunks = await chunks_for(adapter, provider, pending_query, top_k)
        except SynaptError:
            failed += 1
            if failed > 5:
                raise
            continue
        queries += 1
        before = len(seen)
        for chunk in chunks:
            text = chunk.get("text") or ""
            if not is_card_chunk(text):
                continue
            for ref, body in BODY.findall(text):
                if ref not in by_ref:
                    stray.add(ref)
                    continue
                if ref in seen:
                    continue
                local = norm(by_ref[ref]["card_text"].split("\n", 1)[1])
                stored = norm(body)
                verdict = classify(stored, local)
                seen[ref] = verdict
                outcomes[verdict] += 1
                if verdict != "identical" and len(examples[verdict]) < 3:
                    examples[verdict].append({"ref": ref, "stored": stored[:400], "local": local[:400]})
        stalled = stalled + 1 if len(seen) == before else 0
        unread = [r for r in rows if r["claim_ref"] not in seen]
        if not unread:
            break
        row = rng.choice(unread)
        pending_query = "Historical claim card. " + claim_card_text(row, include_outcome=False, masking_safe=True)
    wrong = {k: v for k, v in outcomes.items() if k != "identical"}
    report = {
        "provider": provider,
        "local_cards": len(rows),
        "read_back": len(seen),
        "not_read_back": len(rows) - len(seen),
        "identical": outcomes["identical"],
        "not_identical": sum(wrong.values()),
        "by_outcome": dict(outcomes),
        "cards_in_store_that_are_not_in_this_corpus": len(stray),
        "queries": queries,
        "seconds": round(time.monotonic() - started, 1),
        "examples": examples,
    }
    target = args.corpus / "readback-audit.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "examples"}, indent=2))
    for verdict, items in examples.items():
        for item in items[:2]:
            print(f"\n{verdict} {item['ref']}\n  stored: {item['stored']}\n  local : {item['local']}")
    if report["not_identical"] or report["not_read_back"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--cards", type=int, default=0, help="audit only the first N cards (0 = all)")
    parser.add_argument("--top-k", type=int, default=1900)
    parser.add_argument("--max-queries", type=int, default=400)
    parser.add_argument("--seed", type=int, default=31)
    access.run_as("operator", main(parser.parse_args()))
