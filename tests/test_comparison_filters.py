"""The intake's comparison selections reach the search, and the search obeys them.

Two kinds of control, one request (`filters`):
* the "Same type / state / amount / history" chips are limits on WHAT the compared claims look like;
* the outcome (Settled, Approved, Denied, Pending, Under review) is the STATUS of the compared claims.
Both are hard SQL limits. The data comes from the small Parquet in test_cohort (groups worked out by hand there):
auto/TX 7,000 x30 (24 approved, 6 denied), auto/CA 7,000 x20, auto/TX 9,999 x10, auto/FL 20,000 with two prior x5,
home/TX 7,000 x40, 7 open claims, and claims that closed or were filed after the new claim (never comparable).
"""

import pytest
from fastapi.testclient import TestClient
from test_cohort import SynaptUp, build_source, workflow_claim

from claims.api.main import create_app
from claims.core.schemas import ClaimInput, RetrievalBundle, SearchFilters
from claims.core.settings import Settings


@pytest.fixture
def parquet_ids(tmp_path):
    path = tmp_path / "source.parquet"
    return path, build_source(path)


@pytest.fixture
def settings(tmp_path, parquet_ids):
    return Settings(
        _env_file=None, claims_database_path=tmp_path / "runtime.sqlite", claims_data_path=tmp_path / "absent.json",
        claims_artifact_dir=tmp_path / "models", claims_parquet_path=parquet_ids[0],
    )


def search(client, filters=None, claim=None):
    body = {"claim": claim or workflow_claim()} | ({"filters": filters} if filters is not None else {})
    response = client.post("/api/search", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def cases(client, filters=None, claim=None):
    return search(client, filters, claim)["similar_cases"]


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


# ----- the "Same ..." chips: limits on what the compared claims look like ---------------------------


def test_with_every_chip_off_the_search_still_compares_claims_of_the_same_type_never_another(client):
    found = cases(client)
    assert found and {c["claim_type"] for c in found} == {"auto"}  # 40 identical home claims exist and never appear


def test_same_type_chip_on_is_the_same_search_as_the_default(client):
    assert [c["claim_id"] for c in cases(client, {"claim_type": "auto"})] == [c["claim_id"] for c in cases(client)]


def test_choosing_another_type_explicitly_replaces_the_default_and_compares_that_type(client):
    found = cases(client, {"claim_type": "home"})
    assert found and {c["claim_type"] for c in found} == {"home"}


def test_same_state_chip_limits_the_comparison_to_that_state(client):
    assert {c["state"] for c in cases(client, {"state": "CA"})} == {"CA"}
    assert "CA" not in {c["state"] for c in cases(client, {"state": "TX"})}


def test_similar_amount_chip_is_a_hard_range_on_the_claimed_amount(client):
    found = cases(client, {"min_amount": 9000, "max_amount": 11000})
    assert found and {c["claim_amount"] for c in found} == {9999.0}
    assert cases(client, {"min_amount": 50, "max_amount": 60}) == []


def test_similar_history_chip_is_a_hard_range_on_earlier_claims(client):
    found = cases(client, {"min_previous_claims": 2, "max_previous_claims": 3})
    assert found and all(2 <= c["previous_claims_count"] <= 3 for c in found)
    assert {c["state"] for c in found} == {"FL"}


def test_chips_combine_and_a_combination_nothing_matches_returns_nothing_not_a_broader_search(client):
    assert {c["state"] for c in cases(client, {"state": "TX", "min_amount": 6500, "max_amount": 7500})} == {"TX"}
    assert cases(client, {"state": "FL", "min_amount": 6500, "max_amount": 7500}) == []
    assert cases(client, {"state": "AK"}) == []


# ----- the outcome: the status of the compared claims, and only claims known before this one was filed --


def test_settled_is_approved_and_denied_together_and_never_open_claims(client, settings):
    with TestClient(create_app(settings)) as other:
        store = other.app.state.service.retriever.store
        statuses = {c["claim_status"] for c in store.candidates(ClaimInput.model_validate(workflow_claim()), SearchFilters(), limit=300)}
    assert statuses == {"approved", "denied"}


@pytest.mark.parametrize("status", ["approved", "denied"])
def test_approved_and_denied_each_compare_only_that_outcome(client, status):
    found = cases(client, {"claim_status": status})
    assert found and {c["claim_status"] for c in found} == {status}


@pytest.mark.parametrize("status", ["pending", "under_review"])
def test_pending_and_under_review_compare_only_open_claims_that_were_already_on_file(client, status):
    found = cases(client, {"claim_status": status})
    assert found and {c["claim_status"] for c in found} == {status}
    assert all(c["open_case"] and c["days_to_resolution"] is None for c in found)


def test_claims_that_closed_after_the_new_one_was_filed_are_never_compared(client, parquet_ids, settings):
    _, ids = parquet_ids
    never = set(ids["late"]) | set(ids["boundary"]) | set(ids["open"])
    with TestClient(create_app(settings)) as other:
        store = other.app.state.service.retriever.store
        pool = store.candidates(ClaimInput.model_validate(workflow_claim()), SearchFilters(), limit=300)
    assert pool and not {c["claim_id"] for c in pool} & never


# ----- Synapt's matches obey the same selection -----------------------------------------------------


def synapt_cards(parquet_ids):
    ids = parquet_ids[1]
    return ids["ca"][:2] + ids["home"][:2] + ids["exact"][:1]


def test_related_in_meaning_claims_are_dropped_when_the_selection_excludes_them(settings, parquet_ids):
    ids = parquet_ids[1]
    with TestClient(create_app(settings, adapter=SynaptUp(synapt_cards(parquet_ids)))) as client:
        everything = {c["claim_id"]: c["surfaced_by"] for c in cases(client)}
        texas = {c["claim_id"] for c in cases(client, {"state": "TX"})}
        california = {c["claim_id"] for c in cases(client, {"state": "CA"})}
    assert {i for i in ids["ca"][:2]} <= set(everything) and all(everything[i] == "semantic" for i in ids["ca"][:2])
    assert not set(ids["home"][:2]) & set(everything)  # another type is not "similar", whatever Synapt says
    assert not set(ids["ca"][:2]) & texas
    assert set(ids["ca"][:2]) <= california and not set(ids["exact"][:1]) & california


class _RecordingAdapter(SynaptUp):
    def __init__(self, card_ids):
        super().__init__(card_ids)
        self.seen = []

    def retrieve(self, claim):
        self.seen.append(claim)
        return super().retrieve(claim)


def test_the_synapt_request_is_built_from_the_claim_not_from_the_comparison_selection(settings, parquet_ids):
    adapter = _RecordingAdapter(synapt_cards(parquet_ids))
    with TestClient(create_app(settings, adapter=adapter)) as client:
        search(client, {"state": "CA", "claim_status": "denied"})
        search(client, {})
    assert len(adapter.seen) == 2 and adapter.seen[0] == adapter.seen[1]  # the selection never reaches the adapter
    assert isinstance(adapter.retrieve(adapter.seen[0]), RetrievalBundle)


# ----- the same selection through the investigation route, and what it does not control --------------


def test_an_investigation_compares_only_what_the_selection_allows(client):
    run = client.post("/api/investigations", json={"claim": workflow_claim(), "filters": {"state": "CA"}}).json()
    assert run["similar_cases"] and {c["state"] for c in run["similar_cases"]} == {"CA"}


def test_the_cohort_figures_do_not_follow_the_selection_they_describe_the_claims_own_description(client):
    first = client.post("/api/investigations", json={"claim": workflow_claim()}).json()["cohort"]
    second = client.post(
        "/api/investigations", json={"claim": workflow_claim(), "filters": {"state": "CA", "claim_status": "denied"}}
    ).json()["cohort"]
    for run in (first, second):
        run.pop("elapsed_seconds")
    assert first == second


def test_the_sample_data_search_also_compares_the_claims_own_type_unless_another_is_chosen(tmp_path):
    import json

    def row(claim_id, kind, state):
        return {
            "claim_id": claim_id, "policy_id": "POL-1", "claim_type": kind, "state": state, "policyholder_tenure_years": 2,
            "previous_claims_count": 0, "incident_date": "2023-01-01", "claim_filed_date": "2023-01-11", "claim_amount": 7000,
            "deductible": 500, "claim_status": "approved", "days_to_resolution": 5, "is_fraud_flagged_ground_truth": False,
        }

    sample = tmp_path / "sample.json"
    sample.write_text(json.dumps({"rows": [row("CLM-1", "auto", "TX"), row("CLM-2", "home", "TX"), row("CLM-3", "auto", "CA")]}))
    settings = Settings(
        _env_file=None, claims_database_path=tmp_path / "runtime.sqlite", claims_data_path=sample,
        claims_artifact_dir=tmp_path / "models", claims_parquet_path=tmp_path / "absent.parquet",
    )
    with TestClient(create_app(settings)) as client:
        assert {c["claim_id"] for c in cases(client)} == {"CLM-1", "CLM-3"}
        assert {c["claim_id"] for c in cases(client, {"claim_type": "home"})} == {"CLM-2"}
        assert {c["claim_id"] for c in cases(client, {"state": "CA"})} == {"CLM-3"}
