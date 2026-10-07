"""Verify the live Synapt provider against the committed expected inventory. Read-only.

    uv run python scripts/verify_synapt_store.py                   # live provider vs data/synapt/expected_inventory.json
    uv run python scripts/verify_synapt_store.py --json report.json  # also save the full per-batch report
    uv run python scripts/verify_synapt_store.py --write-expected    # rebuild the inventory from local corpora

The check reads document sizes and character spans from Synapt's graph, so it works on any machine
with the `.env` credentials; it needs no local upload ledger. `--write-expected` needs the corpora
under artifacts/synapt (built by this project) and only writes the inventory after the live provider
passes it. Exit status 0 means verified.
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.adapters import LiveSynaptAdapter
from claims.settings import Settings
from claims.synapt_inventory import (
    INVENTORY_PATH,
    build_expected,
    load_expected,
    summary_lines,
    verify_store,
)


async def main(args) -> bool:
    settings = Settings()
    if settings.synapt_mode != "live":
        raise SystemExit("Live Synapt access is required: set SYNAPT_MODE=live in .env")
    provider = settings.synapt_provider_id
    expected = (
        build_expected(args.base_dir, args.expansion_dir)
        if args.write_expected
        else load_expected(args.inventory)
    )
    report = await verify_store(LiveSynaptAdapter(settings), provider, expected)
    print(f"Synapt provider {provider}")
    for mark, text in summary_lines(report):
        print(f"  [{mark}] {text}")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.write_expected:
        if not report["ok"]:
            raise SystemExit("Not writing the inventory: the live provider does not match these corpora")
        stats = report["stats"]
        expected["verified_against_synapt"] = {
            "date": datetime.now(UTC).date().isoformat(),
            "provider": provider,
            "documents": stats["documents"],
            "chunks": stats["chunks"],
        }
        args.inventory.parent.mkdir(parents=True, exist_ok=True)
        args.inventory.write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.inventory}")
    return report["ok"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--inventory", type=Path, default=ROOT / INVENTORY_PATH)
    parser.add_argument("--json", type=Path, help="save the full report here")
    parser.add_argument("--write-expected", action="store_true", help="rebuild the inventory from local corpora")
    parser.add_argument("--base-dir", type=Path, default=ROOT / "artifacts/synapt/corpus-v3")
    parser.add_argument("--expansion-dir", type=Path, default=ROOT / "artifacts/synapt/corpus-2026-10-07")
    raise SystemExit(0 if asyncio.run(main(parser.parse_args())) else 1)
