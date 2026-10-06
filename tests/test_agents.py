import json

import httpx
import pytest
from pydantic import ValidationError

from claims.agents import AgentError, Agents, Classification, Recommendation
from claims.demo import DEMO_CASES
from claims.models import ClaimInput
from claims.settings import Settings
from claims.workflow import validate_brief


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
    from claims.adapters import FixtureSynaptAdapter

    agent = Agents(Settings(_env_file=None), lambda *args: None)
    claim = ClaimInput.model_validate(DEMO_CASES[1]["claim"])
    evidence = [e.model_dump() for e in FixtureSynaptAdapter().retrieve(claim).evidence]
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
