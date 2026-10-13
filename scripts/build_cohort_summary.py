"""Build the pre-aggregated cohort summary (one pass over the dataset, then every investigation reads three small tables).

    python scripts/build_cohort_summary.py            # writes data/derived/cohort_summary.duckdb
    python scripts/build_cohort_summary.py --verify 40

The summary is exact: after building, it is compared with the full scan for ``--verify`` randomly chosen descriptions and the script
fails (and deletes the file) if a single number differs. The application uses the file only if it records this dataset's SHA-256,
the same cutoff and the same band edges, so a summary for another file is ignored, never served. Nothing here writes to Synapt.
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 7
sys.path.insert(0, str(ROOT / "src"))

from claims.core.settings import Settings
from claims.history.cohort import DEFAULT_CUTOFF, _aggregate
from claims.history.cohort_summary import CohortSummary, build
from claims.history.dataset import ClaimsStore


def main() -> None:
    settings = Settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--output", type=Path, default=settings.claims_cohort_summary_path)
    parser.add_argument("--verify", type=int, default=25, help="descriptions to compare with the full scan (0 to skip)")
    args = parser.parse_args()
    store = ClaimsStore(settings.claims_parquet_path, memory_limit="6GB")
    try:
        built = build(store, args.output, DEFAULT_CUTOFF)
        print(f"built {built['path']} in {built['seconds']} s: {built['rows']}")
        summary = CohortSummary.open(args.output, store, DEFAULT_CUTOFF)
        if summary is None:
            raise SystemExit("the file just built does not open as this dataset's summary")
        if args.verify:
            cells = _sample_cells(store, args.verify)
            mismatches = 0
            started = time.perf_counter()
            for cell in cells:
                if summary.aggregate(cell) != _aggregate(store, cell, DEFAULT_CUTOFF):
                    mismatches += 1
                    print("MISMATCH", cell)
            print(f"verified {len(cells)} descriptions against the full scan in {time.perf_counter() - started:.0f} s: {mismatches} differ")
            if mismatches:
                summary.close()
                args.output.unlink(missing_ok=True)
                raise SystemExit("the summary does not match the scan; it was deleted")
        summary.close()
    finally:
        store.close()


def _sample_cells(store: ClaimsStore, count: int) -> list[dict]:
    """Descriptions drawn at random from the settled claims, so common ones and rare ones are both checked."""
    from claims.corpus.profile_cards import _eligible_sql

    sql = f"""
        SELECT DISTINCT claim_type, state, amount_idx, tenure_idx, history_idx, delay_idx
        FROM ({_eligible_sql(store)}) USING SAMPLE reservoir({int(count)} ROWS) REPEATABLE ({SEED})
    """
    return store._run(sql, [DEFAULT_CUTOFF])


if __name__ == "__main__":
    main()
