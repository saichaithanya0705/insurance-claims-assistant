"""Duplicate-sensitive uploader behavior without network side effects."""

import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "expanded_ingestion", Path(__file__).parents[1] / "scripts" / "ingest_expanded_cards.py"
)
uploader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uploader)


@pytest.fixture
def upload_case(tmp_path, monkeypatch):
    text = "A historical card"
    (tmp_path / "cards.txt").write_text(text, encoding="utf-8")
    batch = {"path": "cards.txt", "sha256": hashlib.sha256(text.encode()).hexdigest(),
             "cards": 1, "claim_ids": ["CLM-0000000001"], "sentinels": [], "marker": "test"}
    (tmp_path / "manifest.json").write_text(json.dumps({"cards": 1, "batches": [batch]}))
    calls = []

    class Adapter:
        async def call_read_tool(self, name, arguments, **kwargs):
            calls.append(name)
            return {"doc_count": 2, "chunks": 2} if name == "trident_get_stats" else {"chunks": []}

        async def ingest(self, *args, **kwargs):
            calls.append("INGEST")
            return {"status": "submitted"}

    monkeypatch.setattr(uploader, "Settings", lambda: SimpleNamespace(
        synapt_mode="live", synapt_provider_id="test-provider"
    ))
    monkeypatch.setattr(uploader, "LiveSynaptAdapter", lambda settings: Adapter())
    args = SimpleNamespace(corpus=tmp_path, max_batches=0, wait=0, submit_only=True,
                           verify_only=False, retry_rejected=False, targeted=False)
    identity = {"provider": "test-provider", "path": batch["path"], "sha256": batch["sha256"]}
    return args, calls, identity


@pytest.mark.parametrize("status", ["write_started", "unknown", "submitted", "unverified"])
def test_tracked_or_uncertain_write_is_never_automatically_repeated(upload_case, status):
    args, calls, identity = upload_case
    uploader.record(args.corpus / "upload-ledger.jsonl", identity | {"status": status})
    args.retry_rejected = True
    asyncio.run(uploader.main(args))
    assert "INGEST" not in calls


class GraphProvider:
    """A provider holding one document for the single test batch, as Synapt's graph would report it."""

    def __init__(self, calls, chunks=1):
        self.calls, self.chunks = calls, chunks

    async def call_read_tool(self, name, arguments, **kwargs):
        self.calls.append(name)
        if name == "trident_get_stats":
            return {"doc_count": 1, "chunks": self.chunks}
        if name == "trident_cypher":
            row = {"f": "doc.txt", "n": self.chunks, "linked": self.chunks, "lo": 0, "hi": 17 + 1094}
            return {"result": json.dumps([row])}
        return {"result": json.dumps([{"source_file": "doc.txt",
                                       "text": "### Historical claim cards; corpus batch test"}])}


@pytest.fixture
def graph_case(upload_case, monkeypatch):
    args, calls, identity = upload_case
    inventory = {"base": {"batches": []}, "procedures": [], "expansion": {"batches": [
        {"name": "cards.txt", "cards": 1, "chars": 17, "marker": "test", "sha256": identity["sha256"]}]}}
    monkeypatch.setattr(uploader, "load_expected", lambda path: inventory)
    args.verify_only = True
    return args, calls, identity, inventory


def test_verify_only_does_not_upload_or_downgrade_prior_verification(graph_case, monkeypatch):
    args, calls, identity, _ = graph_case
    ledger = args.corpus / "upload-ledger.jsonl"
    uploader.record(ledger, identity | {"status": "verified", "verification": {"verified": True}})
    before = ledger.read_bytes()
    # The store now lacks the card (zero chunks): the report says so, the ledger is left alone.
    monkeypatch.setattr(uploader, "LiveSynaptAdapter", lambda settings: GraphProvider(calls, chunks=0))
    asyncio.run(uploader.main(args))
    assert "INGEST" not in calls
    assert ledger.read_bytes() == before
    result = json.loads((args.corpus / "reconciliation.json").read_text())
    assert result["expansion"]["batches"][0]["status"] == "failed"
    assert not result["ok"]


def test_verify_only_records_graph_verification_for_a_submitted_batch(graph_case, monkeypatch):
    args, calls, identity, _ = graph_case
    ledger = args.corpus / "upload-ledger.jsonl"
    uploader.record(ledger, identity | {"status": "submitted"})
    monkeypatch.setattr(uploader, "LiveSynaptAdapter", lambda settings: GraphProvider(calls))
    asyncio.run(uploader.main(args))
    assert "INGEST" not in calls
    entry = uploader.ledger_states(ledger, "test-provider")["cards.txt"]
    assert entry["status"] == "verified" and entry["verification"]["method"] == "graph"


def test_verify_only_ignores_an_inventory_for_a_different_build_of_the_batch(graph_case, monkeypatch):
    args, calls, identity, inventory = graph_case
    inventory["expansion"]["batches"][0]["sha256"] = "0" * 64
    ledger = args.corpus / "upload-ledger.jsonl"
    uploader.record(ledger, identity | {"status": "submitted"})
    monkeypatch.setattr(uploader, "LiveSynaptAdapter", lambda settings: GraphProvider(calls))
    asyncio.run(uploader.main(args))
    assert uploader.ledger_states(ledger, "test-provider")["cards.txt"]["status"] == "submitted"


def test_confirmed_rejection_requires_explicit_retry_and_records_new_submission(upload_case):
    args, calls, identity = upload_case
    ledger = args.corpus / "upload-ledger.jsonl"
    uploader.record(ledger, identity | {"status": "rejected"})
    asyncio.run(uploader.main(args))
    assert "INGEST" not in calls
    args.retry_rejected = True
    asyncio.run(uploader.main(args))
    assert calls.count("INGEST") == 1
    assert uploader.ledger_states(ledger, "test-provider")["cards.txt"]["status"] == "submitted"


def test_cross_provider_ledger_fails_before_any_call(upload_case):
    args, calls, identity = upload_case
    uploader.record(args.corpus / "upload-ledger.jsonl", identity | {"provider": "other", "status": "submitted"})
    with pytest.raises(ValueError, match="different provider"):
        asyncio.run(uploader.main(args))
    assert not calls
