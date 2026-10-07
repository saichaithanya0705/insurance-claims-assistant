"""Upload Parquet-derived card batches once, with crash-safe provider-bound bookkeeping.

Ambiguous writes are retained as unknown and reconciled by retrieving content; never
automatically resubmit a timed-out write. Provider count growth alone is not completion.

`--verify-only` checks every batch from Synapt's graph (document sizes and text spans, see
claims.synapt_inventory) against data/synapt/expected_inventory.json and records the result in the
local ledger. The retrieval check used while uploading (`verify_batch`) cannot confirm a batch once the
store holds more than a few thousand chunks, because the tenant returns at most ~1,900 chunks per query
and rejects a larger `top_k`. This provider is fully populated, so do not upload again.
"""

import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from claims.adapters import LiveSynaptAdapter, SynaptError
from claims.cards import claim_alias, claim_ids_in_text
from claims.settings import Settings
from claims.synapt_inventory import INVENTORY_PATH, load_expected, summary_lines, verify_store


def unwrap(payload):
    result = payload.get("result", payload)
    return json.loads(result) if isinstance(result, str) else result


def record(path, entry):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry | {"at": datetime.now(UTC).isoformat()}) + "\n")
        stream.flush()


def ledger_states(path, provider):
    states = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry["provider"] != provider:
                raise ValueError("Upload ledger belongs to a different provider")
            states[entry["path"]] = entry
    return states


async def provider_stats(adapter, provider):
    return unwrap(await adapter.call_read_tool("trident_get_stats", {"provider_id": provider}))


async def verify_batch(adapter, provider, batch):
    stats = await provider_stats(adapter, provider)
    payload = unwrap(await adapter.call_read_tool("trident_get_chunks", {
        "provider_id": provider,
        "query": batch["marker"] + " historical claim cards auto business home property renters "
                 "claimed amount band policyholder tenure prior claims filed incident outcome",
        "top_k": min(30000, stats.get("chunks", 0) + 100),
    }, max_response_chars=20_000_000))
    chunks = payload if isinstance(payload, list) else payload.get("chunks", [])
    wanted = set(batch["claim_ids"])
    returned = {cid for c in chunks for cid in claim_ids_in_text(c.get("text", ""))}
    found = wanted & returned
    sentinels = {claim_alias(cid) for cid in found} & set(batch["sentinels"])
    return {"readable_cards": len(found), "expected_cards": len(wanted),
            "sentinels_found": len(sentinels), "sentinels_expected": len(batch["sentinels"]),
            "verified": len(found) == len(wanted)}


async def reconcile(adapter, provider, selected, ledger, states):
    """Verify every tracked batch from Synapt's graph and record the outcome in the local ledger."""
    expected = load_expected(ROOT / INVENTORY_PATH)
    report = await verify_store(adapter, provider, expected)
    inventory_sha = {b["name"]: b["sha256"] for b in expected["expansion"]["batches"]}
    results = {b["name"]: b for b in report["expansion"]["batches"]}
    for batch in selected:
        name = Path(batch["path"]).name
        previous, result = states.get(batch["path"]), results.get(name)
        if not previous or result is None:
            continue
        if previous["sha256"] != batch["sha256"]:
            raise ValueError("Tracked batch differs from manifest")
        if inventory_sha.get(name) != batch["sha256"]:
            continue  # the committed inventory describes a different build of this batch
        if result["status"] == "verified" and previous["status"] != "verified":
            record(ledger, {"provider": provider, "path": batch["path"], "sha256": batch["sha256"],
                            "status": "verified", "verification": {"method": "graph", **result},
                            "stats": report["stats"]})
    (ledger.parent / "reconciliation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for mark, text in summary_lines(report):
        print(f"  [{mark}] {text}", flush=True)


async def main(args):
    settings = Settings()
    if settings.synapt_mode != "live":
        raise ValueError("Live configured Synapt access is required")
    provider = settings.synapt_provider_id
    adapter = LiveSynaptAdapter(settings)
    manifest = json.loads((args.corpus / "manifest.json").read_text(encoding="utf-8"))
    ledger = args.corpus / "upload-ledger.jsonl"
    states = ledger_states(ledger, provider)
    selected = manifest["batches"][:args.max_batches or None]
    if args.verify_only:
        await reconcile(adapter, provider, selected, ledger, states)
        return
    for batch in selected:
        identity = {"provider": provider, "path": batch["path"], "sha256": batch["sha256"]}
        previous = states.get(batch["path"])
        if previous and previous["sha256"] != batch["sha256"]:
            raise ValueError("Batch content differs from previously submitted content")
        if previous and previous["status"] == "verified":
            print(f"SKIP verified {batch['path']}", flush=True)
            continue
        retry = args.retry_rejected and previous and previous["status"] == "rejected"
        if args.submit_only and previous and not retry:
            print(f"TRACKED {batch['path']} ({previous['status']}); extraction remains unverified", flush=True)
            continue
        data = (args.corpus / batch["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != batch["sha256"]:
            raise ValueError("Batch hash does not match the manifest")
        before = await provider_stats(adapter, provider)
        if not previous or retry:
            adapter.last_ingest_rejection = None
            record(ledger, identity | {"status": "write_started", "docs_before": before["doc_count"]})
            print(f"SUBMIT {batch['path']} ({batch['cards']} cards; {len(data)} bytes)", flush=True)
            try:
                response = await adapter.ingest(data.decode("utf-8"), Path(batch["path"]).name,
                                               chunking={"chunk_size": 100, "chunk_overlap": 0},
                                               persistent=True)
                record(ledger, identity | {"status": "submitted", "response": response})
                previous = identity | {"status": "submitted"}
            except SynaptError as exc:
                rejection = getattr(adapter, "last_ingest_rejection", None)
                rejected = rejection and rejection.get("accepted") is False
                record(ledger, identity | {"status": "rejected" if rejected else "unknown", "error": str(exc),
                                          "rejection": rejection})
                print("Write response uncertain; reconciling without retry", flush=True)
                if args.submit_only:
                    raise SystemExit("Stopping on uncertain write; reconcile before submitting more")
        if args.submit_only:
            status = previous["status"] if previous else "submitted"
            print(f"TRACKED {batch['path']} ({status}); extraction remains unverified", flush=True)
            continue
        deadline = time.monotonic() + args.wait
        result = {"verified": False}
        while time.monotonic() < deadline:
            await asyncio.sleep(10)
            try:
                current = await provider_stats(adapter, provider)
                if previous or current.get("doc_count", 0) > before["doc_count"]:
                    result = await verify_batch(adapter, provider, batch)
                    print(f"CHECK {batch['path']}: {result}", flush=True)
                    if result["verified"]:
                        record(ledger, identity | {"status": "verified", "verification": result,
                                                  "stats": current})
                        break
            except SynaptError:
                print("Transient verification error; waiting", flush=True)
        if not result["verified"]:
            record(ledger, identity | {"status": "unverified", "verification": result})
            raise SystemExit("Stopping on unverified extraction; re-run reconciles without duplicate writes")
    final = await provider_stats(adapter, provider)
    (args.corpus / "final-provider-stats.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
    print(json.dumps(final, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=Path("artifacts/synapt/corpus-2026-10-07"))
    parser.add_argument("--max-batches", type=int, default=0)
    parser.add_argument("--wait", type=float, default=900)
    parser.add_argument("--submit-only", action="store_true",
                        help="Queue each batch once; a separate run verifies extraction")
    parser.add_argument("--verify-only", action="store_true", help="Reconcile all tracked batches without writes")
    parser.add_argument("--targeted", action="store_true", help="Deprecated: graph verification is always exact")
    parser.add_argument("--retry-rejected", action="store_true", help="Explicitly retry only confirmed rejected writes")
    asyncio.run(main(parser.parse_args()))
