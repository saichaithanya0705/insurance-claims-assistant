import pytest
from fastapi.testclient import TestClient

from claims.api import create_app
from claims.demo import DEMO_CASES
from claims.settings import Settings


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
