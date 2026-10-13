"""The pre-aggregated cohort tables give the same numbers as the scan, and are used only for the dataset they were built from.

The scan of 100 million rows took 5 to 10 s and was the longest step of an investigation, so its three fixed groups are counted once
(`scripts/build_cohort_summary.py`) and read from small tables. Nothing here is allowed to change a figure: every group of the test
dataset, and the percentiles of days, are compared with the scan, and a summary that is not for this file is never used.
"""

import json
import random
import shutil
from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient
from test_cohort import SynaptUp, build_source, workflow_claim

from claims.api.main import create_app
from claims.core.schemas import ClaimInput
from claims.core.settings import Settings
from claims.corpus.profile_cards import _eligible_sql
from claims.history.cohort import DEFAULT_CUTOFF, _aggregate, cell_of, cohort_statistics
from claims.history.cohort_summary import CohortSummary, build, quantiles_from_histogram
from claims.history.dataset import ClaimsStore


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.parquet"
    ids = build_source(path)
    store = ClaimsStore(path, memory_limit="1GB")
    yield store, path, ids, tmp_path
    store.close()


def all_cells(store):
    return store._run(
        f"SELECT DISTINCT claim_type, state, amount_idx, tenure_idx, history_idx, delay_idx FROM ({_eligible_sql(store)}) ORDER BY ALL",
        [DEFAULT_CUTOFF],
    )


# ----- the percentiles ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(6))
def test_percentiles_read_from_a_histogram_equal_quantile_cont_on_the_rows(seed):
    rng = random.Random(seed)
    values = [rng.choice([0, 1, 2, 3, 5, 8, 13, 21, 40, 134]) for _ in range(rng.randrange(1, 400))]
    histogram = sorted((v, values.count(v)) for v in set(values))
    expected = duckdb.sql("SELECT quantile_cont(v, [0.25, 0.5, 0.75]) FROM (SELECT unnest(?::INTEGER[]) AS v)", params=[values]).fetchone()[0]
    assert quantiles_from_histogram(histogram) == expected


def test_a_single_value_two_values_and_nothing():
    assert quantiles_from_histogram([(7, 1)]) == [7.0, 7.0, 7.0]
    assert quantiles_from_histogram([(2, 1), (10, 1)]) == [4.0, 6.0, 8.0]  # interpolated, as quantile_cont does
    assert quantiles_from_histogram([]) is None


# ----- the tables ------------------------------------------------------------------------------------------------------------


def test_every_group_of_the_dataset_has_the_same_figures_from_the_summary_as_from_the_scan(source):
    store, _, _, tmp_path = source
    built = build(store, tmp_path / "summary.duckdb", DEFAULT_CUTOFF)
    assert built["rows"]["cohort_type"] == 2 and built["rows"]["cohort_exact"] >= 4  # auto and home, several descriptions
    summary = CohortSummary.open(tmp_path / "summary.duckdb", store, DEFAULT_CUTOFF)
    assert summary is not None
    cells = all_cells(store)
    assert len(cells) >= 4
    for cell in cells:
        assert summary.aggregate(cell) == _aggregate(store, cell, DEFAULT_CUTOFF), cell
    # a description nobody has, and a type nobody has: zeros and no percentiles, exactly as the scan says
    nobody = dict(cells[0], state="ZZ", amount_idx=99)
    assert summary.aggregate(nobody) == _aggregate(store, nobody, DEFAULT_CUTOFF)
    assert summary.aggregate(dict(nobody, claim_type="boat")) == _aggregate(store, dict(nobody, claim_type="boat"), DEFAULT_CUTOFF)
    summary.close()


def test_the_whole_cohort_answer_is_the_same_with_and_without_the_summary_including_the_card_cross_check(source):
    store, _, ids, tmp_path = source
    build(store, tmp_path / "summary.duckdb", DEFAULT_CUTOFF)
    summary = CohortSummary.open(tmp_path / "summary.duckdb", store, DEFAULT_CUTOFF)
    claim = ClaimInput.model_validate(workflow_claim())
    cards = ids["exact"][:2] + ids["ca"][:2]
    fast = cohort_statistics(store, claim, semantic_ids=cards, mode="live", summary=summary)
    slow = cohort_statistics(store, claim, semantic_ids=cards, mode="live")
    drop = {"elapsed_seconds", "via"}
    assert {k: v for k, v in fast.items() if k not in drop} == {k: v for k, v in slow.items() if k not in drop}
    assert fast["via"] == "summary" and slow["via"] == "scan"
    summary.close()


def test_a_summary_for_another_dataset_cutoff_or_edges_is_never_used(source):
    store, path, _, work = source
    target = work / "summary.duckdb"
    build(store, target, DEFAULT_CUTOFF)
    assert CohortSummary.open(target, store, date(2025, 6, 1)) is None  # another cutoff
    other_path = work / "other.parquet"
    shutil.copy(path, other_path)
    other = ClaimsStore(other_path, memory_limit="1GB")
    other.fingerprint = lambda: {"source_file_sha256": "0" * 64}  # a different file
    try:
        assert CohortSummary.open(target, other, DEFAULT_CUTOFF) is None
    finally:
        other.close()
    assert CohortSummary.open(work / "missing.duckdb", store, DEFAULT_CUTOFF) is None
    assert CohortSummary.open(None, store, DEFAULT_CUTOFF) is None and CohortSummary.open(target, None, DEFAULT_CUTOFF) is None
    broken = work / "broken.duckdb"
    broken.write_bytes(b"this is not a database")
    assert CohortSummary.open(broken, store, DEFAULT_CUTOFF) is None
    # and a summary whose band edges were changed since it was built
    con = duckdb.connect(str(target))
    con.execute("UPDATE meta SET value = ? WHERE key = 'edges'", [json.dumps({"amount": [1], "tenure": [1], "delay": [1]})])
    con.close()
    assert CohortSummary.open(target, store, DEFAULT_CUTOFF) is None


def test_a_build_refuses_a_dataset_whose_days_are_not_whole_numbers(source):
    _, path, _, work = source
    odd = work / "odd.parquet"
    duckdb.sql(
        f"COPY (SELECT * REPLACE (days_to_resolution + 0.5 AS days_to_resolution) FROM read_parquet('{path.as_posix()}')) "
        f"TO '{odd.as_posix()}' (FORMAT PARQUET)"
    )
    other = ClaimsStore(odd, memory_limit="1GB")
    try:
        with pytest.raises(ValueError, match="fractional days"):
            build(other, work / "never.duckdb", DEFAULT_CUTOFF)
        assert not (work / "never.duckdb").exists()
    finally:
        other.close()


# ----- in the application ----------------------------------------------------------------------------------------------------


def settings_for(path, tmp_path, summary):
    return Settings(
        _env_file=None, claims_database_path=tmp_path / "runtime.sqlite", claims_data_path=tmp_path / "absent.json",
        claims_artifact_dir=tmp_path / "models", claims_parquet_path=path, claims_cohort_summary_path=summary,
    )


def test_an_investigation_reads_the_summary_when_there_is_one_and_scans_when_there_is_not(source):
    store, path, _, work = source
    build(store, work / "summary.duckdb", DEFAULT_CUTOFF)
    with TestClient(create_app(settings_for(path, work, work / "summary.duckdb"), adapter=SynaptUp([]))) as client:
        fast = client.post("/api/investigations", json={"claim": workflow_claim()}).json()["cohort"]
    with TestClient(create_app(settings_for(path, work, work / "none.duckdb"), adapter=SynaptUp([]))) as client:
        slow = client.post("/api/investigations", json={"claim": workflow_claim()}).json()["cohort"]
    assert fast["via"] == "summary" and slow["via"] == "scan"
    assert [c["claims"] for c in fast["cohorts"]] == [c["claims"] for c in slow["cohorts"]] == [30, 60, 65]
    assert fast["cohorts"] == slow["cohorts"]


def test_cell_of_and_the_tables_agree_on_which_group_a_claim_belongs_to(source):
    store, _, _, work = source
    build(store, work / "summary.duckdb", DEFAULT_CUTOFF)
    summary = CohortSummary.open(work / "summary.duckdb", store, DEFAULT_CUTOFF)
    claim = ClaimInput.model_validate(workflow_claim())
    assert summary.aggregate(cell_of(claim.model_dump(mode="json")))["exact_claims"] == 30
    summary.close()
