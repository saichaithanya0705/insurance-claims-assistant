"""Every investigation makes one real Synapt query-agent call, and shows its answer beside the brief.

Synapt's Explainability pages list the answers its query agent writes. An investigation otherwise only reads passages and
the graph, which are retrievals, so it would never appear there. These tests pin what makes the single call safe: it asks
a fixed question built from the claim type (never the narrative), carries the run ID as its task ID, runs beside the rest of
retrieval, is display only (never evidence, never cited, never given to a model), fails without failing the run, and is
skipped for evaluation runs, the interactive search and degraded runs, because every call records an episode in the provider.
"""

import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from synapt_stub import StubSynaptAdapter
from test_cohort import LocalCopy, SynaptDown
from test_sidechat import QUERY

from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.schemas import ClaimInput
from claims.core.settings import Settings
from claims.observability import telemetry
from claims.observability.progress import ProgressBoard
from claims.synapt import query_agent

RUN = "11111111-1111-4111-8111-111111111111"
NARRATIVE = "Vehicle stolen overnight from the Willow Street car park; the thieves left the door open."


def claim(kind="auto", description=NARRATIVE, **over):
    return ClaimInput.model_validate({
        "description": description, "claim_type": kind, "state": "TX", "incident_date": "2026-09-01", "claim_filed_date": "2026-09-03",
        "claim_amount": 12000, "deductible": 500, "previous_claims_count": 1, "policyholder_tenure_years": 3,
        "provided_documents": ["police report"], **over,
    })


# ----- the question -------------------------------------------------------------------------------------------------


def test_the_question_is_fixed_and_built_from_the_claim_type_alone():
    auto_theft = query_agent.question_for(claim("auto"))
    assert auto_theft == (
        "For an auto claim involving theft, which documents should a claims handler request and in what order, who is "
        "responsible for each step, and what must a human claims handler review before any decision?"
    )
    assert query_agent.question_for(claim("home", "Burst pipe flooded the kitchen.")) == (
        "For a home claim, which documents should a claims handler request and in what order, who is responsible for each "
        "step, and what must a human claims handler review before any decision?"
    )
    assert query_agent.question_for(claim("business", "Warehouse flooded.")).startswith("For a business claim, which documents")
    no_type = ClaimInput.model_validate(claim("auto").model_dump(mode="json") | {"claim_type": None})
    assert query_agent.question_for(no_type).startswith("For an insurance claim involving theft,")


@pytest.mark.parametrize("kind", ["auto", "home", "renters", "property", "business"])
def test_nothing_about_the_claim_but_its_type_and_a_theft_cue_ever_leaves(kind):
    text = query_agent.question_for(claim(kind, NARRATIVE + " Jane Doe, jane@example.com, 555-123-4567, policy 123-45-6789."))
    for leaked in ("Willow", "car park", "thieves", "Jane", "jane@", "555", "123-45", "12000", "12,000", "500", "TX", "2026", "police report", "3 years"):
        assert leaked not in text, leaked


# ----- the call -----------------------------------------------------------------------------------------------------


class Asker:
    def __init__(self, payload=QUERY, error=None, wait_for=None):
        self.payload, self.error, self.wait_for, self.calls = payload, error, wait_for, []

    def __call__(self, question, **kwargs):
        self.calls.append((question, kwargs))
        if self.wait_for is not None:
            assert self.wait_for.wait(10), "the query agent was not asked beside the rest of retrieval"
        if self.error:
            raise self.error
        return self.payload


def test_the_call_carries_the_run_id_as_its_task_id_and_comes_back_as_a_part_with_synapts_own_numbers():
    ask = Asker()
    result = query_agent.run_query(ask, claim(), {"chunk_bff73f13"}, RUN)
    assert ask.calls == [(query_agent.question_for(claim()), {"task_id": RUN, "top_k": 5})]
    assert result["available"] is True and result["task_id"] == RUN and result["question"] == query_agent.question_for(claim())
    part = result["part"]
    assert part["source"] == "synapt" and part["text"].startswith("For a stolen-vehicle auto claim")
    assert part["synapt"]["task_id"] == RUN and part["synapt"]["query_id"] == QUERY["query_id"]
    assert part["synapt"]["confidence"]["label"] == "High" and part["cites"] == ["chunk_bff73f13"]


def test_the_call_is_a_span_so_the_live_view_and_the_trace_show_it():
    board = ProgressBoard()
    board.register(RUN, "alice")

    class Recorder:
        progress = board

        def add_span(self, **kwargs):
            pass

    with telemetry.Tracer(Recorder()).run(RUN, "investigation"):
        query_agent.run_query(Asker(), claim(), set(), RUN)
    rows = board.read(RUN, viewer_id="alice", admin=True)["spans"]
    call = next(r for r in rows if r["label"].startswith("Query agent"))
    assert call["status"] == "ok" and call["result"] == "Answer · High confidence · 2 passages"
    assert call["detail"].startswith("trident_query · “For an auto claim involving theft") and call["detail"].endswith("top 5")
    person = next(r for r in board.read(RUN, viewer_id="alice")["spans"] if r["label"].startswith("Ask the knowledge base"))
    assert person["detail"] is None and "trident" not in repr(person)


def test_an_answer_without_text_is_an_error_not_an_empty_panel():
    with pytest.raises(Exception, match="no answer"):
        query_agent.run_query(Asker(payload={"answer": " "}), claim(), set(), RUN)


# ----- inside an investigation --------------------------------------------------------------------------------------------


class Agent(StubSynaptAdapter):
    """A Synapt double with the query agent and the graph, to see how an investigation uses them."""

    def __init__(self, **options):
        self.asker = Asker(**options)
        self.graph_called = threading.Event()

    def ask(self, question, **kwargs):
        return self.asker(question, **kwargs)

    def retrieve_graph(self, claim):
        self.graph_called.set()
        from claims.synapt import knowledge_graph as kg

        return kg.context([], [], 0, "provider-1")


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, claims_database_path=tmp_path / "runtime.sqlite", claims_data_path=Path("absent.json"),
        claims_artifact_dir=tmp_path / "models",
    )


def investigate(settings, adapter, **kwargs):
    app = create_app(settings, adapter=adapter, **kwargs)
    with TestClient(app) as client:
        return client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"], "run_id": RUN}).json()


def test_every_investigation_makes_one_call_and_stores_the_answer_beside_the_brief(settings):
    adapter = Agent()
    run = investigate(settings, adapter)
    assert len(adapter.asker.calls) == 1
    question, kwargs = adapter.asker.calls[0]
    assert kwargs == {"task_id": RUN, "top_k": 5} and question.startswith("For ")
    qa = run["query_agent"]
    assert qa["available"] is True and qa["task_id"] == RUN and qa["question"] == question
    assert qa["part"]["synapt"]["query_id"] == QUERY["query_id"]
    assert run["status"] == "awaiting_review" and run["validation"]["passed"] is True


def test_the_answer_is_display_only_never_evidence_never_cited_never_in_the_findings(settings):
    run = investigate(settings, Agent())
    answer = QUERY["answer"].split("\n")[0]
    assert not any(answer in e["text"] or e["source_id"].startswith("query") for e in run["evidence"])
    cited = {s for f in run["findings"] for s in f["source_ids"]} | {s for r in run["recommendations"] for s in r["source_ids"]}
    assert not any(s.startswith("query") or s == QUERY["query_id"] for s in cited)
    assert answer not in json.dumps(run["findings"]) and answer not in json.dumps(run["recommendations"])


def test_the_query_agent_is_asked_beside_the_rest_of_retrieval_not_after_it(settings):
    adapter = Agent()
    adapter.asker.wait_for = adapter.graph_called  # the answer can only come back if the graph lookup has begun meanwhile
    run = investigate(settings, adapter)
    assert run["query_agent"]["available"] is True


def test_a_failed_call_is_reported_in_one_plain_sentence_and_the_run_still_completes(settings):
    run = investigate(settings, Agent(error=RuntimeError("socket closed; token abc123")))
    assert run["query_agent"]["available"] is False and "did not answer" in run["query_agent"]["reason"]
    assert run["status"] == "awaiting_review" and run["evidence"]
    assert any("query agent did not answer" in f["text"] for f in run["findings"] if f["kind"] == "limitation")
    assert "abc123" not in json.dumps(run)


def test_no_call_for_an_adapter_without_the_query_agent_an_evaluation_run_the_search_or_a_degraded_run(settings, tmp_path):
    assert investigate(settings, StubSynaptAdapter())["query_agent"] is None

    adapter = Agent()
    app = create_app(settings, adapter=adapter)
    with TestClient(app) as client:
        with telemetry.origin("evaluation"):
            client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]})
        assert client.post("/api/search", json={"claim": DEMO_CASES[0]["claim"]}).status_code == 200
    assert adapter.asker.calls == [], "evaluation runs and the interactive search must never record an episode"

    adapter2 = Agent()
    degraded = create_app(settings.model_copy(update={"claims_database_path": tmp_path / "d.sqlite"}), adapter=SynaptDown(), fallback=LocalCopy([]))
    with TestClient(degraded) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
    assert run["mode"] == "degraded" and run["query_agent"] is None and adapter2.asker.calls == []


def test_the_live_feed_of_the_run_shows_the_query_agent_call_with_its_question(settings):
    app = create_app(settings, adapter=Agent())
    with TestClient(app) as client:
        client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"], "run_id": RUN})
        spans = client.get(f"/api/investigations/{RUN}/progress").json()["spans"]
    call = next(s for s in spans if s["label"].startswith("Query agent"))
    assert call["result"] == "Answer · High confidence · 2 passages" and call["detail"].startswith("trident_query")
    stage = next(s for s in spans if s["name"] == "retrieve")
    assert call["parent"] == stage["id"]  # nested under the stage it ran in, although it ran on another thread


# ----- who sees what -----------------------------------------------------------------------------------------------------


def test_everyone_but_an_administrator_sees_the_answer_without_the_vendors_name_scores_query_id_or_task_id():
    stored = query_agent.run_query(Asker(), claim(), {"chunk_bff73f13"}, RUN)
    admin = query_agent.present(stored, True)
    person = query_agent.present(stored, False)
    assert admin["task_id"] == RUN and admin["part"]["synapt"]["query_id"] == QUERY["query_id"] and admin["part"]["synapt"]["confidence"]["overall"] == 0.76
    blob = json.dumps(person)
    for word in ("Synapt", "query_id", "task_id", "4af2de76", RUN, "0.76", "0.87", "stores", "latency_ms", "trust"):
        assert word not in blob, word
    assert person["part"]["synapt"]["confidence"] == {"label": "High"} and person["part"]["title"] == "From the knowledge base"
    assert person["question"] == stored["question"] and person["available"] is True
    down = query_agent.present(query_agent.unavailable("The Synapt query agent did not answer for this claim; the brief does not depend on it."), False)
    assert down["reason"] == "The knowledge base query agent did not answer for this claim; the brief does not depend on it."
    assert query_agent.present(None, False) is None


def test_over_the_api_a_person_gets_the_plain_version_and_an_administrator_the_full_one(tmp_path):
    settings = Settings(
        _env_file=None, claims_auth_enabled=True, claims_search_enabled=False, claims_database_path=tmp_path / "cases.sqlite",
        claims_data_path=Path("absent.json"), claims_artifact_dir=tmp_path / "models",
    )
    app = create_app(settings, adapter=Agent())

    def sign_in(client, username, password):
        csrf = client.get("/api/auth/session").json()["csrf_token"]
        response = client.post("/api/auth/login", json={"username": username, "password": password}, headers={"X-CSRF-Token": csrf})
        assert response.status_code == 200, response.text
        return {"X-CSRF-Token": response.json()["csrf_token"]}

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        csrf = {"X-CSRF-Token": client.get("/api/auth/session").json()["csrf_token"]}
        client.post("/api/auth/setup", json={"username": "admin", "password": "Synthetic admin passphrase!", "role": "admin"}, headers=csrf)
        admin = sign_in(client, "admin", "Synthetic admin passphrase!")
        client.post("/api/admin/users", json={"username": "alice", "password": "Synthetic user passphrase!", "role": "user"}, headers=admin)
        client.post("/api/auth/logout", headers=admin)
        alice = sign_in(client, "alice", "Synthetic user passphrase!")
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"], "run_id": RUN}, headers=alice).json()
        shown = json.dumps(run["query_agent"])
        for word in ("Synapt", "query_id", "task_id", "4af2de76", "0.76"):
            assert word not in shown, word
        assert run["query_agent"]["part"]["synapt"]["confidence"] == {"label": "High"}
        assert client.get(f"/api/investigations/{RUN}").json()["query_agent"] == run["query_agent"]
        client.post("/api/auth/logout", headers=alice)
        admin = sign_in(client, "admin", "Synthetic admin passphrase!")
        full = client.get(f"/api/investigations/{RUN}").json()["query_agent"]
        assert full["task_id"] == RUN and full["part"]["synapt"]["query_id"] == QUERY["query_id"]


# ----- a slow answer does not hold the brief ---------------------------------------------------------------------------------


def test_a_slow_answer_does_not_hold_the_brief_and_is_attached_to_the_saved_run_when_it_arrives(settings, monkeypatch):
    from claims.investigation import workflow

    monkeypatch.setattr(workflow, "QUERY_GRACE_SECONDS", 0.3)
    release = threading.Event()
    adapter = Agent()
    adapter.asker.wait_for = release  # the answer is held back, as Synapt held it for 30 to 48 s on 12 October
    app = create_app(settings, adapter=adapter)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"], "run_id": RUN}).json()
        # the brief is ready without it, and the panel says what was asked and that the answer is on its way
        assert run["status"] == "awaiting_review" and run["evidence"] and run["findings"]
        waiting = run["query_agent"]
        assert waiting["pending"] is True and waiting["available"] is False and waiting["part"] is None
        assert waiting["question"] == query_agent.question_for(claim("auto", DEMO_CASES[0]["claim"]["description"]))
        assert not any("query agent" in f["text"].lower() for f in run["findings"] if f["kind"] == "limitation")
        release.set()
        app.state.service.wait_for_judges()
        arrived = client.get(f"/api/investigations/{RUN}").json()["query_agent"]
    assert arrived["available"] is True and not arrived.get("pending") and arrived["part"]["synapt"]["query_id"] == QUERY["query_id"]


def test_a_late_answer_that_never_comes_is_reported_as_not_answered_not_left_waiting_forever(settings, monkeypatch):
    from claims.investigation import workflow

    monkeypatch.setattr(workflow, "QUERY_GRACE_SECONDS", 0.2)
    release = threading.Event()
    adapter = Agent(error=RuntimeError("socket closed; token abc123"))
    adapter.asker.wait_for = release
    app = create_app(settings, adapter=adapter)
    with TestClient(app) as client:
        client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"], "run_id": RUN})
        release.set()
        app.state.service.wait_for_judges()
        late = client.get(f"/api/investigations/{RUN}").json()["query_agent"]
    assert late["available"] is False and not late.get("pending") and "did not answer" in late["reason"]
    assert "abc123" not in json.dumps(late)


def test_a_later_save_of_a_run_that_still_says_pending_cannot_erase_the_answer_that_arrived(tmp_path):
    from claims.storage.run_store import Store

    store = Store(tmp_path / "s.sqlite")
    pending = query_agent.pending("Q?", RUN)
    store.save(RUN, {"run_id": RUN, "query_agent": pending})
    store.set_query_agent(RUN, {"available": True, "question": "Q?", "part": {"text": "answer"}, "task_id": RUN})
    store.save(RUN, {"run_id": RUN, "query_agent": pending, "status": "awaiting_review"})  # the brief's final save, which still says pending
    saved = store.get(RUN)
    assert saved["query_agent"]["available"] is True and saved["query_agent"]["part"]["text"] == "answer" and saved["status"] == "awaiting_review"
    assert store.set_query_agent("no-such-run", pending) is False
    store.connection.close()


def test_a_person_sees_the_waiting_state_without_the_task_id_or_the_vendors_name():
    waiting = query_agent.pending("For an auto claim, which documents ...?", RUN)
    person = query_agent.present(waiting, False)
    assert person["pending"] is True and "task_id" not in person and "Synapt" not in json.dumps(person)
    assert query_agent.present(waiting, True)["task_id"] == RUN
