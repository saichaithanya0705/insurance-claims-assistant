"""The Supervisor Agent: the summary, the one send-back, and the limits on both."""

import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from test_observability import live_settings

from claims.agents import access
from claims.agents.stage_agents import AgentError
from claims.agents.supervisor import (
    Supervisor,
    SupervisorReview,
    feedback_for,
    repairable,
    summary_problem,
)
from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.settings import Settings
from claims.llm.client import CompletionError
from claims.storage.run_store import Store

DOC_ISSUE = "Document names describe reported availability only; document content was not received or reviewed."
CLASS_ISSUE = "Claim classification needs manual review."
EVIDENCE_ISSUE = "No external evidence was retrieved; manual investigation required."


# ----- what can be fixed, and what a summary may say ---------------------------------------------------------------------


def test_only_problems_that_rewriting_the_findings_can_fix_allow_a_send_back():
    assert repairable({"passed": True, "issues": []}) == []
    assert repairable({"passed": False, "issues": [DOC_ISSUE]}) == [DOC_ISSUE]
    assert repairable({"passed": False, "issues": [CLASS_ISSUE]}) == []  # an uncertain category is for the handler
    assert repairable({"passed": False, "issues": [EVIDENCE_ISSUE]}) == []  # missing evidence cannot be rewritten into existence
    assert repairable({"passed": False, "issues": [CLASS_ISSUE, DOC_ISSUE]}) == [DOC_ISSUE]


WORK = {
    "claim": {"claim_type": "auto", "claim_amount": 8500, "deductible": 500, "state": "TX"},
    "findings": [{"kind": "gap", "text": "No police report is on file for the 12 reported incidents.", "source_ids": ["x"]}],
    "recommendations": [{"action": "Request focused clarification or evidence", "reason": "Ask for the police report.", "source_ids": ["x"]}],
    "priority": {"tier": "Low", "score": 10, "components": []},
}
GOOD = "This auto claim reports $8,500 with a $500 deductible. The main gap is a missing police report, so the handler should request it. Priority is low."


def test_a_clean_summary_is_kept():
    assert summary_problem(GOOD, WORK) is None


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("This claim is covered and should be paid.", "coverage"),
        ("The police report was provided and reviewed, so the claim looks fine.", "document"),
        ("The handler should approve the claim.", "decision"),
        ("Synapt found the procedure for this claim, which is auto.", "vendor"),
        ("The knowledge base was searched by a model for this auto claim.", None),  # not a vendor word: allowed
        ("The claim is for $9,999 and has a $500 deductible.", "number"),  # a figure that is not in the brief
        ("The claimant has provided an incident statement but no police report.", "document"),
        ("x " * 600, "long"),
    ],
)
def test_a_summary_that_crosses_a_line_is_refused_with_the_reason(text, why):
    problem = summary_problem(text, WORK)
    assert (problem is None) == (why is None)
    if why:
        assert why in problem


def test_the_feedback_sent_back_is_the_checks_own_words_then_the_supervisors():
    text = feedback_for([DOC_ISSUE], "Say that the claimant reports the documents as available.")
    assert text.startswith("Problems the checks found with your draft:") and DOC_ISSUE in text and "claimant reports" in text


def test_the_sentences_that_cite_nothing_real_are_named_in_the_feedback_and_for_the_supervisor():
    from claims.agents.supervisor import citation_problems

    work = {
        "evidence": [{"source_id": "real"}],
        "findings": [{"kind": "gap", "text": "Fine.", "source_ids": ["real"]}, {"kind": "gap", "text": "Made up.", "source_ids": ["ghost", "real"]}],
        "recommendations": [{"action": "Uncited action", "reason": "r", "source_ids": []}],
    }
    problems = citation_problems(work)
    assert problems == [
        {"kind": "finding", "text": "Made up.", "unknown_source_ids": ["ghost"]},
        {"kind": "recommendation", "text": "Uncited action", "unknown_source_ids": []},
    ]
    text = feedback_for(["A finding cites an unknown source."], "", problems)
    assert "'Made up.' cites ['ghost'], which is not a supplied source" in text and "'Uncited action' cites no source" in text


# ----- the stage, with the model and the revision stood in --------------------------------------------------------------


class Model:
    """Answers each review from a script and records what it was shown."""

    def __init__(self, *answers):
        self.answers, self.seen = list(answers), []

    def __call__(self, work, revisions, allowed, feedback=None):
        self.seen.append({"revisions": revisions, "allowed": allowed, "issues": work["validation"]["issues"], "feedback": feedback})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def review(action="finalize", summary=GOOD, instructions=""):
    return SupervisorReview(action=action, instructions=instructions, summary=summary)


def brief(issues=(), passed=None):
    return {
        "run_id": "run-1",
        "claim": WORK["claim"] | {"description": "Rear-ended at a light.", "provided_documents": ["photos"], "incident_date": "2026-09-01", "claim_filed_date": "2026-09-02"},
        "evidence": [{"source_id": "x"}, {"source_id": "claim:input"}],
        "findings": [{"kind": "limitation", "text": "From retrieval.", "source_ids": []}, {"kind": "fact", "text": "The photos were provided.", "source_ids": ["claim:input"]}],
        "investigator_findings": [{"kind": "fact", "text": "The photos were provided.", "source_ids": ["claim:input"]}],
        "recommendations": [{"action": "Verify applicable policy terms with the handler", "reason": "r", "source_ids": ["x"]}],
        "priority": WORK["priority"],
        "predictions": {"available": False},
        "classification": {"claim_type": "auto", "needs_review": False},
        "similar_cases": [],
        "validation": {"passed": not issues if passed is None else passed, "issues": list(issues), "checks": []},
        "trace": [],
    }


def supervisor_with(monkeypatch, model, revise=None, **settings):
    base = {"_env_file": None, "agent_mode": "live", "llm_api_key": "secret-test"}
    revisions = []

    def revise_brief(work, feedback):
        revisions.append(feedback)
        if isinstance(revise, Exception):
            raise revise
        return revise(work) if revise else work

    service = SimpleNamespace(settings=Settings(**(base | settings)), store=SimpleNamespace(event=lambda *a, **k: None), revise_brief=revise_brief)
    supervisor = Supervisor(service)
    monkeypatch.setattr(Supervisor, "_ask", lambda self, work, revisions, allowed, feedback=None: model(work, revisions, allowed, feedback))
    return supervisor, revisions


def fixed(work):
    """What a good revision returns: the same brief with the findings rewritten and the checks now passing."""
    work = deepcopy(work)
    work["findings"][1] = {"kind": "fact", "text": "The claimant reports photos are available.", "source_ids": ["claim:input"]}
    work["investigator_findings"] = [work["findings"][1]]
    work["validation"] = {"passed": True, "issues": [], "checks": []}
    return work


def test_a_brief_that_passed_is_summarised_and_left_alone(monkeypatch):
    supervisor, revisions = supervisor_with(monkeypatch, Model(review()))
    update = supervisor.supervise(brief())
    assert update["supervisor"]["status"] == "done" and update["supervisor"]["summary"] == GOOD and update["supervisor"]["revised"] is False
    assert revisions == [] and "findings" not in update  # nothing about the brief changed


def test_a_model_that_asks_for_a_fix_when_the_checks_passed_is_not_allowed_one(monkeypatch):
    model = Model(review("revise", instructions="Make it better."))
    supervisor, revisions = supervisor_with(monkeypatch, model)
    update = supervisor.supervise(brief())
    assert revisions == [] and update["supervisor"]["revised"] is False and update["supervisor"]["summary"] == GOOD
    assert model.seen == [{"revisions": 0, "allowed": False, "issues": [], "feedback": None}]


def test_a_brief_that_failed_for_a_reason_rewriting_cannot_fix_is_not_sent_back(monkeypatch):
    supervisor, revisions = supervisor_with(monkeypatch, Model(review("revise", instructions="Try again.")))
    update = supervisor.supervise(brief([CLASS_ISSUE]))
    assert revisions == [] and update["supervisor"]["revised"] is False


def test_a_fixable_brief_is_sent_back_even_if_the_model_answers_finalize_because_the_repair_is_policy(monkeypatch):
    model = Model(review("finalize"), review("finalize"))
    supervisor, revisions = supervisor_with(monkeypatch, model, revise=fixed)
    update = supervisor.supervise(brief([DOC_ISSUE]))
    assert len(revisions) == 1 and DOC_ISSUE in revisions[0]
    assert update["supervisor"]["revised"] is True and update["supervisor"]["revision"]["passed_after"] is True


def test_a_fixable_brief_is_sent_back_once_with_the_checks_words_and_the_fixed_brief_replaces_it(monkeypatch):
    model = Model(review("revise", summary=GOOD, instructions="Say the claimant reports the photos as available."), review("finalize"))
    supervisor, revisions = supervisor_with(monkeypatch, model, revise=fixed)
    update = supervisor.supervise(brief([DOC_ISSUE]))
    assert len(revisions) == 1 and DOC_ISSUE in revisions[0] and "claimant reports the photos" in revisions[0]
    record = update["supervisor"]
    assert record["revised"] is True and record["revision"]["passed_after"] is True and record["summary"] == GOOD
    # the brief that goes on is the fixed one, and its status follows the new checks
    assert update["findings"][1]["text"] == "The claimant reports photos are available." and update["findings"][0]["text"] == "From retrieval."
    assert update["validation"]["passed"] is True and update["status"] == "awaiting_review"
    assert [s["revisions"] for s in model.seen] == [0, 1] and [s["allowed"] for s in model.seen] == [True, False]


def test_it_is_sent_back_once_however_often_the_model_asks(monkeypatch):
    model = Model(review("revise", instructions="a"), review("revise", instructions="b"))
    supervisor, revisions = supervisor_with(monkeypatch, model, revise=lambda w: w)  # the fix does not help
    update = supervisor.supervise(brief([DOC_ISSUE]))
    assert len(revisions) == 1 and update["supervisor"]["revised"] is True and update["supervisor"]["revision"]["passed_after"] is False
    assert update["status"] == "needs_manual_review"  # still flagged, and the handler is told so


def test_a_revision_that_cannot_complete_leaves_the_brief_as_it_was(monkeypatch):
    model = Model(review("revise", instructions="Fix it."), review("finalize"))
    supervisor, revisions = supervisor_with(monkeypatch, model, revise=AgentError("model down"))
    update = supervisor.supervise(brief([DOC_ISSUE]))
    assert len(revisions) == 1 and update["supervisor"]["revised"] is False and update["supervisor"]["revision"]["failure"] == "AgentError"
    assert "findings" not in update and update["supervisor"]["summary"] == GOOD


def test_when_the_model_cannot_be_reached_the_brief_stands_without_a_summary(monkeypatch):
    supervisor, _ = supervisor_with(monkeypatch, Model(CompletionError("down")))
    update = supervisor.supervise(brief([DOC_ISSUE]))
    assert update["supervisor"]["status"] == "unavailable" and update["supervisor"]["summary"] is None and "findings" not in update


BAD = "This claim is covered and the handler should pay it promptly."


def test_a_refused_summary_is_asked_for_once_more_with_the_reason_and_the_second_is_used_if_it_passes(monkeypatch):
    model = Model(review(summary=BAD), review(summary=GOOD))
    supervisor, _ = supervisor_with(monkeypatch, model)
    record = supervisor.supervise(brief())["supervisor"]
    assert record["summary"] == GOOD and record["summary_rejected"] is None
    assert model.seen[1]["feedback"].startswith("Your summary was refused because it states or implies a coverage conclusion")


def test_a_summary_that_fails_the_text_checks_twice_is_dropped_and_the_reason_and_text_kept_for_administrators(monkeypatch):
    model = Model(review(summary=BAD), review(summary=BAD))
    supervisor, _ = supervisor_with(monkeypatch, model)
    record = supervisor.supervise(brief())["supervisor"]
    assert record["summary"] is None and "coverage" in record["summary_rejected"] and record["rejected_text"] == BAD and record["status"] == "done"
    assert len(model.seen) == 2  # asked once more, not again


def test_a_date_written_two_ways_is_the_same_number():
    work = {"claim": {"incident_date": "2026-09-01"}, "findings": [], "recommendations": [], "priority": {}}
    assert summary_problem("The incident was on September 1, 2026 and is an auto claim.", work) is None


def test_it_does_nothing_in_fixture_mode_or_when_switched_off(monkeypatch):
    for settings in ({"agent_mode": "fixture"}, {"agent_supervisor": False}):
        model = Model()  # would fail if asked
        supervisor, _ = supervisor_with(monkeypatch, model, **settings)
        record = supervisor.supervise(brief())["supervisor"]
        assert record["status"] == "skipped" and record["summary"] is None


def test_the_supervisor_runs_as_its_own_agent_with_no_tools():
    from claims.agents import roster

    spec = roster.agent("supervisor")
    assert spec.method == "model" and spec.stage == "supervise" and not spec.tools and spec.model_purpose == "supervision"
    with access.acting_as("supervisor"), pytest.raises(access.AccessDenied):
        access.authorize("trident_get_chunks")


# ----- the real revision, and whole runs ----------------------------------------------------------------------------------


def test_a_real_revision_rewrites_only_what_the_investigator_wrote_and_rechecks_everything(tmp_path):
    app = create_app(
        Settings(_env_file=None, claims_database_path=tmp_path / "r.sqlite", claims_data_path=tmp_path / "absent.json", claims_artifact_dir=tmp_path / "models", claims_search_enabled=False)
    )
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        service = app.state.service
        kept = len(run["findings"]) - len(run["investigator_findings"])
        broken = run | {"findings": [*run["findings"][:kept], {"kind": "fact", "text": "The police report was provided.", "source_ids": ["claim:input"]}], "investigator_findings": [{"kind": "fact", "text": "The police report was provided.", "source_ids": ["claim:input"]}]}
        calls = []
        original = service.agents.investigate
        service.agents.investigate = lambda *a, **k: calls.append(k.get("revision")) or original(*a)
        fixed_work = service.revise_brief(broken, "Problems the checks found with your draft:\n- X")
    assert calls == ["Problems the checks found with your draft:\n- X"]
    assert fixed_work["findings"][:kept] == run["findings"][:kept]  # what retrieval reported is kept
    assert all("police report was provided" not in f["text"] for f in fixed_work["findings"])
    assert fixed_work["validation"]["passed"] is True and fixed_work["priority"] and fixed_work["recommendations"]


def whole_run_mock(monkeypatch, supervisor_actions):
    """A model that writes a bad draft first (a fact that says a document was provided), a clean one when asked to fix it, and a
    Supervisor that follows ``supervisor_actions`` in turn."""
    original = httpx.Client
    state = {"investigations": 0, "reviews": 0, "feedback_seen": None}

    def respond(request):
        body = json.loads(request.content)
        system, user = body["messages"][0]["content"], body["messages"][-1]["content"]
        if "independent reviewer" in system:
            content = {"grounded": True, "boundary_respected": True, "recommendations_supported": True, "score": 0.9, "issues": [], "summary": "Fine."}
        elif "You review a finished claims brief" in system:
            action = supervisor_actions[min(state["reviews"], len(supervisor_actions) - 1)]
            state["reviews"] += 1
            content = {"action": action, "instructions": "Say the claimant reports the documents as available." if action == "revise" else "",
                       "summary": "The brief reports an auto claim and the handler should check the policy terms and what the claimant reports as available. Priority is low."}
        elif "Classify into" in system:
            content = {"claim_type": "auto", "method": "live_model", "needs_review": False}
        elif "Identify useful" in system:
            state["investigations"] += 1
            state["feedback_seen"] = "reviewer_feedback" in user
            text = "The claimant reports the police report is available." if "reviewer_feedback" in user else "The police report was provided and reviewed."
            content = {"findings": [{"kind": "fact", "text": text, "source_ids": ["claim:input"]}, {"kind": "limitation", "text": "Outcomes do not establish coverage.", "source_ids": []}]}
        else:
            content = {"recommendations": [{"action": "Verify applicable policy terms with the handler", "reason": "Policy wording must be checked.", "source_ids": ["claim:input"]}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}, "finish_reason": "stop"}], "usage": {"total_tokens": 10}})

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr("claims.llm.client.time.sleep", lambda seconds: None)
    return state


def run_whole(tmp_path):
    app = create_app(live_settings(tmp_path))
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        app.state.service.wait_for_judges(30)
    store = Store(app.state.service.settings.claims_database_path)
    try:
        spans = store.spans(run["run_id"])
    finally:
        store.close()
    return run, spans


def test_a_whole_run_whose_first_draft_fails_is_fixed_once_and_ends_with_a_passing_brief_and_a_summary(tmp_path, monkeypatch):
    state = whole_run_mock(monkeypatch, ["revise", "finalize"])
    run, spans = run_whole(tmp_path)
    assert state["investigations"] == 2 and state["feedback_seen"] is True and state["reviews"] == 2
    assert run["status"] == "awaiting_review" and run["validation"]["passed"] is True
    assert all("provided and reviewed" not in f["text"] for f in run["findings"])
    record = run["supervisor"]
    assert record["revised"] is True and record["revision"]["passed_after"] is True and record["summary"]
    # the whole thing happened inside one supervise stage, by the named agents
    stages = [s["name"] for s in spans if s["kind"] == "stage"]
    assert stages.count("supervise") == 1 and stages.count("investigate") == 1
    stage = next(s for s in spans if s["kind"] == "stage" and s["name"] == "supervise")
    below, frontier = set(), {stage["span_id"]}
    while frontier:  # everything that happened under the stage, however deep
        frontier = {s["span_id"] for s in spans if s["parent_id"] in frontier}
        below |= frontier
    inside = {s["attributes"]["agent"] for s in spans if s["kind"] == "agent" and s["span_id"] in below}
    assert {"supervisor", "investigator", "risk_analyst", "recommender", "validator"} <= inside


def test_a_whole_run_is_repaired_even_when_the_model_says_finalize_because_a_fixable_failure_always_gets_its_one_repair(tmp_path, monkeypatch):
    state = whole_run_mock(monkeypatch, ["finalize"])
    run, _ = run_whole(tmp_path)
    assert state["investigations"] == 2 and run["status"] == "awaiting_review" and run["supervisor"]["revised"] is True
    assert run["supervisor"]["summary"]
