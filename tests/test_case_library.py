from pathlib import Path

from fastapi.testclient import TestClient

from claims.api.main import create_app
from claims.core.settings import Settings
from claims.investigation.workflow import validate_brief
from claims.storage.run_store import Store


def save(store, run_id, description, status="awaiting_review", amount=8500, filed="2026-09-10"):
    store.save(
        run_id,
        {
            "run_id": run_id,
            "status": status,
            "claim": {
                "description": description,
                "claim_type": "auto",
                "state": "TX",
                "claim_amount": amount,
                "claim_filed_date": filed,
            },
        },
    )


def test_saved_search_is_literal_filtered_paginated_and_persistent(tmp_path):
    path = tmp_path / "cases.sqlite"
    store = Store(path)
    save(store, "one", "Rear-ended at an intersection in Texas")
    save(store, "two", "Rear-ended, repair cost 100% documented", "reviewed", 9000)
    save(store, "three", "Rear-ended while stationary", filed="2026-08-10")
    assert store.search(q="rear-ended")["total"] == 3
    assert store.search(q="Texas auto")["total"] == 3
    assert store.search(q="New York auto")["total"] == 0
    assert store.search(q="ONE")["items"][0]["run_id"] == "one"
    assert store.search(q="auto tx")["total"] == 3
    assert store.search(q="%")["total"] == 1
    assert store.search(q="' OR 1=1 --")["total"] == 0
    result = store.search(
        q="rear-ended",
        status="awaiting_review",
        state="tx",
        claim_type="auto",
        date_from="2026-09-01",
        date_to="2026-09-30",
        min_amount=8000,
        max_amount=8800,
    )
    assert [c["run_id"] for c in result["items"]] == ["one"]
    assert store.search(limit=1)["items"][0]["run_id"] == "three"
    assert store.search(limit=1, offset=1)["items"][0]["run_id"] == "two"
    store.close()
    reopened = Store(path)
    assert reopened.search()["total"] == 3
    reopened.close()


def test_saved_case_route_validation_auth_and_legacy_records(tmp_path):
    settings = Settings(
        _env_file=None,
        claims_database_path=tmp_path / "cases.sqlite",
        claims_data_path=Path("absent.json"),
        claims_artifact_dir=tmp_path / "models",
        claims_api_key="test-library-key",
    )
    app = create_app(settings)
    save(app.state.service.store, "existing", "Rear-ended in Texas")
    with TestClient(app) as client:
        assert client.get("/api/investigations").status_code == 401
        headers = {"X-Claims-Api-Key": "test-library-key"}
        page = client.get("/api/investigations", params={"q": "rear-ended"}, headers=headers)
        assert page.status_code == 200
        assert page.json()["items"][0]["run_id"] == "existing"
        for params in [
            {"limit": 101},
            {"offset": -1},
            {"date_from": "invalid"},
            {"date_from": "2026-10-01", "date_to": "2026-09-01"},
            {"min_amount": 9000, "max_amount": 100},
            {"min_amount": -1},
        ]:
            assert (
                client.get("/api/investigations", params=params, headers=headers).status_code == 422
            )


def test_document_names_cannot_be_validated_as_received_content():
    state = {
        "evidence": [{"source_id": "claim:input"}, {"source_id": "procedure:1"}],
        "findings": [
            {
                "kind": "fact",
                "text": "The claimant provided an incident statement and repair estimate as supporting documents.",
                "source_ids": ["claim:input"],
            }
        ],
        "recommendations": [],
        "classification": {"needs_review": False},
    }
    assert not validate_brief(state)["passed"]
    assert any("reported availability" in issue for issue in validate_brief(state)["issues"])
    state["findings"][0]["text"] = (
        "The claimant reports the incident statement is available; names only."
    )
    assert validate_brief(state)["passed"]
