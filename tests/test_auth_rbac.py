import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from claims.api import create_app
from claims.demo import DEMO_CASES
from claims.settings import Settings

ADMIN_PASSWORD = "Synthetic admin passphrase!"
USER_PASSWORD = "Synthetic user passphrase!"


def login(client, username, password):
    csrf = client.get("/api/auth/session").json()["csrf_token"]
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_accounts_sessions_csrf_ownership_and_admin_boundaries(tmp_path):
    settings = Settings(
        _env_file=None,
        claims_auth_enabled=True,
        claims_search_enabled=False,
        claims_database_path=tmp_path / "cases.sqlite",
        claims_data_path=Path("absent.json"),
        claims_artifact_dir=tmp_path / "models",
        claims_api_key="cannot-bypass-login",
    )
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.get("/api/investigations").status_code == 401
        assert (
            client.get(
                "/api/investigations", headers={"X-Claims-Api-Key": "cannot-bypass-login"}
            ).status_code
            == 401
        )
        session = client.get("/api/auth/session").json()
        assert session["setup_required"]
        setup = {"username": "admin", "password": ADMIN_PASSWORD, "role": "user"}
        assert client.post("/api/auth/setup", json=setup).status_code == 403
        csrf = {"X-CSRF-Token": session["csrf_token"]}
        assert (
            client.post(
                "/api/auth/setup", json=setup, headers=csrf | {"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/auth/setup", json=setup | {"password": "short"}, headers=csrf
            ).status_code
            == 422
        )
        initial = client.post("/api/auth/setup", json=setup, headers=csrf)
        assert initial.status_code == 200
        assert initial.json()["user"]["role"] == "admin"
        assert client.post("/api/auth/setup", json=setup, headers=csrf).status_code == 409
        assert (
            client.post(
                "/api/auth/login", json={"username": "admin", "password": "incorrect"}, headers=csrf
            ).status_code
            == 401
        )
        admin_headers = login(client, "ADMIN", ADMIN_PASSWORD)
        assert "HttpOnly" in str(client.cookies) or client.cookies.get("claims_session")
        assert (
            client.post(
                "/api/admin/users",
                json={"username": "alice", "password": USER_PASSWORD, "role": "user"},
            ).status_code
            == 403
        )
        created = client.post(
            "/api/admin/users",
            json={"username": "alice", "password": USER_PASSWORD, "role": "user"},
            headers=admin_headers,
        )
        assert created.status_code == 200
        alice_id = created.json()["id"]
        assert (
            client.post(
                "/api/admin/users",
                json={"username": "alice", "password": USER_PASSWORD, "role": "admin"},
                headers=admin_headers,
            ).status_code
            == 409
        )
        app.state.service.store.save(
            "private-case",
            {
                "run_id": "private-case",
                "claim": {
                    "description": "Hidden admin car incident",
                    "claim_type": "auto",
                    "state": "TX",
                    "claim_amount": 123,
                },
                "trace": [],
            },
        )
        assert client.get("/api/case-suggestions?q=private").json()["total"] == 1
        assert client.post("/api/auth/logout", headers=admin_headers).status_code == 200
        assert client.get("/api/admin/users").status_code == 401
        headers = login(client, "alice", USER_PASSWORD)
        for path in [
            "/api/admin/users",
            "/api/integration/status",
            "/api/models/status",
            "/api/evaluations/status",
            "/api/feedback/lessons",
        ]:
            assert client.get(path).status_code == 403
        for path in [
            "/api/admin/users",
            "/api/models/train",
            "/api/evaluations/run",
            "/api/search",
        ]:
            assert client.post(path, json={}, headers=headers).status_code == 403
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/investigations/private-case").status_code == 404
        assert (
            client.post(
                "/api/investigations/private-case/feedback",
                json={"rating": 4, "note": "Cannot access"},
                headers=headers,
            ).status_code
            == 404
        )
        assert client.get("/api/investigations").json()["total"] == 0
        assert client.get("/api/case-suggestions?q=private").json()["items"] == []
        run = client.post(
            "/api/investigations", json={"claim": DEMO_CASES[0]["claim"]}, headers=headers
        )
        assert run.status_code == 200, run.text
        run_id = run.json()["run_id"]
        assert app.state.service.store.can_access(run_id, alice_id)
        assert "agent_mode" not in run.json() and "mode" not in run.json()
        assert all(not stage["detail"] for stage in run.json()["trace"])
        assert "method" not in run.json().get("classification", {})
        assert client.get("/api/investigations").json()["total"] == 1
        assert client.get("/api/case-suggestions").json()["total"] == 1
        assert client.get(f"/api/investigations/{run_id}/audit").status_code == 403
        assert (
            client.post(
                f"/api/investigations/{run_id}/review",
                json={"decision": "request_revision", "note": "Review"},
                headers=headers,
            ).status_code
            == 403
        )
        assert client.post("/api/auth/logout", headers=headers).status_code == 200
        admin_headers = login(client, "admin", ADMIN_PASSWORD)
        assert client.get(f"/api/investigations/{run_id}").json()["agent_mode"] == "fixture"
        assert client.get("/api/investigations").json()["total"] == 2
        audit = client.get(f"/api/investigations/{run_id}/audit").json()
        assert any(
            event["kind"] == "submitted_by" and event["body"]["id"] == alice_id
            for event in audit["items"]
        )
        reviewed = client.post(
            f"/api/investigations/{run_id}/review",
            json={"decision": "request_revision", "note": "Synthetic RBAC test revision"},
            headers=admin_headers,
        )
        assert reviewed.status_code == 200
        assert app.state.service.store.can_access(run_id, alice_id)
        assert any(
            user["username"] == "alice" for user in client.get("/api/admin/users").json()["users"]
        )
        app.state.auth.connection.execute(
            "UPDATE sessions SET expires_at=?", (int(time.time()) - 1,)
        )
        app.state.auth.connection.commit()
        assert client.get("/api/investigations").status_code == 401
    db = sqlite3.connect(tmp_path / "auth.sqlite")
    hashes = [row[0] for row in db.execute("SELECT password_hash FROM users")]
    assert all(
        value.startswith("scrypt$") and USER_PASSWORD not in value and ADMIN_PASSWORD not in value
        for value in hashes
    )
    db.close()
    reopened = create_app(settings)
    with TestClient(reopened, client=("127.0.0.1", 50000)) as client:
        assert not client.get("/api/auth/session").json()["setup_required"]
        login(client, "alice", USER_PASSWORD)
        assert client.get("/api/investigations").json()["total"] == 1


def test_setup_loopback_limit_and_failed_login_throttle(tmp_path):
    app = create_app(
        Settings(
            _env_file=None,
            claims_auth_enabled=True,
            claims_database_path=tmp_path / "cases.sqlite",
            claims_data_path=Path("absent.json"),
        )
    )
    app.state.auth.create_user("admin", ADMIN_PASSWORD, "admin", first=True)
    with TestClient(app, client=("192.0.2.1", 50000)) as client:
        csrf = {"X-CSRF-Token": client.get("/api/auth/session").json()["csrf_token"]}
        assert (
            client.post(
                "/api/auth/setup",
                json={"username": "other", "password": ADMIN_PASSWORD},
                headers=csrf,
            ).status_code
            == 403
        )
        for _ in range(10):
            assert (
                client.post(
                    "/api/auth/login", json={"username": "admin", "password": "wrong"}, headers=csrf
                ).status_code
                == 401
            )
        assert (
            client.post(
                "/api/auth/login",
                json={"username": "admin", "password": ADMIN_PASSWORD},
                headers=csrf,
            ).status_code
            == 429
        )
