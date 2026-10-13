"""How well can a bounded set of Synapt claim cards cover the 100M-row dataset? Read-only.

    uv run python scripts/analyze_card_coverage.py
    uv run python scripts/analyze_card_coverage.py --budgets 5000 10000 20887 --json report.json

A claim card describes a claim only through bands (claim type, state, amount band, tenure band,
prior-claims band, filing-delay band). A query never states an outcome, so two claims with the same
bands are the same description, the number of *distinct descriptions* is finite, and a card that
repeats an existing description adds nothing for semantic retrieval.

The question this script answers, for a given number of cards: how likely is it that a NEW claim has
an exact-description twin among the cards? It compares sampling strategies analytically from the
per-description claim counts (an expectation, not a random draw), so the result is exact for the
model and repeatable. It never calls Synapt and never writes to the dataset.

Limits: "exact twin" is a proxy. Semantic retrieval finds near neighbours, not exact matches, so the
final test of any corpus is `scripts/synapt_ingest.py verify` against the provider that holds it.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.core.settings import Settings
from claims.corpus.profile_cards import description_counts
from claims.history.dataset import ClaimsStore


def analyse(rows: list[dict], budgets: list[int]) -> dict:
    n = np.array([r["n"] for r in rows], dtype=np.float64)
    total = n.sum()
    p = n / total
    order = np.argsort(-n)
    stratum = np.array([f"{r['claim_type']}|{r['state']}" for r in rows])
    _, inv = np.unique(stratum, return_inverse=True)
    strata = int(inv.max()) + 1
    report = {
        "eligible_settled_claims": int(total),
        "distinct_card_descriptions": len(rows),
        "claims_per_description": dict(
            zip(
                ("min", "p25", "median", "p75", "p90", "p99", "max"),
                map(float, np.quantile(n, [0, 0.25, 0.5, 0.75, 0.9, 0.99, 1])),
            )
        ),
        "share_of_claims_in_the_most_common_1_percent_of_descriptions": float(
            n[order[: max(1, len(n) // 100)]].sum() / total
        ),
        "by_budget": [],
    }
    for k in budgets:
        k = min(k, len(n))
        # Uniform random draw of k claims.
        random_distinct = float(np.sum(1 - np.power(1 - p, k)))
        random_twin = float(np.sum(p * (1 - np.power(1 - p, k))))
        # Equal allocation to every claim type x state group, random within it (the expansion rule).
        per_group = k / strata
        strat_distinct = strat_twin = 0.0
        for s in range(strata):
            m = inv == s
            q = n[m] / n[m].sum()
            strat_distinct += float(np.sum(1 - np.power(1 - q, per_group)))
            strat_twin += float(np.sum(p[m] * (1 - np.power(1 - q, per_group))))
        # One card per description, most common descriptions first: no card repeats another.
        volume_twin = float(n[order[:k]].sum() / total)
        kinds = np.array([r["claim_type"] for r in rows])
        by_type = {
            kind: {
                "claims": int(n[kinds == kind].sum()),
                "share_with_an_exact_twin": float(n[order[:k]][kinds[order[:k]] == kind].sum() / n[kinds == kind].sum()),
            }
            for kind in sorted(set(kinds))
        }
        report["by_budget"].append(
            {
                "cards": k,
                "new_claim_has_an_exact_twin": {
                    "uniform_random": random_twin,
                    "stratified_type_x_state": strat_twin,
                    "one_card_per_description_most_common_first": volume_twin,
                },
                "volume_first_share_with_an_exact_twin_by_claim_type": by_type,
                "cards_repeating_an_existing_description": {
                    "uniform_random": round(k - random_distinct),
                    "stratified_type_x_state": round(k - strat_distinct),
                    "one_card_per_description_most_common_first": 0,
                },
            }
        )
    return report


def print_report(report: dict) -> None:
    print(f"Settled claims closed before the cutoff: {report['eligible_settled_claims']:,}")
    print(f"Distinct card descriptions among them:    {report['distinct_card_descriptions']:,}")
    q = report["claims_per_description"]
    print(
        f"Claims per description: median {q['median']:.0f}, p90 {q['p90']:.0f}, max {q['max']:,.0f}; "
        f"the most common 1% of descriptions hold "
        f"{report['share_of_claims_in_the_most_common_1_percent_of_descriptions']:.0%} of all claims\n"
    )
    print("Chance that a NEW claim has an exact-description twin among the cards")
    print(f"{'cards':>8} {'random':>9} {'type x state':>13} {'volume-first':>13} {'repeats (random)':>18}")
    for row in report["by_budget"]:
        twin, rep = row["new_claim_has_an_exact_twin"], row["cards_repeating_an_existing_description"]
        print(
            f"{row['cards']:>8,} {twin['uniform_random']:>9.1%} {twin['stratified_type_x_state']:>13.1%} "
            f"{twin['one_card_per_description_most_common_first']:>13.1%} "
            f"{rep['uniform_random']:>10,} ({rep['uniform_random'] / row['cards']:.0%})"
        )
    chosen = next((r for r in report["by_budget"] if r["cards"] == 10000), report["by_budget"][-1])
    print()
    print(f"With {chosen['cards']:,} volume-first cards, share of each claim type that has an exact twin:")
    for kind, row in chosen["volume_first_share_with_an_exact_twin_by_claim_type"].items():
        print(f"  {kind:<9} {row['share_with_an_exact_twin']:>6.1%}  of {row['claims']:>11,} claims")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--parquet", type=Path, default=None)
    parser.add_argument("--cutoff", type=date.fromisoformat, default=date(2026, 1, 1))
    parser.add_argument("--budgets", type=int, nargs="+", default=[1000, 2500, 5000, 10000, 20887])
    parser.add_argument("--memory-limit", default="2GB")
    parser.add_argument("--json", type=Path, help="also save the full report")
    args = parser.parse_args()
    path = args.parquet or Settings().claims_parquet_path
    store = ClaimsStore(path, memory_limit=args.memory_limit)
    try:
        result = analyse(description_counts(store, args.cutoff), args.budgets)
    finally:
        store.close()
    print_report(result)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
