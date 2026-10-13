"""Synapt is required: no setting, adapter or fallback lets the application run without it."""

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import claims
from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.settings import Settings
from claims.synapt import adapter as adapter_module
from claims.synapt.adapter import LiveSynaptAdapter, build_synapt_adapter

CREDENTIALS = {
    "synapt_username": "test-user",
    "synapt_password": "test-password",
    "synapt_provider_id": "test-provider",
}


def test_synapt_cannot_be_switched_off_in_code():
    with pytest.raises(ValidationError, match="Synapt cannot be disabled"):
        Settings(_env_file=None, synapt_mode="fixture", **CREDENTIALS)


def test_synapt_cannot_be_switched_off_from_the_environment(monkeypatch):
    monkeypatch.setenv("SYNAPT_MODE", "fixture")
    with pytest.raises(ValidationError, match="Synapt cannot be disabled"):
        Settings(_env_file=None)


@pytest.mark.parametrize("missing", list(CREDENTIALS))
def test_settings_refuse_to_load_without_each_synapt_credential(missing):
    with pytest.raises(ValidationError, match="Synapt is required"):
        Settings(_env_file=None, **(CREDENTIALS | {missing: ""}))


def test_settings_refuse_to_load_with_no_synapt_configuration_at_all(monkeypatch):
    for name in ("SYNAPT_USERNAME", "SYNAPT_PASSWORD", "SYNAPT_PROVIDER_ID"):
        monkeypatch.delenv(name)
    with pytest.raises(ValidationError, match="Synapt is required"):
        Settings(_env_file=None)


def test_synapt_must_be_reached_over_https():
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings(_env_file=None, synapt_mcp_url="http://synapt.example.com/mcp/", **CREDENTIALS)


def test_the_adapter_factory_only_ever_builds_the_live_adapter():
    adapter = build_synapt_adapter(Settings(_env_file=None, **CREDENTIALS))
    assert isinstance(adapter, LiveSynaptAdapter)


def test_the_product_contains_no_stand_in_for_synapt():
    assert not hasattr(adapter_module, "FixtureSynaptAdapter")
    # Recursive: the package is split into sub-packages, and a top-level glob would scan nothing.
    sources = list(Path(claims.__file__).parent.rglob("*.py"))
    assert len(sources) > 40
    assert [p.name for p in sources if "FixtureSynaptAdapter" in p.read_text(encoding="utf-8")] == []


def test_an_unreachable_synapt_fails_the_investigation_and_nothing_replaces_it(monkeypatch, tmp_path):
    settings = Settings(
        _env_file=None,
        claims_database_path=tmp_path / "runtime.sqlite",
        claims_data_path=tmp_path / "absent.json",
        claims_artifact_dir=tmp_path / "models",
        **CREDENTIALS,
    )
    adapter = LiveSynaptAdapter(settings)

    @asynccontextmanager
    async def synapt_is_down():
        raise ConnectionError("Synapt unreachable")
        yield

    monkeypatch.setattr(adapter, "_session", synapt_is_down)
    claim = DEMO_CASES[0]["claim"]
    with TestClient(create_app(settings, adapter=adapter)) as client:
        run = client.post("/api/investigations", json={"claim": claim}).json()
        search = client.post("/api/search", json={"claim": claim})

    assert run["status"] == "failed"
    assert "no fallback was used" in run["error"]
    assert not run.get("evidence") and not run.get("findings") and not run.get("recommendations")
    assert search.status_code == 503
