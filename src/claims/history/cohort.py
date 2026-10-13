"""Cohort statistics: exact figures for past claims with the same description as a new claim.

The figures come from DuckDB over the full Parquet dataset, in one pass. They do not come from Synapt.
Synapt contributes only an optional cross-check: how many of the similar past claims retrieval already obtained
from its ticket store for this claim describe a claim in the same cohort. No new Synapt request is made for it.

The figures are display-only. They are not evidence, they are never cited, and no language model sees
them, so they describe past claims and never decide anything about the new one.

The counting rule and band edges are the profile-card ones (claims.corpus.profile_cards and claims.corpus.cards), so a
cohort here is the same description a Synapt card carries.
"""

import logging
import math
import time
from bisect import bisect_right
from datetime import date, timedelta

import duckdb

from claims.core.us_states import STATE_NAMES
from claims.corpus.cards import (
    AMOUNT_EDGES,
    DELAY_EDGES,
    TENURE_EDGES,
    amount_band,
    delay_band,
    history_band,
    tenure_band,
)
from claims.corpus.profile_cards import CELL_KEY, _eligible_sql
from claims.history.dataset import COLUMNS, ClaimsStore

logger = logging.getLogger(__name__)

DEFAULT_CUTOFF = date(2026, 1, 1)
MIN_CLAIMS = 30
CROSS_CHECK_LIMIT = 100
# Only cards from the live adapter are Synapt's. A degraded run used the local copy of the cards.
CROSS_CHECK_SOURCE = {"live": "synapt", "degraded": "local_fallback"}
# One prior-claims count per history band (0, 1, 2 or 3, 4+).
HISTORY_REPRESENTATIVE = (0, 1, 2, 4)
# Keys each cohort shares with the claim. Claim type is always shared, so it filters the scan instead.
COHORT_KEYS = {
    "exact": CELL_KEY[1:],
    "type_amount_history": ("amount_idx", "history_idx"),
    "type": (),
}


def band_index(value: float, edges: tuple) -> int:
    """The band a value falls in: how many edges it reaches. Its SQL twin is profile_cards.band_sql."""
    return bisect_right(edges, value)


def history_index(prior_claims: int) -> int:
    """The prior-claims band; the SQL twin is the history CASE in profile_cards._eligible_sql."""
    if prior_claims == 0:
        return 0
    if prior_claims == 1:
        return 1
    return 2 if prior_claims < 4 else 3


def _day(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def cell_of(fields: dict) -> dict:
    """The band indexes of one claim, keyed as profile_cards.CELL_KEY.

    ``fields`` is a ClaimInput dump or a raw Parquet row; both carry the same column names."""
    delay = (_day(fields["claim_filed_date"]) - _day(fields["incident_date"])).days
    return {
        "claim_type": str(fields["claim_type"]),
        "state": fields["state"],
        "amount_idx": band_index(float(fields["claim_amount"]), AMOUNT_EDGES),
        "tenure_idx": band_index(float(fields["policyholder_tenure_years"]), TENURE_EDGES),
        "history_idx": history_index(int(fields["previous_claims_count"])),
        "delay_idx": band_index(delay, DELAY_EDGES),
    }


def _settled_before(row: dict, cutoff: date) -> bool:
    """Python twin of the eligibility in profile_cards._eligible_sql, used for cross-check rows."""
    days = row["days_to_resolution"]
    if row["claim_status"] not in ("approved", "denied") or days is None or not math.isfinite(days):
        return False
    if days < 0 or math.floor(days) > 2_147_483_647:  # TRY_CAST to INTEGER is NULL beyond this
        return False
    return _day(row["claim_filed_date"]) + timedelta(days=math.floor(days)) < cutoff


def _condition(keys: tuple, cell: dict) -> tuple[str, list]:
    parts, params = [], []
    for key in keys:
        if key == "state":
            parts.append("state = ?")
            params.append(cell[key])
        else:
            parts.append(f"{key} = {int(cell[key])}")
    return " AND ".join(parts) or "TRUE", params


def _aggregate(store: ClaimsStore, cell: dict, cutoff: date) -> dict:
    """All three cohorts in one scan: conditional aggregates over the claim type's settled rows."""
    select, params = [], []
    for name, keys in COHORT_KEYS.items():
        condition, cond_params = _condition(keys, cell)
        select += [
            f"count(*) FILTER (WHERE {condition}) AS {name}_claims",
            f"count(*) FILTER (WHERE {condition} AND claim_status = 'approved') AS {name}_approved",
            f"count(*) FILTER (WHERE {condition} AND claim_status = 'denied') AS {name}_denied",
            (
                f"count(*) FILTER (WHERE {condition} AND is_fraud_flagged_ground_truth)"
                f" AS {name}_flagged"
            ),
            (
                "quantile_cont(days_to_resolution, [0.25, 0.5, 0.75])"
                f" FILTER (WHERE {condition}) AS {name}_days"
            ),
        ]
        params += cond_params * 5
    eligible = _eligible_sql(store, ", is_fraud_flagged_ground_truth")
    sql = f"""
        WITH eligible AS (
            SELECT * FROM ({eligible}) WHERE claim_type = ?
        )
        SELECT {", ".join(select)} FROM eligible
    """
    # Placeholders in text order: the cutoff, the claim type, then each cohort's condition.
    return store._run(sql, [cutoff, cell["claim_type"], *params])[0]


def _cross_check(store: ClaimsStore, cell: dict, cutoff: date, semantic_ids, mode: str):
    """How many of the cards retrieval already had describe a claim in the same cohort.

    Cards whose rows cannot be found, or that are not settled before the cutoff, do not match."""
    source = CROSS_CHECK_SOURCE.get(mode)
    ids = list(dict.fromkeys(semantic_ids or []))[:CROSS_CHECK_LIMIT]
    if source is None or not ids:
        return None
    marks = ", ".join("?" for _ in ids)
    columns = ", ".join(COLUMNS)
    rows = store._run(f"SELECT {columns} FROM {store.source} WHERE claim_id IN ({marks})", ids)
    in_exact = in_history = 0
    for row in rows:
        if not _settled_before(row, cutoff):
            continue
        other = cell_of(row)
        if (other["claim_type"], other["amount_idx"], other["history_idx"]) != (
            cell["claim_type"],
            cell["amount_idx"],
            cell["history_idx"],
        ):
            continue
        in_history += 1
        if all(other[key] == cell[key] for key in CELL_KEY):
            in_exact += 1
    return {
        "source": source,
        "cards_returned": len(ids),
        "in_exact_cohort": in_exact,
        "in_type_amount_history_cohort": in_history,
    }


def _band_value(index: int, edges: tuple) -> int:
    """A value that falls in band ``index``, so the wording comes from the same functions as the cards."""
    return 0 if index == 0 else edges[index - 1]


def _definitions(cell: dict) -> dict:
    kind = cell["claim_type"]
    amount = amount_band(_band_value(cell["amount_idx"], AMOUNT_EDGES))
    tenure = tenure_band(_band_value(cell["tenure_idx"], TENURE_EDGES))
    history = history_band(HISTORY_REPRESENTATIVE[cell["history_idx"]])
    if cell["delay_idx"] == 0:
        filed = "filed on the day of the incident"
    else:
        filed = f"filed {delay_band(_band_value(cell['delay_idx'], DELAY_EDGES))} after the incident"
    state = STATE_NAMES.get(cell["state"], cell["state"])
    return {
        "exact": (
            f"{kind} claims in {state}, amount {amount} USD, tenure {tenure}, {history}, {filed}"
        ),
        "type_amount_history": (
            f"{kind} claims, amount {amount} USD, {history}, in any state, tenure and filing delay"
        ),
        "type": f"all {kind} claims, in any state, amount, tenure, prior claims or filing delay",
    }


def _summary(key: str, row: dict, definition: str, min_claims: int) -> dict:
    count = int(row[f"{key}_claims"])
    days = row[f"{key}_days"] if count else None

    def share(part):
        return round(int(part) / count, 4) if count else None

    return {
        "key": key,
        "definition": definition,
        "claims": count,
        "approved_share": share(row[f"{key}_approved"]),
        "denied_share": share(row[f"{key}_denied"]),
        "median_days": round(days[1], 1) if days else None,
        "p25_days": round(days[0], 1) if days else None,
        "p75_days": round(days[2], 1) if days else None,
        "flag_rate": share(row[f"{key}_flagged"]),
        "sufficient": count >= min_claims,
    }


def _notes(cutoff: date, min_claims: int) -> list[str]:
    return [
        (
            "These figures describe past settled claims with similar details. They say nothing "
            "about this claim and do not decide it."
        ),
        (
            "They are computed by DuckDB over the full claims dataset in one pass. "
            "They do not come from Synapt."
        ),
        (
            f"Only approved or denied claims closed before {cutoff.day} {cutoff:%B %Y} are counted. "
            "Claims still pending or under review are not counted."
        ),
        (
            "The fraud figure is the share of claims carrying the dataset's synthetic fraud flag: "
            "a synthetic label, not proof of fraud."
        ),
        (
            f"A cohort with fewer than {min_claims} claims is marked as too few claims for a "
            "stable figure."
        ),
        (
            "The cross-check counts only similar past claims that retrieval already returned for this "
            "claim; it makes no new request."
        ),
    ]


def cohort_statistics(
    store: ClaimsStore | None,
    claim,
    *,
    cutoff: date = DEFAULT_CUTOFF,
    semantic_ids=None,
    mode: str = "live",
    min_claims: int = MIN_CLAIMS,
    late=None,
    summary=None,
) -> dict:
    """Exact statistics for the three cohorts that match ``claim``, computed by DuckDB.

    ``late`` lets a caller start the scan before retrieval has finished: a function returning ``(semantic_ids, mode)``,
    called once the scan is done and only for the cross-check, which is the one part that needs what retrieval returned.

    ``summary`` (a `claims.history.cohort_summary.CohortSummary` that belongs to this dataset) answers the figures from three small tables
    instead of scanning 100 million rows; the numbers are the same."""
    if store is None:
        return {
            "available": False,
            "reason": "The full claims dataset is not loaded, so cohort statistics are unavailable.",
        }
    if claim.claim_type is None:
        return {
            "available": False,
            "reason": "The claim type is unknown, so no comparable cohort can be defined.",
        }
    started = time.perf_counter()
    cell = cell_of(claim.model_dump(mode="json"))
    try:
        row = summary.aggregate(cell) if summary is not None else _aggregate(store, cell, cutoff)
        if late is not None:
            semantic_ids, mode = late()
        cross_check = _cross_check(store, cell, cutoff, semantic_ids, mode)
        dataset_claims = store.row_count()
    except duckdb.Error as error:
        logger.warning("Cohort statistics could not be computed (%s)", error)
        return {"available": False, "reason": "Cohort statistics could not be computed"}
    definitions = _definitions(cell)
    return {
        "available": True,
        "source": "duckdb_parquet",
        "via": "summary" if summary is not None else "scan",
        "cutoff": cutoff.isoformat(),
        "eligibility": f"approved or denied claims closed before {cutoff.day} {cutoff:%B %Y}",
        "dataset_claims": dataset_claims,
        "cohorts": [
            _summary(key, row, definitions[key], min_claims) for key in COHORT_KEYS
        ],
        "synapt_cross_check": cross_check,
        "notes": _notes(cutoff, min_claims),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def trace_attributes(cohort: dict) -> dict:
    """Descriptive trace attributes. They never name Synapt: the cross-check label is for the UI only."""
    if not cohort.get("available"):
        return {"available": False, "reason": cohort.get("reason")}
    attributes = {
        "available": True,
        "source": cohort["source"],
        "via": cohort.get("via"),
        "elapsed_seconds": cohort["elapsed_seconds"],
    }
    for item in cohort["cohorts"]:
        attributes[f"{item['key']}_claims"] = item["claims"]
        attributes[f"{item['key']}_sufficient"] = item["sufficient"]
    check = cohort["synapt_cross_check"]
    if check is not None:
        attributes |= {
            "cross_check_cards": check["cards_returned"],
            "cross_check_in_exact": check["in_exact_cohort"],
            "cross_check_in_type_amount_history": check["in_type_amount_history_cohort"],
        }
    return attributes
