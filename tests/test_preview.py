"""A running investigation shows what has landed so far.

Each stage that produces something to read saves it, and `GET /api/investigations/{id}/preview` returns the few facts worth showing
early, already filtered for the viewer. The parts appear in the order the stages finish, never before, and the finished run replaces
them.
"""

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_query_agent import Agent

from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.settings import Settings
from claims.observability.preview import preview_of

RUN = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, claims_database_path=tmp_path / "runtime.sqlite", claims_data_path=Path("absent.json"),
        claims_artifact_dir=tmp_path / "models",
    )


FULL = {
    "run_id": RUN, "status": "awaiting_review", "claim": {"claim_type": "auto"}, "classification": {"claim_type": "auto"},
    "trace": [{"stage": s, "status": "complete", "detail": ""} for s in ("classify", "retrieve", "investigate", "risk", "recommend", "validate")],
    "evidence": [
        {"source_id": "chunk_a", "title": "Passage", "provenance": "synapt"},
        {"source_id": "graph:procedure:p1", "title": "Knowledge graph procedure: Police report request", "provenance": "synapt"},
        {"source_id": "claim:input", "title": "Submitted claim", "provenance": "user_input"},
    ],
    "similar_cases": [
        {"claim_type": "auto", "state": "TX", "claim_amount": 9000, "claim_status": "approved", "days_to_resolution": 12, "open_case": False},
        {"claim_type": "auto", "state": "TX", "claim_amount": 100, "claim_status": "pending", "open_case": True},
    ],
    "cohort": {"available": True, "cohorts": [{"key": "exact", "claims": 1913, "approved_share": 0.889, "median_days": 12.0, "sufficient": True}]},
    "query_agent": {"available": False, "pending": True, "question": "Q?", "part": None},
    "findings": [{"kind": "gap", "text": "No police report", "source_ids": ["graph:procedure:p1"]}],
    "priority": {"tier": "medium", "score": 25, "components": [{"points": 8, "reason": "Claimed amount is at least $10,000"}]},
    "recommendations": [{"action": "Request focused clarification or evidence", "reason": "Ask for the police report", "source_ids": ["claim:input"]}],
}


def test_each_part_appears_only_once_its_stage_has_finished():
    early = copy.deepcopy(FULL)
    early["status"] = "running"
    early["trace"] = early["trace"][:2]  # classify and retrieve
    out = preview_of(early)
    assert out["stages"] == ["classify", "retrieve"] and out["findings"] is None and out["priority"] is None and out["recommendations"] is None
    assert out["retrieval"]["passages"] == 1 and out["retrieval"]["procedures"] == ["Police report request"]
    assert out["retrieval"]["similar_total"] == 1 and out["retrieval"]["similar_cases"][0]["claim_status"] == "approved"  # the open case is left out
    assert out["retrieval"]["cohort"] == "1,913 past claims with the same description, 88.9% approved, median 12 days to settle"
    assert out["retrieval"]["query_agent"] == {"state": "pending", "question": "Q?"}
    mid = copy.deepcopy(early) | {"trace": FULL["trace"][:3]}
    assert preview_of(mid)["findings"] == [{"kind": "gap", "text": "No police report"}] and preview_of(mid)["priority"] is None
    assert preview_of(FULL)["priority"] == {"tier": "medium", "score": 25, "reasons": ["Claimed amount is at least $10,000"]}
    assert preview_of(FULL)["recommendations"] == [{"action": "Request focused clarification or evidence", "reason": "Ask for the police report"}]


def test_nothing_has_landed_before_retrieval_and_a_missing_cohort_or_answer_is_simply_absent():
    start = {"run_id": RUN, "status": "running", "claim": {"claim_type": None}, "trace": []}
    out = preview_of(start)
    assert out["stages"] == [] and out["retrieval"] is None and out["findings"] is None and out["claim_type"] is None
    bare = {"run_id": RUN, "status": "running", "trace": [{"stage": "retrieve"}], "evidence": [], "cohort": {"available": False, "reason": "no dataset"}}
    assert preview_of(bare)["retrieval"]["cohort"] == "no dataset" and preview_of(bare)["retrieval"]["query_agent"] is None


def test_the_answer_when_it_has_arrived_is_short_and_a_failed_one_says_so():
    answered = copy.deepcopy(FULL) | {"query_agent": {"available": True, "question": "Q?", "part": {"text": "x" * 900}}}
    state = preview_of(answered)["retrieval"]["query_agent"]
    assert state["state"] == "answered" and len(state["answer"]) == 600
    failed = copy.deepcopy(FULL) | {"query_agent": {"available": False, "question": None, "part": None, "reason": "no"}}
    assert preview_of(failed)["retrieval"]["query_agent"]["state"] == "unavailable"


def test_a_stage_saves_what_it_produced_while_the_rest_is_running_and_the_endpoint_serves_it(settings):
    """The investigate stage reads the preview itself, before it returns: retrieval must already be there and the findings not."""
    seen = {}
    app = create_app(settings, adapter=Agent())
    service = app.state.service
    original = service.agents.investigate

    def reading(claim, evidence, similar, run_id):
        seen["at_investigate"] = TestClient(app).get(f"/api/investigations/{RUN}/preview").json()
        return original(claim, evidence, similar, run_id)

    service.agents.investigate = reading
    with TestClient(app) as client:
        client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"], "run_id": RUN})
        final = client.get(f"/api/investigations/{RUN}/preview").json()
    mid = seen["at_investigate"]
    assert mid["status"] == "running" and mid["stages"] == ["classify", "retrieve"]
    assert mid["retrieval"] is not None and mid["retrieval"]["similar_total"] >= 1 and mid["findings"] is None and mid["recommendations"] is None
    assert final["status"] == "awaiting_review" and final["findings"] and final["priority"] and final["recommendations"]


def test_a_person_gets_the_plain_version_and_only_the_owner_or_an_administrator_may_look(tmp_path):
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
        for name in ("alice", "bob"):
            client.post("/api/admin/users", json={"username": name, "password": "Synthetic user passphrase!", "role": "user"}, headers=admin)
        client.post("/api/auth/logout", headers=admin)
        alice = sign_in(client, "alice", "Synthetic user passphrase!")
        client.post("/api/investigations", json={"claim": DEMO_CASES[0]["claim"], "run_id": RUN}, headers=alice)
        mine = client.get(f"/api/investigations/{RUN}/preview")
        assert mine.status_code == 200 and "synapt" not in json.dumps(mine.json()).lower()
        client.post("/api/auth/logout", headers=alice)
        sign_in(client, "bob", "Synthetic user passphrase!")
        assert client.get(f"/api/investigations/{RUN}/preview").status_code in (403, 404)
