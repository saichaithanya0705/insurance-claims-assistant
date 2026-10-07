"""Per-query traces, reconstruction for older runs, system metrics and their access rules."""

import json
import shutil
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from claims import telemetry
from claims.api import create_app
from claims.demo import DEMO_CASES
from claims.observability import Observatory
from claims.settings import Settings
from claims.store import Store

STAGES = ["classify", "retrieve", "investigate", "risk", "recommend", "validate", "judge", "review"]


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        claims_database_path=tmp_path / "runtime.sqlite",
        claims_data_path=tmp_path / "absent.json",
        claims_artifact_dir=tmp_path / "models",
        claims_search_enabled=False,
    )


def reopened(app):
    """A fresh store on the app's database: the app closes its own when its client block ends."""
    return Store(app.state.service.settings.claims_database_path)


def spans_of(app, run_id):
    store = reopened(app)
    try:
        return store.spans(run_id)
    finally:
        store.close()


def by_name(spans, name):
    return [s for s in spans if s["name"] == name]


# ----- span machinery ------------------------------------------------------------------------


def test_span_is_a_no_op_without_an_active_trace(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    with telemetry.span("anything", kind="step", detail=1) as handle:
        handle.set(more=2)
        handle.fail(RuntimeError("x"))
    assert handle.span_id is None
    assert store.light_spans(["nobody"]) == {}


def test_attributes_are_bounded_json_safe_and_never_cut_in_half():
    cleaned = telemetry.clean_attributes(
        {
            "nan": float("nan"),
            "inf": float("inf"),
            "tuple": (1, 2),
            "set": {3},
            "object": object,
            "huge": "x" * 20_000,
            "nested": {"k": [1, {"deep": 2.5}]},
        }
    )
    assert cleaned["nan"] is None and cleaned["inf"] is None
    assert cleaned["tuple"] == [1, 2] and cleaned["set"] == [3]
    assert isinstance(cleaned["object"], str)
    assert cleaned["huge"] == {"truncated": True, "bytes": cleaned["huge"]["bytes"]}
    assert cleaned["nested"] == {"k": [1, {"deep": 2.5}]}
    json.dumps(cleaned, allow_nan=False)  # SQLite's JSON functions reject NaN


def test_a_failing_span_records_the_error_type_only_and_reraises(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    tracer = telemetry.Tracer(store)
    with (
        pytest.raises(RuntimeError),
        tracer.run("r1", "investigation"),
        telemetry.span("work", kind="step"),
    ):
        raise RuntimeError("secret provider message")
    rows = {s["name"]: s for s in store.spans("r1")}
    assert rows["work"]["status"] == "error"
    assert rows["work"]["attributes"]["error_type"] == "RuntimeError"
    assert "secret" not in json.dumps(rows)
    assert rows["work"]["parent_id"] == rows["investigation"]["span_id"]


def test_work_inside_background_work_is_background_too(tmp_path):
    store = Store(tmp_path / "t.sqlite")
    tracer = telemetry.Tracer(store)
    with tracer.run("r1", "investigation"), telemetry.span("judge", kind="stage"):
        context = telemetry.current()
    with (
        telemetry.attach(context),
        telemetry.span("judge.review", kind="evaluation", background=True),
        telemetry.span("llm.judge", kind="llm"),
    ):
        pass
    spans = {s["name"]: s for s in store.spans("r1")}
    assert "background" not in spans["judge"]["attributes"]
    assert spans["judge.review"]["attributes"]["background"] is True
    assert spans["llm.judge"]["attributes"]["background"] is True  # inherited, not repeated by callers
    assert spans["llm.judge"]["parent_id"] == spans["judge.review"]["span_id"]


def test_recording_failure_never_breaks_the_work_it_observes():
    class Broken:
        def add_span(self, **kwargs):
            raise OSError("disk full")

    with telemetry.Tracer(Broken()).run("r1", "investigation"):
        result = 42
    assert result == 42


# ----- a recorded run ------------------------------------------------------------------------


def test_fixture_run_records_every_stage_with_nested_work(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[1]["claim"]}).json()
    spans = spans_of(app, run["run_id"])
    root = by_name(spans, "investigation")[0]
    assert root["parent_id"] is None and root["kind"] == "run"
    assert root["attributes"]["origin"] == "user"
    assert root["attributes"]["outcome"] == "awaiting_review"
    stages = {s["name"]: s for s in spans if s["kind"] == "stage"}
    assert list(stages) == STAGES
    assert all(s["parent_id"] == root["span_id"] for s in stages.values())
    # The handler gate pauses the workflow: that is waiting, not an error.
    assert stages["review"]["status"] == "waiting"
    assert all(stages[name]["status"] == "ok" for name in STAGES[:-1])
    # Nested work hangs under the stage that did it.
    for name, stage in (
        ("knowledge.retrieve", "retrieve"),
        ("history.search", "retrieve"),
        ("feedback.lessons", "retrieve"),
        ("models.predict", "risk"),
        ("priority.score", "risk"),
    ):
        assert by_name(spans, name)[0]["parent_id"] == stages[stage]["span_id"], name
    assert stages["risk"]["attributes"]["priority_score"] == run["priority"]["score"]
    checks = stages["validate"]["attributes"]["checks"]
    assert checks == run["validation"]["checks"]
    ranked = by_name(spans, "history.search")[0]["attributes"]["ranked"]
    assert len(ranked) == len(run["similar_cases"])
    for entry, case in zip(ranked, run["similar_cases"], strict=True):
        assert entry["claim_id"] == case["claim_id"]
        assert entry["total"] == pytest.approx(case["similarity_score"], abs=1e-6)
        parts = entry["keyword_points"] + entry["feature_points"] + entry["semantic_points"]
        assert parts == pytest.approx(entry["total"], abs=2e-6)


def test_review_adds_a_second_root_without_changing_the_investigation_duration(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        before = telemetry.summarize_spans(spans_of(app, run["run_id"]))["duration_ms"]
        client.post(
            f"/api/investigations/{run['run_id']}/review",
            json={"decision": "accept_brief", "note": "Sources checked"},
        )
    spans = spans_of(app, run["run_id"])
    roots = [s["name"] for s in spans if s["parent_id"] is None]
    assert roots == ["investigation", "handler_review"]
    assert by_name(spans, "handler_review")[0]["attributes"]["decision"] == "accept_brief"
    # A second `review` stage ran after the handler decided; the first one was the pause.
    assert [s["status"] for s in by_name(spans, "review")] == ["waiting", "ok"]
    assert telemetry.summarize_spans(spans)["duration_ms"] == pytest.approx(before)


def test_a_failed_run_keeps_the_trace_of_what_it_did_before_failing(settings, monkeypatch):
    app = create_app(settings)

    def explode(*args, **kwargs):
        raise RuntimeError("provider said something private")

    monkeypatch.setattr(app.state.service.agents, "investigate", explode)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
    assert run["status"] == "failed"
    spans = spans_of(app, run["run_id"])
    root = by_name(spans, "investigation")[0]
    assert root["status"] == "error" and root["attributes"]["outcome"] == "failed"
    stages = {s["name"]: s for s in spans if s["kind"] == "stage"}
    assert stages["classify"]["status"] == "ok" and stages["retrieve"]["status"] == "ok"
    assert stages["investigate"]["status"] == "error"
    assert stages["investigate"]["attributes"]["error_type"] == "RuntimeError"
    assert "risk" not in stages
    assert "private" not in json.dumps(spans)


def test_evaluation_suite_runs_are_labelled_so_they_can_be_separated(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/api/evaluations/run", json={"judge": False})
        client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]})
    store = reopened(app)
    origins = [
        by_name(store.spans(row["run_id"]), "investigation")[0]["attributes"]["origin"]
        for row in store.search(limit=100)["items"]
    ]
    store.close()
    assert origins.count("evaluation") == len(DEMO_CASES) and origins.count("user") == 1


# ----- a live-mode run through a mocked model ------------------------------------------------


def live_settings(tmp_path):
    return Settings(
        _env_file=None,
        agent_mode="live",
        nvidia_api_key="fake-nvidia-secret",
        claims_database_path=tmp_path / "live.sqlite",
        claims_data_path=tmp_path / "absent.json",
        claims_artifact_dir=tmp_path / "models",
        claims_search_enabled=False,
    )


def mock_model(monkeypatch, usage=None, fail_first_investigation=False):
    original = httpx.Client
    state = {"failed": False}

    def respond(request):
        body = json.loads(request.content)
        objective = body["messages"][0]["content"]
        if "independent reviewer" in objective:
            content = {
                "grounded": True,
                "boundary_respected": True,
                "recommendations_supported": True,
                "score": 0.9,
                "issues": [],
                "summary": "The brief follows its evidence.",
            }
        elif "Classify into" in objective:
            content = {"claim_type": "auto", "method": "live_model", "needs_review": False}
        elif "Identify useful" in objective:
            if fail_first_investigation and not state["failed"]:
                state["failed"] = True
                return httpx.Response(503, json={})
            content = {
                "findings": [
                    {"kind": "fact", "text": "Claimed amount is reported.", "source_ids": ["claim:input"]},
                    {"kind": "limitation", "text": "Outcomes do not establish coverage.", "source_ids": []},
                ]
            }
        else:
            content = {
                "recommendations": [
                    {
                        "action": "Verify applicable policy terms with the handler",
                        "reason": "Policy wording must be checked.",
                        "source_ids": ["claim:input"],
                    }
                ]
            }
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(content)}, "finish_reason": "stop"}],
                "usage": usage,
            },
        )

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs))
    monkeypatch.setattr("claims.llm.time.sleep", lambda seconds: None)


def test_model_calls_record_purpose_tokens_attempts_and_links_to_the_full_exchange(
    tmp_path, monkeypatch
):
    mock_model(
        monkeypatch,
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        fail_first_investigation=True,
    )
    app = create_app(live_settings(tmp_path))
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        assert run["status"] == "awaiting_review"
        spans = spans_of(app, run["run_id"])
        stages = {s["name"]: s for s in spans if s["kind"] == "stage"}
        llm = {s["attributes"]["purpose"]: s for s in spans if s["kind"] == "llm"}
        assert set(llm) == {"classification", "investigation", "recommendation"}
        for purpose, stage in (
            ("classification", "classify"),
            ("investigation", "investigate"),
            ("recommendation", "recommend"),
        ):
            assert llm[purpose]["parent_id"] == stages[stage]["span_id"]
        assert llm["classification"]["attributes"]["total_tokens"] == 150
        assert llm["classification"]["attributes"]["attempts"] == 1
        # One HTTP 503 was retried: two attempts, the first failed.
        retried = llm["investigation"]["attributes"]
        assert retried["attempts"] == 2
        assert [a["outcome"] for a in retried["attempt_log"]] == ["http_failure", "ok"]
        assert retried["attempt_log"][0]["status_code"] == 503
        digest = telemetry.summarize_spans(spans)["llm"]
        assert digest["calls"] == 3 and digest["retries"] == 1
        assert digest["tokens"] == {"prompt": 300, "completion": 150, "total": 450}
        # The span points at the audit events that hold the whole prompt and the answer.
        store = app.state.service.store
        prompt = store.audit_event(run["run_id"], llm["classification"]["attributes"]["prompt_events"][0])
        output = store.audit_event(run["run_id"], llm["classification"]["attributes"]["output_event"])
        assert prompt["kind"] == "model_prompt" and prompt["body"]["messages"][0]["role"] == "system"
        assert output["kind"] == "model_output" and output["body"]["usage"]["total_tokens"] == 150
        assert "fake-nvidia-secret" not in json.dumps(spans)


def test_the_independent_review_is_recorded_as_background_work(tmp_path, monkeypatch):
    mock_model(monkeypatch, usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
    settings = live_settings(tmp_path).model_copy(
        update={"judge_mode": "inline", "judge_model": "judge-model-x"}
    )
    app = create_app(settings)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        app.state.service.wait_for_judges(30)
    spans = spans_of(app, run["run_id"])
    stages = {s["name"]: s for s in spans if s["kind"] == "stage"}
    review = by_name(spans, "judge.review")[0]
    judge_call = next(s for s in spans if s["kind"] == "llm" and s["attributes"]["purpose"] == "judge")
    assert review["parent_id"] == stages["judge"]["span_id"]
    assert judge_call["parent_id"] == review["span_id"]
    assert review["attributes"]["background"] is True and judge_call["attributes"]["background"] is True
    assert review["attributes"]["status"] == "completed" and review["attributes"]["passed"] is True
    foreground = [s for s in spans if s["kind"] == "llm" and not s["attributes"].get("background")]
    assert {s["attributes"]["purpose"] for s in foreground} == {"classification", "investigation", "recommendation"}
    # The time a handler waited excludes the review, which finishes after the brief is shown.
    digest = telemetry.summarize_spans(spans)
    assert digest["duration_ms"] == by_name(spans, "investigation")[0]["duration_ms"]
    assert digest["llm"]["calls"] == 4


def test_missing_or_malformed_usage_is_recorded_as_absent_not_invented(tmp_path, monkeypatch):
    mock_model(monkeypatch, usage=["unexpected"])
    app = create_app(live_settings(tmp_path))
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
    llm = [s for s in spans_of(app, run["run_id"]) if s["kind"] == "llm"]
    assert llm and all("total_tokens" not in s["attributes"] for s in llm)
    assert telemetry.summarize_spans(spans_of(app, run["run_id"]))["llm"]["tokens"]["total"] == 0


# ----- reconstruction for runs saved before tracing ------------------------------------------


def event(id, time, kind, **fields):
    base = dict.fromkeys(
        (
            "stage", "model", "role", "attempt", "elapsed_seconds", "prompt_tokens",
            "completion_tokens", "total_tokens", "reason", "decision",
        )
    )
    return base | {"id": id, "run_id": "legacy-run", "time": time, "kind": kind, **fields}


def test_reconstruction_places_stages_and_model_calls_and_says_it_is_approximate():
    day = "2026-10-07T14:12:"
    events = [
        event(1, day + "39.000000+00:00", "model_prompt", role="Classify into auto", model="m1", attempt=1),
        event(2, day + "40.500000+00:00", "model_output", role="Classify into auto", model="m1",
              attempt=1, elapsed_seconds=1.5, prompt_tokens=10, completion_tokens=5, total_tokens=15),
        event(3, day + "40.500000+00:00", "stage", stage="classify"),
        event(4, day + "46.000000+00:00", "stage", stage="retrieve"),
        event(5, day + "46.100000+00:00", "model_prompt", role="Identify useful gaps", model="m1", attempt=1),
        event(6, day + "46.800000+00:00", "model_failure", role="Identify useful gaps", attempt=1, reason="http_failure"),
        event(7, day + "46.900000+00:00", "model_prompt", role="Identify useful gaps", model="m1", attempt=2),
        event(8, day + "49.000000+00:00", "model_output", role="Identify useful gaps", model="m1",
              attempt=2, elapsed_seconds=2.1, prompt_tokens=200, completion_tokens=40, total_tokens=240),
        event(9, day + "49.000000+00:00", "stage", stage="investigate"),
        event(10, day + "50.000000+00:00", "model_prompt", role="judge", model="judge-m", attempt=1),
        event(11, day + "50.000000+00:00", "stage", stage="judge"),
        event(12, day + "58.000000+00:00", "model_output", role="judge", model="judge-m",
              attempt=1, elapsed_seconds=8.0, prompt_tokens=300, completion_tokens=20, total_tokens=320),
        event(13, day + "59.000000+00:00", "submitted_by"),
        event(14, "2026-10-07T15:00:00.000000+00:00", "handler_review", decision="accept_brief"),
    ]
    spans = telemetry.reconstruct_spans("legacy-run", events, {"status": "reviewed", "mode": "live", "agent_mode": "live"})
    assert all(s["attributes"]["reconstructed"] for s in spans)
    by = {s["name"]: s for s in spans}
    assert by["investigation"]["duration_ms"] == pytest.approx(11_000)  # first event to last stage
    assert by["investigation"]["attributes"]["origin"] == "user"
    assert by["classify"]["duration_ms"] == pytest.approx(1_500)
    assert by["retrieve"]["duration_ms"] == pytest.approx(5_500)
    assert by["investigate"]["duration_ms"] == pytest.approx(3_000)
    llm = [s for s in spans if s["kind"] == "llm"]
    assert [s["attributes"]["purpose"] for s in llm] == ["classification", "investigation", "judge"]
    investigation_call = llm[1]
    assert investigation_call["attributes"]["attempts"] == 2
    assert investigation_call["attributes"]["total_tokens"] == 240
    assert investigation_call["parent_id"] == by["investigate"]["span_id"]
    assert investigation_call["attributes"]["prompt_events"] == [5, 7]
    assert investigation_call["attributes"]["output_event"] == 8
    judge_call = llm[2]
    assert judge_call["attributes"]["background"] is True
    assert judge_call["parent_id"] == by["judge"]["span_id"]
    assert judge_call["duration_ms"] == pytest.approx(8_000)
    assert by["handler_review"]["attributes"]["outcome"] == "accept_brief"
    digest = telemetry.summarize_spans(spans)
    # The background judge is not part of the time a handler waited for the brief.
    assert digest["duration_ms"] == pytest.approx(11_000)
    assert digest["llm"]["tokens"]["total"] == 15 + 240 + 320
    assert digest["llm"]["retries"] == 1


def test_a_run_with_no_stage_events_has_no_reconstructed_trace():
    assert telemetry.reconstruct_spans("x", [event(1, "2026-10-07T14:12:39+00:00", "model_prompt")]) == []


def test_every_run_in_the_shipped_template_database_reconstructs_cleanly(tmp_path):
    template = Path("data/bootstrap/claims.sqlite")
    if not template.exists():
        pytest.skip("template database not present")
    copy = tmp_path / "template.sqlite"
    shutil.copyfile(template, copy)
    store = Store(copy)
    observatory = Observatory(store)
    runs = [row["run_id"] for row in store.search(limit=100)["items"]]
    assert runs
    raw = sqlite3.connect(copy)
    traced = 0
    for run_id in runs:
        trace = observatory.trace(run_id)
        if trace is None:
            continue
        traced += 1
        assert trace["source"] == "reconstructed" and trace["note"]
        assert all(s["duration_ms"] >= 0 and s["offset_ms"] >= 0 for s in trace["spans"])
        assert trace["spans"][0]["name"] in ("investigation", "handler_review")
        expected = sum(
            row[0]
            for row in raw.execute(
                "SELECT json_extract(body,'$.usage.total_tokens') FROM audit "
                "WHERE run_id=? AND kind='model_output'",
                (run_id,),
            )
            if row[0]
        )
        assert trace["summary"]["llm"]["tokens"]["total"] == expected, run_id
    assert traced > 0
    # The dashboard also accepts them, in full.
    summary = observatory.summary("all")
    assert summary["queries"]["total"] == traced
    assert summary["coverage"]["reconstructed"] == traced


# ----- dashboard aggregation -----------------------------------------------------------------


def test_summary_counts_filters_by_origin_and_keeps_empty_time_buckets(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        for index in (0, 1, 2):
            client.post("/api/investigations", json={"claim": DEMO_CASES[index]["claim"]})
        client.post("/api/evaluations/run", json={"judge": False})
        everything = client.get("/api/observability/summary?window=24h").json()
        handlers = client.get("/api/observability/summary?window=24h&origin=user").json()
        suite = client.get("/api/observability/summary?window=7d&origin=evaluation").json()
        assert client.get("/api/observability/summary?window=bogus").status_code == 422
    assert handlers["queries"]["total"] == 3
    assert suite["queries"]["total"] == len(DEMO_CASES)
    assert everything["queries"]["total"] == 3 + len(DEMO_CASES)
    assert everything["queries"]["by_origin"] == {"user": 3, "evaluation": len(DEMO_CASES)}
    assert everything["queries"]["success_rate"] == 1.0
    stage_names = [s["stage"] for s in everything["stages"]]
    assert stage_names == [n for n in STAGES if n in stage_names]
    assert {"classify", "retrieve", "validate"} <= set(stage_names)
    assert everything["latency_ms"]["count"] == everything["queries"]["total"]
    assert everything["latency_ms"]["p95"] >= everything["latency_ms"]["p50"] >= 0
    assert everything["coverage"] == {
        "recorded": everything["queries"]["total"],
        "reconstructed": 0,
        "note": everything["coverage"]["note"],
    }
    assert len(everything["series"]) == 24
    assert sum(b["queries"] for b in everything["series"]) == everything["queries"]["total"]
    operations = {o["name"] for o in everything["operations"]}
    assert {"history.search", "models.predict", "priority.score"} <= operations
    api = everything["api"]
    assert api["requests"] >= 4 and api["server_errors"] == 0
    routes = {r["route"] for r in api["routes"]}
    assert "/api/investigations" in routes  # a route template, not a raw URL
    assert everything["quality"]["validation_pass_rate"] is not None


def test_summary_reports_failures_errors_and_judge_outcomes(settings, monkeypatch):
    app = create_app(settings)
    service = app.state.service
    original = service.agents.investigate
    calls = {"n": 0}

    def sometimes_fail(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return original(*args, **kwargs)

    monkeypatch.setattr(service.agents, "investigate", sometimes_fail)
    with TestClient(app) as client:
        for index in (0, 1, 2):
            client.post("/api/investigations", json={"claim": DEMO_CASES[index]["claim"]})
        summary = client.get("/api/observability/summary?window=24h").json()
    assert summary["queries"]["failed"] == 1
    assert summary["queries"]["success_rate"] == pytest.approx(2 / 3)
    error = summary["errors"][0]
    assert error["error_type"] == "RuntimeError" and error["span"] in ("investigate", "investigation")
    investigate = next(s for s in summary["stages"] if s["stage"] == "investigate")
    assert investigate["errors"] == 1 and investigate["count"] == 3
    assert summary["quality"]["judge"]["skipped"] == 2  # judge is off in this configuration


def test_the_request_log_is_bounded_and_stores_templates_not_identifiers(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        client.get(f"/api/investigations/{run['run_id']}")
        client.get("/api/investigations/does-not-exist")
    rows = reopened(app).requests_since()
    routes = {(r["method"], r["route"], r["status"]) for r in rows}
    assert ("GET", "/api/investigations/{run_id}", 200) in routes
    assert ("GET", "/api/investigations/{run_id}", 404) in routes
    assert run["run_id"] not in json.dumps(rows)


# ----- access rules --------------------------------------------------------------------------

ADMIN_PASSWORD = "Synthetic admin passphrase!"
USER_PASSWORD = "Synthetic user passphrase!"


def sign_in(client, username, password):
    csrf = client.get("/api/auth/session").json()["csrf_token"]
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}, headers={"X-CSRF-Token": csrf}
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_technical_traces_are_for_administrators_and_handlers_get_the_plain_explanation(tmp_path):
    settings = Settings(
        _env_file=None,
        claims_auth_enabled=True,
        claims_search_enabled=False,
        claims_database_path=tmp_path / "cases.sqlite",
        claims_data_path=tmp_path / "absent.json",
        claims_artifact_dir=tmp_path / "models",
    )
    app = create_app(settings)
    peer = ("127.0.0.1", 50000)
    with TestClient(app, client=peer) as admin, TestClient(app, client=peer) as alice:
        csrf = {"X-CSRF-Token": admin.get("/api/auth/session").json()["csrf_token"]}
        admin.post("/api/auth/setup", json={"username": "admin", "password": ADMIN_PASSWORD}, headers=csrf)
        admin_headers = sign_in(admin, "admin", ADMIN_PASSWORD)
        admin.post(
            "/api/admin/users",
            json={"username": "alice", "password": USER_PASSWORD, "role": "user"},
            headers=admin_headers,
        )
        alice_headers = sign_in(alice, "alice", USER_PASSWORD)
        mine = alice.post(
            "/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}, headers=alice_headers
        ).json()["run_id"]
        theirs = admin.post(
            "/api/investigations", json={"claim": DEMO_CASES[1]["claim"]}, headers=admin_headers
        ).json()["run_id"]

        # A handler can read the explanation of their own query, and only theirs.
        assert alice.get(f"/api/investigations/{mine}/explanation").status_code == 200
        assert alice.get(f"/api/investigations/{theirs}/explanation").status_code == 404
        # Everything technical is closed to them, including a single audit event by id.
        for path in (
            f"/api/investigations/{mine}/trace",
            f"/api/investigations/{mine}/audit",
            f"/api/investigations/{mine}/audit/1",
            "/api/traces",
            "/api/observability/summary",
        ):
            assert alice.get(path).status_code == 403, path
        # Administrators get all of it.
        assert admin.get(f"/api/investigations/{mine}/trace").json()["source"] == "recorded"
        assert admin.get(f"/api/investigations/{mine}/explanation").status_code == 200
        listing = admin.get("/api/traces").json()
        assert listing["total"] == 2
        item = next(i for i in listing["items"] if i["run_id"] == mine)
        assert item["duration_ms"] > 0 and item["trace_source"] == "recorded" and item["origin"] == "user"
        assert admin.get("/api/observability/summary?window=24h").json()["queries"]["total"] == 2
        assert admin.get(f"/api/investigations/{mine}/audit/999999").status_code == 404
        # Unauthenticated callers get nothing, and the request log still saw the rejections.
        anonymous = TestClient(app, client=peer)
        assert anonymous.get(f"/api/investigations/{mine}/explanation").status_code == 401
    statuses = {r["status"] for r in reopened(app).requests_since()}
    assert {200, 401, 403, 404} <= statuses
