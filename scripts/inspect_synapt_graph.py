"""Provider-scoped read-only MCP document inventory and graph identity checks."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from claims.adapters import LiveSynaptAdapter
from claims.settings import Settings


async def main():
    settings = Settings()
    adapter = LiveSynaptAdapter(settings)
    payload = await adapter.call_read_tool("trident_cypher", {
        "provider_id": settings.synapt_provider_id,
        "query": (
            "MATCH (d:Document {provider_id: $provider_id}) "
            "OPTIONAL MATCH (d)-[:CONTAINS]->(c:Chunk) "
            "RETURN elementId(d) AS node_id, properties(d) AS document, "
            "count(c) AS linked_chunks ORDER BY document.filename LIMIT 500"
        ),
    })
    result = payload.get("result", payload)
    result = json.loads(result) if isinstance(result, str) else result
    output = Path("artifacts/synapt/audit-2026-10-07/documents.json")
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
