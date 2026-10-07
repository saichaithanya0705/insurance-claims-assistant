"""Upload a built corpus to the Synapt provider named in .env, one batch at a time.

Safe to re-run: every submitted batch is recorded in <corpus>/ledger.jsonl and skipped next time.
Each batch is submitted once (a timeout may follow a successful write, so it is never auto-retried).
Submission is asynchronous on Synapt's side, so after each batch the provider's document count is
polled until it grows (completion) before the next batch is sent.

    python scripts/synapt_ingest.py status
    python scripts/synapt_ingest.py ingest --max-batches 1            # pilot
    python scripts/synapt_ingest.py ingest --procedures               # also upload procedures
    python scripts/synapt_ingest.py verify --sample 20                # retrieval recall check
"""

import argparse
import asyncio
import hashlib
import json
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from claims.adapters import LiveSynaptAdapter, SynaptError
from claims.cards import (
    amount_band,
    claim_card_text,
    claim_ids_in_text,
    history_band,
    is_card_chunk,
)
from claims.dataset import ClaimsStore
from claims.settings import Settings


def read_ledger(path: Path) -> dict:
    if not path.exists():
        return {}
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {entry["path"]: entry for entry in entries}


async def stats(adapter: LiveSynaptAdapter, provider: str) -> dict:
    payload = await adapter.call_read_tool("trident_get_stats", {"provider_id": provider})
    result = payload.get("result", payload)
    return json.loads(result) if isinstance(result, str) else result


async def cards_in_provider(adapter, provider: str) -> int:
    """How many of the best-matching passages are already historical claim cards."""
    payload = await adapter.call_read_tool(
        "trident_get_chunks", {"provider_id": provider, "query": "Historical claim card.", "top_k": 20}
    )
    raw = payload.get("result", payload)
    chunks = json.loads(raw) if isinstance(raw, str) else raw
    chunks = chunks if isinstance(chunks, list) else chunks.get("chunks", [])
    return sum(is_card_chunk(c.get("text") or "") for c in chunks)


async def wait_for_growth(adapter, provider, before: int, timeout: float) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(5)
        current = await stats(adapter, provider)
        if current.get("doc_count", 0) > before:
            return current
    return None


async def ingest(args, settings, adapter):
    corpus = args.corpus
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    ledger_path = corpus / "ledger.jsonl"
    done = read_ledger(ledger_path)
    work = []
    if args.procedures:
        work += [(p, None) for p in manifest["procedures"]]
    work += [(b["path"], b["sha256"]) for b in manifest["batches"]]
    pending = [(p, sha) for p, sha in work if p not in done]
    if args.max_batches:
        pending = pending[: args.max_batches]
    print(f"{len(done)} already submitted; {len(pending)} to submit now (dry run: {args.dry_run})")
    if pending and not done and not args.dry_run and not args.force:
        # A fresh clone has no local ledger, but the provider is shared by every machine.
        existing = await cards_in_provider(adapter, settings.synapt_provider_id)
        if existing:
            raise SystemExit(
                f"Provider {settings.synapt_provider_id} already contains historical claim cards "
                f"({existing} of the top 20 passages). Uploading again would duplicate them. "
                "Use `status`/`verify` to inspect it, or pass --force to upload anyway."
            )
    chunking = (
        {"chunk_size": args.chunk_size, "chunk_overlap": args.chunk_overlap}
        if args.chunk_size
        else None
    )
    for path, expected in pending:
        text = (corpus / path).read_text(encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if expected and digest != expected:
            raise SystemExit(f"{path} changed since the manifest was written; rebuild the corpus")
        if args.dry_run:
            print(f"  would submit {path} ({len(text.encode('utf-8')):,} bytes)")
            continue
        before = (await stats(adapter, settings.synapt_provider_id)).get("doc_count", 0)
        try:
            result = await adapter.ingest(text, Path(path).name, chunking=chunking)
        except SynaptError:
            # The write may have succeeded even though the response was lost; check before retrying.
            landed = await wait_for_growth(adapter, settings.synapt_provider_id, before, 120)
            if not landed:
                raise SystemExit(
                    f"{path}: submission failed and the provider's document count did not grow; "
                    "nothing was recorded. Re-run to retry this batch."
                ) from None
            result = {"req_id": None, "response_keys": ["response lost; landing verified from stats"]}
        entry = {
            "path": path,
            "sha256": digest,
            "req_id": result.get("req_id"),
            "response_keys": result.get("response_keys"),
            "submitted_at": datetime.now(UTC).isoformat(),
            "docs_before": before,
        }
        with ledger_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry) + "\n")
        grown = await wait_for_growth(adapter, settings.synapt_provider_id, before, args.wait)
        print(
            f"  {path}: submitted req_id={result.get('req_id')}; "
            + (
                f"extracted (docs {before} -> {grown['doc_count']}, chunks {grown.get('chunks')})"
                if grown
                else f"NOT yet extracted after {args.wait:.0f}s; re-check with `status`"
            )
        )
        if not grown:
            raise SystemExit("Stopping: wait for extraction to finish before submitting more.")
        await asyncio.sleep(args.delay)


async def verify(args, settings, adapter):
    """Semantic precision: do the cards Synapt returns for a claim resemble that claim?

    For sampled ingested claims, a card-shaped query asks Synapt for similar cards. Each returned
    card is joined back to the Parquet row and compared with the query claim (claim type, state,
    amount band, history band). A random pair of corpus cards gives the chance baseline. Identity
    is deliberately not tested: many cards share identical descriptors.
    """
    corpus = args.corpus
    ledger = read_ledger(corpus / "ledger.jsonl")
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    ids = [i for b in manifest["batches"] if b["path"] in ledger for i in b["claim_ids"]]
    if not ids:
        raise SystemExit("No submitted batches in the ledger yet.")
    rng = random.Random(7)
    sample = rng.sample(ids, min(args.sample, len(ids)))
    store = ClaimsStore(args.parquet)
    marks = ",".join("?" for _ in ids)
    corpus_rows = {
        r["claim_id"]: r
        for r in store.rows(f"SELECT * FROM {store.source} WHERE claim_id IN ({marks})", ids)
    }
    keys = {
        "claim type": lambda r: r["claim_type"],
        "state": lambda r: r["state"],
        "amount band": lambda r: amount_band(r["claim_amount"]),
        "prior-claims band": lambda r: history_band(r["previous_claims_count"]),
    }
    hits = {name: [] for name in keys}
    chance = {name: [] for name in keys}
    failures = 0
    try:
        for claim_id in sample:
            row = corpus_rows[claim_id]
            query = "Historical claim card. " + claim_card_text(
                row, include_outcome=False, masking_safe=True
            )
            try:
                payload = await adapter.call_read_tool(
                    "trident_get_chunks",
                    {"provider_id": settings.synapt_provider_id, "query": query,
                     "top_k": settings.synapt_case_top_k},
                )
            except SynaptError:
                failures += 1  # one transient failure must not abort the whole check
                continue
            raw = payload.get("result", payload)
            chunks = json.loads(raw) if isinstance(raw, str) else raw
            chunks = chunks if isinstance(chunks, list) else chunks.get("chunks", [])
            returned = list(
                dict.fromkeys(
                    cid
                    for c in chunks
                    if is_card_chunk(c.get("text") or "")
                    for cid in claim_ids_in_text(c["text"])
                )
            )
            matched = [corpus_rows[cid] for cid in returned if cid in corpus_rows]
            if not matched:
                continue
            others = rng.sample(list(corpus_rows.values()), len(matched))
            for name, key in keys.items():
                hits[name].append(sum(key(m) == key(row) for m in matched) / len(matched))
                chance[name].append(sum(key(o) == key(row) for o in others) / len(others))
    finally:
        store.close()
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None
    report = {
        "queries": len(sample) - failures,
        "failed_queries": failures,
        "cards_returned_per_query": settings.synapt_case_top_k,
        "share_of_returned_cards_matching_the_query_claim": {
            name: {"synapt": mean(hits[name]), "random_pair": mean(chance[name])} for name in keys
        },
    }
    print(json.dumps(report, indent=2))



async def main(args):
    settings = Settings()
    if settings.synapt_mode != "live":
        raise SystemExit("Set SYNAPT_MODE=live (and credentials/provider) in .env first.")
    adapter = LiveSynaptAdapter(settings)
    if args.command == "status":
        current = await stats(adapter, settings.synapt_provider_id)
        ledger = read_ledger(args.corpus / "ledger.jsonl")
        print(json.dumps({"provider": settings.synapt_provider_id, "stats": current,
                          "ledger_batches": len(ledger)}, indent=2))
    elif args.command == "ingest":
        await ingest(args, settings, adapter)
    else:
        await verify(args, settings, adapter)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("command", choices=["status", "ingest", "verify"])
    parser.add_argument("--corpus", type=Path, default=Path("artifacts/synapt/corpus-v3"))
    parser.add_argument("--max-batches", type=int, default=0, help="0 = all remaining")
    parser.add_argument("--procedures", action="store_true", help="also upload the 5 procedures")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="upload even if cards already exist")
    parser.add_argument("--wait", type=float, default=300, help="seconds to wait per batch")
    parser.add_argument("--delay", type=float, default=3, help="seconds between batches")
    parser.add_argument("--chunk-size", type=int, default=0, help="0 = provider default")
    parser.add_argument("--chunk-overlap", type=int, default=0)
    parser.add_argument("--sample", type=int, default=20)
    parser.add_argument(
        "--parquet", type=Path, default=Path("data/raw/parquet/insurance_claims_100M.parquet")
    )
    try:
        asyncio.run(main(parser.parse_args()))
    except SynaptError as exc:
        raise SystemExit(str(exc)) from None
