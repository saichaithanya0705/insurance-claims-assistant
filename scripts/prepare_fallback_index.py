"""Build the local fallback index ahead of time and, with --measure, test how well it retrieves.

    uv run python scripts/prepare_fallback_index.py                   # build or load the index
    uv run python scripts/prepare_fallback_index.py --measure         # also run the precision test

The fallback (claims.retrieval.fallback) is used only when a live Synapt call fails. It needs the card file written by
`scripts/build_profile_corpus.py` and, for embeddings, the local model from `scripts/prepare_case_search.py`;
without that model it scores with TF-IDF. Building the index once here means the first degraded run in a demo
does not have to.

--measure repeats the protocol of `scripts/synapt_ingest.py verify` without calling Synapt: it samples claims
from the cards, asks the local index for the 20 closest cards to a card-shaped description of each, and reports
how often the returned cards share the claim's type, state, amount band and prior-claims band, next to the rate
expected by chance. Run `verify` against Synapt on the same corpus to compare the two.
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.core.settings import Settings
from claims.corpus.cards import amount_band, claim_card_text, history_band
from claims.retrieval.fallback import LocalKnowledge


def measure(index: LocalKnowledge, cards: Path, sample: int, top_k: int) -> dict:
    manifest = json.loads((cards.parent / "manifest.json").read_text(encoding="utf-8"))
    ids = [i for batch in manifest["batches"] for i in batch["claim_ids"]]
    cursor = duckdb.connect().execute("SELECT * FROM read_parquet(?)", [cards.as_posix()])
    names = [d[0] for d in cursor.description]
    rows = {r["claim_id"]: r for r in (dict(zip(names, values)) for values in cursor.fetchall())}
    rng = random.Random(7)
    chosen = rng.sample(ids, min(sample, len(ids)))
    keys = {
        "claim type": lambda r: r["claim_type"],
        "state": lambda r: r["state"],
        "amount band": lambda r: amount_band(r["claim_amount"]),
        "prior-claims band": lambda r: history_band(r["previous_claims_count"]),
    }
    hits = {name: [] for name in keys}
    chance = {name: [] for name in keys}
    for claim_id in chosen:
        row = rows[claim_id]
        query = claim_card_text(row, include_outcome=False, masking_safe=True)
        matched = [rows[i] for i in index.search(query, top_k) if i in rows]
        others = rng.sample(list(rows.values()), len(matched))
        for name, key in keys.items():
            hits[name].append(sum(key(m) == key(row) for m in matched) / len(matched))
            chance[name].append(sum(key(o) == key(row) for o in others) / len(others))

    def mean(values):
        return round(sum(values) / len(values), 3)

    return {
        "backend": index.backend,
        "queries": len(chosen),
        "cards_returned_per_query": top_k,
        "share_of_returned_cards_matching_the_query_claim": {
            name: {"fallback": mean(hits[name]), "random_pair": mean(chance[name])} for name in keys
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--sample", type=int, default=60)
    args = parser.parse_args()
    settings = Settings()
    index = LocalKnowledge(settings)
    if not index.available():
        raise SystemExit(
            f"No local card file at {index.cards_path} (or CLAIMS_FALLBACK_ENABLED is false). "
            "Build it with scripts/build_profile_corpus.py."
        )
    started = time.perf_counter()
    index.warm()
    print(f"index ready: backend={index.backend}, cards={index.status()['cards']:,}, "
          f"{time.perf_counter() - started:.1f}s")
    if args.measure:
        print(json.dumps(measure(index, index.cards_path, args.sample, settings.synapt_case_top_k), indent=2))
