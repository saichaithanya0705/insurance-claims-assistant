"""Build the Synapt corpus (claim cards + procedures) from the full Parquet dataset. Local only:
nothing is uploaded. Upload with scripts/synapt_ingest.py."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from claims.corpus import build_corpus
from claims.dataset import ClaimsStore

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parquet", type=Path, default=Path("data/raw/parquet/insurance_claims_100M.parquet")
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/synapt/corpus-v3"))
    parser.add_argument(
        "--per-type",
        type=int,
        default=200,
        help="Cards per claim type (5 types). 200 gives 1,000 cards in ~10 batches.",
    )
    parser.add_argument("--cutoff", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    store = ClaimsStore(args.parquet)
    try:
        manifest = build_corpus(
            store, args.output, per_type=args.per_type, cutoff=args.cutoff, seed=args.seed
        )
    finally:
        store.close()
    print(
        json.dumps(
            {
                "output": str(args.output),
                "cards": manifest["cards"],
                "cards_by_type": manifest["cards_by_type"],
                "batches": len(manifest["batches"]),
                "largest_batch_bytes": max(b["bytes"] for b in manifest["batches"]),
                "procedures": len(manifest["procedures"]),
                "source_sha256": manifest["source"]["source_file_sha256"],
            },
            indent=2,
        )
    )
