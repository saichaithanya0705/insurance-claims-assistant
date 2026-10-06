from types import SimpleNamespace

import pytest

from claims.evaluation import EvaluationService, judge_case_payload
from claims.settings import Settings


def test_judge_receives_full_claim_and_identified_historical_evidence():
    import json

    output = {
        "claim": {"description": "A car collision", "claimed_amount": 42000},
        "findings": [],
        "recommendations": [],
        "evidence": [
            {
                "source_id": "history-1",
                "title": "Prior claim",
                "provenance": "published_synthetic",
                "text": "Historical amount 3183.90",
            }
        ],
    }
    payload = judge_case_payload(output)
    assert json.loads(payload["input"])["current_claim"]["claimed_amount"] == 42000
    assert "handler review" in payload["input"]
    evidence = json.loads(payload["retrieval_context"][0])
    assert evidence["source_id"] == "history-1"
    assert evidence["provenance"] == "published_synthetic"
    assert evidence["evidence"] == "Historical amount 3183.90"


def test_evaluation_rejects_unresolved_recommendation_citations_and_bad_validation():
    class BrokenService:
        store = SimpleNamespace(event=lambda *args: None)

        def create(self, claim, filters):
            return {
                "run_id": "broken",
                "status": "needs_manual_review",
                "mode": "fixture",
                "review": None,
                "classification": {"needs_review": True},
                "validation": {"passed": False},
                "evidence": [{"source_id": "real"}],
                "findings": [
                    {"kind": "gap", "text": "Missing report", "source_ids": ["real"]},
                    {"kind": "contradiction", "text": "Conflicting facts", "source_ids": ["real"]},
                ],
                "recommendations": [{"source_ids": ["unknown"]}],
            }

    report = EvaluationService(BrokenService(), Settings(_env_file=None)).run()
    assert report["passed"] == 0
    assert all(not case["checks"]["all_citations_resolve"] for case in report["cases"])
    assert not report["cases"][0]["checks"]["expected_validation_outcome"]


@pytest.mark.parametrize(
    "records,expected",
    [
        ([], "no_outputs"),
        ([{"status": "completed"}], "partial"),
        ([{"status": "failed"}], "failed"),
    ],
)
def test_judge_status_requires_complete_metric_coverage(monkeypatch, records, expected):
    class FailedService:
        store = SimpleNamespace(event=lambda *args: None)

        def create(self, claim, filters):
            return {"run_id": "failed", "status": "failed", "mode": "fixture"}

    evaluation = EvaluationService(
        FailedService(),
        Settings(_env_file=None, nvidia_api_key="fake-test", deepeval_model="judge-test"),
    )
    monkeypatch.setattr(
        evaluation, "status", lambda: {"deepeval_installed": True, "judge_configured": True}
    )
    monkeypatch.setattr(evaluation, "_judge", lambda outputs: records)
    evaluation.run(judge=True)
    assert evaluation.latest["judge_status"] == expected
    assert evaluation.latest["judge_expected_metrics"] == 12
