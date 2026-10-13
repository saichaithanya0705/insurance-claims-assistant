"""Profile cards: one Synapt card per distinct claim description, most common first.

A claim card describes a claim only through bands (claim type, state, amount, tenure, prior claims
and filing delay), so many claims produce the same card text and a card that repeats a description
adds nothing for semantic retrieval. Counting the descriptions shows how few there really are
(about 200,000 among 72 million settled claims, and the most common 1% hold 28% of all claims).

So instead of sampling claims, this module sorts every description by how many claims share it and
writes one card for each of the most common ones. Each card describes one real exemplar claim (the
same alias scheme as every other card, so the application reads the claim from Parquet exactly as
before). The default ``description`` format embeds only that description; the ``profile`` format of
the first corpus also appended a count, a share and a median computed by DuckDB, which lowered
retrieval and is kept only to reproduce that corpus.

The analysis behind this choice is `scripts/analyze_card_coverage.py`; see docs/CORPUS_STRATEGY.md.
Nothing here talks to Synapt.
"""

import hashlib
import json
from datetime import date
from pathlib import Path

from claims.corpus.builder import (
    ATTRIBUTION,
    CLAIM_TYPES,
    DATASET_URL,
    SOPS,
    sop_document,
)
from claims.corpus.card_dataset import write_batches, write_parquet
from claims.corpus.cards import (
    AMOUNT_EDGES,
    DELAY_EDGES,
    TENURE_EDGES,
    amount_band,
    claim_alias,
    claim_card_text,
    history_band,
)
from claims.history.dataset import COLUMNS, ClaimsStore

CELL_KEY = ("claim_type", "state", "amount_idx", "tenure_idx", "history_idx", "delay_idx")


def band_sql(expression: str, edges: tuple) -> str:
    """SQL twin of ``claims.corpus.cards._band``: the index of the band ``expression`` falls in."""
    cases = " ".join(f"WHEN {expression} < {edge} THEN {i}" for i, edge in enumerate(edges))
    return f"CASE {cases} ELSE {len(edges)} END"


def _eligible_sql(store: ClaimsStore, extra_columns: str = "") -> str:
    """Settled claims closed strictly before the cutoff (``?``), with their band indexes."""
    delay = "date_diff('day', incident_date, claim_filed_date)"
    return f"""
        SELECT claim_id, claim_type, state, claim_status, days_to_resolution{extra_columns},
               {band_sql("claim_amount", AMOUNT_EDGES)} AS amount_idx,
               {band_sql("policyholder_tenure_years", TENURE_EDGES)} AS tenure_idx,
               CASE WHEN previous_claims_count = 0 THEN 0 WHEN previous_claims_count = 1 THEN 1
                    WHEN previous_claims_count < 4 THEN 2 ELSE 3 END AS history_idx,
               {band_sql(delay, DELAY_EDGES)} AS delay_idx
        FROM {store.source}
        WHERE claim_status IN ('approved', 'denied')
          AND isfinite(days_to_resolution) AND days_to_resolution >= 0
          AND claim_filed_date + TRY_CAST(floor(days_to_resolution) AS INTEGER) < ?
    """


def description_counts(store: ClaimsStore, cutoff: date) -> list[dict]:
    """Claims per distinct description (no outcome: a query never states one), most common first."""
    sql = f"""
        SELECT {", ".join(CELL_KEY)}, count(*) AS n
        FROM ({_eligible_sql(store)}) GROUP BY ALL
        ORDER BY n DESC, {", ".join(CELL_KEY)}
    """
    return store._run(sql, [cutoff])  # aggregate rows, not claim rows, so not store.rows()


def select_profiles(
    store: ClaimsStore,
    *,
    cutoff: date,
    budget: int | None = None,
    per_type: int | None = None,
    seed: int = 2026,
) -> list[dict]:
    """The most common descriptions, each with one deterministic exemplar claim.

    Give either ``budget`` (the most common descriptions overall) or ``per_type`` (the most common
    descriptions within each claim type, so every category gets the same number of cards). Each row
    is a full claim record (the exemplar) plus ``profile_claims`` (how many eligible claims share the
    description), ``profile_approved_share`` and ``profile_median_days``.
    """
    if (budget is None) == (per_type is None):
        raise ValueError("Give exactly one of budget or per_type")
    limit = budget if budget is not None else per_type
    if not 1 <= limit <= 200_000:
        raise ValueError("The number of cards must be between 1 and 200,000")
    keys = ", ".join(CELL_KEY)
    columns = ", ".join(f"s.{c}" for c in COLUMNS)
    if budget is not None:
        top_sql = f"SELECT * FROM cells ORDER BY n DESC, {keys} LIMIT ?"
    else:
        top_sql = (
            "SELECT * EXCLUDE (rk) FROM (SELECT *, row_number() OVER ("
            f"PARTITION BY claim_type ORDER BY n DESC, {keys}) AS rk FROM cells) WHERE rk <= ?"
        )
    sql = f"""
        WITH eligible AS ({_eligible_sql(store, ", hash(claim_id, ?) AS h")}),
        cells AS (
            SELECT {keys}, count(*) AS n,
                   avg(CASE WHEN claim_status = 'approved' THEN 1.0 ELSE 0.0 END) AS approved_share,
                   median(days_to_resolution) AS median_days,
                   arg_min(claim_id, h) AS exemplar_id
            FROM eligible GROUP BY {keys}
        ),
        top AS ({top_sql})
        SELECT {columns}, t.n AS profile_claims, t.approved_share AS profile_approved_share,
               t.median_days AS profile_median_days
        FROM top t JOIN {store.source} s ON s.claim_id = t.exemplar_id
        ORDER BY t.n DESC, s.claim_id
    """
    # Placeholders appear in this order: the seed (in the hash), the cutoff, then the row limit.
    rows = store.rows(sql, [seed, cutoff, limit])
    for row in rows:
        row["profile_claims"] = int(row["profile_claims"])
    return rows


def profile_sentence(claims: int, approved_share: float, median_days: float) -> str:
    """What the whole group looks like. Counts of dataset outcomes, never a statement about a claim."""
    return (
        f"Profile: {claims:,} settled claims in the dataset share this description; "
        f"{round(approved_share * 100)}% were approved and the median time to settle was "
        f"{round(median_days)} days."
    )


CARD_FORMATS = ("description", "profile")
CARD_ORDERS = ("balanced", "common_first")


def balanced_order(records: list[dict]) -> list[dict]:
    """Interleave the (claim type, state) groups so every batch, the first one included, spans them.

    Most common first puts the 500 commonest descriptions in the first batch, and those come from a
    dozen states, so a pilot of that batch would test almost none of the region tokens. Round-robin over
    the groups, each in most-common-first order, makes any prefix of the corpus representative, and a
    partly uploaded corpus stays balanced. Deterministic: ties are broken by claim ID.
    """
    taken: dict[tuple, int] = {}
    keyed = []
    for record in sorted(records, key=lambda r: (-r["profile_claims"], r["claim_id"])):
        group = (record["claim_type"], record["state"])
        keyed.append(((taken.get(group, 0), record["state"], record["claim_type"]), record))
        taken[group] = taken.get(group, 0) + 1
    return [record for _, record in sorted(keyed, key=lambda item: item[0])]


def render_profile_card(row: dict, card_format: str = "description") -> str:
    """One card. ``description`` is only what a query can state; ``profile`` (the first corpus's
    format) also appends the exemplar's outcome and the group profile, which lowered retrieval by
    diluting the match and which the application never reads (see docs/CORPUS_STRATEGY.md)."""
    alias = claim_alias(row["claim_id"])
    header = f"## history:{alias}\nclaim_ref: {alias}\n"
    if card_format == "description":
        return f"{header}{claim_card_text(row, include_outcome=False, masking_safe=True)}\n"
    if card_format == "profile":
        profile = profile_sentence(
            row["profile_claims"], row["profile_approved_share"], row["profile_median_days"]
        )
        return f"{header}{claim_card_text(row, masking_safe=True)} {profile}\n"
    raise ValueError(f"card_format must be one of {CARD_FORMATS}")


def build_profile_corpus(
    store: ClaimsStore,
    output: Path,
    *,
    budget: int | None = None,
    per_type: int | None = 2_000,
    cutoff: date = date(2026, 1, 1),
    batch_cards: int = 500,
    seed: int = 2026,
    card_format: str = "description",
    order: str = "balanced",
) -> dict:
    """Write Parquet cards, marker-headed text batches, the procedures and a manifest. Local only."""
    if card_format not in CARD_FORMATS:
        raise ValueError(f"card_format must be one of {CARD_FORMATS}")
    if order not in CARD_ORDERS:
        raise ValueError(f"order must be one of {CARD_ORDERS}")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output must be empty; use a new directory for a new corpus")
    if not 1 <= batch_cards <= 1000:
        raise ValueError("batch_cards must be between 1 and 1,000")
    if budget is not None:
        per_type = None
    rows = select_profiles(store, budget=budget, per_type=per_type, cutoff=cutoff, seed=seed)
    if not rows:
        raise ValueError("No eligible claims to describe")
    counts = description_counts(store, cutoff)
    eligible_claims = sum(c["n"] for c in counts)
    records = []
    for row in rows:
        # Fraud labels and policy identifiers stay in the source, never in retrieval context.
        fields = {k: v for k, v in row.items() if k not in {"policy_id", "is_fraud_flagged_ground_truth"}}
        records.append(fields | {
            "claim_ref": claim_alias(row["claim_id"]),
            "card_text": render_profile_card(row, card_format),
            "amount_band": amount_band(row["claim_amount"]),
            "history_band": history_band(row["previous_claims_count"]),
            "source_url": DATASET_URL,
            "provenance": "published_synthetic_tabular_record",
            "license": "CC-BY-NC-4.0",
            "historical_cutoff_exclusive": cutoff.isoformat(),
            "has_incident_narrative": False,
            "has_policy_wording": False,
        })
    if order == "balanced":
        records = balanced_order(records)
    output.mkdir(parents=True, exist_ok=True)
    parquet = output / "claim_cards.parquet"
    write_parquet(records, parquet)
    batches = write_batches(output, records, batch_cards, prefix="profile")
    procedures = []
    for source_id, title, body in SOPS:
        name = f"procedures/{source_id.lower()}.txt"
        target = output / name
        target.parent.mkdir(exist_ok=True)
        target.write_text(sop_document(source_id, title, body), encoding="utf-8")
        procedures.append(name)
    covered = sum(r["profile_claims"] for r in rows)
    claims_by_type, covered_by_type = {}, {}
    for c in counts:
        claims_by_type[c["claim_type"]] = claims_by_type.get(c["claim_type"], 0) + c["n"]
    for r in rows:
        covered_by_type[r["claim_type"]] = covered_by_type.get(r["claim_type"], 0) + r["profile_claims"]
    manifest = {
        "schema_version": 3,
        "kind": "profile_cards",
        "card_format": card_format,
        "order": order,
        "cards": len(records),
        "batches": batches,
        "procedures": sorted(procedures),
        "parquet": {"path": parquet.name, "bytes": parquet.stat().st_size,
                    "sha256": hashlib.sha256(parquet.read_bytes()).hexdigest()},
        "source": store.fingerprint() | {"url": DATASET_URL, "license": "CC-BY-NC-4.0",
                                         "attribution": ATTRIBUTION},
        "selection": {
            "rule": "one card per distinct claim description (type, state, amount, tenure, prior-claims "
                    "and filing-delay bands), most common description first "
                    + ("overall" if budget is not None else "within each claim type")
                    + "; the exemplar is the claim with the smallest hash(claim_id, seed) in its description",
            "budget": budget, "cards_per_type": per_type, "seed": seed,
            "cutoff_exclusive": cutoff.isoformat(),
            "eligibility": "approved or denied, closed strictly before the cutoff",
        },
        "coverage": {
            "eligible_claims": eligible_claims,
            "distinct_descriptions": len(counts),
            "descriptions_with_a_card": len(rows),
            "claims_whose_exact_description_has_a_card": covered,
            "share_of_eligible_claims": covered / eligible_claims,
            "smallest_profile_claims": min(r["profile_claims"] for r in rows),
            "by_claim_type": {
                kind: {"cards": sum(r["claim_type"] == kind for r in rows),
                       "eligible_claims": claims_by_type[kind],
                       "share_with_an_exact_twin": covered_by_type.get(kind, 0) / claims_by_type[kind]}
                for kind in sorted(claims_by_type)
            },
        },
        "cards_by_type": {k: sum(r["claim_type"] == k for r in records) for k in CLAIM_TYPES},
        "excluded": ["policy_id", "is_fraud_flagged_ground_truth", "numeric claim identifiers"],
        "id_scheme": "CLM-0000000012 -> claimref_aaaaaaaabc (digits a-j); state -> regionkey_xx, "
                     "both chosen to survive Synapt PII masking",
        "source_boundary": "No incident narratives, policy terms or rejection reasons are invented",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
