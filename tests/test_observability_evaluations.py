"""Judge metrics are traced under their case's run, and Observability lists evaluation runs.

Before: the judge scored each brief after its investigation ended, outside any trace, so its model calls
and the evaluation run itself were invisible in Observability."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.settings import Settings
from claims.evaluation.service import METRIC_COUNT, EvaluationService
from claims.llm.client import CompletionClient
from claims.observability import telemetry
from claims.observability.observatory import Observatory


class _TracedMetric:
    """A DeepEval-shaped metric whose measure() makes one traced (fake) judge-model call."""

    def __init__(self, name):
        self.__name__ = name
        self.threshold = 0.5

    def measure(self, case):
        with telemetry.span(
            "llm.judge_metric", kind="llm", purpose="judge_metric", model="judge-test", total_tokens=40
        ):
            pass
        self.score, self.reason = 0.8, "fine"


class _Recorder:
    def __init__(self):
        self.spans = []

    def add_span(self, **span):
        self.spans.append(span)


@pytest.fixture
def judged(tmp_path, monkeypatch):
    pytest.importorskip("deepeval")
    from deepeval import metrics, test_case

    monkeypatch.setattr(metrics, "FaithfulnessMetric", lambda **kw: _TracedMetric("Faithfulness"))
    monkeypatch.setattr(metrics, "ContextualRelevancyMetric", lambda **kw: _TracedMetric("Contextual Relevancy"))
    monkeypatch.setattr(metrics, "GEval", lambda **kw: _TracedMetric(kw["name"] + " [GEval]"))
    monkeypatch.setattr(test_case, "LLMTestCase", lambda **kw: SimpleNamespace(**kw))
    settings = Settings(
        _env_file=None, claims_database_path=tmp_path / "j.sqlite", claims_data_path=tmp_path / "missing.json",
        claims_artifact_dir=tmp_path / "models", nvidia_api_key="fake-test", deepeval_model="judge-test",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        evaluation = EvaluationService(app.state.service, settings)
        monkeypatch.setattr(evaluation, "status", lambda: {"deepeval_installed": True, "judge_configured": True})
        evaluation.run(judge=True)
        yield app, client, evaluation


def test_every_judge_metric_is_a_background_span_under_its_cases_run(judged):
    app, _, evaluation = judged
    store = app.state.service.store
    for case in evaluation.latest["cases"]:
        spans = store.spans(case["run_id"])
        root = next(s for s in spans if s["parent_id"] is None and s["name"] == "investigation")
        metrics = [s for s in spans if s["name"] == "judge.metric"]
        assert [m["attributes"]["metric"] for m in metrics] == [
            "Faithfulness", "Contextual Relevancy", "Claims handling safety and usefulness",
        ]
        assert all(m["parent_id"] == root["span_id"] and m["kind"] == "evaluation" for m in metrics)
        assert all(m["attributes"]["background"] is True and m["attributes"]["score"] == 0.8 for m in metrics)
        calls = [s for s in spans if s["name"] == "llm.judge_metric"]
        assert len(calls) == METRIC_COUNT and all(c["attributes"]["background"] is True for c in calls)
        assert {c["parent_id"] for c in calls} == {m["span_id"] for m in metrics}


def test_judging_afterwards_does_not_change_the_runs_duration_or_stages(judged):
    app, _, evaluation = judged
    store = app.state.service.store
    run_id = evaluation.latest["cases"][0]["run_id"]
    spans = store.spans(run_id)
    root = next(s for s in spans if s["parent_id"] is None and s["name"] == "investigation")
    digest = telemetry.summarize_spans(spans)
    assert digest["duration_ms"] == root["duration_ms"]
    assert next(s["stage"] for s in digest["stages"]) == "classify"
    assert digest["llm"]["by_purpose"]["judge_metric"]["calls"] == METRIC_COUNT


def test_the_overview_lists_judge_metric_calls_as_their_own_purpose(judged):
    app, _, _ = judged
    summary = Observatory(app.state.service.store).summary("all", "all")
    purposes = {row["purpose"]: row for row in summary["llm"]["by_purpose"]}
    assert purposes["judge_metric"]["calls"] == len(DEMO_CASES) * METRIC_COUNT


def test_the_evaluations_list_reports_cases_the_judge_and_its_model_calls(judged):
    _, client, evaluation = judged
    listing = client.get("/api/observability/evaluations").json()
    assert len(listing["items"]) == 1
    item = listing["items"][0]
    assert item["cases"]["total"] == len(DEMO_CASES) and len(item["cases"]["items"]) == len(DEMO_CASES)
    assert item["cases"]["items"][0]["run_id"] == evaluation.latest["cases"][0]["run_id"]
    judge = item["judge"]
    assert judge["requested"] is True and judge["status"] == "completed" and judge["model"] == "judge-test"
    assert judge["completed_metrics"] == len(DEMO_CASES) * METRIC_COUNT
    assert judge["mean_score"] == pytest.approx(0.8)
    assert sorted(m["metric"] for m in judge["metrics"]) == sorted(
        ["Faithfulness", "Contextual Relevancy", "Claims handling safety and usefulness [GEval]"]
    )
    assert all(m["completed"] == len(DEMO_CASES) and m["passed"] == len(DEMO_CASES) for m in judge["metrics"])
    assert judge["model_calls"] == {
        "traced": True, "calls": len(DEMO_CASES) * METRIC_COUNT,
        "tokens": 40 * len(DEMO_CASES) * METRIC_COUNT, "total_ms": judge["model_calls"]["total_ms"],
    }
    assert item["duration_seconds"] is not None and item["duration_seconds"] >= 0


def test_an_older_report_without_timing_or_traced_calls_still_lists(tmp_path):
    settings = Settings(
        _env_file=None, claims_database_path=tmp_path / "o.sqlite", claims_data_path=tmp_path / "missing.json",
        claims_artifact_dir=tmp_path / "models",
    )
    app = create_app(settings)
    with TestClient(app):
        store = app.state.service.store
        store.event("evaluation", "evaluation_report", {
            "status": "completed", "mode": "live", "passed": 4, "total": 4, "judge_requested": True,
            "judge_status": "completed", "judge_model": "m", "cases": [{"case": "a", "passed": True, "run_id": "gone"}],
            "judge_results": [{"metric": "Faithfulness", "status": "completed", "score": 0.9, "passed": True}],
        })
        item = Observatory(store).evaluations()["items"][0]
    assert item["duration_seconds"] is None and item["started_at"] is None
    assert item["judge"]["model_calls"]["traced"] is False and item["judge"]["mean_score"] == 0.9


def test_an_evaluation_with_no_judge_still_lists_its_cases(tmp_path):
    settings = Settings(
        _env_file=None, claims_database_path=tmp_path / "n.sqlite", claims_data_path=tmp_path / "missing.json",
        claims_artifact_dir=tmp_path / "models",
    )
    app = create_app(settings)
    with TestClient(app) as client:
        evaluation = EvaluationService(app.state.service, settings)
        evaluation.run(judge=False)
        item = client.get("/api/observability/evaluations").json()["items"][0]
    assert item["judge"]["requested"] is False and item["judge"]["metrics"] == []
    assert item["cases"]["total"] == len(DEMO_CASES)


def test_the_completion_client_labels_a_call_with_the_purpose_it_is_given():
    recorder = _Recorder()
    client = CompletionClient(Settings(_env_file=None), lambda *args: None)
    client._complete = lambda *args, **kwargs: "ok"  # no network: only the span label matters
    with telemetry.attach(telemetry.resume(recorder, "run-1", "root-1")):
        client.complete([{"role": "user", "content": "x"}], None, purpose="judge_metric")
        client.complete([{"role": "user", "content": "x"}], None)
    first, second = recorder.spans
    assert first["name"] == "llm.judge_metric" and first["attributes"]["purpose"] == "judge_metric"
    assert first["attributes"]["background"] is True and first["parent_id"] == "root-1"
    assert second["attributes"]["purpose"] == "completion"


def test_resume_needs_a_native_root_span():
    assert telemetry.resume(_Recorder(), "run-1", None) is None
    context = telemetry.resume(_Recorder(), "run-1", "root-1")
    assert context.run_id == "run-1" and context.span_id == "root-1" and context.background is True
    assert json.dumps(context.background)  # a plain flag, safe to log
