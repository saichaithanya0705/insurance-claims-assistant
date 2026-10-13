"""The evaluation can run in the background and says what it is doing, step by step."""

import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.settings import Settings
from claims.evaluation.service import METRIC_COUNT, EvaluationBusy, EvaluationService


class FakeInvestigations:
    """A service whose create() can be held open, so a run stays 'running' for as long as a test needs."""

    store = SimpleNamespace(event=lambda *args: None)

    def __init__(self, gate=None):
        self.gate = gate

    def create(self, claim, filters):
        if self.gate is not None:
            assert self.gate.wait(10), "test gate was never released"
        return {"run_id": "r", "status": "needs_manual_review", "mode": "fixture", "review": None,
                "classification": {"needs_review": True}, "validation": {"passed": False},
                "evidence": [], "findings": [], "recommendations": []}


def wait_until_finished(evaluation, timeout=20):
    deadline = time.monotonic() + timeout
    while evaluation.progress_snapshot()["state"] == "running":
        assert time.monotonic() < deadline, "evaluation did not finish"
        time.sleep(0.05)


def test_a_background_run_reports_each_golden_case_and_finishes():
    evaluation = EvaluationService(FakeInvestigations(), Settings(_env_file=None))
    started = evaluation.start()
    assert started["progress"]["state"] in ("running", "done")
    wait_until_finished(evaluation)
    progress = evaluation.status()["progress"]
    assert progress["state"] == "done" and progress["finished_at"]
    golden = [s for s in progress["steps"] if s["id"].startswith("golden:")]
    assert len(golden) == len(DEMO_CASES) and all(s["state"] in ("done", "failed") for s in golden)
    assert progress["done_steps"] == progress["total_steps"] == len(DEMO_CASES)
    assert any("Finished" in e["text"] for e in progress["events"])


def test_a_second_run_is_refused_while_one_is_active_and_allowed_after():
    gate = threading.Event()
    evaluation = EvaluationService(FakeInvestigations(gate), Settings(_env_file=None))
    evaluation.start()
    assert evaluation.progress_snapshot()["state"] == "running"
    with pytest.raises(EvaluationBusy):
        evaluation.start()
    with pytest.raises(EvaluationBusy):
        evaluation.run()
    gate.set()
    wait_until_finished(evaluation)
    evaluation.run()  # the lock was released
    assert evaluation.progress_snapshot()["state"] == "done"


def test_judge_steps_are_listed_and_unfinished_ones_are_marked_not_run(monkeypatch):
    evaluation = EvaluationService(
        FakeInvestigations(), Settings(_env_file=None, nvidia_api_key="fake-test", deepeval_model="judge-test")
    )
    monkeypatch.setattr(evaluation, "status", lambda: {"deepeval_installed": True, "judge_configured": True})
    monkeypatch.setattr(evaluation, "_judge", lambda outputs: [])
    evaluation.run(judge=True)
    progress = evaluation.progress_snapshot()
    judge_steps = [s for s in progress["steps"] if s["id"].startswith("judge:")]
    assert len(judge_steps) == len(DEMO_CASES) * METRIC_COUNT
    assert all(s["state"] == "skipped" for s in judge_steps)
    assert progress["total_steps"] == len(DEMO_CASES) * (1 + METRIC_COUNT)


def test_an_unavailable_judge_is_stated_in_the_log_and_the_total_shrinks(monkeypatch):
    evaluation = EvaluationService(FakeInvestigations(), Settings(_env_file=None))
    monkeypatch.setattr(evaluation, "status", lambda: {"deepeval_installed": False, "judge_configured": False})
    evaluation.run(judge=True)
    progress = evaluation.progress_snapshot()
    assert progress["total_steps"] == len(DEMO_CASES)
    assert any("could not start" in e["text"] for e in progress["events"])
    assert evaluation.latest["judge_status"].startswith("unavailable")


def test_the_api_starts_a_background_run_and_refuses_a_second(tmp_path):
    settings = Settings(_env_file=None, claims_database_path=tmp_path / "eval.sqlite",
                        claims_data_path=tmp_path / "missing.json", claims_artifact_dir=tmp_path / "models")
    app = create_app(settings)
    with TestClient(app) as client:
        first = client.post("/api/evaluations/run", json={"judge": False, "background": True})
        assert first.status_code == 200 and first.json()["progress"]["state"] in ("running", "done")
        if first.json()["progress"]["state"] == "running":
            assert client.post("/api/evaluations/run", json={"background": True}).status_code == 409
        deadline = time.monotonic() + 60
        while client.get("/api/evaluations/status").json()["progress"]["state"] == "running":
            assert time.monotonic() < deadline
            time.sleep(0.1)
        done = client.get("/api/evaluations/status").json()
        assert done["progress"]["state"] == "done" and done["total"] == len(DEMO_CASES)
        assert done["judge_requested"] is False


class _FakeMetric:
    """Stands in for a DeepEval metric; the custom one carries DeepEval's '[GEval]' display suffix."""

    def __init__(self, name):
        self.__name__ = name
        self.threshold = 0.5

    def measure(self, case):
        self.score, self.reason = 0.8, "fine"


def test_the_real_judge_loop_reports_one_step_per_metric_even_with_deepevals_display_names(tmp_path, monkeypatch):
    pytest.importorskip("deepeval")
    from deepeval import metrics, test_case

    monkeypatch.setattr(metrics, "FaithfulnessMetric", lambda **kw: _FakeMetric("Faithfulness"))
    monkeypatch.setattr(metrics, "ContextualRelevancyMetric", lambda **kw: _FakeMetric("Contextual Relevancy"))
    monkeypatch.setattr(metrics, "GEval", lambda **kw: _FakeMetric(kw["name"] + " [GEval]"))
    monkeypatch.setattr(test_case, "LLMTestCase", lambda **kw: SimpleNamespace(**kw))
    settings = Settings(_env_file=None, claims_database_path=tmp_path / "j.sqlite",
                        claims_data_path=tmp_path / "missing.json", claims_artifact_dir=tmp_path / "models",
                        nvidia_api_key="fake-test", deepeval_model="judge-test")
    app = create_app(settings)
    with TestClient(app):
        evaluation = EvaluationService(app.state.service, settings)
        monkeypatch.setattr(evaluation, "status", lambda: {"deepeval_installed": True, "judge_configured": True})
        evaluation.run(judge=True)
    progress = evaluation.progress_snapshot()
    expected = len(DEMO_CASES) * (1 + METRIC_COUNT)
    assert len(progress["steps"]) == expected and progress["total_steps"] == expected
    assert progress["done_steps"] == expected and all(s["state"] == "done" for s in progress["steps"])
    assert not any("GEval" in s["label"] or "GEval" in s["id"] for s in progress["steps"])
    assert evaluation.latest["judge_status"] == "completed" and evaluation.latest["judge_completed_metrics"] == 12
    assert any("scored 0.80" in e["text"] for e in progress["events"])
