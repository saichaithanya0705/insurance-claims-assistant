"""Unit tests never inherit live credentials or make external requests."""

import httpx
import pytest

from claims.settings import Settings


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

    def blocked(*args, **kwargs):
        raise AssertionError(
            "External network calls are forbidden in unit tests; use mocked transport or the explicit live script"
        )

    async def async_blocked(*args, **kwargs):
        return blocked(*args, **kwargs)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_blocked)
