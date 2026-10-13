"""Build the sorted native copy of the claims dataset (about 5 minutes, about 2.6 GB), then prove it gives the same answers.

    python scripts/build_claims_copy.py            # writes data/derived/claims_sorted.duckdb
    python scripts/build_claims_copy.py --verify 20

The search for the 300 closest past claims scans every claim of the new claim's type. On the Parquet file that takes 3 to 4 s; on this
copy (DuckDB's own format, sorted by type, state and amount, with each claim's closing date stored) it takes about 1.4 s. After
building, the script runs ``--verify`` searches (random claims from the dataset, with and without a state, an outcome or an amount
range) on both and fails, deleting the copy, if a single row or its order differs. The application uses the copy only if it records
this dataset's SHA-256, its row count and this layout, so a copy of another file is ignored. Nothing here writes to Synapt.
"""

import argparse
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.core.schemas import ClaimInput, SearchFilters
from claims.core.settings import Settings
from claims.history.dataset import ClaimsStore

FILTERS = (
    {},
    {"state": "TX"},
    {"claim_status": "approved"},
    {"claim_status": "pending"},
    {"min_amount": 2000, "max_amount": 40000},
    {"min_previous_claims": 1, "max_previous_claims": 3},
)


def claim_from(row: dict) -> ClaimInput:
    return ClaimInput.model_validate({
        "description": "A verification claim drawn from the dataset itself.",
        "claim_type": row["claim_type"], "state": row["state"], "incident_date": row["incident_date"],
        "claim_filed_date": row["claim_filed_date"], "claim_amount": row["claim_amount"], "deductible": row["deductible"],
        "previous_claims_count": row["previous_claims_count"], "policyholder_tenure_years": row["policyholder_tenure_years"],
    })


def main() -> None:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--output", type=Path, default=settings.claims_sorted_copy_path)
    parser.add_argument("--verify", type=int, default=20, help="searches to compare with the Parquet file (0 to skip)")
    args = parser.parse_args()
    store = ClaimsStore(settings.claims_parquet_path, memory_limit="8GB")
    try:
        built = store.build_copy(args.output)
        print(f"built {built['path']}: {built['rows']:,} rows, {built['bytes'] / 1e9:.2f} GB, {built['seconds']} s")
        if not store.attach_copy(args.output):
            raise SystemExit("the copy just built does not attach as this dataset's copy")
        if args.verify:
            rng = random.Random(11)
            sample = store.sample(args.verify, seed=rng.randrange(1_000_000))
            mismatches, fast_s, raw_s = 0, 0.0, 0.0
            for i, row in enumerate(sample):
                claim = claim_from(row)
                filters = SearchFilters.model_validate(FILTERS[i % len(FILTERS)])
                started = time.perf_counter()
                with_copy = store.candidates(claim, filters, limit=300)
                fast_s += time.perf_counter() - started
                alias, store.copy_alias = store.copy_alias, None  # the same search on the Parquet file
                try:
                    started = time.perf_counter()
                    plain = store.candidates(claim, filters, limit=300)
                    raw_s += time.perf_counter() - started
                finally:
                    store.copy_alias = alias
                if with_copy != plain:
                    mismatches += 1
                    print("MISMATCH", row["claim_id"], FILTERS[i % len(FILTERS)])
            print(f"verified {len(sample)} searches: {mismatches} differ; copy {fast_s / len(sample):.2f} s each, Parquet {raw_s / len(sample):.2f} s each")
            if mismatches:
                args.output.unlink(missing_ok=True)
                raise SystemExit("the copy does not match the Parquet file; it was deleted")
    finally:
        store.close()


if __name__ == "__main__":
    main()
