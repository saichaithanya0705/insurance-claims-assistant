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


def test_verify_only_does_not_upload_or_downgrade_prior_verification(upload_case):
    args, calls, identity = upload_case
    ledger = args.corpus / "upload-ledger.jsonl"
    uploader.record(ledger, identity | {"status": "verified", "verification": {"verified": True}})
    before = ledger.read_bytes()
    args.verify_only = True
    asyncio.run(uploader.main(args))
    assert "INGEST" not in calls
    assert ledger.read_bytes() == before
    result = json.loads((args.corpus / "reconciliation.json").read_text())
    assert result["batches"][0]["status"] == "verified"
    assert result["batches"][0]["current_inventory"]["verified"] is False


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
