"""The sorted native copy of the dataset answers the closest-claims search exactly as the Parquet file does, and only for its own dataset.

The search scans every claim of the new claim's type. On the Parquet file that takes 3 to 4 s; on a copy in DuckDB's own format,
sorted by type, state and amount, with each claim's closing date stored once, about 1.4 s. Nothing may change an answer, so these tests
compare the two row for row and in order across filters and filing dates (including dates that fall exactly on a closing date, where
"settled before the new claim was filed" is a strict comparison), and check that a copy that is not for this file is never used.
"""

import json
import shutil
from datetime import date

import duckdb
import pytest
from test_cohort import build_source, workflow_claim

from claims.core.schemas import ClaimInput, SearchFilters
from claims.history.dataset import COPY_VERSION, ClaimsStore
from claims.history.retriever import HistoricalRetriever


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.parquet"
    build_source(path)
    store = ClaimsStore(path, memory_limit="1GB")
    yield store, path, tmp_path
    store.close()


def claim(**over):
    return ClaimInput.model_validate(workflow_claim() | over)


FILTERS = [
    {},
    {"state": "TX"},
    {"state": "CA"},
    {"claim_status": "approved"},
    {"claim_status": "denied"},
    {"claim_status": "pending"},
    {"claim_status": "under_review"},
    {"min_amount": 7000, "max_amount": 9999},
    {"min_previous_claims": 0, "max_previous_claims": 0},
    {"claim_type": "home"},
]


def same_both_ways(store, claim_, filters, limit=300):
    with_copy = store.candidates(claim_, filters, limit=limit)
    alias, store.copy_alias = store.copy_alias, None
    try:
        plain = store.candidates(claim_, filters, limit=limit)
    finally:
        store.copy_alias = alias
    return with_copy, plain


def test_the_copy_holds_every_row_and_attaches_only_after_it_is_proved_to_be_this_datasets(source):
    store, _, tmp_path = source
    built = store.build_copy(tmp_path / "copy.duckdb")
    assert built["rows"] == store.row_count() and built["bytes"] > 0 and not (tmp_path / "copy.duckdb.building").exists()
    assert store.copy_alias is None  # building does not switch the store over; attaching does
    assert store.attach_copy(tmp_path / "copy.duckdb") is True and store.copy_alias == "fastcopy"
    assert store.attach_copy(tmp_path / "copy.duckdb") is True  # asking again is harmless


@pytest.mark.parametrize("filters", FILTERS)
def test_the_search_returns_the_same_rows_in_the_same_order_with_the_copy_as_without_it(source, filters):
    store, _, tmp_path = source
    store.build_copy(tmp_path / "copy.duckdb")
    store.attach_copy(tmp_path / "copy.duckdb")
    with_copy, plain = same_both_ways(store, claim(), SearchFilters.model_validate(filters))
    assert with_copy == plain
    if filters in ({}, {"state": "TX"}):
        assert with_copy  # a search that finds nothing would prove nothing


def test_the_strict_before_comparison_holds_on_the_days_claims_close(source):
    """Claims in the test dataset close on 9 January 2026, on the cutoff of 1 January and on days in between: sweep the filing date over them."""
    store, _, tmp_path = source
    store.build_copy(tmp_path / "copy.duckdb")
    store.attach_copy(tmp_path / "copy.duckdb")
    seen = set()
    for filed in [date(2025, 6, 1), date(2025, 12, 31), date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 9), date(2026, 1, 10), date(2026, 3, 1)]:
        c = claim(incident_date=filed.isoformat(), claim_filed_date=filed.isoformat())
        with_copy, plain = same_both_ways(store, c, SearchFilters())
        assert with_copy == plain, filed
        seen.add(len(plain))
    assert len(seen) > 1  # the sweep crossed real boundaries, not one flat answer


def test_a_lookup_by_claim_id_stays_on_the_parquet_file(source):
    store, _, tmp_path = source
    store.build_copy(tmp_path / "copy.duckdb")
    store.attach_copy(tmp_path / "copy.duckdb")
    some = [r["claim_id"] for r in store.candidates(claim(), SearchFilters(), limit=5)]
    found = store.candidates(claim(), SearchFilters(), ids=some)
    assert sorted(r["claim_id"] for r in found) == sorted(some)


def test_a_copy_for_another_dataset_layout_or_row_count_is_never_used(source):
    store, path, tmp_path = source
    target = tmp_path / "copy.duckdb"
    store.build_copy(target)
    other_path = tmp_path / "other.parquet"
    shutil.copy(path, other_path)
    other = ClaimsStore(other_path, memory_limit="1GB")
    other.fingerprint = lambda: {"source_file_sha256": "0" * 64, "rows": other.row_count()}  # a different file
    try:
        assert other.attach_copy(target) is False and other.copy_alias is None
    finally:
        other.close()
    assert store.attach_copy(tmp_path / "missing.duckdb") is False and store.attach_copy(None) is False
    broken = tmp_path / "broken.duckdb"
    broken.write_bytes(b"this is not a database")
    assert store.attach_copy(broken) is False
    for key, value in (("version", COPY_VERSION + 1), ("rows", store.row_count() + 1), ("order", ["claim_id"])):
        edited = tmp_path / f"edited-{key}.duckdb"
        shutil.copy(target, edited)
        con = duckdb.connect(str(edited))
        con.execute("UPDATE meta SET value = ? WHERE key = ?", [json.dumps(value), key])
        con.close()
        assert store.attach_copy(edited) is False and store.copy_alias is None, key
    assert store.attach_copy(target) is True  # and the genuine one still attaches afterwards


def test_a_store_without_a_copy_searches_the_parquet_file_exactly_as_before(source):
    store, _, _ = source
    assert store.copy_alias is None
    rows = store.candidates(claim(), SearchFilters(), limit=300)
    assert rows and {r["claim_type"] for r in rows} == {"auto"}  # the pool is the new claim's own type, as ever


def test_the_retriever_uses_the_copy_when_it_is_given_one_and_returns_the_same_cases(source):
    store, path, tmp_path = source
    store.build_copy(tmp_path / "copy.duckdb")
    plain = HistoricalRetriever(tmp_path / "none.json", path)
    fast = HistoricalRetriever(tmp_path / "none.json", path, copy_path=tmp_path / "copy.duckdb")
    try:
        assert plain.store.copy_alias is None and fast.store.copy_alias == "fastcopy"
        c = claim()
        a, b = plain.search(c, SearchFilters(), 5, []), fast.search(c, SearchFilters(), 5, [])
        assert a and [x["claim_id"] for x in a] == [x["claim_id"] for x in b] and a == b
        assert fast.search(c, SearchFilters(), 5, [], pool=fast.prefetch(c, SearchFilters())) == b
    finally:
        plain.close()
        fast.close()
