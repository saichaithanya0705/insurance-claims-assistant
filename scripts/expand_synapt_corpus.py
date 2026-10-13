"""Build stratified, deduplicated Parquet claim cards locally; no upload side effects."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from claims.core.settings import Settings
from claims.corpus.card_dataset import build_card_dataset, known_claim_ids
from claims.history.dataset import ClaimsStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/synapt/corpus-2026-10-07"))
    parser.add_argument("--per-cell", type=int, default=100)
    parser.add_argument("--batch-cards", type=int, default=500)
    parser.add_argument("--cutoff", type=date.fromisoformat, default=date(2026, 1, 1))
    args = parser.parse_args()
    # DuckDB reservoir sampling depends on scheduling with multiple threads.
    store = ClaimsStore(Settings().claims_parquet_path, memory_limit="1GB", threads=1)
    try:
        report = build_card_dataset(store, args.output, per_cell=args.per_cell,
                                    batch_cards=args.batch_cards, cutoff=args.cutoff,
                                    excluded=known_claim_ids(Path("artifacts/synapt")))
    finally:
        store.close()
    print(json.dumps({k: v for k, v in report.items() if k not in {"batches", "cards_by_type_state"}}, indent=2))
    print(f"Batches: {len(report['batches'])}; type/state cells: {len(report['cards_by_type_state'])}")


if __name__ == "__main__":
    main()
