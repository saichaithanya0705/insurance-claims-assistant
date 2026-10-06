"""Corpus contracts use isolated synthetic rows, never credentials or network access."""

import hashlib
import json
import runpy
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pytest

module = runpy.run_path(str(Path(__file__).parents[1] / "scripts" / "prepare_synapt_corpus.py"))
prepare = module["prepare"]
digest_json = module["digest_json"]


def row(index, kind="auto", **overrides):
    return {
        "claim_id": f"CLM-{index:05d}",
        "policy_id": f"POL-{index:05d}",
        "claim_type": kind,
        "state": "CA",
        "policyholder_tenure_years": 3.25,
        "previous_claims_count": 1,
        "incident_date": "2025-01-01",
        "claim_filed_date": "2025-01-02",
        "claim_amount": 1234.56 + index,
        "deductible": 250.0,
        "claim_status": "approved",
        "days_to_resolution": 10.5,
        "is_fraud_flagged_ground_truth": True,
        # Additional future outcome fields must never appear in upload documents.
        "future_target_secret": "excluded target sentinel",
        **overrides,
    }


def source_file(tmp_path, rows):
    source = tmp_path / "claims.json"
    source.write_text(
        json.dumps(
            {
                "metadata": {
                    "dataset": module["DATASET"],
                    "rows_sha256": digest_json(rows),
                    "synthetic": True,
                    "license": "CC-BY-NC-4.0",
                },
                "rows": rows,
            }
        ),
        encoding="utf-8",
    )
    return source


def standard_rows(count=30):
    return [
        row(i, module["CLAIM_TYPES"][i % 5], claim_status="denied" if i % 2 else "approved")
        for i in range(count)
    ]


def test_cutoff_fractional_days_and_excluded_targets(tmp_path):
    rows = standard_rows()
    rows += [
        row(100, claim_status="under_review"),
        row(101, days_to_resolution=None),
        row(102, claim_filed_date="2025-12-31", days_to_resolution=1.1),
        row(103, claim_filed_date="2025-12-31", days_to_resolution=0.9),
        row(104, days_to_resolution=-1),
        rows[0].copy(),
    ]
    outputs = prepare(source_file(tmp_path, rows), tmp_path / "pilot", tmp_path / "full")
    full = outputs["expansion"]
    assert full["historical_cards"] == 31
    assert full["source"]["excluded_count"] == 5
    assert full["source"]["excluded_reasons"] == {
        "not_closed_status": 1,
        "missing_resolution_duration": 1,
        "closed_on_or_after_cutoff": 1,
        "invalid_record": 1,
        "duplicate_claim_id": 1,
    }
    assert "CLM-00103" in full["claim_ids"]
    assert "CLM-00102" not in full["claim_ids"]
    for output in (tmp_path / "pilot", tmp_path / "full"):
        for path in (output / "upload").glob("*.txt"):
            text = path.read_text(encoding="utf-8")
            assert "is_fraud_flagged_ground_truth" not in text
            assert "future_target_secret" not in text
            assert "excluded target sentinel" not in text
            assert "source_id:" in text and "provenance:" in text and "attribution:" in text
            assert "Educational decision support only" in text
            assert "does not decide coverage" in text
            assert "theft-gap" not in text and "home-conflict" not in text


def test_source_integrity_and_original_field_preservation(tmp_path):
    rows = standard_rows()
    source = source_file(tmp_path, rows)
    outputs = prepare(source, tmp_path / "pilot", tmp_path / "full")
    probes = outputs["expansion"]["factual_probes"]
    by_id = {r["claim_id"]: r for r in rows}
    full_text = "\n".join(
        p.read_text(encoding="utf-8") for p in (tmp_path / "full" / "upload").glob("*.txt")
    )
    for probe in probes:
        original = by_id[probe["claim_id"]]
        assert probe["source_row_sha256"] == digest_json(original)
        assert all(snippet in full_text for snippet in probe["expected_snippets"])
        derived = date.fromisoformat(original["claim_filed_date"]) + timedelta(
            days=original["days_to_resolution"]
        )
        assert f"derived_closed_date: {derived.isoformat()}" in full_text
    content = json.loads(source.read_text(encoding="utf-8"))
    content["rows"][0]["claim_amount"] += 1
    source.write_text(json.dumps(content), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256"):
        prepare(source, tmp_path / "other-pilot", tmp_path / "other-full")


def test_pilot_full_uniqueness_type_coverage_and_byte_limits(tmp_path):
    rows = standard_rows(250)
    outputs = prepare(
        source_file(tmp_path, rows),
        tmp_path / "pilot",
        tmp_path / "full",
        max_cards=100,
        max_bytes=5000,
    )
    pilot, full = outputs["pilot"], outputs["expansion"]
    assert pilot["historical_cards"] == 10
    assert pilot["synthetic_procedure_documents"] == 5
    assert pilot["upload_document_count"] == 15
    assert pilot["claim_type_counts"] == dict.fromkeys(module["CLAIM_TYPES"], 2)
    assert len(set(pilot["claim_ids"])) == 10
    assert len(set(full["claim_ids"])) == 250
    assert set(pilot["claim_ids"]) <= set(full["claim_ids"])
    full_files = [record for record in full["files"] if record["path"].startswith("upload/")]
    flattened = [cid for record in full_files for cid in record["claim_ids"]]
    assert Counter(flattened) == Counter(full["claim_ids"])
    for name, output in (("pilot", tmp_path / "pilot"), ("expansion", tmp_path / "full")):
        for record in outputs[name]["files"]:
            raw = (output / record["path"]).read_bytes()
            assert len(raw) == record["bytes"]
            assert hashlib.sha256(raw).hexdigest() == record["sha256"]
            raw.decode("utf-8")
            if record["path"].startswith("upload/"):
                assert record["bytes"] <= outputs[name]["batch_max_bytes"]
                assert len(record["claim_ids"]) <= outputs[name]["batch_max_cards"]
        qa = json.loads((output / "QA_NOT_FOR_UPLOAD.json").read_text(encoding="utf-8"))
        assert "NOT FOR UPLOAD" in qa["warning"]
        assert not (output / "upload" / "QA_NOT_FOR_UPLOAD.json").exists()
    assert (tmp_path / "pilot" / "pilot-combined.txt").stat().st_size <= 25 * 1024


def test_reproducible_idempotent_and_refuses_conflicting_content(tmp_path):
    source = source_file(tmp_path, standard_rows())
    pilot, full = tmp_path / "pilot", tmp_path / "full"
    first = prepare(source, pilot, full)
    assert first == prepare(source, pilot, full)
    snapshot = {p.relative_to(pilot): p.read_bytes() for p in pilot.rglob("*") if p.is_file()}
    changed = next((pilot / "upload").glob("*.txt"))
    changed.write_bytes(b"Keep this existing content")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        prepare(source, pilot, full)
    assert changed.read_bytes() == b"Keep this existing content"
    for relative, raw in snapshot.items():
        if pilot / relative != changed:
            assert (pilot / relative).read_bytes() == raw


def test_unknown_existing_upload_files_are_not_silently_preserved(tmp_path):
    source = source_file(tmp_path, standard_rows())
    pilot = tmp_path / "pilot"
    (pilot / "upload").mkdir(parents=True)
    unrelated = pilot / "upload" / "existing.txt"
    unrelated.write_text("Existing provider content", encoding="utf-8")
    with pytest.raises(ValueError, match="unrecognized"):
        prepare(source, pilot, tmp_path / "full")
    assert unrelated.read_text(encoding="utf-8") == "Existing provider content"


def test_rejects_overlarge_batch_limits_and_unattributed_source(tmp_path):
    source = source_file(tmp_path, standard_rows())
    with pytest.raises(ValueError, match="Batch limits"):
        prepare(source, tmp_path / "pilot", tmp_path / "full", max_cards=101)
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["metadata"]["license"] = "unknown"
    source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="noncommercial"):
        prepare(source, tmp_path / "pilot", tmp_path / "full")


def test_both_outputs_are_preflighted_before_writing_and_must_not_overlap(tmp_path):
    source = source_file(tmp_path, standard_rows())
    full = tmp_path / "full"
    full.mkdir()
    (full / "manifest.json").write_text("Existing content", encoding="utf-8")
    pilot = tmp_path / "pilot"
    with pytest.raises(ValueError, match="refusing to overwrite"):
        prepare(source, pilot, full)
    assert not pilot.exists()
    with pytest.raises(ValueError, match="nonnested"):
        prepare(source, pilot, pilot / "nested-expansion")
