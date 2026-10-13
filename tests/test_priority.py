from claims.core.demo_cases import DEMO_CASES
from claims.core.schemas import ClaimInput
from claims.investigation.priority import FLAGGED_SIMILAR_THRESHOLD, score_priority, tier_for


def claim(**changes):
    return ClaimInput.model_validate(DEMO_CASES[0]["claim"] | changes)


def score(claim_, findings=(), predictions=None, similar=(), classification=None):
    return score_priority(
        claim_,
        list(findings),
        predictions or {"available": False},
        list(similar),
        classification or {"needs_review": False},
    )


def test_tier_boundaries():
    assert [tier_for(n) for n in (0, 19, 20, 39, 40, 59, 60, 100)] == [
        "low", "low", "medium", "medium", "high", "high", "critical", "critical",
    ]


def test_an_ordinary_claim_is_low_and_has_no_investigation_reasons():
    result = score(claim())
    assert result["score"] == 0 and result["tier"] == "low" and result["components"] == []
    assert result["service_urgency"] == "normal" and result["investigation_priority"] == "normal"


def test_every_point_is_attributed_and_the_total_matches():
    findings = [
        {"kind": "contradiction", "text": "x", "source_ids": ["claim:input"]},
        {"kind": "gap", "text": "y", "source_ids": ["claim:input"]},
    ]
    result = score(
        claim(
            claim_amount=60_000,
            incident_date="2026-08-01",
            claim_filed_date="2026-08-20",
            previous_claims_count=3,
        ),
        findings,
    )
    points = {c["reason"][:20]: c["points"] for c in result["components"]}
    assert sum(points.values()) == result["score"] == 25 + 10 + 10 + 15 + 5
    assert result["tier"] == "critical"  # 65 points is at or above the 60-point floor
    assert result["service_urgency"] == "urgent" and result["investigation_priority"] == "elevated"
    # Evidence gaps add points but are not by themselves an investigation trigger.
    assert not any("gap" in r.lower() for r in result["reasons"])


def test_score_is_capped_and_critical_when_every_signal_fires():
    similar = [{"dataset_fraud_flag": True}] * 3
    result = score(
        claim(
            claim_amount=500_000,
            incident_date="2026-05-01",
            claim_filed_date="2026-08-20",
            previous_claims_count=6,
        ),
        [{"kind": "contradiction", "text": "x", "source_ids": ["claim:input"]}],
        {"available": True, "fraud": {"review_signal": True}},
        similar,
        {"needs_review": True},
    )
    assert result["score"] == 100 and result["tier"] == "critical"
    assert sum(c["points"] for c in result["components"]) > 100  # capped, not silently dropped


def test_similar_flagged_claims_need_the_threshold_and_are_not_proof():
    one = score(claim(), similar=[{"dataset_fraud_flag": True}])
    assert one["similar_flagged"] == 1 and not one["reasons"]
    many = score(claim(), similar=[{"dataset_fraud_flag": True}] * FLAGGED_SIMILAR_THRESHOLD + [{}])
    assert many["similar_flagged"] == FLAGGED_SIMILAR_THRESHOLD
    reason = next(r for r in many["reasons"] if "dataset fraud flag" in r)
    assert "not proof" in reason and f"of {FLAGGED_SIMILAR_THRESHOLD + 1}" in reason


def test_unavailable_models_cannot_add_fraud_points():
    result = score(claim(), predictions={"available": False, "fraud": {"review_signal": True}})
    assert result["score"] == 0
