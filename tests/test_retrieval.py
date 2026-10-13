from claims.core.demo_cases import DEMO_CASES
from claims.core.schemas import ClaimInput, SearchFilters
from claims.history.retriever import HistoricalRetriever


def test_filters_and_historical_availability(tmp_path):
    retrieval = HistoricalRetriever(tmp_path / "missing.json")
    claim = ClaimInput.model_validate(DEMO_CASES[0]["claim"])
    result = retrieval.search(
        claim,
        SearchFilters(
            claim_type="auto", state="TX", claim_status="approved", min_amount=4000, max_amount=6000
        ),
    )
    assert len(result) == 1
    assert result[0]["claim_id"] == "FIX-0-0"
    retrieval.rows[0]["claim_filed_date"] = "2026-09-02"
    assert retrieval.search(claim, SearchFilters(claim_type="auto", state="TX")) == []


def test_no_matches_is_empty_not_unfiltered_fallback(tmp_path):
    retrieval = HistoricalRetriever(tmp_path / "missing.json")
    claim = ClaimInput.model_validate(DEMO_CASES[0]["claim"])
    assert retrieval.search(claim, SearchFilters(state="AK")) == []


def test_semantic_case_fusion_respects_filters_and_temporal_availability(tmp_path):
    retrieval = HistoricalRetriever(tmp_path / "missing.json")
    claim = ClaimInput.model_validate(DEMO_CASES[0]["claim"])
    baseline = retrieval.search(claim, SearchFilters(claim_type="auto"))
    target = baseline[-1]["claim_id"]
    fused = retrieval.search(claim, SearchFilters(claim_type="auto"), semantic_ids=[target])
    assert fused[0]["claim_id"] == target and fused[0]["semantic_match"]
    assert not retrieval.search(claim, SearchFilters(state="AK"), semantic_ids=[target])
    row = next(row for row in retrieval.rows if row["claim_id"] == target)
    row["claim_filed_date"] = claim.claim_filed_date.isoformat()
    assert target not in {
        r["claim_id"] for r in retrieval.search(claim, SearchFilters(), semantic_ids=[target])
    }
