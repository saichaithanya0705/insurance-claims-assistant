import json

import httpx
import pytest
from pydantic import ValidationError

from claims.agents.stage_agents import Classification
from claims.core.schemas import Finding
from claims.core.settings import Settings
from claims.llm.client import CompletionClient, CompletionError


def mocked(monkeypatch, responses):
    original, requests, audit = httpx.Client, [], []

    def respond(request):
        requests.append(json.loads(request.content))
        status, payload = responses.pop(0)
        return httpx.Response(status, json=payload)

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs))
    monkeypatch.setattr("claims.llm.client.time.sleep", lambda seconds: None)
    settings = Settings(_env_file=None, agent_mode="live", nvidia_api_key="fake-nvidia-secret")
    return CompletionClient(settings, lambda *args: audit.append(args)), requests, audit


def reply(finish_reason="stop", usage=None):
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {"claim_type": "auto", "method": "live_model", "needs_review": False}
                    ),
                    "reasoning_content": "Do not retain this private trace",
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }


def test_nvidia_request_contract_and_safe_optional_telemetry(monkeypatch):
    client, requests, audit = mocked(monkeypatch, [(200, reply(usage=["unexpected"]))])
    assert (
        client.complete([{"role": "user", "content": "Classify"}], Classification).claim_type
        == "auto"
    )
    assert requests[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert requests[0]["max_tokens"] == 4096 and not requests[0]["stream"]
    assert "fake-nvidia-secret" not in str(audit) and "private trace" not in str(audit)
    assert audit[-1][2]["usage"] == {}


def test_nonretryable_authorization_failure_is_safe_and_single_attempt(monkeypatch):
    client, requests, audit = mocked(monkeypatch, [(401, {"error": "fake-nvidia-secret"})])
    with pytest.raises(CompletionError, match="HTTP 401"):
        client.complete([], Classification)
    assert len(requests) == 1 and "fake-nvidia-secret" not in str(audit)


def test_rate_limit_retries_without_losing_schema(monkeypatch):
    client, requests, _ = mocked(monkeypatch, [(429, {}), (200, reply())])
    assert client.complete([], Classification).claim_type == "auto"
    assert len(requests) == 2 and requests[1]["response_format"] == {"type": "json_object"}


def test_truncated_valid_json_is_rejected_and_retried(monkeypatch):
    client, requests, audit = mocked(monkeypatch, [(200, reply("length")), (200, reply())])
    assert client.complete([], Classification).claim_type == "auto"
    assert len(requests) == 2 and audit[1][1] == "model_failure"


def test_nvidia_credential_is_never_selected_for_another_host():
    with pytest.raises(ValidationError, match="LLM_API_KEY"):
        Settings(
            _env_file=None,
            agent_mode="live",
            nvidia_api_key="fake-nvidia-secret",
            llm_base_url="https://example.com/v1",
        )
    settings = Settings(
        _env_file=None,
        agent_mode="live",
        nvidia_api_key="fake-nvidia-secret",
        llm_api_key="fake-generic-secret",
        llm_base_url="https://example.com/v1",
    )
    assert settings.llm_api_key.get_secret_value() == "fake-generic-secret"


def test_nvidia_environment_and_secret_repr(tmp_path):
    env = tmp_path / "test.env"
    env.write_text("AGENT_MODE=live\nNVIDIA_API_KEY=fake-nvidia-secret\nLLM_API_KEY=\n")
    settings = Settings(_env_file=env)
    assert (
        settings.agent_mode == "live"
        and settings.llm_api_key.get_secret_value() == "fake-nvidia-secret"
    )
    assert "fake-nvidia-secret" not in repr(settings)


def test_substantive_finding_requires_citation_and_negative_conflict_is_rejected():
    with pytest.raises(ValidationError, match="supporting source"):
        Finding(kind="fact", text="An uncited asserted fact", source_ids=[])
    with pytest.raises(ValidationError, match="Absence"):
        Finding(kind="contradiction", text="No contradiction found", source_ids=["claim:input"])
    assert Finding(kind="limitation", text="Unknown policy coverage", source_ids=[])


def test_callers_can_shorten_the_budget_and_disable_retries(monkeypatch):
    import httpx

    from claims.core.settings import Settings
    from claims.llm.client import CompletionClient, CompletionError

    seen = []

    class Client:
        def __init__(self, *args, timeout=None, **kwargs):
            seen.append(timeout)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, *args, **kwargs):
            raise httpx.ReadTimeout("slow")

    monkeypatch.setattr("claims.llm.client.httpx.Client", Client)
    monkeypatch.setattr("claims.llm.client.time.sleep", lambda seconds: None)
    settings = Settings(_env_file=None, agent_mode="live", nvidia_api_key="k", llm_timeout_seconds=60)
    client = CompletionClient(settings, lambda *a: None)
    with pytest.raises(CompletionError):
        client.complete([{"role": "user", "content": "x"}], timeout=12, attempts=1)
    assert seen == [12]  # one attempt, with the caller's shorter timeout
    seen.clear()
    with pytest.raises(CompletionError):
        client.complete([{"role": "user", "content": "x"}])
    assert seen == [60, 60]  # default: two attempts at the configured timeout
