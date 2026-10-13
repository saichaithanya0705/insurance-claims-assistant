"""The agents, their roles and prompts, and the role-based limits on the tools each one may call."""

import json

import pytest
from fastapi.testclient import TestClient
from mcp.types import Tool
from test_synapt import (  # the Synapt test doubles
    query_tool,
    result,
    stub_session,
    tickets_result,
    tool,
)

from claims.agents import access, roster
from claims.agents.stage_agents import Agents
from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.schemas import ClaimInput
from claims.core.settings import Settings
from claims.observability import telemetry
from claims.storage.run_store import Store
from claims.synapt.adapter import READ_ONLY_TOOLS, TICKET_NEIGHBOURS, LiveSynaptAdapter


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        synapt_mode="live",
        synapt_username="test-user",
        synapt_password="very-secret-password",
        synapt_provider_id="provider-1",
    )


@pytest.fixture
def claim():
    return ClaimInput.model_validate(DEMO_CASES[0]["claim"])


SYNAPT_FACING = {
    "passage_retriever": {"trident_get_chunks", "trident_search", "trident_get_procedures", "trident_ticket_neighbours"},
    "graph_navigator": {"trident_search", "trident_traverse"},
    "knowledge_qa": {"trident_query"},
}
STAGES = ["classify", "retrieve", "investigate", "risk", "recommend", "validate", "supervise", "judge"]


# ----- the roster ----------------------------------------------------------------------------------------------------


def test_every_tool_an_actor_holds_is_a_known_tool():
    for spec in roster.AGENTS.values():
        assert spec.tools <= roster.TOOLS.keys(), spec.id
    synapt = {t.id for t in roster.TOOLS.values() if t.system == "synapt"}
    # The ticket-neighbour permission is the read-only, ticket-only leg of trident_query.
    assert synapt <= READ_ONLY_TOOLS | {"trident_ingest", "trident_feedback", TICKET_NEIGHBOURS}


def test_exactly_the_three_retrieval_agents_hold_knowledge_base_tools_and_each_holds_only_its_own():
    holders = {s.id: {t for t in s.tools if t.startswith("trident_")} for s in roster.investigation_agents()}
    assert {agent: tools for agent, tools in holders.items() if tools} == SYNAPT_FACING


def test_no_agent_can_write_to_the_knowledge_base():
    writes = {t.id for t in roster.TOOLS.values() if t.writes}
    assert writes == {"trident_ingest", "trident_feedback"}
    for spec in roster.investigation_agents():
        assert not spec.tools & writes, spec.id
    holders = {w: [s.id for s in roster.AGENTS.values() if w in s.tools] for w in writes}
    assert holders == {"trident_ingest": ["ingestion"], "trident_feedback": ["reviewer"]}


def test_a_model_agent_has_its_own_written_role_and_a_rules_agent_has_none():
    prompts = {}
    for spec in roster.investigation_agents():
        prompt = roster.prompt_for(spec.id)
        if spec.method == "model":
            assert prompt and spec.model_purpose, spec.id
            prompts[spec.id] = prompt
        else:
            assert not prompt and not spec.model_purpose, spec.id
    assert len(set(prompts.values())) == len(prompts)  # no two agents share a role
    for agent in ("triage", "investigator", "recommender"):
        assert roster.agent(agent).name in prompts[agent]
        assert "hold no tools" in prompts[agent] or "no tools" in prompts[agent]


def test_every_workflow_stage_but_the_human_gate_has_an_agent():
    assert {spec.stage for spec in roster.investigation_agents()} == set(STAGES)


def test_what_a_person_sees_names_no_vendor_tool_prompt_or_identity():
    person = json.dumps(roster.describe(admin=False))
    for word in ("trident", "Synapt", "synapt", "prompt", "identity", "claims-assistant"):
        assert word not in person, word
    assert "Knowledge-base passage search" in person  # what each agent can use is still said, in plain words
    admin = roster.describe(admin=True)
    by_id = {a["id"]: a for a in admin["agents"]}
    assert by_id["graph_navigator"]["tools"] == sorted(SYNAPT_FACING["graph_navigator"])
    assert by_id["investigator"]["prompt"].startswith("You are the Investigation Agent")
    assert by_id["passage_retriever"]["identity"] == "claims-assistant.passage_retriever"


# ----- the check ------------------------------------------------------------------------------------------------------


class Recorder:
    def __init__(self):
        self.spans = []

    def add_span(self, **span):
        self.spans.append(span)


def test_a_tool_outside_the_agents_list_is_refused_and_leaves_a_mark():
    recorder = Recorder()
    with telemetry.attach(telemetry.resume(recorder, "run-1", "root")), access.acting_as("graph_navigator"):
        assert access.authorize("trident_traverse") == "graph_navigator"
        with pytest.raises(access.AccessDenied, match="graph_navigator"):
            access.authorize("trident_get_chunks")
        with pytest.raises(access.AccessDenied):
            access.authorize("trident_ingest")
    spans = {s["name"]: s for s in recorder.spans}
    agent = spans["agent.graph_navigator"]["attributes"]
    assert agent["tool_calls"] == {"trident_traverse": 1} and agent["tools_denied"] == ["trident_get_chunks", "trident_ingest"]
    assert agent["tool_total"] == 1 and agent["refused"] == 2
    denied = [s for s in recorder.spans if s["name"] == "access.denied"]
    assert [d["attributes"]["tool"] for d in denied] == ["trident_get_chunks", "trident_ingest"]
    assert all(d["status"] == "error" and d["attributes"]["agent"] == "graph_navigator" for d in denied)


def test_with_no_agent_acting_nothing_gets_through():
    with pytest.raises(access.AccessDenied, match="no agent is acting"):
        access.authorize("trident_get_chunks")
    assert access.current() is None and not access.permits("trident_get_chunks")


def test_a_capability_that_needs_tools_the_agent_lacks_does_nothing_first():
    with access.acting_as("passage_retriever"):
        access.require("trident_get_chunks", "trident_search")  # holds both
        with pytest.raises(access.AccessDenied):
            access.require("trident_search", "trident_traverse")  # holds one of two: refused as a whole
        access.require("trident_traverse", "trident_search", any_of=True)  # holds one of the two: enough when either will do
    with access.acting_as("investigator"), pytest.raises(access.AccessDenied):
        access.require("trident_get_chunks", "trident_search", any_of=True)


def test_work_recorded_inside_an_agent_carries_the_agent():
    recorder = Recorder()
    with telemetry.attach(telemetry.resume(recorder, "run-1", "root")):
        with telemetry.span("outside"):
            pass
        with access.acting_as("history_analyst"), telemetry.span("inside"):
            pass
    by_name = {s["name"]: s for s in recorder.spans}
    assert "agent" not in by_name["outside"]["attributes"]
    assert by_name["inside"]["attributes"]["agent"] == "history_analyst"


# ----- the Synapt adapter ---------------------------------------------------------------------------------------------


def test_the_passage_search_runs_as_the_passage_retriever_and_calls_only_its_tools(monkeypatch, settings, claim):
    adapter = LiveSynaptAdapter(settings)
    recorder = Recorder()
    calls = stub_session(
        monkeypatch, adapter, [tool(), query_tool(), tool("trident_ingest")],
        {"trident_get_chunks": result([]), "trident_query": tickets_result([])},
    )
    with telemetry.attach(telemetry.resume(recorder, "run-1", "root")):
        adapter.retrieve(claim)
    # The query tool is called only for the ticket-only leg (similar past claims), never to ask a question.
    assert [name for name, _ in calls] == ["trident_get_chunks", "trident_query"]
    assert calls[1][1]["ticket_mode"] == "only"
    agents = [s for s in recorder.spans if s["kind"] == "agent"]
    assert [a["attributes"]["agent"] for a in agents] == ["passage_retriever"]
    assert agents[0]["attributes"]["tool_calls"] == {"trident_get_chunks": 1, "trident_ticket_neighbours": 1}


@pytest.mark.parametrize("agent", ["investigator", "recommender", "triage", "judge", "history_analyst", "knowledge_qa"])
def test_an_agent_without_the_passage_tools_cannot_use_the_passage_search(monkeypatch, settings, claim, agent):
    adapter = LiveSynaptAdapter(settings)
    calls = stub_session(monkeypatch, adapter, [tool()], result([]))
    with access.acting_as(agent), pytest.raises(access.AccessDenied):
        adapter.retrieve(claim)
    assert calls == []  # refused before the first call, not after it


@pytest.mark.parametrize("agent", ["investigator", "passage_retriever", "knowledge_qa", "validator"])
def test_an_agent_without_both_graph_tools_cannot_use_the_graph_lookup(monkeypatch, settings, claim, agent):
    adapter = LiveSynaptAdapter(settings)
    calls = stub_session(monkeypatch, adapter, [tool(), tool("trident_traverse")], result([]))
    with access.acting_as(agent), pytest.raises(access.AccessDenied):
        adapter.retrieve_graph(claim)
    assert calls == []


def test_only_the_knowledge_qa_agent_can_ask_the_query_agent(monkeypatch, settings):
    adapter = LiveSynaptAdapter(settings)
    query_tool = Tool(
        name="trident_query",
        inputSchema={
            "type": "object",
            "properties": {key: {"type": "string"} for key in ("provider_id", "question", "ticket_mode", "task_id")}
            | {"top_k": {"type": "integer"}},
            "required": ["provider_id", "question"],
        },
    )
    calls = stub_session(monkeypatch, adapter, [query_tool], result([]))
    for agent in ("passage_retriever", "graph_navigator", "investigator", "operator", "ingestion"):
        with access.acting_as(agent), pytest.raises(access.AccessDenied):
            adapter.ask("How should this be handled?")
    assert calls == []
    adapter.ask("How should this be handled?")  # no agent named: the capability belongs to the Knowledge Q&A Agent
    assert [name for name, _ in calls] == ["trident_query"]


def test_a_denied_call_is_not_an_outage_so_it_is_not_retried_or_answered_with_the_fallback(monkeypatch, settings, claim):
    from claims.synapt.adapter import SynaptError

    adapter = LiveSynaptAdapter(settings)
    stub_session(monkeypatch, adapter, [tool()], result([]))
    with access.acting_as("investigator"), pytest.raises(access.AccessDenied) as caught:
        adapter.retrieve(claim)
    assert not isinstance(caught.value, SynaptError)


def test_feedback_and_ingestion_each_belong_to_one_actor_and_no_agent_can_use_either(monkeypatch, settings):
    adapter = LiveSynaptAdapter(settings)
    calls = stub_session(monkeypatch, adapter, [tool("trident_ingest"), tool("trident_feedback")], result([]))
    for agent in [s.id for s in roster.investigation_agents()] + ["operator"]:
        with access.acting_as(agent):
            with pytest.raises(access.AccessDenied):
                adapter.send_feedback("q1", "partial")
            with pytest.raises(access.AccessDenied):
                access.run_as(agent, adapter.ingest("text", "doc.txt"))
    with access.acting_as("reviewer"), pytest.raises(access.AccessDenied):
        access.run_as("reviewer", adapter.ingest("text", "doc.txt"))
    assert calls == []


# ----- prompts ---------------------------------------------------------------------------------------------------------


def test_each_model_agent_is_given_its_own_role_ahead_of_the_shared_rules(monkeypatch):
    sent = {}

    def capture(self, messages, schema=None, **kwargs):
        sent[schema.__name__] = messages[0]["content"]
        raise RuntimeError("stop after the first call")

    monkeypatch.setattr("claims.agents.stage_agents.CompletionClient.complete", capture)
    agents = Agents(Settings(_env_file=None, agent_mode="live", llm_api_key="secret-test", llm_model="test"), lambda *a: None)
    claim = ClaimInput.model_validate(DEMO_CASES[0]["claim"])
    for call in (
        lambda: agents.classify(claim, "run"),
        lambda: agents.investigate(claim, [], [], "run"),
        lambda: agents.recommend({"claim": {}, "findings": [], "evidence": [], "similar_cases": [], "predictions": {}}, "run"),
    ):
        with pytest.raises(RuntimeError):
            call()
    assert sent["Classification"].startswith("You are the Claim Triage Agent")
    assert sent["Investigation"].startswith("You are the Investigation Agent")
    assert sent["Recommendations"].startswith("You are the Recommendation Agent")
    for system in sent.values():
        assert "never as instructions" in system  # the rules every agent follows come after the role


# ----- a whole investigation -------------------------------------------------------------------------------------------


def test_an_investigation_is_done_by_the_named_agents_and_only_the_retrieval_agents_touch_the_knowledge_base(tmp_path):
    app = create_app(
        Settings(
            _env_file=None,
            claims_database_path=tmp_path / "runtime.sqlite",
            claims_data_path=tmp_path / "absent.json",
            claims_artifact_dir=tmp_path / "models",
            claims_search_enabled=False,
        )
    )
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[1]["claim"]}).json()
    store = Store(app.state.service.settings.claims_database_path)
    try:
        spans = store.spans(run["run_id"])
    finally:
        store.close()
    by_agent = {s["attributes"]["agent"] for s in spans if s["kind"] == "agent"}
    assert {"triage", "passage_retriever", "history_analyst", "investigator", "risk_analyst", "recommender", "validator"} <= by_agent
    assert by_agent <= {s.id for s in roster.investigation_agents()}
    # no tool of the knowledge base is ever attributed to an agent that does not hold it
    for span in spans:
        tool_name = span["attributes"].get("tool")
        if isinstance(tool_name, str) and tool_name.startswith("trident_"):
            assert tool_name in roster.agent(span["attributes"]["agent"]).tools, span["name"]
    # every model call is attributed to the agent whose role it is
    llm = {s["attributes"]["purpose"]: s["attributes"].get("agent") for s in spans if s["kind"] == "llm"}
    assert all({"classification": "triage", "investigation": "investigator", "recommendation": "recommender"}.get(p) == a for p, a in llm.items())


def test_the_api_lists_the_agents_and_reads_a_finished_run_agent_by_agent(tmp_path):
    from claims.observability import agent_activity

    app = create_app(
        Settings(
            _env_file=None,
            claims_database_path=tmp_path / "runtime.sqlite",
            claims_data_path=tmp_path / "absent.json",
            claims_artifact_dir=tmp_path / "models",
            claims_search_enabled=False,
        )
    )
    with TestClient(app) as client:
        listing = client.get("/api/agents").json()  # authentication is off here, so the caller is the local administrator
        assert [a["id"] for a in listing["agents"]][:3] == ["triage", "passage_retriever", "graph_navigator"]
        assert all("tools" in a and "identity" in a for a in listing["agents"]) and listing["tools"]
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        activity = client.get(f"/api/investigations/{run['run_id']}/agents").json()["agents"]
        assert client.get("/api/investigations/no-such-run/agents").status_code == 404
    by_id = {a["id"]: a for a in activity}
    assert by_id["triage"]["ran"] and by_id["triage"]["status"] == "ok" and by_id["triage"]["duration_ms"] >= 0
    assert by_id["passage_retriever"]["method"] == "model" and "tools_used" in by_id["passage_retriever"]
    assert by_id["investigator"]["tool_calls"] == 0 and by_id["investigator"]["tools_used"] == {}
    store = Store(app.state.service.settings.claims_database_path)
    try:
        spans = store.spans(run["run_id"])
    finally:
        store.close()
    person = json.dumps(agent_activity.summary(spans, admin=False))
    for word in ("trident", "Synapt", "synapt", "tools_used", "tools_refused", '"models"'):
        assert word not in person, word


def test_the_graphs_the_agents_run_in_are_read_from_the_compiled_langgraph_graphs(tmp_path):
    app = create_app(
        Settings(
            _env_file=None,
            claims_database_path=tmp_path / "runtime.sqlite",
            claims_data_path=tmp_path / "absent.json",
            claims_artifact_dir=tmp_path / "models",
            claims_search_enabled=False,
        )
    )
    with TestClient(app) as client:
        graph = client.get("/api/agents/graph").json()
    stages = {n["id"]: n["agents"] for n in graph["investigation"]["nodes"]}
    assert list(stages) == ["classify", "retrieve", "investigate", "risk", "recommend", "validate", "supervise", "judge", "review"]
    assert stages["classify"] == ["triage"] and stages["investigate"] == ["investigator"] and stages["review"] == []
    assert set(stages["retrieve"]) == {"passage_retriever", "graph_navigator", "knowledge_qa", "history_analyst"}
    inner = graph["retrieve"]
    assert {n["id"] for n in inner["nodes"]} == {"passage_retriever", "graph_navigator", "knowledge_qa", "history_analyst", "assemble_evidence"}
    # the four agents all start from the beginning and all feed the join: they run side by side
    assert {(e["from"], e["to"]) for e in inner["edges"] if e["to"] == "assemble_evidence"} == {
        (a, "assemble_evidence") for a in ("passage_retriever", "graph_navigator", "knowledge_qa", "history_analyst")
    }
    assert "graph TD" in graph["investigation"]["mermaid"] or "graph" in graph["investigation"]["mermaid"]
    # inside the supervise stage: review, and a conditional send-back to revise that returns to review
    loop = graph["supervise"]
    assert {n["id"] for n in loop["nodes"]} == {"review", "revise"}
    edges = {(e["from"], e["to"]): e["conditional"] for e in loop["edges"]}
    assert edges[("review", "revise")] is True and edges[("revise", "review")] is False
    assert stages["supervise"] == ["supervisor"]


def test_the_independent_review_is_marked_as_background_work_on_its_agent_span(tmp_path, monkeypatch):
    from test_observability import live_settings, mock_model

    mock_model(monkeypatch, usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
    settings = live_settings(tmp_path).model_copy(update={"judge_mode": "inline", "judge_model": "judge-model-x"})
    app = create_app(settings)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        app.state.service.wait_for_judges(30)
    store = Store(app.state.service.settings.claims_database_path)
    try:
        spans = store.spans(run["run_id"])
    finally:
        store.close()
    judge = next(s for s in spans if s["kind"] == "agent" and s["attributes"]["agent"] == "judge")
    assert judge["attributes"]["background"] is True and judge["attributes"]["role"] == "Independent Judge"


def test_the_page_says_whether_an_agents_connector_client_id_is_set_and_never_shows_it(tmp_path):
    app = create_app(
        Settings(
            _env_file=None,
            claims_database_path=tmp_path / "runtime.sqlite",
            claims_data_path=tmp_path / "absent.json",
            claims_artifact_dir=tmp_path / "models",
            claims_search_enabled=False,
            synapt_agent_graph_navigator_client_id="client-123-secret-looking",
        )
    )
    with TestClient(app) as client:
        text = client.get("/api/agents").text
    by_id = {a["id"]: a for a in json.loads(text)["agents"]}
    assert by_id["graph_navigator"]["client_id_set"] is True
    assert by_id["passage_retriever"]["client_id_set"] is False and by_id["triage"]["client_id_set"] is False
    assert "client-123-secret-looking" not in text


def test_the_live_feed_lists_each_agent_and_names_no_vendor_to_someone_who_is_not_an_administrator(tmp_path):
    app = create_app(
        Settings(
            _env_file=None,
            claims_database_path=tmp_path / "runtime.sqlite",
            claims_data_path=tmp_path / "absent.json",
            claims_artifact_dir=tmp_path / "models",
            claims_search_enabled=False,
        )
    )
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        person = app.state.service.progress.read(run["run_id"], viewer_id="local", admin=False)
    agents = [r for r in person["spans"] if r["kind"] == "agent"]
    names = {a.name for a in roster.investigation_agents()}
    assert {r["label"] for r in agents} <= names and {r["agent"] for r in agents} >= {"triage", "passage_retriever", "investigator"}
    assert all(r["parent"] is not None for r in agents)  # an agent hangs under its stage
    # work is listed under its stage, not under the agent that did it, and still says which agent did it
    by_id = {r["id"]: r for r in person["spans"]}
    for row in person["spans"]:
        if row["kind"] not in ("agent", "stage", "run"):
            assert by_id[row["parent"]]["kind"] != "agent", row["label"]
    blob = json.dumps(person).lower()
    for word in ("synapt", "trident", "nvidia"):
        assert word not in blob, word
