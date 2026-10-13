import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from claims.api.main import create_app
from claims.core.settings import Settings
from claims.investigation.intake_extract import IntakeExtractor, IntakeReading, clean_reading
from claims.llm.client import CompletionError

NOTES = (
    "Rear-ended at a red light in Austin, Texas on 2026-03-03. Repair estimate came to "
    "$12,400 with a $500 deductible. Customer for 6 years, 1 prior claim. "
    "She sent photos but no police report yet."
)
TODAY = date(2026, 10, 10)
ADMIN_PASSWORD = "Synthetic admin passphrase!"
USER_PASSWORD = "Synthetic user passphrase!"


def live_settings(**changes):
    return Settings(
        _env_file=None, agent_mode="live", nvidia_api_key="fake-nvidia-secret", **changes
    )


def reading(**fields):
    return IntakeReading.model_validate(fields)


def found(value, quote):
    return {"value": value, "quote": quote}


def mock_model(monkeypatch, payload, status=200):
    """Answer the chat-completions call with ``payload`` as the model's JSON content."""
    original, requests = httpx.Client, []

    def respond(request):
        requests.append(json.loads(request.content))
        body = {"choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}]}
        return httpx.Response(status, json=body if status == 200 else {"error": "x"})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs))
    monkeypatch.setattr("claims.llm.client.time.sleep", lambda seconds: None)
    return requests


def test_values_without_a_verbatim_quote_are_dropped():
    result = clean_reading(
        reading(
            state=found("TX", "Austin, Texas"),
            claim_amount=found(12400, "$12,400"),
            deductible=found(500, "a $750 deductible"),  # not in the notes
            previous_claims_count=found(1, ""),  # no quote at all
            claim_type=found("auto", "rear-ended at a RED   light"),  # case and spacing differ
        ),
        NOTES,
        TODAY,
    )
    assert set(result) == {"state", "claim_amount", "claim_type"}
    assert result["state"] == {"value": "TX", "quote": "Austin, Texas"}
    assert result["claim_type"]["value"] == "auto"


def test_values_outside_the_intake_rules_are_dropped():
    notes = "Claim of $5 on 2026-03-03, then 2099-01-01 and 2026-02-01 and 3000 earlier claims."
    result = clean_reading(
        reading(
            state=found("ZZ", "Claim"),
            claim_type=found("boat", "Claim"),
            claim_amount=found(-5, "$5"),
            deductible=found(2e9, "$5"),
            incident_date=found("2026-03-03", "2026-03-03"),
            claim_filed_date=found("2026-02-01", "2026-02-01"),  # before the incident
            previous_claims_count=found(3000, "3000 earlier claims"),
            policyholder_tenure_years=found(150, "Claim"),
            provided_documents=found("photos", "Claim"),  # not a list
            theft=found("yes", "Claim"),  # not a boolean
        ),
        notes,
        TODAY,
    )
    assert set(result) == {"incident_date"}
    future = clean_reading(reading(incident_date=found("2099-01-01", "2099-01-01")), notes, TODAY)
    assert future == {}
    fractional = clean_reading(
        reading(previous_claims_count=found(1.5, "earlier claims")), notes, TODAY
    )
    assert fractional == {}


def test_state_names_dates_documents_and_flags_are_normalised():
    result = clean_reading(
        reading(
            state=found("texas", "Austin, Texas"),
            incident_date=found("2026-03-03", "2026-03-03"),
            policyholder_tenure_years=found("6", "6 years"),
            provided_documents=found(["Photos", "photos", " Police Report "], "She sent photos"),
            missing_documents=found(["police report"], "no police report"),
            theft=found(True, "Rear-ended"),
        ),
        NOTES,
        TODAY,
    )
    assert result["state"]["value"] == "TX"
    assert result["policyholder_tenure_years"]["value"] == 6.0
    assert result["provided_documents"]["value"] == ["photos", "police report"]
    assert result["missing_documents"]["value"] == ["police report"]
    assert result["theft"]["value"] is True


def test_live_model_reply_is_filtered_before_it_is_returned(monkeypatch):
    requests = mock_model(
        monkeypatch,
        {
            "state": found("TX", "Austin, Texas"),
            "claim_amount": found(12400, "$12,400"),
            "deductible": found(500, "an invented $500 quote"),
            "extra_field": found("ignored", "Austin"),
        },
    )
    result = IntakeExtractor(live_settings()).extract(NOTES, TODAY)
    assert result["model"] == "nvidia/nemotron-3-super-120b-a12b"
    assert set(result["fields"]) == {"state", "claim_amount"}
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert "fake-nvidia-secret" not in json.dumps(requests)


def test_personal_identifiers_are_masked_before_the_model_sees_the_notes(monkeypatch):
    requests = mock_model(monkeypatch, {})
    IntakeExtractor(live_settings()).extract(NOTES + " SSN 123-45-6789, jane@example.com", TODAY)
    prompt = json.dumps(requests[0]["messages"])
    assert "123-45-6789" not in prompt and "jane@example.com" not in prompt


def test_model_failure_is_reported_as_unavailable(monkeypatch):
    mock_model(monkeypatch, {}, status=401)
    from claims.investigation.intake_extract import IntakeUnavailable

    with pytest.raises(IntakeUnavailable):
        IntakeExtractor(live_settings()).extract(NOTES, TODAY)


def app_for(tmp_path, **changes):
    return create_app(
        Settings(
            _env_file=None,
            claims_search_enabled=False,
            claims_database_path=tmp_path / "cases.sqlite",
            claims_data_path=Path("absent.json"),
            claims_artifact_dir=tmp_path / "models",
            **changes,
        )
    )


def test_fixture_mode_is_deterministic_and_quotes_the_notes(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        first = client.post("/api/intake/extract", json={"description": NOTES})
        second = client.post("/api/intake/extract", json={"description": NOTES})
    assert first.status_code == 200 and first.json() == second.json()
    body = first.json()
    assert body["model"] == "fixture-extractor"
    assert body["fields"]["state"] == {"value": "TX", "quote": "Texas"}
    assert body["fields"]["claim_amount"]["value"] == 12400
    assert all(item["quote"] in NOTES for item in body["fields"].values())


def test_request_is_validated(tmp_path):
    with TestClient(app_for(tmp_path)) as client:
        for payload in ({"description": "short"}, {"description": "x" * 6001}, {"description": "12345 67890"}, {}):
            assert client.post("/api/intake/extract", json=payload).status_code == 422
        assert client.post("/api/intake/extract", json={"description": NOTES, "x": 1}).status_code == 422


def test_model_failure_returns_a_safe_503_not_a_500(tmp_path, monkeypatch):
    def fail(self, *args, **kwargs):
        raise CompletionError("secret provider detail fake-nvidia-secret")

    monkeypatch.setattr("claims.investigation.intake_extract.CompletionClient.complete", fail)
    app = app_for(tmp_path, agent_mode="live", nvidia_api_key="fake-nvidia-secret")
    with TestClient(app) as client:
        response = client.post("/api/intake/extract", json={"description": NOTES})
    assert response.status_code == 503
    assert response.json() == {"detail": "The model could not read these notes right now."}
    assert "secret" not in response.text


def test_endpoint_requires_a_session_and_allows_ordinary_users(tmp_path):
    app = app_for(tmp_path, claims_auth_enabled=True)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        assert client.post("/api/intake/extract", json={"description": NOTES}).status_code == 401
        csrf = {"X-CSRF-Token": client.get("/api/auth/session").json()["csrf_token"]}
        setup = {"username": "admin", "password": ADMIN_PASSWORD}
        assert client.post("/api/auth/setup", json=setup, headers=csrf).status_code == 200
        admin = client.post("/api/auth/login", json=setup, headers=csrf).json()["csrf_token"]
        user = {"username": "alice", "password": USER_PASSWORD, "role": "user"}
        headers = {"X-CSRF-Token": admin}
        assert client.post("/api/admin/users", json=user, headers=headers).status_code == 200
        client.post("/api/auth/logout", headers=headers)
        csrf = {"X-CSRF-Token": client.get("/api/auth/session").json()["csrf_token"]}
        login = client.post("/api/auth/login", json={k: user[k] for k in ("username", "password")}, headers=csrf)
        headers = {"X-CSRF-Token": login.json()["csrf_token"]}
        # Without the CSRF token the write is refused, like every other state-changing route.
        assert client.post("/api/intake/extract", json={"description": NOTES}).status_code == 403
        assert client.post("/api/intake/extract", json={"description": NOTES}, headers=headers).status_code == 200
