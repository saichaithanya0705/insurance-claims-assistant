import asyncio
import json
from datetime import date
from types import SimpleNamespace

import duckdb
import pytest
from mcp.types import CallToolResult

from claims.core.settings import Settings
from claims.corpus.card_dataset import build_card_dataset, known_claim_ids, select_expansion
from claims.history.dataset import ClaimsStore
from claims.synapt.adapter import LiveSynaptAdapter, SynaptError


@pytest.fixture
def settings():
    return Settings(_env_file=None, synapt_provider_id="test-provider",
                    synapt_username="fixture-user", synapt_password="fixture-password")


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.parquet"
    connection = duckdb.connect()
    connection.execute("""
        COPY (SELECT printf('CLM-%010d', i) claim_id, 'POL-100000001' policy_id,
          (['auto','business','home','property','renters'])[1+i%5] claim_type,
          (['TX','CA'])[1+(i//5)%2] state, 4.0 policyholder_tenure_years,
          (i%4)::INTEGER previous_claims_count, DATE '2023-01-01' incident_date,
          DATE '2023-01-03' claim_filed_date, (1000+i*50)::DOUBLE claim_amount,
          500.0 deductible, 'approved' claim_status, 15.0 days_to_resolution,
          true is_fraud_flagged_ground_truth FROM range(500) t(i))
        TO ? (FORMAT PARQUET)
    """, [str(path)])
    connection.close()
    store = ClaimsStore(path, memory_limit="256MB", threads=1)
    yield store
    store.close()


def test_export_roundtrip_stratification_and_label_boundary(source, tmp_path):
    output = tmp_path / "cards"
    manifest = build_card_dataset(source, output, per_cell=3, batch_cards=7)
    assert manifest["cards"] == 30
    assert set(manifest["cards_by_type_state"].values()) == {3}
    assert len(manifest["batches"]) == 5
    connection = duckdb.connect()
    rows = connection.execute("SELECT * FROM read_parquet(?)", [str(output / "claim_cards.parquet")])
    names = [d[0] for d in rows.description]
    assert "is_fraud_flagged_ground_truth" not in names
    assert "policy_id" not in names
    records = [dict(zip(names, row)) for row in rows.fetchall()]
    assert len(records) == 30
    assert all(r["has_incident_narrative"] is False for r in records)
    assert all(r["has_policy_wording"] is False for r in records)
    assert all("Outcome approved after 15 days" in r["card_text"] for r in records)
    assert all("POL-" not in r["card_text"] and "fraud" not in r["card_text"] for r in records)
    connection.close()


def test_selection_is_repeatable_excludes_known_and_future(source):
    kwargs = {"per_cell": 2, "cutoff": date(2026, 1, 1)}
    first = select_expansion(source, **kwargs)
    assert first == select_expansion(source, **kwargs)
    ids = {r["claim_id"] for r in first}
    new = select_expansion(source, excluded=ids, **kwargs)
    assert not ids & {r["claim_id"] for r in new}
    assert select_expansion(source, per_cell=2, cutoff=date(2023, 1, 10)) == []


def test_union_inventory_and_manifest_and_no_overwrite(source, tmp_path):
    output = tmp_path / "cards"
    manifest = build_card_dataset(source, output, per_cell=1)
    (tmp_path / "inventory.json").write_text(json.dumps({"claim_ids": ["CLM-9999999999"]}))
    known = known_claim_ids(tmp_path)
    assert len(known) == manifest["cards"] + 1
    with pytest.raises(ValueError, match="empty"):
        build_card_dataset(source, output, per_cell=1)


@pytest.mark.parametrize("body", [{"accepted": False}, {"result": '{"accepted": false}'}])
def test_ingest_rejects_negative_acknowledgement(monkeypatch, settings, body):
    adapter = LiveSynaptAdapter(settings)

    async def fake(*args, **kwargs):
        return body

    monkeypatch.setattr(adapter, "_explicit_tool", fake)
    with pytest.raises(SynaptError, match="rejected"):
        asyncio.run(adapter.ingest("Cards", "cards.txt"))


def test_ingest_disables_default_expiry_when_schema_supports_it(monkeypatch, settings):
    adapter = LiveSynaptAdapter(settings)
    values = {}

    async def fake(name, arguments, **kwargs):
        values.update(arguments(SimpleNamespace(inputSchema={"properties": {
            k: {} for k in ("provider_id", "content", "extraction_mode", "has_ttl")
        }})))
        return {"accepted": True}

    monkeypatch.setattr(adapter, "_explicit_tool", fake)
    asyncio.run(adapter.ingest("Cards", "cards.txt"))
    assert values["has_ttl"] is False


@pytest.mark.parametrize("query", [
    "MATCH (d:Document) RETURN d LIMIT 10",
    "MATCH (d:Document {provider_id: $provider_id}) DELETE d",
    "MATCH (d:Document {provider_id: $provider_id}) RETURN d; CREATE ()",
])
def test_cypher_audit_cannot_mutate_or_read_unscoped(settings, query):
    adapter = LiveSynaptAdapter(settings)
    tool = SimpleNamespace(name="trident_cypher")
    with pytest.raises(SynaptError, match="provider-scoped MATCH"):
        adapter._validate_arguments(tool, {"query": query})


def test_bulk_inventory_budget_is_explicit_and_stays_bounded(settings):
    adapter = LiveSynaptAdapter(settings)
    result = CallToolResult(content=[], structuredContent={"result": "x" * 100_000})
    with pytest.raises(SynaptError, match="budget"):
        adapter._structured_payload(result, 10_000)
    assert len(adapter._structured_payload(result, 200_000)["result"]) == 100_000
    with pytest.raises(SynaptError, match="budget"):
        asyncio.run(adapter.call_read_tool("trident_get_stats", {}, max_response_chars=100_000_000))
