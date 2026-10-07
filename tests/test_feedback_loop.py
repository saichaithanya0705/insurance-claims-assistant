"""Reviewed feedback -> admin promotion -> cited evidence in later investigations."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claims.adapters import FixtureSynaptAdapter, SynaptError
from claims.api import create_app
from claims.demo import DEMO_CASES
from claims.settings import Settings

AUTO = DEMO_CASES[0]["claim"]
HOME = DEMO_CASES[2]["claim"]


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        claims_database_path=tmp_path / "runtime.sqlite",
        claims_data_path=tmp_path / "absent.json",
        claims_artifact_dir=tmp_path / "models",
    )


def reviewed_feedback(client, claim=AUTO, rating=4, note="Ask for the police report early"):
    run = client.post("/api/investigations", json={"claim": claim}).json()
    review = {"decision": "accept_brief", "note": "Sources and limits checked"}
    assert client.post(f"/api/investigations/{run['run_id']}/review", json=review).status_code == 200
    client.post(f"/api/investigations/{run['run_id']}/feedback", json={"rating": rating, "note": note})
    lessons = client.get("/api/feedback/lessons").json()["candidate_lessons"]
    return run, lessons[0]


def test_candidates_start_unpromoted_with_claim_context(settings):
    with TestClient(create_app(settings)) as client:
        _, lesson = reviewed_feedback(client)
        assert lesson["promoted"] is False and lesson["promotion_ref"] is None
        assert lesson["claim_type"] == "auto" and lesson["state"] == "TX"


def test_promoted_lesson_is_cited_evidence_for_the_same_claim_type_only(settings):
    with TestClient(create_app(settings)) as client:
        _, lesson = reviewed_feedback(client)
        promoted = client.post(f"/api/feedback/lessons/{lesson['id']}/promote")
        assert promoted.status_code == 200
        assert promoted.json() == {"id": lesson["id"], "promoted": True, "reference": "local"}

        same = client.post("/api/investigations", json={"claim": AUTO}).json()
        cited = [e for e in same["evidence"] if e["provenance"] == "handler_lesson"]
        assert [e["source_id"] for e in cited] == [f"lesson:{lesson['id']}"]
        assert "police report" in cited[0]["text"] and "Advisory context only" in cited[0]["text"]
        assert AUTO["description"] not in cited[0]["text"]  # no claim text is reused
        assert same["validation"]["passed"]
        assert "1 reviewed handler lesson(s) applied" in same["trace"][1]["detail"]

        other = client.post("/api/investigations", json={"claim": HOME}).json()
        assert not [e for e in other["evidence"] if e["provenance"] == "handler_lesson"]
        assert client.get("/api/feedback/lessons").json()["candidate_lessons"][0]["promoted"]


def test_promotion_is_explicit_one_shot_and_needs_an_accepted_brief(settings):
    with TestClient(create_app(settings)) as client:
        _, lesson = reviewed_feedback(client)
        assert client.post(f"/api/feedback/lessons/{lesson['id']}/promote").status_code == 200
        assert client.post(f"/api/feedback/lessons/{lesson['id']}/promote").status_code == 409
        assert client.post("/api/feedback/lessons/999/promote").status_code == 404
        # Feedback on a brief that was never accepted is stored but cannot be promoted.
        unaccepted = client.post("/api/investigations", json={"claim": AUTO}).json()
        feedback = client.post(
            f"/api/investigations/{unaccepted['run_id']}/feedback",
            json={"rating": 5, "note": "Great but unreviewed"},
        ).json()
        assert feedback["reviewed"] is False
        refused = client.post(f"/api/feedback/lessons/{feedback['id']}/promote")
        assert refused.status_code == 409 and "accepted" in refused.json()["detail"]


def test_nothing_is_promoted_automatically(settings):
    with TestClient(create_app(settings)) as client:
        reviewed_feedback(client)
        run = client.post("/api/investigations", json={"claim": AUTO}).json()
        assert not [e for e in run["evidence"] if e["provenance"] == "handler_lesson"]


class IngestingAdapter(FixtureSynaptAdapter):
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def ingest(self, content, filename, document_type="text", *, chunking=None):
        if self.fail:
            raise SynaptError("provider down")
        self.calls.append((content, filename))
        return {"status": "submitted", "req_id": "req-77"}


def live_service(settings, adapter):
    app = create_app(settings.model_copy(update={"synapt_mode": "live"}), adapter=adapter)
    return TestClient(app)


def test_live_promotion_ingests_once_into_synapt_without_claim_text(settings):
    adapter = IngestingAdapter()
    with live_service(settings, adapter) as client:
        _, lesson = reviewed_feedback(client)
        result = client.post(f"/api/feedback/lessons/{lesson['id']}/promote").json()
        assert result["reference"] == "req-77"
        (content, filename), = adapter.calls
        assert filename == f"handler-lesson-{lesson['id']}.txt"
        assert "handler_lesson_ref: LESSON-" in content and "claim_type: auto" in content
        assert "police report" in content and AUTO["description"] not in content
        assert "CLM-" not in content


def test_failed_live_ingestion_leaves_the_lesson_unpromoted(settings):
    with live_service(settings, IngestingAdapter(fail=True)) as client:
        _, lesson = reviewed_feedback(client)
        refused = client.post(f"/api/feedback/lessons/{lesson['id']}/promote")
        assert refused.status_code == 502 and "provider down" not in refused.text
        assert client.get("/api/feedback/lessons").json()["candidate_lessons"][0]["promoted"] is False


def test_only_administrators_can_promote(tmp_path):
    from test_auth_rbac import ADMIN_PASSWORD, USER_PASSWORD, login

    settings = Settings(
        _env_file=None,
        claims_auth_enabled=True,
        claims_search_enabled=False,
        claims_database_path=tmp_path / "cases.sqlite",
        claims_data_path=Path("absent.json"),
        claims_artifact_dir=tmp_path / "models",
    )
    with TestClient(create_app(settings), client=("127.0.0.1", 50000)) as client:
        csrf = {"X-CSRF-Token": client.get("/api/auth/session").json()["csrf_token"]}
        client.post("/api/auth/setup", json={"username": "admin", "password": ADMIN_PASSWORD}, headers=csrf)
        admin = login(client, "admin", ADMIN_PASSWORD)
        client.post(
            "/api/admin/users",
            json={"username": "pat", "password": USER_PASSWORD, "role": "user"},
            headers=admin,
        )
        client.post("/api/auth/logout", headers=admin)
        user = login(client, "pat", USER_PASSWORD)
        assert client.post("/api/feedback/lessons/1/promote", headers=user).status_code == 403
        assert client.get("/api/feedback/lessons", headers=user).status_code == 403
