"""The model's part in the agents that read the knowledge base: the guards, the tool loop, and the three follow-ups."""

import json
from types import SimpleNamespace

import httpx
import pytest

from claims.agents import access
from claims.agents.tools import (
    AgentTool,
    ToolArgumentError,
    run_tool_loop,
    safe_query,
    safe_question,
)
from claims.core.schemas import ClaimInput, Evidence
from claims.core.settings import Settings
from claims.llm.client import CompletionClient, CompletionError
from claims.observability import telemetry
from claims.retrieval.agents import HandlingQuestion, RetrievalAgents

CLAIM = ClaimInput(
    description="A burst pipe flooded our kitchen floor in Columbus, Ohio on June 4. John Smith called the plumber at once.",
    claim_type="home",
    state="OH",
    incident_date="2026-06-04",
    claim_filed_date="2026-06-06",
    claim_amount=7200,
    deductible=500,
    previous_claims_count=0,
    policyholder_tenure_years=3,
    provided_documents=["photos"],
)


# ----- the guards -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["water damage documentation", "documents for a burst pipe claim", "Plumbing leak evidence, photos"])
def test_a_few_plain_words_describing_a_kind_of_procedure_are_allowed(text):
    assert safe_query(text, CLAIM) == text


@pytest.mark.parametrize(
    "text",
    [
        "water",  # one word
        "documents for a claim of 7200 dollars",  # a number
        "claim from john@example.com",  # an address
        "what documents does Columbus require",  # a place from the narrative
        "procedure for Ohio claims",  # the state
        "ask John Smith about it",  # a name from the narrative
        "water damage; drop table procedures",  # symbols
        " ".join(["word"] * 15),  # too long
        "",
        None,
    ],
)
def test_a_search_that_could_carry_the_claimants_details_is_refused(text):
    with pytest.raises(ToolArgumentError):
        safe_query(text, CLAIM)


def test_a_handling_question_must_be_one_clean_sentence_with_no_numbers_or_names():
    good = "For a home claim involving water damage, which documents should a claims handler request first and who reviews them?"
    assert safe_question(good, CLAIM) == good
    for bad in (
        "Which documents?",  # too short
        good.replace("?", "."),  # not a question
        good.replace("home claim", "home claim for $7200"),
        good.replace("home claim", "home claim in Columbus"),
        good.replace("home claim", "home claim of 2026"),
    ):
        with pytest.raises(ToolArgumentError):
            safe_question(bad, CLAIM)


# ----- the loop -------------------------------------------------------------------------------------------------------


class Scripted:
    """A model that answers each turn from a script, and remembers what it was shown."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.seen = []

    def chat_with_tools(self, messages, tools, **kwargs):
        self.seen.append([dict(m) for m in messages])
        turn = self.turns.pop(0)
        calls = [{"id": f"c{i}", "name": n, "arguments": a} for i, (n, a) in enumerate(turn)]
        return {
            "content": None if calls else "Nothing is missing.",
            "tool_calls": calls,
            "message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for c in calls
            ]},
        }


def tools_for(log, *, boom=False):
    def search(args):
        log.append(("search", args["query"]))
        if boom:
            raise RuntimeError("the knowledge base is down")
        return [{"id": "p1"}]

    def keep(args):
        log.append(("keep", args["ids"]))
        return {"kept": args["ids"]}

    return {
        "search": AgentTool("search", "search", {"type": "object"}, search, guard=lambda a: {"query": safe_query(a.get("query"), CLAIM)}),
        "keep": AgentTool("keep", "keep", {"type": "object"}, keep, final=True),
    }


def loop(model, tools, rounds=3, exploratory=1):
    return run_tool_loop(
        model, system="role", user={"claim": "x"}, tools=tools, run_id="run", role="passage_retriever", max_rounds=rounds, exploratory_rounds=exploratory
    )


def test_the_model_searches_and_then_ends_its_turn_with_the_final_tool_without_another_model_call():
    log = []
    model = Scripted([("search", {"query": "water damage documentation"})], [("keep", {"ids": ["p1"]})])
    with access.acting_as("passage_retriever"):
        outcome = loop(model, tools_for(log))
    assert log == [("search", "water damage documentation"), ("keep", ["p1"])]
    assert outcome.stopped == "final_tool" and outcome.rounds == 2 and model.turns == []
    # the second turn was shown what the search returned
    assert any(m.get("role") == "tool" and "p1" in m["content"] for m in model.seen[1])


def test_a_model_that_has_nothing_to_add_ends_the_loop_at_once():
    log = []
    with access.acting_as("passage_retriever"):
        outcome = loop(Scripted([]), tools_for(log))
    assert outcome.stopped == "finished" and outcome.rounds == 1 and log == []


def test_a_tool_the_model_was_not_offered_is_refused_recorded_and_never_run():
    class Recorder:
        def __init__(self):
            self.spans = []

        def add_span(self, **span):
            self.spans.append(span)

    recorder, log = Recorder(), []
    model = Scripted([("trident_ingest", {"content": "x"})], [])
    with telemetry.attach(telemetry.resume(recorder, "run-1", "root")), access.acting_as("passage_retriever"):
        outcome = loop(model, tools_for(log))
    assert outcome.refused == ["trident_ingest"] and log == []
    agent = next(s for s in recorder.spans if s["kind"] == "agent")["attributes"]
    assert agent["tools_denied"] == ["trident_ingest"] and agent["refused"] == 1
    assert any(s["name"] == "access.denied" and s["attributes"]["tool"] == "trident_ingest" for s in recorder.spans)
    refusal = next(m for m in model.seen[1] if m.get("role") == "tool")
    assert "not one of your tools" in refusal["content"]


def test_an_argument_the_guard_refuses_goes_back_to_the_model_and_nothing_is_sent():
    log = []
    model = Scripted([("search", {"query": "what does Columbus require"})], [])
    with access.acting_as("passage_retriever"):
        loop(model, tools_for(log))
    assert log == []  # the search never ran
    assert "must not repeat names or places" in next(m for m in model.seen[1] if m.get("role") == "tool")["content"]


def test_a_tool_that_fails_is_reported_to_the_model_without_stopping_the_run():
    log = []
    model = Scripted([("search", {"query": "water damage documentation"})], [])
    with access.acting_as("passage_retriever"):
        outcome = loop(model, tools_for(log, boom=True))
    assert outcome.calls == [{"tool": "search", "ok": False, "error": "RuntimeError"}]
    content = next(m for m in model.seen[1] if m.get("role") == "tool")["content"]
    assert "could not be used" in content and "down" not in content  # the cause is not passed on


def test_after_its_look_around_the_model_can_only_choose_so_it_cannot_keep_searching():
    log = []
    turns = [[("search", {"query": "water damage documentation"})] for _ in range(5)]
    model = Scripted(*turns)
    with access.acting_as("passage_retriever"):
        outcome = loop(model, tools_for(log), rounds=2)
    # round 1 searched; in round 2 only the final tool was offered, so a further search does not run, and is not a policy refusal
    assert log == [("search", "water damage documentation")]
    assert outcome.refused == [] and outcome.stopped == "limit" and outcome.rounds == 2
    assert outcome.calls[-1] == {"tool": "search", "ok": False, "error": "closed"}


def test_the_loop_stops_at_its_round_limit():
    log = []
    with access.acting_as("passage_retriever"):
        outcome = loop(Scripted([("search", {"query": "water damage documentation"})], [("search", {"query": "plumbing leak evidence"})]), tools_for(log), rounds=2, exploratory=2)
    assert outcome.stopped == "limit" and outcome.rounds == 2 and len(log) == 2


# ----- the model transport --------------------------------------------------------------------------------------------


def client_with(monkeypatch, handler, **settings):
    original = httpx.Client
    seen = []

    def respond(request):
        seen.append(json.loads(request.content))
        return handler(request)

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs))
    base = {"_env_file": None, "agent_mode": "live", "llm_api_key": "secret-test", "llm_model": "nvidia/nemotron-3-super-120b-a12b"}
    return CompletionClient(Settings(**(base | settings)), lambda *a, **k: None), seen


def reply(message):
    return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": "tool_calls"}], "usage": {"total_tokens": 9}})


def test_the_client_offers_the_tools_turns_thinking_off_and_reads_the_calls_the_model_asks_for(monkeypatch):
    call = {"id": "abc", "type": "function", "function": {"name": "search", "arguments": '{"query": "water damage"}'}}
    client, seen = client_with(monkeypatch, lambda request: reply({"content": None, "tool_calls": [call]}))
    turn = client.chat_with_tools([{"role": "user", "content": "x"}], [{"type": "function", "function": {"name": "search"}}], run_id="r", role="graph_navigator")
    assert turn["tool_calls"] == [{"id": "abc", "name": "search", "arguments": {"query": "water damage"}}]
    assert turn["message"]["tool_calls"][0]["function"]["name"] == "search"
    assert seen[0]["tools"][0]["function"]["name"] == "search" and seen[0]["tool_choice"] == "auto"
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "secret-test" not in json.dumps(seen)


def test_a_turn_with_no_calls_is_the_models_final_answer(monkeypatch):
    client, _ = client_with(monkeypatch, lambda request: reply({"content": "Nothing is missing."}))
    turn = client.chat_with_tools([], [], run_id="r", role="x")
    assert turn["tool_calls"] == [] and turn["content"] == "Nothing is missing."


def test_arguments_that_are_not_a_json_object_are_retried_then_refused(monkeypatch):
    bad = {"id": "a", "type": "function", "function": {"name": "search", "arguments": "not json"}}
    client, seen = client_with(monkeypatch, lambda request: reply({"content": None, "tool_calls": [bad]}))
    with pytest.raises(CompletionError, match="validation"):
        client.chat_with_tools([], [], run_id="r", role="x")
    assert len(seen) == 2


def test_tool_calling_is_for_the_openai_compatible_provider_only():
    client = CompletionClient(Settings(_env_file=None), lambda *a, **k: None, provider="anthropic")
    with pytest.raises(CompletionError, match="OpenAI-compatible"):
        client.chat_with_tools([], [], run_id="r", role="x")


# ----- the follow-ups -------------------------------------------------------------------------------------------------


def procedure_hit(node_id, name, intent="Handling steps", search_text=None):
    return {"node_id": node_id, "name": name, "intent": intent, "score": 0.9, "search_text": search_text or f"{name}: {intent}"}


class FollowUpAdapter:
    """Answers the follow-up reads a model may ask for, and records them."""

    def __init__(self):
        self.calls = []

    def graph_search(self, query, top_k=8):
        self.calls.append(("graph_search", query))
        return [
            procedure_hit("n-water", "Synthetic home water damage documentation procedure", "Request photographs and a plumber's invoice"),
            procedure_hit("n-auto", "Synthetic auto collision documentation procedure", "Request a repair estimate"),
        ]

    def graph_walk(self, node_id):
        self.calls.append(("graph_walk", node_id))
        return {"procedure_id": node_id, "steps": [{"number": 1, "text": "Request photographs", "needs": "", "who": ""}], "entities": [], "chunk_ids": [], "edge_counts": {}}

    def passage_search(self, query, top_k=5):
        self.calls.append(("passage_search", query))
        return [
            Evidence(source_id="chunk-new", title="Water damage procedure", text="Request photographs of the damage.", provenance="synapt", provider_id="p"),
            Evidence(source_id="chunk-known", title="Known", text="Already retrieved.", provenance="synapt", provider_id="p"),
            Evidence(source_id="chunk-other", title="Other", text="Something else.", provenance="synapt", provider_id="p"),
        ]


def agents_with(monkeypatch, adapter, model, **settings):
    base = {"_env_file": None, "agent_mode": "live", "llm_api_key": "secret-test"}
    service = SimpleNamespace(settings=Settings(**(base | settings)), adapter=adapter, store=SimpleNamespace(event=lambda *a, **k: None))
    agents = RetrievalAgents(service)
    monkeypatch.setattr(RetrievalAgents, "_client", lambda self: model)
    return agents


BASE_GRAPH = {"available": True, "procedures": [{"node_id": "n-base", "name": "Synthetic home claim documentation procedure", "intent": "Request an incident statement", "steps": []}], "searches": [], "calls": 4}


def test_the_navigator_reads_a_procedure_the_model_found_and_marks_it_as_found_by_the_model(monkeypatch):
    adapter = FollowUpAdapter()
    model = Scripted([("search_procedures", {"query": "water damage documentation"})], [("read_procedure", {"node_id": "n-water"}), ("read_procedure", {"node_id": "n-auto"})])
    with access.acting_as("graph_navigator"):
        graph = agents_with(monkeypatch, adapter, model).graph_followup(CLAIM, BASE_GRAPH, "run")
    assert [p["node_id"] for p in graph["procedures"]] == ["n-base", "n-water"]  # the auto procedure does not fit a home claim
    added = graph["procedures"][1]
    assert added["found_by"] == "model" and added["applies_because"] == "water_damage"
    assert graph["followup"]["read"] == ["Synthetic home water damage documentation procedure"] and graph["calls"] == 4 + 2
    assert ("graph_walk", "n-auto") not in adapter.calls and ("graph_walk", "n-water") in adapter.calls


def test_a_model_search_that_finds_nothing_fitting_adds_nothing_and_does_not_put_a_limitation_in_the_brief(monkeypatch):
    """A first version added a 'no procedure fits' limitation to the brief. On the live pack it appeared in 7 of 20 briefs, most of
    them wrongly, because the standard search had already read the relevant procedure; so a model's search that finds nothing new
    is recorded for the graph panel and nowhere else."""

    class OnlyAuto(FollowUpAdapter):
        def graph_search(self, query, top_k=8):
            self.calls.append(("graph_search", query))
            return [procedure_hit("n-auto", "Synthetic auto collision documentation procedure", "Request a repair estimate")]

    model = Scripted([("search_procedures", {"query": "water damage documentation"})], [])
    with access.acting_as("graph_navigator"):
        graph = agents_with(monkeypatch, OnlyAuto(), model).graph_followup(CLAIM, BASE_GRAPH, "run")
    assert graph["followup"]["searches"][0]["fitting"] == 0 and "gap" not in graph["followup"]
    assert [p["node_id"] for p in graph["procedures"]] == ["n-base"]


def test_the_navigator_keeps_the_standard_result_when_the_model_adds_nothing_or_cannot_be_reached(monkeypatch):
    with access.acting_as("graph_navigator"):
        assert agents_with(monkeypatch, FollowUpAdapter(), Scripted([])).graph_followup(CLAIM, BASE_GRAPH, "run") is BASE_GRAPH

        class Down:
            def chat_with_tools(self, *a, **k):
                raise CompletionError("down")

        assert agents_with(monkeypatch, FollowUpAdapter(), Down()).graph_followup(CLAIM, BASE_GRAPH, "run") is BASE_GRAPH


def test_the_model_steps_do_nothing_when_switched_off_or_when_the_adapter_cannot_do_them(monkeypatch):
    boom = Scripted()  # would fail if asked
    with access.acting_as("graph_navigator"):
        off = agents_with(monkeypatch, FollowUpAdapter(), boom, agent_llm_retrieval=False)
        assert off.graph_followup(CLAIM, BASE_GRAPH, "run") is BASE_GRAPH
        assert off.passage_followup(CLAIM, [], "run") == [] and off.write_question(CLAIM, "run") is None
        fixture = agents_with(monkeypatch, FollowUpAdapter(), boom, agent_mode="fixture")
        assert fixture.graph_followup(CLAIM, BASE_GRAPH, "run") is BASE_GRAPH
        bare = agents_with(monkeypatch, SimpleNamespace(), boom)  # a stand-in adapter without the follow-up reads
        assert bare.graph_followup(CLAIM, BASE_GRAPH, "run") is BASE_GRAPH and bare.passage_followup(CLAIM, [], "run") == []


def test_the_retriever_keeps_only_new_passages_the_model_chose_and_found(monkeypatch):
    adapter = FollowUpAdapter()
    model = Scripted([("search_passages", {"query": "water damage documentation"})], [("keep_passages", {"source_ids": ["chunk-new", "chunk-known", "made-up-id"]})])
    existing = [{"source_id": "chunk-known", "title": "Known", "text": "Already retrieved.", "provenance": "synapt"}]
    with access.acting_as("passage_retriever"):
        kept = agents_with(monkeypatch, adapter, model).passage_followup(CLAIM, existing, "run")
    assert [k["source_id"] for k in kept] == ["chunk-new"]  # not the one it already had, not an ID the search never returned
    assert kept[0]["provenance"] == "synapt" and kept[0]["provider_id"] == "p"
    shown = next(m for m in model.seen[1] if m.get("role") == "tool")["content"]
    assert "chunk-new" in shown and "chunk-known" not in shown  # what it already had is not offered again


def test_the_retriever_cannot_search_with_the_claimants_details(monkeypatch):
    adapter = FollowUpAdapter()
    model = Scripted([("search_passages", {"query": "claim for John Smith in Columbus"})], [])
    with access.acting_as("passage_retriever"):
        agents_with(monkeypatch, adapter, model).passage_followup(CLAIM, [], "run")
    assert adapter.calls == []


def test_the_question_writer_uses_a_clean_question_and_the_fixed_one_otherwise(monkeypatch):
    class Writer:
        def __init__(self, text):
            self.text, self.sent = text, []

        def complete(self, messages, schema, **kwargs):
            self.sent.append(messages)
            return HandlingQuestion(question=self.text)

    good = "For a home claim involving water damage, which documents should a claims handler request first and who reviews them?"
    writer = Writer(good)
    with access.acting_as("knowledge_qa"):
        assert agents_with(monkeypatch, FollowUpAdapter(), writer).write_question(CLAIM, "run") == good
        sent = json.dumps(writer.sent)
        assert "Columbus" not in sent and "John" not in sent and "burst pipe" not in sent  # only the type and conditions go to the model
        dirty = Writer("For the claim of John Smith in Columbus, which documents should a claims handler request first?")
        assert agents_with(monkeypatch, FollowUpAdapter(), dirty).write_question(CLAIM, "run") is None


# ----- the time budget ------------------------------------------------------------------------------------------------


def test_a_slow_model_call_uses_up_the_budget_and_the_loop_stops_before_asking_again():
    import time

    class SlowThenCalls(Scripted):
        def chat_with_tools(self, messages, tools, **kwargs):
            self.kwargs = kwargs
            time.sleep(0.3)
            return super().chat_with_tools(messages, tools, **kwargs)

    log = []
    model = SlowThenCalls([("search", {"query": "water damage documentation"})], [("keep", {"ids": ["p1"]})])
    started = time.perf_counter()
    with access.acting_as("passage_retriever"):
        outcome = run_tool_loop(model, system="r", user={}, tools=tools_for(log), run_id="run", role="passage_retriever", budget_seconds=0.6)
    assert outcome.stopped == "budget" and outcome.rounds == 1 and log == [("search", "water damage documentation")]
    assert model.kwargs["attempts"] == 1 and 0 < model.kwargs["timeout"] <= 0.61  # one attempt, with only the time that is left
    assert time.perf_counter() - started < 1.5


def test_a_tool_that_does_not_come_back_in_time_is_abandoned_not_awaited():
    import time

    def hang(args):
        time.sleep(3)
        return "late"

    tools = {"search": AgentTool("search", "s", {"type": "object"}, hang)}
    started = time.perf_counter()
    with access.acting_as("passage_retriever"):
        outcome = run_tool_loop(Scripted([("search", {})]), system="r", user={}, tools=tools, run_id="run", role="passage_retriever", budget_seconds=0.8)
    assert outcome.stopped == "budget" and time.perf_counter() - started < 2
