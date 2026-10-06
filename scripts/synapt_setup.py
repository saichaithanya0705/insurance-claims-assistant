"""Explicit live inspection or single-attempt ingestion. Never runs on app startup."""

import argparse
import asyncio
import json
from pathlib import Path

from claims.adapters import LiveSynaptAdapter, SynaptError
from claims.settings import Settings


async def main(args):
    settings = Settings()
    adapter = LiveSynaptAdapter(settings)
    if args.command == "discover":
        result = await adapter.discover()
    elif args.command == "ingest":
        path = args.file.resolve()
        result = await adapter.ingest(path.read_text(encoding="utf-8"), path.name)
    else:
        result = await adapter.call_read_tool(
            "trident_get_stats", {"provider_id": settings.synapt_provider_id}
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("discover")
    commands.add_parser("stats")
    commands.add_parser("ingest").add_argument("file", type=Path)
    try:
        asyncio.run(main(parser.parse_args()))
    except SynaptError as exc:
        raise SystemExit(str(exc)) from None
