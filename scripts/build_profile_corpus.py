"""Build the profile-card corpus from the full Parquet dataset. Local only: nothing is uploaded.

    uv run python scripts/build_profile_corpus.py --output artifacts/synapt/corpus-profile-2026-10-09

One card per distinct claim description, most common first (see docs/CORPUS_STRATEGY.md and
claims.corpus.profile_cards). The output directory must be empty. Upload it to a NEW, empty provider with
`scripts/synapt_ingest.py ingest --procedures --max-batches 5` (procedures) and then
`scripts/ingest_expanded_cards.py --corpus <output>` (cards).
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.core.settings import Settings
from claims.corpus.profile_cards import build_profile_corpus
from claims.history.dataset import ClaimsStore

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--parquet", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-type", type=int, default=2_000,
                        help="cards per claim type, most common description first (default)")
    parser.add_argument("--budget", type=int, default=None,
                        help="instead: the most common descriptions overall, regardless of type")
    parser.add_argument("--cutoff", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument("--batch-cards", type=int, default=500)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--card-format", choices=("description", "profile"), default="description",
                        help="description: only what a query can state (default); profile: also the "
                             "exemplar's outcome and the group profile (the first corpus's format)")
    parser.add_argument("--order", choices=("balanced", "common_first"), default="balanced",
                        help="balanced: round-robin over (claim type, state) so every batch spans them "
                             "(default); common_first: the most common descriptions first")
    parser.add_argument("--memory-limit", default="3GB")
    args = parser.parse_args()
    store = ClaimsStore(args.parquet or Settings().claims_parquet_path, memory_limit=args.memory_limit)
    try:
        manifest = build_profile_corpus(
            store, args.output, budget=args.budget, per_type=args.per_type, cutoff=args.cutoff,
            batch_cards=args.batch_cards, seed=args.seed, card_format=args.card_format,
            order=args.order,
        )
    finally:
        store.close()
    summary = {k: manifest[k] for k in ("cards", "cards_by_type", "coverage")}
    summary["batches"] = len(manifest["batches"])
    summary["procedures"] = len(manifest["procedures"])
    summary["largest_batch_bytes"] = max(b["bytes"] for b in manifest["batches"])
    print(json.dumps(summary, indent=2))
