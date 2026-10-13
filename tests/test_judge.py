import json

import pytest

from claims.core.settings import Settings
from claims.evaluation.judge import PASS_SCORE, JudgeVerdict, LLMJudge
from claims.llm.client import CompletionError

STATE = {
    "claim": {"description": "Rear-ended at a junction", "claim_amount": 8500},
    "evidence": [
        {"source_id": "claim:input", "title": "Submitted claim", "text": "x" * 5000,
         "provenance": "user_input"},
        {"source_id": "sop-1", "title": "SOP", "text": "Request an incident statement.",
         "provenance": "synthetic_fixture"},
    ],
    "findings": [{"kind": "fact", "text": "Claimed $8,500.", "source_ids": ["claim:input"]}],
    "recommendations": [
        {"action": "Verify submitted facts", "reason": "Unverified", "source_ids": ["claim:input"]}
    ],
}


def settings(**changes):
    values = {
        "_env_file": None,
        "agent_mode": "live",
        "nvidia_api_key": "nvapi-test-key",
        "llm_model": "nvidia/author-model",
        "judge_mode": "inline",
        "judge_model": "google/independent-judge",
    }
    return Settings(**(values | changes))


def verdict(**changes):
    values = {
        "grounded": True,
        "boundary_respected": True,
        "recommendations_supported": True,
        "score": 0.9,
        "issues": [],
        "summary": "Findings follow the cited evidence.",
    }
    return JudgeVerdict(**(values | changes))


class Calls(list):
    """Recorded judge requests; ``result`` is what the stubbed model returns next."""


@pytest.fixture
def calls(monkeypatch):
    seen = Calls()
    seen.result = {"value": verdict()}

    def complete(
        self, messages, schema=None, *, model=None, run_id="x", role="judge", timeout=None, attempts=2
    ):
        seen.append(
            {"messages": messages, "model": model, "role": role, "timeout": timeout, "attempts": attempts}
        )
        return seen.result["value"]

    monkeypatch.setattr("claims.evaluation.judge.CompletionClient.complete", complete)
    return seen


def test_judge_is_skipped_unless_inline_and_live(calls):
    off = LLMJudge(settings(judge_mode="off"), lambda *a: None).evaluate(STATE, "run")
    assert off["status"] == "skipped" and "disabled" in off["reason"]
    fixture = LLMJudge(settings(agent_mode="fixture"), lambda *a: None).evaluate(STATE, "run")
    assert fixture["status"] == "skipped" and "fixture" in fixture["reason"]
    assert calls == []  # no model request was made


def test_a_different_model_judges_and_the_verdict_is_structured(calls):
    result = LLMJudge(settings(), lambda *a: None).evaluate(STATE, "run-1")
    assert result["status"] == "completed" and result["passed"] is True
    assert result["model"] == "google/independent-judge" and result["independent"] is True
    assert calls[0]["model"] == "google/independent-judge" and calls[0]["role"] == "judge"
    # Advisory and run in the background: a bounded per-attempt budget (60 s; 35 s failed about a
    # quarter of live verdicts on endpoint latency) and at most two attempts.
    assert calls[0]["timeout"] == 60 and calls[0]["attempts"] == 2
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert {e["source_id"] for e in payload["evidence"]} == {"claim:input", "sop-1"}
    assert len(payload["evidence"][0]["text"]) == 5000  # no silently discarded evidence
    assert "untrusted" in calls[0]["messages"][0]["content"]


def test_judge_falls_back_but_never_claims_independence_from_the_author(calls):
    same = LLMJudge(settings(judge_model="", deepeval_model=""), lambda *a: None).evaluate(STATE, "r")
    assert same["model"] == "nvidia/author-model" and same["independent"] is False
    via_deepeval = LLMJudge(settings(judge_model="", deepeval_model="meta/other"), lambda *a: None)
    assert via_deepeval.evaluate(STATE, "r")["model"] == "meta/other"


@pytest.mark.parametrize(
    "changes",
    [
        {"grounded": False},
        {"boundary_respected": False},
        {"recommendations_supported": False},
        {"score": PASS_SCORE - 0.01},
    ],
)
def test_any_failed_dimension_flags_the_brief(calls, changes):
    calls.result["value"] = verdict(issues=["Finding 2 cites nothing relevant"], **changes)
    result = LLMJudge(settings(), lambda *a: None).evaluate(STATE, "run")
    assert result["status"] == "completed" and result["passed"] is False
    assert result["issues"] == ["Finding 2 cites nothing relevant"]


def test_provider_failure_is_reported_without_details_and_does_not_raise(monkeypatch):
    def broken(self, *args, **kwargs):
        raise CompletionError("secret-detail-from-provider")

    monkeypatch.setattr("claims.evaluation.judge.CompletionClient.complete", broken)
    result = LLMJudge(settings(), lambda *a: None).evaluate(STATE, "run")
    assert result["status"] == "failed" and "secret-detail" not in json.dumps(result)


def test_verdict_schema_rejects_out_of_range_scores_and_unknown_fields():
    with pytest.raises(ValueError):
        verdict(score=1.5)
    with pytest.raises(ValueError):
        JudgeVerdict(**verdict().model_dump(), extra="x")


@pytest.mark.parametrize("changes", [{"grounded": "true"}, {"score": "0.9"},
                                    {"score": float("nan")}, {"score": float("inf")}])
def test_verdict_schema_rejects_coercion_and_nonfinite_scores(changes):
    with pytest.raises(ValueError):
        verdict(**changes)


def test_concrete_issues_cannot_coexist_with_a_passing_verdict(calls):
    calls.result["value"] = verdict(issues=["Claim amount was invented."])
    result = LLMJudge(settings(), lambda *a: None).evaluate(STATE, "run")
    assert result["status"] == "completed" and result["passed"] is False


@pytest.mark.parametrize("mutation", ["unknown_citation", "duplicate_source", "empty_text"])
def test_invalid_brief_is_not_sent_to_judge(calls, mutation):
    from copy import deepcopy

    state = deepcopy(STATE)
    if mutation == "unknown_citation":
        state["findings"][0]["source_ids"] = ["invented"]
    elif mutation == "duplicate_source":
        state["evidence"].append(dict(state["evidence"][0]))
    else:
        state["evidence"][0]["text"] = " "
    result = LLMJudge(settings(), lambda *a: None).evaluate(state, "run")
    assert result["status"] == "failed" and calls == []


def test_oversize_context_fails_visibly_instead_of_truncating(calls):
    from copy import deepcopy

    from claims.evaluation.judge import MAX_EVIDENCE_CHARS

    state = deepcopy(STATE)
    state["evidence"][0]["text"] = "x" * (MAX_EVIDENCE_CHARS + 1)
    result = LLMJudge(settings(), lambda *a: None).evaluate(state, "run")
    assert result["status"] == "failed" and "context budget" in result["reason"]
    assert calls == []


@pytest.mark.parametrize("text", [
    "A repair estimate was provided and reviewed.",
    "Approve the claim and send payment.",
])
def test_judge_cannot_override_known_content_guardrail_failure(calls, text):
    from copy import deepcopy

    state = deepcopy(STATE)
    state["findings"][0]["text"] = text
    result = LLMJudge(settings(), lambda *a: None).evaluate(state, "run")
    assert result["status"] == "failed" and "content" in result["reason"]
    assert calls == []


# --- background judge: the brief is returned immediately, the verdict is merged later -------------

import threading
from pathlib import Path

from fastapi.testclient import TestClient

from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES


class FakeJudge:
    """Stands in for LLMJudge: enabled, slow until released, returning a canned verdict."""

    def __init__(self, outcome="completed"):
        self.release, self.outcome = threading.Event(), outcome

    def skipped(self):
        return None

    def pending(self):
        return {"status": "pending", "model": "fake/judge", "independent": True, "reason": "running"}

    def evaluate(self, snapshot, run_id):
        assert set(snapshot) == {"claim", "evidence", "findings", "recommendations"}
        self.release.wait(10)
        if self.outcome == "raise":
            raise RuntimeError("provider exploded")
        return {
            "status": "completed", "passed": True, "score": 0.9, "model": "fake/judge",
            "independent": True, "grounded": True, "boundary_respected": True,
            "recommendations_supported": True, "issues": [], "summary": "Looks grounded.",
        }


def background_app(tmp_path, judge):
    settings = Settings(
        _env_file=None,
        claims_database_path=tmp_path / "runtime.sqlite",
        claims_data_path=Path("absent.json"),
        claims_artifact_dir=tmp_path / "models",
    )
    app = create_app(settings)
    app.state.service.judge_agent = judge
    return app


def test_brief_is_returned_at_once_and_the_verdict_arrives_later(tmp_path):
    judge = FakeJudge()
    app = background_app(tmp_path, judge)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        assert run["status"] == "awaiting_review"  # not held up by the judge
        assert run["judge"]["status"] == "pending"
        assert any(t["stage"] == "judge" for t in run["trace"])
        assert client.get(f"/api/investigations/{run['run_id']}").json()["judge"]["status"] == "pending"
        judge.release.set()
        app.state.service.wait_for_judges()
        saved = client.get(f"/api/investigations/{run['run_id']}").json()
        assert saved["judge"]["status"] == "completed" and saved["judge"]["score"] == 0.9
        audit = client.get(f"/api/investigations/{run['run_id']}/audit").json()["items"]
        assert any(item["kind"] == "judge_verdict" for item in audit)


def test_a_later_review_save_cannot_erase_a_finished_verdict(tmp_path):
    judge = FakeJudge()
    app = background_app(tmp_path, judge)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        judge.release.set()
        app.state.service.wait_for_judges()
        # The review resumes the graph, whose checkpoint still says "pending"; the save must keep
        # the verdict that arrived in the meantime.
        reviewed = client.post(
            f"/api/investigations/{run['run_id']}/review",
            json={"decision": "accept_brief", "note": "Sources and limits checked"},
        )
        assert reviewed.status_code == 200 and reviewed.json()["status"] == "reviewed"
        assert client.get(f"/api/investigations/{run['run_id']}").json()["judge"]["status"] == "completed"


def test_a_crashing_judge_is_recorded_as_failed_and_never_breaks_the_run(tmp_path):
    judge = FakeJudge(outcome="raise")
    app = background_app(tmp_path, judge)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        judge.release.set()
        app.state.service.wait_for_judges()
        saved = client.get(f"/api/investigations/{run['run_id']}").json()
        assert saved["status"] == "awaiting_review"
        assert saved["judge"]["status"] == "failed" and "provider exploded" not in str(saved["judge"])


def test_disabled_judge_runs_no_thread(tmp_path):
    app = background_app(tmp_path, LLMJudge(app_settings := Settings(_env_file=None), lambda *a: None))
    assert app_settings.judge_mode == "off"
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        assert run["judge"]["status"] == "skipped" and "disabled" in run["judge"]["reason"]
        assert app.state.service.judge_threads == []
