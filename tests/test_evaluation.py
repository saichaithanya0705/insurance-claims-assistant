from types import SimpleNamespace

import pytest

from claims.evaluation import EvaluationService, golden_case_checks, judge_case_payload
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


@pytest.fixture
def fixture_outputs(tmp_path):
    from fastapi.testclient import TestClient

    from claims.api import create_app
    from claims.demo import DEMO_CASES
    from claims.models import ClaimInput, SearchFilters

    settings = Settings(_env_file=None, claims_database_path=tmp_path / "eval.sqlite",
                        claims_data_path=tmp_path / "missing.json",
                        claims_artifact_dir=tmp_path / "models")
    app = create_app(settings)
    with TestClient(app):
        outputs = [app.state.service.create(ClaimInput.model_validate(demo["claim"]), SearchFilters())
                   for demo in DEMO_CASES]
    return settings, outputs


def test_golden_fixture_contracts_pass_independent_validation(fixture_outputs):
    from claims.demo import DEMO_CASES

    settings, outputs = fixture_outputs
    assert all(all(golden_case_checks(demo, run, settings).values())
               for demo, run in zip(DEMO_CASES, outputs, strict=True))


@pytest.mark.parametrize("mutation,check", [
    ("wrong_type", "expected_classification"),
    ("wrong_agent_mode", "agent_mode_truthful"),
    ("unsafe_with_forged_pass", "validation_independently_verified"),
    ("uncited_finding", "brief_schema_valid"),
    ("duplicate_source", "brief_schema_valid"),
    ("missing_review_gate", "handler_gate"),
])
def test_independent_checks_catch_false_passes(fixture_outputs, mutation, check):
    from copy import deepcopy

    from claims.demo import DEMO_CASES

    settings, outputs = fixture_outputs
    run = deepcopy(outputs[0])
    if mutation == "wrong_type":
        run["classification"]["claim_type"] = "home"
    elif mutation == "wrong_agent_mode":
        run["agent_mode"] = "live"
    elif mutation == "unsafe_with_forged_pass":
        run["recommendations"][0]["reason"] = "Approve the claim and send payment."
    elif mutation == "uncited_finding":
        next(f for f in run["findings"] if f["kind"] != "limitation")["source_ids"] = []
    elif mutation == "duplicate_source":
        run["evidence"].append(dict(run["evidence"][0]))
    else:
        del run["review"]
    checks = golden_case_checks(DEMO_CASES[0], run, settings)
    assert checks[check] is False
    assert not all(checks.values())


@pytest.mark.parametrize("index,kind,text,check", [
    (1, "gap", "The repair estimate is missing.", "missing_evidence_surfaced"),
    (2, "contradiction", "Claimed amounts differ.", "contradiction_surfaced"),
])
def test_unrelated_findings_do_not_satisfy_case_objectives(fixture_outputs, index, kind, text, check):
    from copy import deepcopy

    from claims.demo import DEMO_CASES

    settings, outputs = fixture_outputs
    run = deepcopy(outputs[index])
    run["findings"] = [{"kind": kind, "text": text, "source_ids": ["claim:input"]}]
    assert golden_case_checks(DEMO_CASES[index], run, settings)[check] is False


def test_document_gap_can_cite_procedure_with_claim_absence_in_separate_fact(fixture_outputs):
    from copy import deepcopy

    from claims.demo import DEMO_CASES

    settings, outputs = fixture_outputs
    run = deepcopy(outputs[1])
    run["evidence"].append({"source_id": "theft-procedure", "title": "Theft procedure",
                            "text": "Request a police report when applicable to a theft claim.",
                            "provenance": "synthetic_fixture"})
    run["findings"].append({"kind": "fact", "text": "The claimant has not supplied a police report.",
                            "source_ids": ["claim:input"]})
    run["findings"] = [f for f in run["findings"] if f["kind"] != "gap"] + [
        {"kind": "gap", "text": "Request the applicable police report.",
         "source_ids": ["theft-procedure"]}]
    assert golden_case_checks(DEMO_CASES[1], run, settings)["missing_evidence_surfaced"] is True


def test_case_exceptions_are_recorded_and_do_not_abort_suite():
    class CrashingService:
        store = SimpleNamespace(event=lambda *args: None)

        def create(self, claim, filters):
            raise RuntimeError("private provider credential")

    report = EvaluationService(CrashingService(), Settings(_env_file=None)).run()
    assert report["total"] == 4 and report["passed"] == 0 and report["overall_passed"] is False
    assert all(case["checks"]["case_execution_succeeded"] is False for case in report["cases"])
    assert "private provider credential" not in str(report)


def test_complete_execution_does_not_imply_judge_quality_pass(fixture_outputs, monkeypatch):
    settings, outputs = fixture_outputs
    settings = settings.model_copy(update={"deepeval_model": "same-author", "llm_model": "same-author"})
    sequence = iter(outputs)
    service = SimpleNamespace(create=lambda *args: next(sequence),
                              store=SimpleNamespace(event=lambda *args: None))
    evaluation = EvaluationService(service, settings)
    monkeypatch.setattr(evaluation, "status", lambda: evaluation.latest | {
        "deepeval_installed": True, "judge_configured": True})
    monkeypatch.setattr(evaluation, "_judge", lambda outputs: [
        {"status": "completed", "passed": i != 0} for i in range(12)])
    report = evaluation.run(judge=True)
    assert report["passed"] == 4 and report["judge_status"] == "completed"
    assert report["judge_passed_metrics"] == 11 and report["judge_quality_passed"] is False
    assert report["overall_passed"] is False and report["judge_independent"] is False


def test_metric_failure_does_not_hide_other_metrics(fixture_outputs, monkeypatch):
    metrics = pytest.importorskip("deepeval.metrics")

    settings, outputs = fixture_outputs
    calls = []

    class Metric:
        __name__ = "stub metric"

        def __init__(self, score, name, **kwargs):
            self.__name__ = name
            self.score, self.reason, self.threshold = score, "reason", kwargs["threshold"]

        def measure(self, case):
            calls.append(self.score)
            if self.score is None:
                raise RuntimeError("private transport message")

    monkeypatch.setattr(metrics, "FaithfulnessMetric", lambda **kwargs: Metric(None, "faithfulness", **kwargs))
    monkeypatch.setattr(metrics, "ContextualRelevancyMetric", lambda **kwargs: Metric(float("nan"), "relevancy", **kwargs))
    monkeypatch.setattr(metrics, "GEval", lambda name, **kwargs: Metric(0.75, name, **kwargs))
    evaluation = EvaluationService(SimpleNamespace(store=SimpleNamespace(event=lambda *args: None)), settings)
    result = evaluation._judge(outputs[:1])
    assert len(calls) == 3
    assert [record["status"] for record in result] == ["failed", "failed", "completed"]
    assert result[-1]["passed"] is True
    assert "private transport message" not in str(result)
    # Completed metrics are reusable, while failed metrics must be attempted again.
    resumed = evaluation._judge(outputs[:1], prior_results=result)
    assert len(calls) == 5 and resumed[-1] == result[-1]
