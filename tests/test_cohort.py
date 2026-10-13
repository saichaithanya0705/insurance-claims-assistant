"""Cohort statistics: exact DuckDB figures for past claims with the same description as a new claim.

Every expected number below is worked out by hand from the small Parquet that build_source writes.
The cohort of the claim used throughout is: auto, TX, amount 7,000 (band 3), tenure 2 years (band 1),
no prior claims (band 0), filed 10 days after the incident (band 3).
"""

import json
from datetime import date, timedelta

import duckdb
import pytest
from fastapi.testclient import TestClient

from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.schemas import ClaimInput, Evidence, RetrievalBundle, SearchFilters
from claims.core.settings import Settings
from claims.corpus.cards import AMOUNT_EDGES, DELAY_EDGES, TENURE_EDGES
from claims.corpus.profile_cards import CELL_KEY, _eligible_sql, band_sql
from claims.history.cohort import (
    CROSS_CHECK_LIMIT,
    _settled_before,
    band_index,
    cell_of,
    cohort_statistics,
    history_index,
    trace_attributes,
)
from claims.history.dataset import COLUMNS, ClaimsStore
from claims.storage.run_store import Store
from claims.synapt.adapter import SynaptError

CUTOFF = date(2026, 1, 1)
INCIDENT = date(2023, 1, 1)


def build_source(path):
    """Write a Parquet file with the real columns and return the claim IDs of each group.

    exact:    30 auto/TX/7,000/tenure 2/no prior/10 days; 24 approved, 6 denied; 3 flagged
    ca:       20 auto/CA/7,000/tenure 2/no prior/10 days; all approved (same type, amount, history)
    tx_other: 10 auto/TX/9,999/tenure 4/no prior/2 days; 5 approved, 5 denied; all flagged
    fl:        5 auto/FL/20,000/tenure 4/two prior/20 days; all approved
    home:     40 home/TX/7,000/tenure 2/no prior/10 days; all flagged (another type must not count)
    open:      7 pending or under review, same band as exact (never eligible)
    late:      5 approved that closed on 9 January 2026 (after the cutoff, never eligible)
    boundary:  1 approved that closed on 1 January 2026 (closing on the cutoff is not before it)
    """
    ids, rows = {}, []

    def add(group, kind, state, amount, tenure, prior, delay, status, days, flagged=False,
            incident=INCIDENT):
        claim_id = f"CLM-{len(rows) + 1:010d}"
        ids.setdefault(group, []).append(claim_id)
        filed = incident + timedelta(days=delay)
        rows.append((claim_id, "POL-100000001", kind, state, tenure, prior, incident, filed,
                     amount, 500.0, status, days, flagged))

    for i in range(1, 31):
        add("exact", "auto", "TX", 7000.0, 2.0, 0, 10,
            "approved" if i <= 24 else "denied", 2.0 * i, flagged=i <= 3)
    for _ in range(20):
        add("ca", "auto", "CA", 7000.0, 2.0, 0, 10, "approved", 4.0)
    for i in range(10):
        add("tx_other", "auto", "TX", 9999.0, 4.0, 0, 2,
            "approved" if i < 5 else "denied", 100.0, flagged=True)
    for _ in range(5):
        add("fl", "auto", "FL", 20000.0, 4.0, 2, 20, "approved", 50.0)
    for _ in range(40):
        add("home", "home", "TX", 7000.0, 2.0, 0, 10, "approved", 3.0, flagged=True)
    for status in ("pending",) * 4 + ("under_review",) * 3:
        add("open", "auto", "TX", 7000.0, 2.0, 0, 10, status, float("nan"), flagged=True)
    for _ in range(5):
        add("late", "auto", "TX", 7000.0, 2.0, 0, 10, "approved", 10.0, flagged=True,
            incident=date(2025, 12, 20))
    add("boundary", "auto", "TX", 7000.0, 2.0, 0, 10, "approved", 10.0, flagged=True,
        incident=date(2025, 12, 12))

    connection = duckdb.connect()
    connection.execute("""
        CREATE TABLE claims(claim_id VARCHAR, policy_id VARCHAR, claim_type VARCHAR, state VARCHAR,
          policyholder_tenure_years DOUBLE, previous_claims_count INTEGER, incident_date DATE,
          claim_filed_date DATE, claim_amount DOUBLE, deductible DOUBLE, claim_status VARCHAR,
          days_to_resolution DOUBLE, is_fraud_flagged_ground_truth BOOLEAN)
    """)
    connection.executemany("INSERT INTO claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    connection.execute("COPY claims TO ? (FORMAT PARQUET)", [str(path)])
    connection.close()
    return ids


def make_claim(**changes) -> ClaimInput:
    values = {
        "description": "Rear-ended at a junction; the repair estimate is attached.",
        "claim_type": "auto",
        "state": "TX",
        "incident_date": date(2025, 5, 1),
        "claim_filed_date": date(2025, 5, 11),
        "claim_amount": 7000,
        "deductible": 500,
        "previous_claims_count": 0,
        "policyholder_tenure_years": 2,
    }
    return ClaimInput(**(values | changes))


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.parquet"
    ids = build_source(path)
    store = ClaimsStore(path, memory_limit="256MB", threads=1)
    yield store, ids
    store.close()


@pytest.fixture
def store(source):
    return source[0]


def cohort_for(store, claim=None, **kwargs):
    return cohort_statistics(store, claim or make_claim(), **kwargs)


# ----- the figures, worked out by hand -------------------------------------------------------


def test_the_exact_cohort_is_the_thirty_settled_claims_with_the_same_description(store):
    cohort = cohort_for(store)
    assert cohort["available"] is True
    exact = cohort["cohorts"][0]
    assert exact["key"] == "exact"
    assert exact["claims"] == 30
    assert exact["approved_share"] == 0.8  # 24 of 30
    assert exact["denied_share"] == 0.2  # 6 of 30
    # Days are 2, 4, ..., 60: median 31, quartiles 16.5 and 45.5 (linear interpolation).
    assert (exact["p25_days"], exact["median_days"], exact["p75_days"]) == (16.5, 31.0, 45.5)
    assert exact["flag_rate"] == 0.1  # 3 of 30 carry the synthetic flag
    assert exact["sufficient"] is True
    assert exact["definition"] == (
        "auto claims in Texas, amount 5,000-10,000 USD, tenure 1-3 years, no prior claims, "
        "filed 8-15 days after the incident"
    )


def test_the_type_amount_history_cohort_adds_other_states_tenures_and_delays(store):
    # Exact 30 + CA 20 + TX 9,999 10 = 60 claims with the same type, amount band and history band.
    cohort = cohort_for(store)["cohorts"][1]
    assert cohort["key"] == "type_amount_history"
    assert cohort["claims"] == 60
    assert cohort["approved_share"] == 0.8167  # 49 of 60
    assert cohort["denied_share"] == 0.1833  # 11 of 60
    assert (cohort["p25_days"], cohort["median_days"], cohort["p75_days"]) == (4.0, 21.0, 50.5)
    assert cohort["flag_rate"] == 0.2167  # 13 of 60
    assert cohort["sufficient"] is True
    assert cohort["definition"] == (
        "auto claims, amount 5,000-10,000 USD, no prior claims, in any state, tenure and filing delay"
    )


def test_the_type_cohort_is_every_settled_claim_of_that_type_and_no_other(store):
    # 30 + 20 + 10 + 5 auto claims. The 40 home claims, the 12 open claims, the 5 late claims and
    # the boundary claim never count, and their flags are not in the rate.
    cohort = cohort_for(store)["cohorts"][2]
    assert cohort["key"] == "type"
    assert cohort["claims"] == 65
    assert cohort["approved_share"] == 0.8308  # 54 of 65
    assert cohort["denied_share"] == 0.1692  # 11 of 65
    assert (cohort["p25_days"], cohort["median_days"], cohort["p75_days"]) == (4.0, 26.0, 50.0)
    assert cohort["flag_rate"] == 0.2  # 13 of 65
    assert cohort["definition"] == (
        "all auto claims, in any state, amount, tenure, prior claims or filing delay"
    )


def test_open_late_and_boundary_claims_are_excluded_from_every_cohort(store):
    counts = [c["claims"] for c in cohort_for(store)["cohorts"]]
    assert counts == [30, 60, 65]
    # The open claims are flagged and sit in the exact band; counting them would move the rate.
    assert cohort_for(store)["cohorts"][0]["flag_rate"] == 0.1


def test_a_cohort_with_no_claims_reports_none_not_a_division_by_zero(store):
    cohort = cohort_for(store, make_claim(state="NY"))  # no New York claims in the file
    exact = cohort["cohorts"][0]
    assert exact["claims"] == 0 and exact["sufficient"] is False
    assert exact["approved_share"] is None and exact["denied_share"] is None
    assert exact["median_days"] is None and exact["p25_days"] is None and exact["p75_days"] is None
    assert exact["flag_rate"] is None
    assert cohort["cohorts"][1]["claims"] == 60  # the broader cohorts still have claims


def test_a_claim_type_with_no_history_has_only_empty_cohorts(store):
    cohort = cohort_for(store, make_claim(claim_type="business"))
    assert [c["claims"] for c in cohort["cohorts"]] == [0, 0, 0]
    assert all(c["median_days"] is None and c["flag_rate"] is None for c in cohort["cohorts"])


def test_the_sufficiency_threshold_marks_small_cohorts_without_hiding_them(store):
    cohort = cohort_for(store, min_claims=31)
    exact, broad = cohort["cohorts"][0], cohort["cohorts"][1]
    assert exact["claims"] == 30 and exact["sufficient"] is False
    assert exact["flag_rate"] == 0.1  # still computed; the UI marks it as insufficient
    assert broad["sufficient"] is True
    assert cohort_for(store, min_claims=30)["cohorts"][0]["sufficient"] is True


def test_the_cutoff_is_a_closing_date_strictly_before_it(store):
    # The boundary claim closes on 1 January 2026, so it is excluded under the default cutoff.
    assert cohort_for(store, cutoff=date(2026, 1, 2))["cohorts"][2]["claims"] == 66


def test_the_result_states_its_source_eligibility_and_timing(store):
    cohort = cohort_for(store)
    assert cohort["source"] == "duckdb_parquet"
    assert cohort["cutoff"] == "2026-01-01"
    assert cohort["eligibility"] == "approved or denied claims closed before 1 January 2026"
    assert cohort["dataset_claims"] == 118
    assert isinstance(cohort["elapsed_seconds"], float) and cohort["elapsed_seconds"] >= 0
    assert cohort["synapt_cross_check"] is None


def test_the_notes_say_where_the_numbers_come_from_and_what_the_flag_means(store):
    notes = " ".join(cohort_for(store)["notes"])
    assert "DuckDB" in notes and "do not come from Synapt" in notes
    assert "not proof of fraud" in notes
    assert "pending or under review" in notes
    assert "fewer than 30 claims" in notes


def test_the_figures_never_use_words_that_state_a_conclusion(store):
    text = json.dumps(cohort_for(store)).lower()
    for word in ("covered", "eligible", "likely", "probability", "fraud rate", "predicted", "valid"):
        assert word not in text, word


def test_unavailable_without_the_full_dataset():
    cohort = cohort_statistics(None, make_claim())
    assert cohort["available"] is False and "not loaded" in cohort["reason"]


def test_unavailable_when_the_claim_type_is_unknown(store):
    cohort = cohort_for(store, make_claim(claim_type=None))
    assert cohort["available"] is False and "claim type" in cohort["reason"]


# ----- the Synapt cross-check ----------------------------------------------------------------


def test_the_cross_check_counts_cards_that_describe_the_same_cohort(source):
    store, ids = source
    semantic = [
        ids["exact"][0],
        ids["ca"][0],  # same type, amount and history, another state: the broader cohort only
        ids["fl"][0],  # same type only
        ids["home"][0],  # same band, another type
        ids["open"][0],  # same band but never settled
        ids["late"][0],  # same band but closed after the cutoff
        ids["boundary"][0],  # closed on the cutoff
        "CLM-9999999999",  # not in the file
        ids["exact"][0],  # repeated: counted once
    ]
    check = cohort_for(store, semantic_ids=semantic, mode="live")["synapt_cross_check"]
    assert check == {
        "source": "synapt",
        "cards_returned": 8,
        "in_exact_cohort": 1,
        "in_type_amount_history_cohort": 2,
    }


def test_every_exact_card_is_counted_and_card_labels_follow_the_bundle_mode(source):
    store, ids = source
    semantic = ids["exact"] + ids["ca"][:3]
    live = cohort_for(store, semantic_ids=semantic, mode="live")["synapt_cross_check"]
    assert (live["in_exact_cohort"], live["in_type_amount_history_cohort"]) == (30, 33)
    degraded = cohort_for(store, semantic_ids=semantic, mode="degraded")["synapt_cross_check"]
    assert degraded["source"] == "local_fallback" and degraded["cards_returned"] == 33
    assert degraded["in_exact_cohort"] == 30


def test_no_ids_or_an_unknown_bundle_mode_means_no_cross_check(store):
    assert cohort_for(store, semantic_ids=[])["synapt_cross_check"] is None
    assert cohort_for(store, semantic_ids=None)["synapt_cross_check"] is None
    # Only live Synapt cards and degraded local cards are labelled; a test double is not Synapt.
    assert cohort_for(store, semantic_ids=["CLM-0000000001"], mode="fixture")["synapt_cross_check"] is None


def test_the_cross_check_looks_at_no_more_than_the_limit(source):
    store, _ = source
    semantic = [f"CLM-{n:010d}" for n in range(1, CROSS_CHECK_LIMIT + 51)]
    check = cohort_for(store, semantic_ids=semantic)["synapt_cross_check"]
    assert check["cards_returned"] == CROSS_CHECK_LIMIT


def test_a_duckdb_error_is_reported_as_unavailable_not_raised(store, monkeypatch):
    def broken(*args, **kwargs):
        raise duckdb.Error("simulated read failure")

    monkeypatch.setattr(ClaimsStore, "_run", broken)
    cohort = cohort_for(store)
    assert cohort == {"available": False, "reason": "Cohort statistics could not be computed"}


# ----- band helpers agree with the SQL that the profile cards use ----------------------------


@pytest.mark.parametrize(
    ("edges", "values"),
    [
        (AMOUNT_EDGES, [0, 999.99, 1000, 2499.5, 2500, 4999.99, 5000, 9999.99, 10000, 99999,
                        100000, 250000, 1e7]),
        (TENURE_EDGES, [0, 0.5, 1, 2.99, 3, 4.99, 5, 9.99, 10, 19.99, 20, 60]),
        (DELAY_EDGES, [0, 1, 3, 4, 7, 8, 14, 15, 30, 31, 60, 61, 400]),
    ],
)
def test_python_band_index_agrees_with_band_sql(edges, values):
    connection = duckdb.connect()
    literals = ",".join(f"({float(v)}::DOUBLE)" for v in values)
    sql_rows = connection.execute(
        f"SELECT x, {band_sql('x', edges)} FROM (VALUES {literals}) t(x)"
    ).fetchall()
    connection.close()
    sql_index = dict(sql_rows)
    for value in values:
        assert band_index(float(value), edges) == sql_index[float(value)], value


def test_history_bands_match_the_profile_card_rule():
    assert [history_index(n) for n in (0, 1, 2, 3, 4, 10)] == [0, 1, 2, 2, 3, 3]


def test_python_cells_agree_with_the_sql_cells_row_by_row(source):
    store, _ = source
    raw = {row["claim_id"]: row for row in store._run(f"SELECT {', '.join(COLUMNS)} FROM {store.source}")}
    sql_rows = store._run(_eligible_sql(store), [CUTOFF])
    # 30 exact + 20 CA + 10 TX other + 5 FL + 40 home settled before the cutoff; 13 are never counted.
    assert len(sql_rows) == 105
    for row in sql_rows:
        cell = cell_of(raw[row["claim_id"]])
        assert {key: cell[key] for key in CELL_KEY} == {key: row[key] for key in CELL_KEY}


def test_python_eligibility_agrees_with_the_sql_eligibility(source):
    store, _ = source
    eligible = {r["claim_id"] for r in store._run(f"SELECT claim_id FROM ({_eligible_sql(store)})", [CUTOFF])}
    for row in store._run(f"SELECT {', '.join(COLUMNS)} FROM {store.source}"):
        assert _settled_before(row, CUTOFF) == (row["claim_id"] in eligible), row["claim_id"]


def test_trace_attributes_never_name_synapt_and_keep_the_counts(source):
    store, ids = source
    cohort = cohort_for(store, semantic_ids=ids["exact"][:2], mode="live")
    attributes = trace_attributes(cohort)
    assert "synapt" not in json.dumps(attributes).lower()
    assert attributes["exact_claims"] == 30 and attributes["type_claims"] == 65
    assert attributes["cross_check_in_exact"] == 2
    unavailable = trace_attributes(cohort_statistics(None, make_claim()))
    assert unavailable == {"available": False, "reason": unavailable["reason"]}


# ----- the workflow: cohort in the run, the trace and never in the evidence ------------------

WORKFLOW_CLAIM = {
    "incident_date": "2025-05-01",
    "claim_filed_date": "2025-05-11",
    "claim_amount": 7000,
    "previous_claims_count": 0,
    "policyholder_tenure_years": 2,
}


def workflow_claim():
    return DEMO_CASES[0]["claim"] | WORKFLOW_CLAIM


@pytest.fixture
def workflow_settings(tmp_path):
    source_path = tmp_path / "source.parquet"
    build_source(source_path)
    return Settings(
        _env_file=None,
        claims_database_path=tmp_path / "runtime.sqlite",
        claims_data_path=tmp_path / "absent.json",
        claims_artifact_dir=tmp_path / "models",
        claims_parquet_path=source_path,
    )


class SynaptDown:
    """Test double: the live adapter fails the way a real outage does."""

    def retrieve(self, claim):
        raise SynaptError("Synapt is unreachable")


class LocalCopy:
    """Test double for the degraded-mode fallback: it names the cards it has, labelled degraded."""

    def __init__(self, card_ids):
        self.card_ids = card_ids

    def available(self):
        return True

    def warm(self):
        return None

    def retrieve(self, claim):
        return RetrievalBundle(
            mode="degraded",
            evidence=[Evidence(source_id="local:procedure", title="Local copy", text="Request an incident statement.", provenance="local_copy")],
            warnings=["Degraded copy in use"],
            semantic_claim_ids=self.card_ids,
        )


class SynaptUp:
    """Test double for a healthy live adapter that returns the same card IDs as the local copy."""

    def __init__(self, card_ids):
        self.card_ids = card_ids

    def retrieve(self, claim):
        return RetrievalBundle(
            mode="live",
            evidence=[Evidence(source_id="procedure:auto", title="Procedure", text="Request an incident statement.", provenance="synapt")],
            semantic_claim_ids=self.card_ids,
        )


def spans_of(app, run_id):
    store = Store(app.state.service.settings.claims_database_path)
    try:
        return store.spans(run_id)
    finally:
        store.close()


def by_name(spans, name):
    return [s for s in spans if s["name"] == name]


def test_a_run_carries_its_cohort_and_the_exact_figures(workflow_settings):
    app = create_app(workflow_settings)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": workflow_claim()}).json()
    assert run["cohort"]["available"] is True
    assert [c["claims"] for c in run["cohort"]["cohorts"]] == [30, 60, 65]
    assert run["cohort"]["synapt_cross_check"] is None  # the stub returns no card IDs


def test_the_cohort_is_never_evidence_for_the_brief_or_the_model(workflow_settings):
    app = create_app(workflow_settings)
    with TestClient(app):
        result = app.state.service.retrieve_context(
            ClaimInput.model_validate(workflow_claim()), SearchFilters()
        )
    assert result["cohort"]["available"] is True
    blob = json.dumps(result["evidence"]).lower()
    assert "cohort" not in blob
    for cohort in result["cohort"]["cohorts"]:
        assert cohort["definition"].lower() not in blob
    assert "approved_share" not in blob and "median" not in blob


def test_the_trace_has_a_cohort_span_without_synapt_and_keeps_the_synapt_spans(workflow_settings):
    app = create_app(workflow_settings)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": workflow_claim()}).json()
    spans = spans_of(app, run["run_id"])
    cohort_span = by_name(spans, "cohort.statistics")[0]
    stage = next(s for s in spans if s["kind"] == "stage" and s["name"] == "retrieve")
    assert cohort_span["kind"] == "compute"
    # the figures are the Claims History Analyst's work, and it works inside the retrieve stage
    agent = next(s for s in spans if s["span_id"] == cohort_span["parent_id"])
    assert agent["kind"] == "agent" and agent["attributes"]["agent"] == "history_analyst" and agent["parent_id"] == stage["span_id"]
    assert "synapt" not in json.dumps(cohort_span["attributes"]).lower()
    assert cohort_span["attributes"]["exact_claims"] == 30
    assert by_name(spans, "knowledge.retrieve") and by_name(spans, "history.search")


def test_the_cross_check_is_labelled_local_fallback_when_the_bundle_is_degraded(workflow_settings):
    # CLM-1 and CLM-2 are exact-cohort claims; CLM-31 is a CA claim of the same type, amount and history.
    card_ids = ["CLM-0000000001", "CLM-0000000002", "CLM-0000000031"]
    app = create_app(workflow_settings, adapter=SynaptDown(), fallback=LocalCopy(card_ids))
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": workflow_claim()}).json()
    assert run["mode"] == "degraded"
    assert run["cohort"]["synapt_cross_check"] == {
        "source": "local_fallback",
        "cards_returned": 3,
        "in_exact_cohort": 2,
        "in_type_amount_history_cohort": 3,
    }


def test_the_cross_check_is_labelled_synapt_when_the_bundle_is_live(workflow_settings):
    card_ids = ["CLM-0000000001", "CLM-0000000031"]  # the first exact card, and the first CA card
    app = create_app(workflow_settings, adapter=SynaptUp(card_ids))
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": workflow_claim()}).json()
    assert run["mode"] == "live"
    assert run["cohort"]["synapt_cross_check"] == {
        "source": "synapt",
        "cards_returned": 2,
        "in_exact_cohort": 1,
        "in_type_amount_history_cohort": 2,
    }


def test_the_case_search_skips_the_cohort_scan_and_does_not_return_it(workflow_settings):
    app = create_app(workflow_settings)
    with TestClient(app) as client:
        context = app.state.service.retrieve_context(
            ClaimInput.model_validate(workflow_claim()), SearchFilters(), with_cohort=False
        )
        search = client.post("/api/search", json={"claim": workflow_claim()}).json()
    assert context["cohort"] is None
    assert "cohort" not in search
    assert search["similar_cases"]  # the search itself still works
