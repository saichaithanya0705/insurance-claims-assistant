"""The shared model request budget: the brief's calls wait for a slot, an agent's optional calls yield first."""

import httpx
import pytest

from claims.core.settings import Settings
from claims.llm import ratelimit
from claims.llm.client import CompletionClient, CompletionError
from claims.llm.ratelimit import RateGate


class Clock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def gate(per_minute, reserve):
    clock = Clock()
    return RateGate(per_minute, reserve, clock=clock, sleep=clock.sleep), clock


def test_an_optional_call_is_allowed_only_while_more_than_the_reserve_is_free():
    g, _ = gate(per_minute=5, reserve=3)
    assert [g.acquire(optional=True) for _ in range(4)] == [True, True, False, False]  # 5 free, 4 free, then 3 free is not above 3
    assert g.free() == 3


def test_the_briefs_own_calls_still_get_the_reserve_after_optional_work_has_stopped():
    g, _ = gate(per_minute=5, reserve=3)
    for _ in range(3):
        g.acquire(optional=True)
    assert [g.acquire() for _ in range(3)] == [True, True, True] and g.free() == 0


def test_an_essential_call_waits_for_the_window_to_slide_instead_of_starting_a_429():
    g, clock = gate(per_minute=2, reserve=0)
    g.acquire(), g.acquire()
    clock.now += 10
    assert g.acquire(max_wait=60) is True
    assert clock.slept and abs(sum(clock.slept) - 50) < 1  # it waited for the first slot to leave the minute


def test_an_essential_call_goes_ahead_when_the_wait_would_be_too_long_and_the_provider_decides():
    g, clock = gate(per_minute=1, reserve=0)
    g.acquire()
    assert g.acquire(max_wait=5) is True
    assert clock.slept == []  # it did not sit out a minute


def test_the_window_forgets_requests_older_than_a_minute():
    g, clock = gate(per_minute=2, reserve=1)
    g.acquire(), g.acquire()
    clock.now += 61
    assert g.free() == 2 and g.acquire(optional=True)


def test_one_gate_serves_every_client_of_an_endpoint_and_zero_switches_it_off():
    s = Settings(_env_file=None, llm_requests_per_minute=10, llm_optional_reserve=2)
    assert ratelimit.gate_for(s) is ratelimit.gate_for(s)
    assert ratelimit.gate_for(Settings(_env_file=None, llm_requests_per_minute=0)) is None


def test_an_agents_optional_model_call_is_refused_when_only_the_reserve_is_left(monkeypatch):
    settings = Settings(_env_file=None, agent_mode="live", llm_api_key="secret-test", llm_requests_per_minute=3, llm_optional_reserve=2)
    sent = []
    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(lambda r: sent.append(1) or httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})), **kw)
    )
    client = CompletionClient(settings, lambda *a, **k: None)
    assert client.chat_with_tools([], [], run_id="r", role="x")["content"] == "ok"  # 3 free > 2: allowed
    with pytest.raises(CompletionError, match="kept for the brief"):
        client.chat_with_tools([], [], run_id="r", role="x")  # 2 free is not above the reserve
    assert len(sent) == 1  # nothing was sent for the refused call


def test_a_rate_limited_provider_is_waited_for_as_long_as_it_asks_up_to_ten_seconds(monkeypatch):
    slept = []
    monkeypatch.setattr("claims.llm.client.time.sleep", slept.append)
    original = httpx.Client
    replies = [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})]
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(lambda r: replies.pop(0)), **kw))
    client = CompletionClient(Settings(_env_file=None, agent_mode="live", llm_api_key="secret-test"), lambda *a, **k: None)
    assert client.chat_with_tools([], [], run_id="r", role="x")["content"] == "ok"
    assert slept == [7.0]
    assert CompletionClient._retry_delay(httpx.Response(429, headers={"Retry-After": "99"})) == 10.0
    assert CompletionClient._retry_delay(httpx.Response(429)) == 3.0
    assert CompletionClient._retry_delay(httpx.Response(503)) == 0.5


# ----- the budget adapts, and the brief's calls wait out a rate limit ---------------------------------------------------


def test_a_429_halves_the_budget_down_to_a_floor_and_a_run_of_successes_raises_it_again():
    g, clock = gate(per_minute=36, reserve=10)
    g.throttled()
    assert g.limit == 18
    g.throttled()  # a second 429 within a few seconds belongs to the same burst
    assert g.limit == 18
    for _ in range(4):
        clock.now += 10
        g.throttled()
    assert g.limit == ratelimit.FLOOR
    for _ in range(ratelimit.RAISE_AFTER):
        g.succeeded()
    assert g.limit == ratelimit.FLOOR + 1
    for _ in range(ratelimit.RAISE_AFTER * 100):
        g.succeeded()
    assert g.limit == 36  # never above the ceiling


def test_the_reserve_for_the_briefs_calls_shrinks_with_the_budget_so_optional_work_still_yields_first():
    g, clock = gate(per_minute=36, reserve=10)
    g.throttled()
    assert g.limit == 18 and g.reserve == 10
    for _ in range(3):
        clock.now += 10
        g.throttled()
    assert g.limit == ratelimit.FLOOR and g.reserve == ratelimit.FLOOR - 1


def structured_client(monkeypatch, replies, **settings):
    from claims.agents.stage_agents import Classification

    original = httpx.Client
    sent = []

    def respond(request):
        sent.append(1)
        return replies.pop(0)

    monkeypatch.setattr(httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    client = CompletionClient(Settings(_env_file=None, agent_mode="live", llm_api_key="secret-test", **settings), lambda *a, **k: None)
    return client, Classification, sent


OK = httpx.Response(200, json={"choices": [{"message": {"content": '{"claim_type": "auto", "method": "live_model", "needs_review": false}'}, "finish_reason": "stop"}]})


def test_the_briefs_own_call_waits_out_a_rate_limit_and_succeeds_instead_of_failing_the_run(monkeypatch):
    slept = []
    monkeypatch.setattr("claims.llm.client.time.sleep", slept.append)
    client, schema, sent = structured_client(monkeypatch, [httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(429), OK], llm_requests_per_minute=20)
    result = client.complete([{"role": "user", "content": "x"}], schema, run_id="r", role="Classify")
    assert result.claim_type == "auto" and len(sent) == 3
    assert slept == [3.0, 6.0]  # at least 3 s, then 6 s, even though the provider asked for 1
    assert ratelimit.gate_for(client.settings).limit == 10  # two 429s in one burst halve the budget of 20 once


def test_a_rate_limit_that_does_not_lift_fails_the_call_after_the_waits_and_does_not_hang(monkeypatch):
    slept = []
    monkeypatch.setattr("claims.llm.client.time.sleep", slept.append)
    client, schema, sent = structured_client(monkeypatch, [httpx.Response(429)] * 8, llm_requests_per_minute=20)
    with pytest.raises(CompletionError, match="rejected"):
        client.complete([{"role": "user", "content": "x"}], schema, run_id="r", role="Classify")
    assert len(sent) == 8 and sum(slept) < 60  # two attempts of four posts each, with bounded waits between
