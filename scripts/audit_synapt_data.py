"""Read current Synapt MCP passages and measure coverage without making writes."""

import asyncio
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from claims.adapters import LiveSynaptAdapter
from claims.cards import claim_ids_in_text
from claims.settings import Settings


def unwrap(payload):
    result = payload.get("result", payload)
    return json.loads(result) if isinstance(result, str) else result


async def main():
    settings = Settings()
    adapter = LiveSynaptAdapter(settings)
    discovery = await adapter.discover()
    stats = unwrap(await adapter.call_read_tool(
        "trident_get_stats", {"provider_id": settings.synapt_provider_id}
    ))
    payload = unwrap(await adapter.call_read_tool(
        "trident_get_chunks", {
            "provider_id": settings.synapt_provider_id,
            "query": "Historical claim card",
            "top_k": min(30000, stats.get("chunks", 0) + 100),
        }
    , max_response_chars=20_000_000))
    chunks = payload if isinstance(payload, list) else payload.get("chunks", [])
    ids = sorted({cid for chunk in chunks for cid in claim_ids_in_text(chunk.get("text", ""))})
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "provider": settings.synapt_provider_id,
        "stats": stats,
        "returned_chunks": len(chunks),
        "inventory_complete_by_chunk_count": len(chunks) == stats.get("chunks"),
        "distinct_readable_claim_ids": len(ids),
        "claim_ids": ids,
        "documents_in_returned_chunks": dict(Counter(c.get("source_file") for c in chunks)),
        "doc_types": dict(Counter(c.get("doc_type") for c in chunks)),
        "ingestion_schema": discovery["tool_schemas"].get("trident_ingest"),
    }
    output = Path("artifacts/synapt/audit-2026-10-07")
    output.mkdir(parents=True, exist_ok=True)
    # Keep timestamped snapshots as evidence; the root files are the latest inventory.
    snapshot = output / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    snapshot.mkdir(exist_ok=True)
    for target in (output, snapshot):
        (target / "inventory.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (target / "passages.json").write_text(json.dumps(chunks, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k not in {"claim_ids", "ingestion_schema", "documents_in_returned_chunks"}}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
