"""Claude as the provider behind the brief: the Messages API request, the forced-tool answer, per-role models, retries and secrecy.

The completion client has two providers behind one `complete()`. These tests pin what the Anthropic one sends (a system prompt on its own,
merged user turns, one forced tool whose input schema is the Pydantic schema), how it reads the answer back, which model each role gets,
what is retried, that the key never reaches an audit event or an error, and that the judge stays on its own provider so it stays independent.
"""

import json

import httpx
import pytest

from claims.agents.stage_agents import Agents, Classification, Recommendations
from claims.core.demo_cases import DEMO_CASES
from claims.core.schemas import ClaimInput
from claims.core.settings import Settings
from claims.evaluation.judge import LLMJudge
from claims.llm.client import ANTHROPIC_TOOL, CompletionClient, CompletionError

KEY = "sk-ant-test-secret-1234567890"


def settings(**over):
    base = {
        "_env_file": None, "agent_mode": "live", "llm_provider": "anthropic", "anthropic_api_key": KEY, "llm_api_key": "nvidia-test-key",
        "llm_model": "nvidia/nemotron-3-super-120b-a12b", "anthropic_model": "claude-sonnet-5-5",
        "anthropic_model_classification": "claude-haiku-5-5", "anthropic_model_recommendation": "claude-haiku-5-5",
        "judge_model": "openai/gpt-oss-20b", "judge_mode": "inline",
    }
    return Settings(**(base | over))


def tool_answer(data, stop="tool_use", usage=(100, 20)):
    return httpx.Response(200, json={
        "id": "msg_1", "type": "message", "role": "assistant", "stop_reason": stop,
        "content": [{"type": "tool_use", "id": "toolu_1", "name": ANTHROPIC_TOOL, "input": data}],
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
    })


def text_answer(text):
    return httpx.Response(200, json={
        "type": "message", "role": "assistant", "stop_reason": "end_turn", "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": 5, "output_tokens": 3},
    })


@pytest.fixture
def wire(monkeypatch):
    """Replace the HTTP transport; each request is recorded and answered from the queue (an Exception is raised)."""
    sent, queue = [], []
    original = httpx.Client

    def respond(request):
        body = json.loads(request.content)
        sent.append({"url": str(request.url), "headers": dict(request.headers), "body": body})
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item(body) if callable(item) else item

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs))
    return sent, queue


def client(s=None, audit=None):
    return CompletionClient(s or settings(), (lambda *a: audit.append(a)) if audit is not None else (lambda *a, **k: None))


# ----- what is sent -----------------------------------------------------------------------------------------------------------


def test_the_request_is_a_messages_api_call_with_the_system_prompt_apart_and_one_forced_tool(wire):
    sent, queue = wire
    queue.append(tool_answer({"claim_type": "auto", "method": "live_model", "needs_review": False}))
    out = client().complete(
        [{"role": "system", "content": "You support a claims handler."}, {"role": "user", "content": "A car was rear-ended."}],
        Classification, run_id="r",
    )
    assert out.claim_type.value == "auto"
    request = sent[0]
    assert request["url"] == "https://api.anthropic.com/v1/messages"
    assert request["headers"]["x-api-key"] == KEY and request["headers"]["anthropic-version"] == "2023-06-01"
    body = request["body"]
    assert body["model"] == "claude-haiku-5-5"  # classification has its own model
    assert body["system"] == "You support a claims handler." and body["messages"] == [{"role": "user", "content": "A car was rear-ended."}]
    assert body["temperature"] == 0 and body["max_tokens"] == 4096 and "response_format" not in body
    assert body["tools"][0]["name"] == ANTHROPIC_TOOL and body["tool_choice"] == {"type": "tool", "name": ANTHROPIC_TOOL}
    assert body["tools"][0]["input_schema"] == Classification.model_json_schema()


def test_each_role_gets_its_own_model_and_the_rest_get_the_default(wire):
    sent, queue = wire
    claim = ClaimInput.model_validate(DEMO_CASES[0]["claim"])
    agents = Agents(settings(), lambda *a: None)
    queue.append(tool_answer({"claim_type": "auto", "method": "live_model", "needs_review": False}))
    agents.classify(claim, "r")
    queue.append(tool_answer({"findings": [{"kind": "fact", "text": "Reported.", "source_ids": ["claim:input"]}]}))
    agents.investigate(claim, [{"source_id": "claim:input", "title": "t", "text": "x", "provenance": "user_input"}], [], "r")
    queue.append(tool_answer({"recommendations": [{"action": "Verify submitted facts", "reason": "Because.", "source_ids": ["claim:input"]}]}))
    agents.recommend({"claim": {}, "findings": [], "evidence": [{"source_id": "claim:input"}], "similar_cases": [], "predictions": {}}, "r")
    assert [r["body"]["model"] for r in sent] == ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]


def test_a_second_turn_from_the_same_role_is_joined_to_the_first_as_the_api_requires(wire):
    sent, queue = wire
    queue.append(lambda body: tool_answer({"recommendations": [{"action": "Verify submitted facts", "reason": "x" * 5, "source_ids": ["claim:input"]}]}))
    client().complete(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "first"}, {"role": "user", "content": "second"}],
        Recommendations, run_id="r",
    )
    assert sent[0]["body"]["messages"] == [{"role": "user", "content": "first\n\nsecond"}]


def test_text_without_a_schema_is_returned_as_text_with_no_tool(wire):
    sent, queue = wire
    queue.append(text_answer("Hello."))
    assert client().complete([{"role": "user", "content": "hi"}], run_id="r") == "Hello."
    assert "tools" not in sent[0]["body"] and "tool_choice" not in sent[0]["body"]


# ----- what comes back -------------------------------------------------------------------------------------------------------


def test_usage_is_recorded_with_the_names_the_rest_of_the_application_reads(wire):
    _, queue = wire
    queue.append(tool_answer({"claim_type": "home", "method": "live_model", "needs_review": False}, usage=(640, 25)))
    audit = []
    client(audit=audit).complete([{"role": "user", "content": "x"}], Classification, run_id="r", role="classify")
    output = next(a for a in audit if a[1] == "model_output")[2]
    assert output["usage"] == {"prompt_tokens": 640, "completion_tokens": 25, "total_tokens": 665}
    assert output["model"] == "claude-haiku-5-5" and output["output"]["claim_type"] == "home"


@pytest.mark.parametrize("bad", [
    {"claim_type": "boat", "method": "live_model", "needs_review": False},  # not a type
    {},  # an empty tool call
])
def test_an_answer_that_does_not_fit_the_schema_is_retried_with_what_to_fix_then_fails_safely(wire, bad):
    sent, queue = wire
    queue.extend([tool_answer(bad), tool_answer(bad)])
    with pytest.raises(CompletionError):
        client().complete([{"role": "system", "content": "S"}, {"role": "user", "content": "x"}], Classification, run_id="r")
    assert len(sent) == 2
    # the second request carries the first's complaint, joined to the user turn
    assert "did not validate" in sent[1]["body"]["messages"][0]["content"] or "did not validate" in str(sent[1]["body"]["messages"])


def test_a_cut_off_answer_is_not_trusted(wire):
    _, queue = wire
    queue.extend([tool_answer({"claim_type": "auto", "method": "m", "needs_review": False}, stop="max_tokens")] * 2)
    with pytest.raises(CompletionError):
        client().complete([{"role": "user", "content": "x"}], Classification, run_id="r")


def test_a_good_answer_after_a_bad_one_is_returned(wire):
    _, queue = wire
    queue.extend([tool_answer({}), tool_answer({"claim_type": "auto", "method": "live_model", "needs_review": False})])
    assert client().complete([{"role": "user", "content": "x"}], Classification, run_id="r").claim_type.value == "auto"


# ----- failures and secrecy --------------------------------------------------------------------------------------------------


def test_an_overloaded_response_is_retried_and_a_bad_request_is_not(wire):
    sent, queue = wire
    queue.extend([httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}),
                  tool_answer({"claim_type": "auto", "method": "live_model", "needs_review": False})])
    assert client().complete([{"role": "user", "content": "x"}], Classification, run_id="r").claim_type.value == "auto"
    assert len(sent) == 2
    sent.clear()
    queue.append(httpx.Response(404, json={"type": "error", "error": {"type": "not_found_error", "message": "model: claude-nope"}}))
    audit = []
    with pytest.raises(CompletionError) as caught:
        client(audit=audit).complete([{"role": "user", "content": "x"}], Classification, run_id="r")
    assert len(sent) == 1 and "HTTP 404" in str(caught.value)
    failure = next(a for a in audit if a[1] == "model_failure")[2]
    assert failure["status_code"] == 404 and failure["error_kind"] == "not_found_error"
    assert "claude-nope" not in json.dumps(audit)  # only the kind of error is kept, never its text


def test_the_api_key_never_reaches_an_audit_event_a_span_or_an_error_message(wire):
    _, queue = wire
    queue.append(httpx.Response(401, json={"type": "error", "error": {"type": "authentication_error", "message": "bad key " + KEY}}))
    audit = []
    with pytest.raises(CompletionError) as caught:
        client(audit=audit).complete([{"role": "user", "content": "x"}], Classification, run_id="r")
    assert KEY not in json.dumps(audit, default=str) and KEY not in str(caught.value)


# ----- settings and the judge ------------------------------------------------------------------------------------------------


def test_the_anthropic_provider_needs_its_key_and_an_https_endpoint():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        settings(anthropic_api_key="")
    with pytest.raises(ValueError, match="HTTPS"):
        settings(anthropic_base_url="http://api.anthropic.com")
    with pytest.raises(ValueError, match="HTTPS"):
        settings(anthropic_base_url="https://user:pw@api.anthropic.com")
    assert settings(llm_provider="openai_compatible", anthropic_api_key="").llm_provider == "openai_compatible"  # not needed, so not asked for


def test_models_per_role_fall_back_to_the_default_and_the_other_provider_keeps_its_own():
    s = settings()
    assert [s.model_for(p) for p in ("classification", "investigation", "recommendation", "intake", "other")] == [
        "claude-haiku-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-sonnet-5-5", "claude-sonnet-5-5"]
    assert s.model_for("classification", "openai_compatible") == "nvidia/nemotron-3-super-120b-a12b"
    assert s.writer_models() == {"claude-haiku-5-5", "claude-sonnet-5-5"}
    assert settings(llm_provider="openai_compatible").writer_models() == {"nvidia/nemotron-3-super-120b-a12b"}


def test_the_judge_stays_on_its_own_provider_and_is_independent_only_while_it_is_not_a_writer():
    s = settings()
    judge = LLMJudge(s, lambda *a: None)
    assert judge.model == "openai/gpt-oss-20b" and judge.independent is True and s.judge_provider == "openai_compatible"
    # a Claude model that also writes is not an independent judge, even though it is Claude judging
    same = settings(judge_provider="anthropic", judge_model="claude-haiku-5-5")
    assert LLMJudge(same, lambda *a: None).independent is False
    other = settings(judge_provider="anthropic", judge_model="claude-opus-5-5")
    assert LLMJudge(other, lambda *a: None).independent is True


def test_the_judge_call_goes_to_the_judges_provider_not_the_writers(wire):
    sent, queue = wire
    queue.append(httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
        "grounded": True, "boundary_respected": True, "recommendations_supported": True, "score": 0.9, "issues": [], "summary": "Fine."})},
        "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}))
    from claims.evaluation.judge import JudgeVerdict

    s = settings()
    CompletionClient(s, lambda *a: None, provider=s.judge_provider).complete([{"role": "user", "content": "x"}], JudgeVerdict, model=s.judge_model, run_id="r")
    assert sent[0]["url"] == "https://integrate.api.nvidia.com/v1/chat/completions" and sent[0]["body"]["model"] == "openai/gpt-oss-20b"
    assert "x-api-key" not in sent[0]["headers"]


def test_a_local_env_file_overrides_the_tracked_one(tmp_path):
    tracked, local = tmp_path / ".env", tmp_path / ".env.local"
    tracked.write_text("LLM_PROVIDER=openai_compatible\nANTHROPIC_MODEL=claude-sonnet-5-5\n", encoding="utf-8")
    local.write_text(f"LLM_PROVIDER=anthropic\nANTHROPIC_API_KEY={KEY}\nANTHROPIC_MODEL_CLASSIFICATION=claude-haiku-5-5\n", encoding="utf-8")
    s = Settings(_env_file=(tracked, local), agent_mode="live", llm_api_key="nv", llm_model="m", synapt_username="u", synapt_password="p", synapt_provider_id="x")
    assert s.llm_provider == "anthropic" and s.model_for("classification") == "claude-haiku-5-5" and s.anthropic_api_key.get_secret_value() == KEY


# ----- the OpenAI-compatible provider (NVIDIA NIM): a model per role, and the thinking switch only where a model has one -------------


def nim(**over):
    return settings(llm_provider="openai_compatible", anthropic_api_key="", **over)


def chat_answer(data):
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(data)}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13}})


def test_each_role_can_have_its_own_nim_model_and_the_rest_use_the_default(wire):
    sent, queue = wire
    s = nim(llm_model="nvidia/nemotron-3-super-120b-a12b", llm_model_classification="z-ai/glm-5.3-flash", llm_model_recommendation="meta/muse-glimmer-30b")
    assert [s.model_for(p) for p in ("classification", "investigation", "recommendation", "intake")] == [
        "z-ai/glm-5.3-flash", "nvidia/nemotron-3-super-120b-a12b", "meta/muse-glimmer-30b", "nvidia/nemotron-3-super-120b-a12b"]
    assert s.writer_models() == {"z-ai/glm-5.3-flash", "nvidia/nemotron-3-super-120b-a12b", "meta/muse-glimmer-30b"}
    queue.append(chat_answer({"claim_type": "auto", "method": "live_model", "needs_review": False}))
    CompletionClient(s, lambda *a, **k: None).complete([{"role": "user", "content": "x"}], Classification, run_id="r")
    assert sent[0]["url"] == "https://integrate.api.nvidia.com/v1/chat/completions" and sent[0]["body"]["model"] == "z-ai/glm-5.3-flash"


def test_the_thinking_switch_is_sent_only_to_models_that_have_one_and_the_list_is_a_setting(wire):
    sent, queue = wire
    queue.extend([chat_answer({"claim_type": "auto", "method": "m", "needs_review": False})] * 3)
    ask = lambda s: CompletionClient(s, lambda *a, **k: None).complete([{"role": "user", "content": "x"}], Classification, run_id="r")
    ask(nim(llm_model="nvidia/nemotron-3-super-120b-a12b"))
    ask(nim(llm_model="meta/muse-glimmer-30b"))
    ask(nim(llm_model="z-ai/glm-5.3-flash", llm_thinking_switch_prefixes="z-ai/glm"))
    assert sent[0]["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in sent[1]["body"]
    assert sent[2]["body"]["chat_template_kwargs"] == {"enable_thinking": False}
