"""A handler rates a knowledge-base answer and the verdict goes back to Synapt (`trident_feedback`).

The tenant's schema has no provider field, so the usual provider scoping cannot apply. These tests pin what replaces it: the
query ID is looked up from the saved run (never taken from the request), every argument is validated against the discovered
schema, a verdict is sent once per answer, nothing is saved unless Synapt accepted it, a note is masked, and the brief is
untouched.
"""

import copy
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from mcp.types import CallToolResult, TextContent, Tool
from test_query_agent import QUERY, Agent
from test_sidechat import RUN as SAMPLE_RUN

from claims.agents import access
from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.settings import Settings
from claims.storage.run_store import Store
from claims.synapt import query_feedback as qf
from claims.synapt.adapter import LiveSynaptAdapter, SynaptError

RID = "11111111-1111-4111-8111-111111111111"

# ----- the adapter ---------------------------------------------------------------------------------------------------

FEEDBACK_TOOL = Tool(
    name="trident_feedback",
    inputSchema={
        "type": "object", "additionalProperties": False, "required": ["feedback_id", "caller_type", "verdict"],
        "properties": {
            "feedback_id": {"type": "string"},
            "caller_type": {"enum": ["user", "agent", "mcp_tool"], "type": "string"},
            "verdict": {"enum": ["deflected", "partial", "not_deflected"], "type": "string"},
            "post_action": {"anyOf": [{"enum": ["proceeded", "retried", "fallback", "escalated", "failed"], "type": "string"}, {"type": "null"}], "default": None},
            "score": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": None},
            "reason": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        },
    },
)


def json_result(payload):
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload))])


@pytest.fixture
def adapter():
    """The adapter, used as the human reviewer: the only actor that may send feedback to Synapt."""
    with access.acting_as("reviewer"):
        yield LiveSynaptAdapter(Settings(_env_file=None, synapt_username="test-user", synapt_password="very-secret-password", synapt_provider_id="provider-1"))


def session_with(monkeypatch, adapter, tools, response):
    calls = []

    class Session:
        async def list_tools(self, cursor=None):
            return SimpleNamespace(tools=tools, nextCursor=None)

        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            if isinstance(response, Exception):
                raise response
            return response

    @asynccontextmanager
    async def session():
        yield Session()

    monkeypatch.setattr(adapter, "_session", session)
    return calls


def test_the_verdict_goes_to_synapt_exactly_as_its_schema_defines_it_with_no_provider_field(monkeypatch, adapter):
    calls = session_with(monkeypatch, adapter, [FEEDBACK_TOOL], json_result({"accepted": True, "status_code": 200, "status": "received"}))
    answer = adapter.send_feedback("4af2de76-8a69-4f27-9424-2e161dd8475f", "partial", reason="Missed the police report step")
    assert answer["accepted"] is True
    assert calls == [("trident_feedback", {
        "feedback_id": "4af2de76-8a69-4f27-9424-2e161dd8475f", "caller_type": "user", "verdict": "partial", "reason": "Missed the police report step",
    })]


def test_a_verdict_the_schema_does_not_define_is_refused_before_anything_is_sent(monkeypatch, adapter):
    calls = session_with(monkeypatch, adapter, [FEEDBACK_TOOL], json_result({"accepted": True}))
    with pytest.raises(SynaptError):
        adapter.send_feedback("q1", "excellent")
    with pytest.raises(SynaptError):
        adapter.send_feedback("q1", "partial", caller_type="robot")
    with pytest.raises(SynaptError):
        adapter.send_feedback("  ", "partial")
    assert calls == []


def test_a_tenant_without_the_tool_or_a_response_that_is_not_accepted_is_an_error(monkeypatch, adapter):
    session_with(monkeypatch, adapter, [], json_result({"accepted": True}))
    with pytest.raises(SynaptError, match="does not expose the feedback tool"):
        adapter.send_feedback("q1", "partial")
    session_with(monkeypatch, adapter, [FEEDBACK_TOOL], json_result({"accepted": False, "status": "rejected"}))
    with pytest.raises(SynaptError, match="did not accept"):
        adapter.send_feedback("q1", "partial")


def test_a_failed_send_is_not_retried_because_the_write_may_have_landed(monkeypatch, adapter):
    import httpx

    calls = session_with(monkeypatch, adapter, [FEEDBACK_TOOL], httpx.ConnectTimeout("slow"))
    with pytest.raises(SynaptError):
        adapter.send_feedback("q1", "partial")
    assert len(calls) == 1


def test_a_long_note_is_cut_and_a_blank_one_is_not_sent(monkeypatch, adapter):
    calls = session_with(monkeypatch, adapter, [FEEDBACK_TOOL], json_result({"accepted": True}))
    adapter.send_feedback("q1", "deflected", reason="x" * 900)
    adapter.send_feedback("q2", "deflected", reason="   ")
    assert len(calls[0][1]["reason"]) == 500 and "reason" not in calls[1][1]


# ----- the service --------------------------------------------------------------------------------------------------


class Sender:
    def __init__(self, error=None):
        self.sent, self.error = [], error

    def send_feedback(self, feedback_id, verdict, **kwargs):
        self.sent.append((feedback_id, verdict, kwargs))
        if self.error:
            raise self.error
        return {"accepted": True}


def saved_run():
    run = copy.deepcopy(SAMPLE_RUN)
    run["query_agent"] = {"available": True, "question": "Q", "task_id": RID, "part": {"source": "synapt", "status": "ok", "synapt": {"query_id": "inv-query-id"}}}
    return run


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "fb.sqlite")
    s.save(RID, saved_run())
    yield s
    s.connection.close()


def side_answer(store, with_synapt=True):
    part = {"source": "synapt", "status": "ok", "synapt": {"query_id": "side-query-id"}} if with_synapt else {"source": "claim", "status": "ok", "synapt": None}
    return store.add_side_question(RID, "alice", "Which documents?", {"question": "Which documents?", "parts": [part]})["id"]


def test_each_choice_maps_to_the_verdict_synapt_defines_and_the_query_id_comes_from_the_saved_run(tmp_path):
    send = Sender()
    for choice, verdict in (("helpful", "deflected"), ("partly", "partial"), ("not_helpful", "not_deflected")):
        fresh = Store(tmp_path / f"{choice}.sqlite")
        fresh.save(RID, saved_run())
        qf.submit(fresh, send, saved_run(), target="investigation", choice=choice, reason=None, owner="alice")
        fresh.connection.close()
        assert send.sent[-1] == ("inv-query-id", verdict, {"caller_type": "user", "reason": None})
    assert qf.CHOICES == {"helpful": "deflected", "partly": "partial", "not_helpful": "not_deflected"}


def test_a_side_chat_answer_is_rated_through_its_own_query_id(store):
    send = Sender()
    target = f"side:{side_answer(store)}"
    done = qf.submit(store, send, saved_run(), target=target, choice="helpful", reason="Clear steps", owner="alice")
    assert send.sent == [("side-query-id", "deflected", {"caller_type": "user", "reason": "Clear steps"})]
    assert done["target"] == target and done["choice"] == "helpful"


def test_what_cannot_be_rated_is_refused_with_a_reason(store):
    send = Sender()
    no_answer = side_answer(store, with_synapt=False)
    for target, status in ((f"side:{no_answer}", 404), ("side:999", 404), ("somewhere", 404), ("side:x", 404)):
        with pytest.raises(qf.FeedbackError) as error:
            qf.submit(store, send, saved_run(), target=target, choice="helpful", reason=None, owner="a")
        assert error.value.status == status, target
    bare = saved_run()
    bare["query_agent"] = {"available": False, "reason": "x", "part": None}
    with pytest.raises(qf.FeedbackError) as error:
        qf.submit(store, send, bare, target="investigation", choice="helpful", reason=None, owner="a")
    assert error.value.status == 404
    with pytest.raises(qf.FeedbackError) as bad:
        qf.submit(store, send, saved_run(), target="investigation", choice="great", reason=None, owner="a")
    assert bad.value.status == 422
    assert send.sent == []


def test_one_verdict_per_answer_and_a_note_is_masked_before_it_leaves(store):
    send = Sender()
    qf.submit(store, send, saved_run(), target="investigation", choice="not_helpful", reason="Email jane@example.com or 555-123-4567 about it", owner="alice")
    assert send.sent[0][2]["reason"] == "Email [EMAIL REDACTED] or [PHONE REDACTED] about it"
    with pytest.raises(qf.FeedbackError) as again:
        qf.submit(store, send, saved_run(), target="investigation", choice="helpful", reason=None, owner="bob")
    assert again.value.status == 409 and len(send.sent) == 1
    assert qf.listing(store, RID) == [{"target": "investigation", "choice": "not_helpful", "sent_at": qf.listing(store, RID)[0]["sent_at"]}]
    assert "inv-query-id" not in json.dumps(qf.listing(store, RID)) and "not_deflected" not in json.dumps(qf.listing(store, RID))


def test_a_failed_send_saves_nothing_hides_the_providers_error_and_can_be_tried_again(store):
    send = Sender(error=RuntimeError("socket closed token abc123"))
    with pytest.raises(qf.FeedbackError) as failed:
        qf.submit(store, send, saved_run(), target="investigation", choice="helpful", reason=None, owner="alice")
    assert failed.value.status == 502 and "abc123" not in str(failed.value)
    assert qf.listing(store, RID) == []
    send.error = None
    assert qf.submit(store, send, saved_run(), target="investigation", choice="helpful", reason=None, owner="alice")["choice"] == "helpful"


def test_without_a_synapt_connection_feedback_says_so(store):
    with pytest.raises(qf.FeedbackError) as error:
        qf.submit(store, object(), saved_run(), target="investigation", choice="helpful", reason=None, owner="alice")
    assert error.value.status == 503


def test_rating_an_answer_changes_nothing_about_the_investigation_but_adds_one_audit_event(store):
    before_run = json.dumps(store.get(RID), sort_keys=True)
    before_spans = store.spans(RID)
    before = store.audit_records(RID)["total"]
    qf.submit(store, Sender(), saved_run(), target="investigation", choice="partly", reason=None, owner="alice")
    assert json.dumps(store.get(RID), sort_keys=True) == before_run and store.spans(RID) == before_spans
    audit = store.audit_records(RID)
    assert audit["total"] == before + 1 and audit["items"][-1]["kind"] == "query_feedback"
    assert audit["items"][-1]["body"] == {"target": "investigation", "choice": "partly", "verdict": "partial"}


# ----- through the API ----------------------------------------------------------------------------------------------


class RatedAgent(Agent):
    def __init__(self, **options):
        super().__init__(**options)
        self.feedback = []

    def send_feedback(self, feedback_id, verdict, **kwargs):
        self.feedback.append((feedback_id, verdict, kwargs))
        return {"accepted": True, "status": "received"}


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, claims_database_path=tmp_path / "runtime.sqlite", claims_data_path=Path("absent.json"), claims_artifact_dir=tmp_path / "models")


def test_over_the_api_a_verdict_reaches_synapt_once_and_the_page_can_see_what_was_rated(settings):
    adapter = RatedAgent()
    app = create_app(settings, adapter=adapter)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"], "run_id": RID}).json()
        assert client.get(f"/api/investigations/{RID}/query-feedback").json() == {"items": []}
        sent = client.post(f"/api/investigations/{RID}/query-feedback", json={"target": "investigation", "choice": "helpful", "reason": "Clear"})
        assert sent.status_code == 200 and sent.json()["choice"] == "helpful"
        assert adapter.feedback == [(QUERY["query_id"], "deflected", {"caller_type": "user", "reason": "Clear"})]
        assert client.post(f"/api/investigations/{RID}/query-feedback", json={"target": "investigation", "choice": "partly"}).status_code == 409
        assert [i["target"] for i in client.get(f"/api/investigations/{RID}/query-feedback").json()["items"]] == ["investigation"]
        # a side answer has its own query, rated separately
        asked = client.post(f"/api/investigations/{RID}/side-chat", json={"question": "Which documents should I request?"}).json()
        side = client.post(f"/api/investigations/{RID}/query-feedback", json={"target": f"side:{asked['id']}", "choice": "partly"})
        assert side.status_code == 200 and len(adapter.feedback) == 2
        assert client.get(f"/api/investigations/{RID}").json()["evidence"] == run["evidence"]  # the brief is untouched


def test_the_api_validates_the_request_and_unknown_cases(settings):
    app = create_app(settings, adapter=RatedAgent())
    with TestClient(app) as client:
        client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"], "run_id": RID})
        url = f"/api/investigations/{RID}/query-feedback"
        assert client.post(url, json={"target": "investigation", "choice": "great"}).status_code == 422
        assert client.post(url, json={"target": "../etc", "choice": "helpful"}).status_code == 422
        assert client.post(url, json={"target": "investigation", "choice": "helpful", "query_id": "x"}).status_code == 422  # a query ID is never taken from the request
        assert client.post(url, json={"target": "investigation", "choice": "helpful", "reason": "x" * 601}).status_code == 422
        other = "33333333-3333-4333-8333-333333333333"
        assert client.post(f"/api/investigations/{other}/query-feedback", json={"target": "investigation", "choice": "helpful"}).status_code == 404
        assert client.get(f"/api/investigations/{other}/query-feedback").status_code == 404


def test_only_the_owner_and_an_administrator_can_rate_and_nobody_but_an_administrator_sees_a_query_id(tmp_path):
    settings = Settings(
        _env_file=None, claims_auth_enabled=True, claims_search_enabled=False, claims_database_path=tmp_path / "cases.sqlite",
        claims_data_path=Path("absent.json"), claims_artifact_dir=tmp_path / "models",
    )
    adapter = RatedAgent()
    app = create_app(settings, adapter=adapter)

    def sign_in(client, username, password):
        csrf = client.get("/api/auth/session").json()["csrf_token"]
        response = client.post("/api/auth/login", json={"username": username, "password": password}, headers={"X-CSRF-Token": csrf})
        assert response.status_code == 200, response.text
        return {"X-CSRF-Token": response.json()["csrf_token"]}

    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        csrf = {"X-CSRF-Token": client.get("/api/auth/session").json()["csrf_token"]}
        client.post("/api/auth/setup", json={"username": "admin", "password": "Synthetic admin passphrase!", "role": "admin"}, headers=csrf)
        admin = sign_in(client, "admin", "Synthetic admin passphrase!")
        for name in ("alice", "bob"):
            client.post("/api/admin/users", json={"username": name, "password": "Synthetic user passphrase!", "role": "user"}, headers=admin)
        client.post("/api/auth/logout", headers=admin)

        alice = sign_in(client, "alice", "Synthetic user passphrase!")
        client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"], "run_id": RID}, headers=alice)
        assert QUERY["query_id"] not in json.dumps(client.get(f"/api/investigations/{RID}").json()["query_agent"])
        done = client.post(f"/api/investigations/{RID}/query-feedback", json={"target": "investigation", "choice": "helpful"}, headers=alice)
        assert done.status_code == 200 and QUERY["query_id"] not in json.dumps(done.json())
        assert adapter.feedback[0][0] == QUERY["query_id"]  # the real ID went to Synapt although the person never saw it
        client.post("/api/auth/logout", headers=alice)

        bob = sign_in(client, "bob", "Synthetic user passphrase!")
        assert client.get(f"/api/investigations/{RID}/query-feedback").status_code == 404
        assert client.post(f"/api/investigations/{RID}/query-feedback", json={"target": "investigation", "choice": "partly"}, headers=bob).status_code == 404
