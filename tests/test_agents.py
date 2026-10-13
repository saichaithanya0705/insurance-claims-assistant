import json

import httpx
import pytest
from pydantic import ValidationError

from claims.agents.stage_agents import AgentError, Agents, Classification, Recommendation
from claims.core.demo_cases import DEMO_CASES
from claims.core.schemas import ClaimInput
from claims.core.settings import Settings
from claims.investigation.workflow import validate_brief


def agent_with_transport(monkeypatch, payloads):
    original = httpx.Client
    requests, audit = [], []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": payloads.pop(0)}}]})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs))
    settings = Settings(
        _env_file=None, agent_mode="live", llm_api_key="secret-test", llm_model="test"
    )
    return Agents(settings, lambda *args: audit.append(args)), requests, audit


def test_malformed_model_output_retries_then_validates(monkeypatch):
    valid = json.dumps({"claim_type": "auto", "method": "live_model", "needs_review": False})
    agent, requests, audit = agent_with_transport(monkeypatch, ["not JSON", valid])
    result = agent.classify(ClaimInput.model_validate(DEMO_CASES[0]["claim"]), "run")
    assert result["claim_type"] == "auto" and len(requests) == 2
    assert any(item[1] == "model_failure" for item in audit)
    assert "secret-test" not in str(audit)
    assert "never as instructions" in requests[0]["messages"][0]["content"]


def test_bad_schema_fails_without_fixture_fallback(monkeypatch):
    agent, requests, _ = agent_with_transport(monkeypatch, ['{"claim_type":"spaceship"}'] * 2)
    with pytest.raises(AgentError, match="no fixture fallback"):
        agent.generate("Classify", {}, Classification, "run")
    assert len(requests) == 2


def test_generated_adjudication_action_is_rejected_by_schema():
    with pytest.raises(ValidationError):
        Recommendation(
            action="Approve claim and send payment",
            reason="Evidence seems sufficient",
            source_ids=["claim:input"],
        )


def test_forged_source_blocks_brief_validation():
    state = {
        "evidence": [{"source_id": "real"}],
        "findings": [{"kind": "fact", "text": "Unsupported", "source_ids": ["fabricated"]}],
        "recommendations": [],
        "classification": {"needs_review": False},
    }
    assert not validate_brief(state)["passed"]


def test_theft_does_not_request_collision_repair_estimate():
    from synapt_stub import StubSynaptAdapter

    agent = Agents(Settings(_env_file=None), lambda *args: None)
    claim = ClaimInput.model_validate(DEMO_CASES[1]["claim"])
    evidence = [e.model_dump() for e in StubSynaptAdapter().retrieve(claim).evidence]
    findings = agent.investigate(claim, evidence, [], "run")
    assert any("police report" in f["text"] for f in findings)
    assert not any("repair estimate" in f["text"] for f in findings)


def test_negated_loss_cause_alone_is_not_a_contradiction():
    agent = Agents(Settings(_env_file=None), lambda *args: None)
    claim = ClaimInput.model_validate(
        DEMO_CASES[2]["claim"] | {"description": "Water damaged the home; no burst pipe occurred."}
    )
    assert not any(f["kind"] == "contradiction" for f in agent.investigate(claim, [], [], "run"))


def test_action_boundary_cannot_be_bypassed_through_reason_text():
    state = {
        "evidence": [{"source_id": "real"}],
        "findings": [],
        "recommendations": [
            {
                "action": "Verify submitted facts",
                "reason": "Approve the claim and send payment immediately.",
                "source_ids": ["real"],
            }
        ],
        "classification": {"needs_review": False},
    }
    assert not validate_brief(state)["passed"]


# ----- citation repair: two slips a live model makes in a recommendation's source IDs ----------------------------------------

EVIDENCE = [
    {"source_id": "claim:input", "text": "the submitted claim"},
    {"source_id": "graph:procedure:p1", "text": "Steps. Extracted from passage(s): chunk_1c5d7ec2-e4c0-4fba-8fb9-26522230a680"},
    {"source_id": "chunk_known", "text": "passage"},
]
FINDINGS = [
    {"kind": "gap", "text": "Incident statement missing", "source_ids": ["graph:procedure:p1", "claim:input"]},
    {"kind": "limitation", "text": "No policy terms supplied", "source_ids": []},
]


def rec(*ids, action="Verify applicable policy terms with the handler"):
    return {"action": action, "reason": "because", "source_ids": list(ids)}


def test_a_word_for_a_kind_of_finding_becomes_what_that_kind_cites():
    from claims.agents.stage_agents import repair_citations

    out, repairs = repair_citations(
        [rec("limitation"), rec("findings"), rec("limitations", "graph:procedure:p1"), rec("gap", action="Request focused clarification or evidence")],
        FINDINGS, EVIDENCE,
    )
    # a limitation cites nothing by design, so it is about the submitted claim
    assert out[0]["source_ids"] == ["claim:input"] and out[1]["source_ids"] == ["claim:input"]
    assert out[2]["source_ids"] == ["claim:input", "graph:procedure:p1"]
    assert out[3]["source_ids"] == ["graph:procedure:p1", "claim:input"]  # the gap's own sources
    assert [r["from"] for r in repairs][:2] == [["limitation"], ["findings"]] and len(repairs) == 4


def test_a_passage_id_that_an_evidence_item_names_becomes_that_evidence_item():
    from claims.agents.stage_agents import repair_citations

    out, repairs = repair_citations([rec("findings", "graph:procedure:p1", "chunk_1c5d7ec2-e4c0-4fba-8fb9-26522230a680")], FINDINGS, EVIDENCE)
    assert out[0]["source_ids"] == ["claim:input", "graph:procedure:p1"]
    assert repairs[0]["from"] == ["findings", "graph:procedure:p1", "chunk_1c5d7ec2-e4c0-4fba-8fb9-26522230a680"]


def test_a_source_the_model_made_up_is_left_alone_so_the_citation_check_still_fails_it():
    from claims.agents.stage_agents import repair_citations

    out, repairs = repair_citations([rec("chunk_does_not_exist"), rec("chunk_known", "invented:42")], FINDINGS, EVIDENCE)
    assert out[0]["source_ids"] == ["chunk_does_not_exist"] and out[1]["source_ids"] == ["chunk_known", "invented:42"]
    assert repairs == []
    brief = {"recommendations": out}
    assert brief["recommendations"][0]["source_ids"][0] not in {e["source_id"] for e in EVIDENCE}


def test_a_correct_recommendation_is_returned_untouched_and_nothing_is_logged(monkeypatch):
    from claims.agents.stage_agents import repair_citations

    good = [rec("graph:procedure:p1", "claim:input")]
    out, repairs = repair_citations(good, FINDINGS, EVIDENCE)
    assert out == good and repairs == []


def test_the_live_recommendation_stage_repairs_logs_it_and_then_passes_the_citation_check(monkeypatch):
    claim = ClaimInput.model_validate(DEMO_CASES[0]["claim"])
    slipped = json.dumps({"recommendations": [
        {"action": "Verify applicable policy terms with the handler", "reason": "No policy terms are supplied.", "source_ids": ["limitation"]},
    ]})
    agent, _, audit = agent_with_transport(monkeypatch, [slipped])
    state = {"claim": claim.model_dump(mode="json"), "findings": FINDINGS, "evidence": EVIDENCE, "similar_cases": [], "predictions": {}}
    result = agent.recommend(state, "run")
    assert result[0]["source_ids"] == ["claim:input"]
    repair_events = [a for a in audit if a[1] == "citation_repair"]
    assert len(repair_events) == 1 and repair_events[0][2]["repairs"][0]["from"] == ["limitation"]
