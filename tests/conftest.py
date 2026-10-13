"""Unit tests never inherit live credentials or make external requests."""

import httpx
import pytest
from synapt_stub import StubSynaptAdapter

from claims.core.settings import Settings


@pytest.fixture(autouse=True)
def isolate_configuration_and_network(monkeypatch, tmp_path):
    # DeepEval's pytest plugin loads .env into os.environ before test execution.
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    # Unit tests must never scan the real 100M-row dataset that may sit in data/raw/parquet.
    monkeypatch.setenv("CLAIMS_PARQUET_PATH", str(tmp_path / "no-parquet-in-unit-tests.parquet"))
    # Existing workflow tests exercise the service without browser authentication.
    # Dedicated RBAC tests explicitly enable it and exercise real sessions.
    monkeypatch.setenv('CLAIMS_AUTH_ENABLED', 'false')
    # Synapt is required by Settings. Unit tests supply dummy credentials (the network is blocked
    # below, so nothing can be sent anywhere) and a test double in place of the live adapter.
    # Tests of the real adapter build LiveSynaptAdapter themselves, with a mocked session.
    monkeypatch.setenv("SYNAPT_USERNAME", "unit-test-user")
    monkeypatch.setenv("SYNAPT_PASSWORD", "unit-test-password")
    monkeypatch.setenv("SYNAPT_PROVIDER_ID", "unit-test-provider")
    monkeypatch.setattr("claims.api.main.build_synapt_adapter", lambda settings: StubSynaptAdapter())
    # Degraded-mode fallback reads local artifacts that exist only on some machines, so unit tests
    # switch it off and tests of it opt in with an explicit card file.
    monkeypatch.setenv("CLAIMS_FALLBACK_ENABLED", "false")
    # The request budget is process-wide; unit tests make bursts of mocked model calls and must neither wait for it nor share it.
    monkeypatch.setenv("LLM_REQUESTS_PER_MINUTE", "0")
    monkeypatch.setattr("claims.llm.ratelimit._gates", {})

    def blocked(*args, **kwargs):
        raise AssertionError(
            "External network calls are forbidden in unit tests; use mocked transport or the explicit live script"
        )

    async def async_blocked(*args, **kwargs):
        return blocked(*args, **kwargs)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_blocked)
