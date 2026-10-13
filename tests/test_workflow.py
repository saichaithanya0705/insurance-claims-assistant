import pytest
from fastapi.testclient import TestClient

from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.settings import Settings


@pytest.mark.parametrize("text", [
    "The claimant submitted a repair estimate.",
    "A repair estimate was provided and reviewed.",
    "The police report was received.",
    "Received the incident statement.",
    "No contradictions were reported; a repair estimate was received.",
    "The claimant reports damage, but photographs were reviewed.",
    "The police report was not received, but the repair estimate was verified.",
    "The repair estimate was received with the police report not provided.",
])
def test_document_receipt_guard_handles_both_orders_and_unrelated_qualifiers(text):
    from claims.investigation.workflow import asserts_document_receipt

    assert asserts_document_receipt(text) is True


@pytest.mark.parametrize("text", [
    "The claimant reports a repair estimate is available.",
    "The repair estimate was not provided.",
    "No police report was received.",
    "Received no documents.",
    "The documents have not been reviewed.",
    "The claimant reports that photographs were provided.",
    "Document receipt is unverified.",
])
def test_document_receipt_guard_keeps_local_reported_and_negated_statements(text):
    from claims.investigation.workflow import asserts_document_receipt

    assert asserts_document_receipt(text) is False


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        claims_database_path=tmp_path / "runtime.sqlite",
        claims_data_path=tmp_path / "absent.json",
        claims_artifact_dir=tmp_path / "models",
    )


def test_complete_spine_review_feedback_and_replay_guard(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]})
        assert response.status_code == 200
        run = response.json()
        assert run["status"] == "awaiting_review"
        assert run["validation"]["passed"]
        assert run["predictions"]["available"] is False
        assert run["agent_mode"] == "fixture"
        decision = {"decision": "accept_brief", "note": "Verified sources and limits"}
        assert (
            client.post(f"/api/investigations/{run['run_id']}/review", json=decision).json()[
                "status"
            ]
            == "reviewed"
        )
        assert (
            client.post(f"/api/investigations/{run['run_id']}/review", json=decision).status_code
            == 409
        )
        feedback = client.post(
            f"/api/investigations/{run['run_id']}/feedback",
            json={"rating": 4, "note": "Useful qualified comparison"},
        ).json()
        assert feedback["reviewed"] and not feedback["published_to_synapt"]
        assert len(client.get("/api/feedback/lessons").json()["candidate_lessons"]) == 1


def test_persistent_interrupt_survives_restart(settings):
    with TestClient(create_app(settings)) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
    with TestClient(create_app(settings)) as client:
        result = client.post(
            f"/api/investigations/{run['run_id']}/review",
            json={"decision": "request_revision", "note": "Need policy evidence"},
        )
        assert result.status_code == 200
        assert result.json()["status"] == "revision_requested"


def test_supported_contradiction_elevates_investigation_priority(settings):
    with TestClient(create_app(settings)) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[2]["claim"]}).json()
        assert run["priority"]["service_urgency"] == "urgent"
        assert run["priority"]["investigation_priority"] == "elevated"
        assert any("Conflicting evidence" in reason for reason in run["priority"]["reasons"])


def test_ambiguous_claim_cannot_accept(settings):
    with TestClient(create_app(settings)) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[3]["claim"]}).json()
        assert run["status"] == "needs_manual_review"
        assert (
            client.post(
                f"/api/investigations/{run['run_id']}/review",
                json={"decision": "accept_brief", "note": "Looks okay"},
            ).status_code
            == 409
        )


def test_provider_failure_has_no_fake_success(settings):
    class Broken:
        def retrieve(self, claim):
            raise RuntimeError("password=DO-NOT-PRINT")

    with TestClient(create_app(settings, adapter=Broken())) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
        assert run["status"] == "failed"
        assert "DO-NOT-PRINT" not in str(run)


def test_input_validation_and_api_access(settings):
    with TestClient(create_app(settings)) as client:
        bad = DEMO_CASES[0]["claim"] | {"claim_amount": -1}
        assert client.post("/api/investigations", json={"claim": bad}).status_code == 422
        assert (
            client.post(
                "/api/investigations",
                json={
                    "claim": DEMO_CASES[0]["claim"],
                    "filters": {"min_amount": 100, "max_amount": 1},
                },
            ).status_code
            == 422
        )
    protected = settings.model_copy(
        update={"claims_api_key": __import__("pydantic").SecretStr("private-test")}
    )
    with TestClient(create_app(protected)) as client:
        assert client.get("/api/health").status_code == 401
        assert (
            client.get("/api/health", headers={"X-Claims-Api-Key": "private-test"}).status_code
            == 200
        )


def test_eval_does_not_claim_judge_pass(settings):
    with TestClient(create_app(settings)) as client:
        report = client.post("/api/evaluations/run", json={"judge": True}).json()
        assert report["passed"] == report["total"] == 4, report
        assert report["judge_status"].startswith("unavailable")


def test_repeated_checkpoints_and_audit_writes_use_independent_transactions(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        assert app.state.service.store.connection is not app.state.service.checkpoint_connection
        for _ in range(20):
            run = client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}).json()
            assert run["status"] == "awaiting_review", run
            result = client.post(
                f"/api/investigations/{run['run_id']}/review",
                json={"decision": "accept_brief", "note": "Checked source evidence"},
            )
            assert result.json()["status"] == "reviewed"


def test_search_is_retrieval_only_and_history_sources_resolve(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        result = client.post("/api/search", json={"claim": DEMO_CASES[0]["claim"]}).json()
        assert result["similar_cases"] and "run_id" not in result
        assert result["semantic_case_matches"] == 0
        ids = {e["source_id"] for e in result["evidence"]}
        assert all("history:" + case["claim_id"] in ids for case in result["similar_cases"])
        assert (
            app.state.service.store.connection.execute(
                "SELECT COUNT(*) FROM investigations"
            ).fetchone()[0]
            == 0
        )


INVALID_CLAIMS = {
    "incident and filing dates in the future": {"claim_filed_date": "2030-01-01", "incident_date": "2030-01-01"},
    "filed before the incident": {"incident_date": "2026-09-10", "claim_filed_date": "2026-09-01"},
    "negative amount": {"claim_amount": -5},
    "state is not a two-letter code": {"state": "Texas"},
    "description too short": {"description": "hi"},
    "unknown claim type": {"claim_type": "boat"},
    "unexpected extra field": {"is_fraud": True},
}


@pytest.mark.parametrize("change", INVALID_CLAIMS.values(), ids=INVALID_CLAIMS.keys())
def test_every_invalid_input_is_refused_before_any_work_happens(settings, change):
    app = create_app(settings)
    with TestClient(app) as client:
        response = client.post(
            "/api/investigations", json={"claim": DEMO_CASES[0]["claim"] | change, "filters": {}}
        )
        assert response.status_code == 422
        count = app.state.service.store.connection.execute("SELECT COUNT(*) FROM investigations")
        assert count.fetchone()[0] == 0


@pytest.mark.parametrize("status", ["approved", "denied", "pending", "under_review"])
def test_all_four_dataset_statuses_are_accepted_as_filters(settings, status):
    with TestClient(create_app(settings)) as client:
        body = {"claim": DEMO_CASES[0]["claim"], "filters": {"claim_status": status}}
        assert client.post("/api/search", json=body).status_code == 200
    with TestClient(create_app(settings)) as client:
        body = {"claim": DEMO_CASES[0]["claim"], "filters": {"claim_status": "settled"}}
        assert client.post("/api/search", json=body).status_code == 422


def test_queue_orders_open_investigations_by_audited_priority_and_filters_by_tier(settings):
    with TestClient(create_app(settings)) as client:
        ids = {
            case["id"]: client.post("/api/investigations", json={"claim": case["claim"]}).json()
            for case in DEMO_CASES
        }
        scores = {name: run["priority"]["score"] for name, run in ids.items()}
        # Every point is attributed and the tier follows the documented floors.
        for run in ids.values():
            assert sum(c["points"] for c in run["priority"]["components"]) >= run["priority"]["score"]
        queue = client.get("/api/queue").json()
        assert {item["run_id"] for item in queue["items"]} == {r["run_id"] for r in ids.values()}
        assert [item["priority_score"] for item in queue["items"]] == sorted(scores.values(), reverse=True)
        top = queue["items"][0]["priority_tier"]
        only = client.get(f"/api/queue?tier={top}").json()
        assert only["items"] and all(item["priority_tier"] == top for item in only["items"])
        # A reviewed investigation leaves the queue but stays searchable.
        done = ids["auto-ready"]["run_id"]
        client.post(f"/api/investigations/{done}/review", json={"decision": "accept_brief", "note": "Checked"})
        assert done not in {item["run_id"] for item in client.get("/api/queue").json()["items"]}
        by_priority = client.get("/api/investigations?sort=priority").json()["items"]
        assert [i["priority_score"] for i in by_priority] == sorted(
            [i["priority_score"] for i in by_priority], reverse=True
        )
        assert client.get("/api/queue?tier=bogus").status_code == 422
