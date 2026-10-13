"""The live view of an investigation in progress.

Spans are saved only when they close, so the board (`claims.observability.progress`) is told when each one OPENS. These tests check
that a call still running is visible while it runs, that a waiting run says it is queued, that a viewer sees only what
their role allows (no tool name, query, model or identifier for anyone but an administrator), that only the owner may
follow a run, and that the board stays bounded and safe under threads.
"""

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.schemas import ClaimInput, RetrievalBundle, SearchFilters
from claims.core.settings import Settings
from claims.observability import telemetry
from claims.observability.progress import KEEP, ProgressBoard

RUN = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
ADMIN_PASSWORD = "Synthetic admin passphrase!"
USER_PASSWORD = "Synthetic user passphrase!"


def span(board, run_id, name, kind="tool", parent=None, background=False, **attributes):
    span_id = f"s{len(board._runs[run_id].spans) + 1}"
    board.span_start(run_id, span_id, parent, name, kind, attributes, background)
    return span_id


# ----- the board on its own --------------------------------------------------------------------------


def test_a_registered_run_is_queued_then_running_then_finished():
    board = ProgressBoard()
    board.register(RUN, "alice")
    assert board.read(RUN, viewer_id="alice")["state"] == "queued"
    assert board.read(RUN, viewer_id="alice")["running_ms"] is None
    board.mark_running(RUN)
    assert board.read(RUN, viewer_id="alice")["state"] == "running"
    assert board.read(RUN, viewer_id="alice")["running_ms"] is not None
    board.finish(RUN, "awaiting_review")
    done = board.read(RUN, viewer_id="alice")
    assert done["state"] == "done" and done["outcome"] == "awaiting_review"
    board.register(OTHER, "alice")
    board.finish(OTHER, "failed")
    assert board.read(OTHER, viewer_id="alice")["state"] == "failed"


def test_a_call_that_is_still_running_is_visible_before_it_ends():
    board = ProgressBoard()
    board.register(RUN, "alice")
    sid = span(board, RUN, "synapt.call_tool", purpose="graph_search", tool="trident_search", query="auto claim", top_k=6)
    running = board.read(RUN, viewer_id="alice", admin=True)["spans"][0]
    assert running["status"] == "running" and running["duration_ms"] is None and running["result"] is None
    board.span_end(RUN, sid, "ok", 812.4, {"items": 3})
    ended = board.read(RUN, viewer_id="alice", admin=True)["spans"][0]
    assert ended["status"] == "ok" and ended["duration_ms"] == 812.4 and ended["result"] == "3 procedures"


def test_polling_with_a_cursor_returns_only_what_changed():
    board = ProgressBoard()
    board.register(RUN, "alice")
    first = span(board, RUN, "history.search", kind="retrieval")
    cursor = board.read(RUN, viewer_id="alice")["next"]
    assert board.read(RUN, cursor, viewer_id="alice")["spans"] == []
    second = span(board, RUN, "feedback.lessons", kind="retrieval")
    changed = board.read(RUN, cursor, viewer_id="alice")
    assert [s["id"] for s in changed["spans"]] == [second]
    board.span_end(RUN, first, "ok", 5.0, {"results": 8})
    again = board.read(RUN, changed["next"], viewer_id="alice")
    assert [s["id"] for s in again["spans"]] == [first] and again["spans"][0]["status"] == "ok"
    assert [s["id"] for s in board.read(RUN, 0, viewer_id="alice")["spans"]] == [first, second]


def test_only_the_owner_and_an_administrator_can_read_a_run():
    board = ProgressBoard()
    board.register(RUN, "alice")
    assert board.read(RUN, viewer_id="alice") is not None
    assert board.read(RUN, viewer_id="bob") is None
    assert board.read(RUN, viewer_id=None) is None
    assert board.read(RUN, viewer_id="bob", admin=True) is not None
    assert board.read("unknown", viewer_id="alice", admin=True) is None
    board.register(OTHER, None)  # a run with no owner (a script, an evaluation) is administrators only
    assert board.read(OTHER, viewer_id="alice") is None and board.read(OTHER, viewer_id="x", admin=True) is not None
    assert board.can_read(RUN, "alice", False) and not board.can_read(RUN, "bob", False)


def test_a_person_sees_plain_labels_and_an_administrator_also_sees_the_technical_line():
    board = ProgressBoard()
    board.register(RUN, "alice")
    sid = span(board, RUN, "synapt.call_tool", purpose="similar_claims", tool="trident_query", query="Q-SECRET-QUERY text", top_k=20)
    board.span_end(RUN, sid, "ok", 900.0, {"items": 3})
    llm = span(board, RUN, "llm.investigation", kind="llm", purpose="investigation", model="nvidia/some-model")
    board.span_end(RUN, llm, "ok", 4100.0, {"total_tokens": 1234, "attempts": 2})
    person = board.read(RUN, viewer_id="alice")["spans"]
    admin = board.read(RUN, viewer_id="alice", admin=True)["spans"]
    assert [s["label"] for s in person] == ["Find similar past claims", "Model drafts the findings"]
    assert [s["result"] for s in person] == ["3 past claims", "1,234 tokens"]
    assert all(s["detail"] is None for s in person)
    blob = repr(person).lower()
    for word in ("trident", "synapt", "nvidia", "q-secret-query", "some-model", "top_k", "attempts"):
        assert word not in blob
    assert admin[0]["detail"] == "trident_query · “Q-SECRET-QUERY text” · top 20"
    assert admin[1]["detail"] == "nvidia/some-model" and admin[1]["result"] == "1,234 tokens · 2 attempts"
    assert admin[0]["label"] == "Ticket-store search for similar past claims (trident_query, ticket_mode=only)"


def test_only_known_scalar_attributes_are_kept_and_long_text_is_cut():
    board = ProgressBoard()
    board.register(RUN, "alice")
    sid = span(
        board, RUN, "synapt.call_tool", purpose="procedures", tool="trident_get_chunks", query="q" * 1000,
        api_token="secret-token-value", attempt_log=[{"x": 1}], prompt="the whole prompt", items=5,
    )
    run = board._runs[RUN]
    kept = run.spans[sid].attributes
    assert "api_token" not in kept and "attempt_log" not in kept and "prompt" not in kept
    assert len(kept["query"]) == 300 and kept["items"] == 5
    assert "secret-token-value" not in repr(board.read(RUN, viewer_id="alice", admin=True))
    assert {"query", "tool", "model", "total_tokens"} <= KEEP and "prompt" not in KEEP and "attempt_log" not in KEEP


def test_stage_rows_carry_their_stage_key_and_a_result_in_words():
    board = ProgressBoard()
    board.register(RUN, "alice")
    sid = span(board, RUN, "retrieve", kind="stage")
    board.span_end(RUN, sid, "ok", 8000.0, {"evidence": 18, "similar_cases": 8})
    row = board.read(RUN, viewer_id="alice")["spans"][0]
    assert row["name"] == "retrieve" and row["label"] == "Gather evidence and compare past claims"
    assert row["result"] == "18 evidence items, 8 comparison cases"
    # a non-stage span never exposes its internal name
    other = span(board, RUN, "history.search", kind="retrieval")
    assert next(s for s in board.read(RUN, viewer_id="alice")["spans"] if s["id"] == other)["name"] is None


def test_a_failed_span_says_so_and_only_an_administrator_sees_the_error_type():
    board = ProgressBoard()
    board.register(RUN, "alice")
    sid = span(board, RUN, "synapt.call_tool", purpose="procedures", tool="trident_get_chunks")
    board.span_end(RUN, sid, "error", 100.0, {"error_type": "SynaptError"})
    assert board.read(RUN, viewer_id="alice")["spans"][0]["result"] == "Failed"
    assert board.read(RUN, viewer_id="alice", admin=True)["spans"][0]["result"] == "Failed (SynaptError)"


def test_counts_for_the_header_and_background_work_that_is_not_waited_on():
    board = ProgressBoard()
    board.register(RUN, "alice")
    span(board, RUN, "synapt.call_tool", purpose="procedures")
    span(board, RUN, "synapt.call_tool", purpose="similar_claims")
    span(board, RUN, "llm.classification", kind="llm", purpose="classification")
    span(board, RUN, "judge.review", kind="evaluation", background=True)
    counts = board.read(RUN, viewer_id="alice")["counts"]
    assert counts == {"knowledge_calls": 2, "model_calls": 1, "open": 3}  # the background review is not waited on


def test_the_board_is_bounded_in_spans_runs_and_how_long_finished_runs_stay():
    board = ProgressBoard(max_runs=3, max_spans=5, keep_finished_seconds=60)
    board.register(RUN, "alice")
    for _ in range(9):
        board.span_start(RUN, f"s{len(board._runs[RUN].spans)}", None, "history.search", "retrieval", {})
    read = board.read(RUN, viewer_id="alice")
    assert len(read["spans"]) == 5 and read["truncated"] is True
    for n in range(6):
        board.register(f"run-{n}", "alice")
        board.finish(f"run-{n}", "done")
    assert len(board._runs) <= 3
    old = ProgressBoard(keep_finished_seconds=1)
    old.register(RUN, "alice")
    old.finish(RUN, "done")
    old._runs[RUN].finished_at -= 10
    old.register(OTHER, "alice")
    assert not old.known(RUN) and old.known(OTHER)


def test_many_threads_opening_and_closing_spans_never_corrupt_the_board():
    board = ProgressBoard(max_spans=2000)
    board.register(RUN, "alice")
    errors = []

    def worker(n):
        try:
            for i in range(60):
                sid = f"t{n}-{i}"
                board.span_start(RUN, sid, None, "synapt.call_tool", "tool", {"purpose": "procedures"})
                board.read(RUN, 0, viewer_id="alice", admin=True)
                board.span_end(RUN, sid, "ok", 1.0, {"items": i})
        except Exception as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join(20) for t in threads]
    assert not errors
    final = board.read(RUN, 0, viewer_id="alice")
    assert len(final["spans"]) == 480 and all(s["status"] == "ok" for s in final["spans"])


def test_telemetry_reports_a_span_when_it_opens_and_again_when_it_closes():
    board = ProgressBoard()
    board.register(RUN, "alice")

    class Recorder:
        progress = board

        def add_span(self, **kwargs):
            pass

    recorder = Recorder()
    seen = []
    with (
        telemetry.Tracer(recorder).run(RUN, "investigation"),
        telemetry.span("history.search", kind="retrieval") as handle,
    ):
        seen.append(board.read(RUN, viewer_id="alice")["spans"][-1]["status"])
        handle.set(results=4, pool_size=300, ranked=[{"huge": "list"}])
    rows = {s["label"]: s for s in board.read(RUN, viewer_id="alice")["spans"]}
    assert seen == ["running"]
    assert rows["Compare against past claims in the dataset"]["result"] == "4 similar claims ranked from 300 candidates"


def test_a_recorder_without_a_board_still_works():
    class Recorder:
        def __init__(self):
            self.spans = []

        def add_span(self, **kwargs):
            self.spans.append(kwargs)

    recorder = Recorder()
    with telemetry.Tracer(recorder).run(RUN, "investigation"):
        pass
    assert len(recorder.spans) == 1


# ----- a real investigation, followed while it runs ------------------------------------------------------------


def claim_and_filters():
    return ClaimInput.model_validate(DEMO_CASES[0]["claim"]), SearchFilters()


class Gated:
    """A Synapt double whose retrieval waits for the test, so the run can be inspected in the middle of a call."""

    def __init__(self):
        self.inside = threading.Event()
        self.release = threading.Event()

    def retrieve(self, claim):
        with telemetry.span(
            "synapt.call_tool", kind="tool", tool="trident_query", purpose="similar_claims", query="auto claim in regionkey_ae.", top_k=20
        ) as handle:
            self.inside.set()
            assert self.release.wait(20), "the test never released the call"
            handle.set(items=3)
        return RetrievalBundle(mode="live", evidence=[], warnings=[], semantic_claim_ids=[])


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, claims_database_path=tmp_path / "runtime.sqlite", claims_data_path=Path("absent.json"),
        claims_artifact_dir=tmp_path / "models",
    )


def test_a_call_in_flight_is_visible_to_the_person_waiting_and_closes_when_it_returns(settings):
    gate = Gated()
    app = create_app(settings, adapter=gate)
    service = app.state.service
    claim, filters = claim_and_filters()
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.update(run=service.create(claim, filters, run_id=RUN, owner="alice")))
    with TestClient(app):
        worker.start()
        assert gate.inside.wait(20)
        mid = service.progress.read(RUN, viewer_id="alice", admin=True)
        assert mid["state"] == "running" and mid["outcome"] is None
        by_label = {s["label"]: s for s in mid["spans"]}
        stage = by_label["Gather evidence and compare past claims"]
        call = by_label["Ticket-store search for similar past claims (trident_query, ticket_mode=only)"]
        assert stage["status"] == "running" and call["status"] == "running"
        assert call["detail"] == "trident_query · “auto claim in regionkey_ae.” · top 20"
        assert call["duration_ms"] is None
        assert by_label["Classify the claim"]["status"] == "ok"  # the stage before it already finished
        assert "Compare evidence, gaps and contradictions" not in by_label  # later stages have not started
        gate.release.set()
        worker.join(60)
    end = service.progress.read(RUN, viewer_id="alice", admin=True)
    assert end["state"] == "done" and end["outcome"] == "awaiting_review"
    rows = {s["label"]: s for s in end["spans"]}
    assert rows["Ticket-store search for similar past claims (trident_query, ticket_mode=only)"]["result"] == "3 past claims"
    assert rows["Ticket-store search for similar past claims (trident_query, ticket_mode=only)"]["duration_ms"] > 0
    assert rows["Gather evidence and compare past claims"]["status"] == "ok"
    assert rows["Wait for a handler"]["status"] == "waiting"  # the handler gate is waiting, not failing
    assert outcome["run"]["status"] == "awaiting_review"


def test_the_endpoint_answers_while_the_investigation_request_is_still_in_flight(settings):
    gate = Gated()
    app = create_app(settings, adapter=gate)
    claim = DEMO_CASES[0]["claim"]
    posted = {}
    with TestClient(app) as client:
        worker = threading.Thread(
            target=lambda: posted.update(response=client.post("/api/investigations", json={"claim": claim, "run_id": RUN}))
        )
        worker.start()
        assert gate.inside.wait(20)
        live = client.get(f"/api/investigations/{RUN}/progress")
        assert live.status_code == 200
        body = live.json()
        assert body["state"] == "running" and body["counts"]["knowledge_calls"] == 1 and body["counts"]["open"] >= 2
        assert any(s["status"] == "running" for s in body["spans"])
        cursor = body["next"]
        # The past-claim workers beside the passage search may still be closing their spans (and their agents'): follow the cursor
        # until they have, then nothing may come back, because nothing changed.
        for _ in range(50):
            more = client.get(f"/api/investigations/{RUN}/progress?after={cursor}").json()
            if not more["spans"]:
                break
            cursor = more["next"]
            time.sleep(0.1)
        assert client.get(f"/api/investigations/{RUN}/progress?after={cursor}").json()["spans"] == []
        assert client.get(f"/api/investigations/{RUN}").status_code in (200, 404)  # the saved run is not final yet
        gate.release.set()
        worker.join(60)
        assert posted["response"].status_code == 200 and posted["response"].json()["run_id"] == RUN
        final = client.get(f"/api/investigations/{RUN}/progress?after={cursor}").json()
        assert final["state"] == "done" and any(s["status"] == "ok" for s in final["spans"])


def test_a_second_investigation_waits_its_turn_and_is_shown_as_queued(settings):
    app = create_app(settings)
    service = app.state.service
    claim, filters = claim_and_filters()
    worker = threading.Thread(target=lambda: service.create(claim, filters, run_id=RUN, owner="alice"))
    with TestClient(app):
        service.lock.acquire()  # another investigation is running
        try:
            worker.start()
            deadline = time.time() + 10
            while not service.progress.known(RUN) and time.time() < deadline:
                time.sleep(0.02)
            queued = service.progress.read(RUN, viewer_id="alice")
            assert queued["state"] == "queued" and queued["spans"] == [] and queued["running_ms"] is None
        finally:
            service.lock.release()
        worker.join(60)
        done = service.progress.read(RUN, viewer_id="alice")
        assert done["state"] == "done" and done["running_ms"] is not None and done["running_ms"] > 0


def test_a_client_supplied_id_is_validated_and_cannot_be_reused(settings):
    app = create_app(settings)
    claim = DEMO_CASES[0]["claim"]
    with TestClient(app) as client:
        assert client.post("/api/investigations", json={"claim": claim, "run_id": "not-a-uuid"}).status_code == 422
        first = client.post("/api/investigations", json={"claim": claim, "run_id": RUN.upper()})
        assert first.status_code == 200 and first.json()["run_id"] == RUN  # stored in lower case
        assert client.post("/api/investigations", json={"claim": claim, "run_id": RUN}).status_code == 409
        without = client.post("/api/investigations", json={"claim": claim})
        assert without.status_code == 200 and without.json()["run_id"] != RUN
        assert client.get("/api/investigations/33333333-3333-4333-8333-333333333333/progress").status_code == 404


def test_a_failed_investigation_reports_failed_not_done(settings):
    class Broken:
        def retrieve(self, claim):
            raise RuntimeError("boom")

    app = create_app(settings, adapter=Broken())
    claim = DEMO_CASES[0]["claim"]
    with TestClient(app) as client:
        assert client.post("/api/investigations", json={"claim": claim, "run_id": RUN}).json()["status"] == "failed"
        body = client.get(f"/api/investigations/{RUN}/progress").json()
        assert body["state"] == "failed" and body["outcome"] == "failed"
        assert any(s["status"] == "error" for s in body["spans"])


# ----- who may follow a run -----------------------------------------------------------------------------------


def sign_in(client, username, password):
    csrf = client.get("/api/auth/session").json()["csrf_token"]
    response = client.post("/api/auth/login", json={"username": username, "password": password}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_only_the_owner_and_an_administrator_can_follow_a_run_and_the_wording_follows_the_role(tmp_path):
    settings = Settings(
        _env_file=None, claims_auth_enabled=True, claims_search_enabled=False,
        claims_database_path=tmp_path / "cases.sqlite", claims_data_path=Path("absent.json"),
        claims_artifact_dir=tmp_path / "models",
    )
    app = create_app(settings)
    claim = DEMO_CASES[0]["claim"]
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.get(f"/api/investigations/{RUN}/progress").status_code == 401
        csrf = {"X-CSRF-Token": client.get("/api/auth/session").json()["csrf_token"]}
        client.post("/api/auth/setup", json={"username": "admin", "password": ADMIN_PASSWORD, "role": "admin"}, headers=csrf)
        admin = sign_in(client, "admin", ADMIN_PASSWORD)
        for name in ("alice", "bob"):
            assert client.post("/api/admin/users", json={"username": name, "password": USER_PASSWORD, "role": "user"}, headers=admin).status_code == 200
        client.post("/api/auth/logout", headers=admin)

        alice = sign_in(client, "alice", USER_PASSWORD)
        assert client.post("/api/investigations", json={"claim": claim, "run_id": RUN}, headers=alice).status_code == 200
        mine = client.get(f"/api/investigations/{RUN}/progress")
        assert mine.status_code == 200 and mine.json()["state"] == "done"
        text = repr(mine.json()).lower()
        for word in ("trident", "synapt", "nvidia", "mcp", "query", "model call"):
            assert word not in text
        assert all(s["detail"] is None for s in mine.json()["spans"])
        client.post("/api/auth/logout", headers=alice)

        bob = sign_in(client, "bob", USER_PASSWORD)
        assert client.get(f"/api/investigations/{RUN}/progress").status_code == 404
        client.post("/api/auth/logout", headers=bob)

        admin = sign_in(client, "admin", ADMIN_PASSWORD)
        theirs = client.get(f"/api/investigations/{RUN}/progress")
        assert theirs.status_code == 200
        assert any(s["detail"] for s in theirs.json()["spans"])  # the technical line is administrators only
