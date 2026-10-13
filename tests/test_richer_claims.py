import csv
import io
import json
import runpy
from datetime import date, timedelta
from pathlib import Path

import httpx
import numpy as np
import pytest

from claims.ml.fraud_features import file_digest, rows_digest
from claims.ml.reviewed_claims import reviewed_records
from claims.ml.richer_data import (
    MENDELEY_ID,
    normalize_records,
    parse_csv,
    production_blockers,
    read_parquet,
    verified_records,
    write_parquet,
)
from claims.ml.richer_fraud import RichFeatureEncoder, choose_configurations, temporal_cohorts


@pytest.fixture
def raw():
    return {
        "policy_number": "P1",
        "incident_date": "2015-01-03",
        "fraud_reported": "Y",
        "months_as_customer": "24",
        "policy_state": "OH",
        "policy_deductable": "500",
        "total_claim_amount": "8000",
        "incident_type": "Single Vehicle Collision",
        "collision_type": "?",
        "incident_state": "TX",
        "incident_severity": "Minor Damage",
        "police_report_available": "?",
        "property_damage": "?",
        "authorities_contacted": "Police",
        "number_of_vehicles_involved": "1",
        "bodily_injuries": "0",
        "witnesses": "2",
        "auto_make": "Toyota",
        "auto_model": "Camry",
        "auto_year": "2010",
        "incident_hour_of_the_day": "12",
    }


def csv_bytes(rows):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode()


def test_original_labels_missing_values_dates_and_unique_claims_are_preserved(raw, tmp_path):
    rows, audit = normalize_records([raw, dict(raw)])
    assert audit["exact_duplicates_removed"] == 1
    assert len(rows) == 1 and rows[0]["is_fraud"] is True
    assert rows[0]["tenure_years"] == 2
    assert rows[0]["vehicle_age_years"] == 5
    assert rows[0]["collision_type"] is None
    assert rows[0]["police_report_available"] is None
    assert rows[0]["claim_filed_date"] is None and rows[0]["currency"] is None
    path = tmp_path / "claims.parquet"
    write_parquet(rows, path)
    assert read_parquet(path) == rows
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "change",
    [
        {"fraud_reported": "?"},
        {"fraud_reported": "yes"},
        {"total_claim_amount": "nan"},
        {"policy_deductable": "-1"},
        {"auto_year": "2020"},
    ],
)
def test_invalid_source_labels_and_values_are_quarantined(raw, change):
    rows, audit = normalize_records([{**raw, **change}])
    assert not rows and audit["rejected_rows"] == 1


def test_all_conflicting_claim_versions_are_quarantined(raw):
    rows, audit = normalize_records([raw, {**raw, "fraud_reported": "N"}, raw])
    assert not rows
    assert audit["conflicting_claims"] == 1 and audit["rejected_rows"] == 3


def test_schema_and_ragged_csv_are_rejected():
    for data in (b"a,a\n1,2\n", b"a,b\n1\n", b"a,b\n1,2,3\n"):
        with pytest.raises(ValueError):
            parse_csv(data)


def test_original_csv_is_rechecked_against_parquet_labels(raw, tmp_path):
    rows, audit = normalize_records([raw])
    (tmp_path / "original.csv").write_bytes(csv_bytes([raw]))
    write_parquet(rows, tmp_path / "claims.parquet")
    manifest = {
        "source_id": MENDELEY_ID,
        "benchmark_eligible": True,
        "raw_csv": "original.csv",
        "raw_csv_sha256": file_digest(tmp_path / "original.csv"),
        "parquet": "claims.parquet",
        "parquet_sha256": file_digest(tmp_path / "claims.parquet"),
        "rows_sha256": rows_digest(rows),
        "audit": audit,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    assert verified_records(path)[1] == rows
    rows[0]["is_fraud"] = False
    write_parquet(rows, tmp_path / "claims.parquet")
    manifest.update(
        parquet_sha256=file_digest(tmp_path / "claims.parquet"), rows_sha256=rows_digest(rows)
    )
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="original source"):
        verified_records(path)


def test_feature_allowlist_and_training_only_missing_imputation(raw):
    row = normalize_records([raw])[0][0]
    row2 = {**row, "claim_amount": 12000}
    encoder = RichFeatureEncoder("assessment", native=True).fit([row, row2])
    future = {
        **row,
        "claim_amount": None,
        "is_fraud": False,
        "fraud_reported": "N",
        "settlement_amount": 999999,
    }
    x = encoder.transform([future])
    assert 10000 in x[0] and encoder.medians["claim_amount"] == 10000
    np.testing.assert_array_equal(
        x, encoder.transform([{**future, "is_fraud": True, "settlement_amount": 0}])
    )
    assert not {
        "is_fraud",
        "label_observed_at",
        "claim_id",
        "policy_id",
        "settlement_amount",
    } & set(encoder.numeric + encoder.categorical)


def date_rows(*, reviewed=False):
    rows = []
    for day in range(60):
        date_text = (date(2024, 1, 1) + timedelta(days=day)).isoformat()
        for offset in range(10):
            rows.append(
                {
                    "claim_id": f"C{day}-{offset}",
                    "policy_id": f"P{day}-{offset}",
                    "incident_date": date_text,
                    "claim_filed_date": date_text if reviewed else None,
                    "is_fraud": offset % 3 == 0,
                    "label_observed_at": date_text + "T12:00:00+00:00" if reviewed else None,
                }
            )
    return rows


def test_cohorts_purge_policies_keep_same_days_and_require_mature_labels():
    rows = date_rows(reviewed=True)
    rows[0]["policy_id"] = rows[-1]["policy_id"]
    rows[1]["label_observed_at"] = "2025-01-01T00:00:00+00:00"
    groups, split = temporal_cohorts(rows)
    assert split["date_field"] == "claim_filed_date"
    assert split["policy_rows_purged"] == 1 and split["immature_label_rows_purged"] == 1
    for i in range(4):
        assert max(r["claim_filed_date"] for r in groups[i]) < min(
            r["claim_filed_date"] for r in groups[i + 1]
        )
    for i in range(5):
        for j in range(i + 1, 5):
            assert not {r["policy_id"] for r in groups[i]} & {r["policy_id"] for r in groups[j]}


def test_selection_does_not_use_test_metrics():
    results = [
        {
            "configuration": f"{group}_{family}",
            "validation": {
                "average_precision": 0.3 if family == "forest" else 0.4,
                "recall_at_50pct_precision": 0.2,
            },
            "test_accuracy": 1 if family == "forest" else 0,
        }
        for group in ("base", "incident", "assessment")
        for family in ("forest", "catboost")
    ]
    selected = choose_configurations(results)
    assert all(r["configuration"].endswith("catboost") for r in selected.values())


@pytest.fixture
def reviewed():
    row = {
        "claim_id": "C1",
        "policy_id": "P1",
        "claim_type": "auto",
        "incident_date": "2024-01-01",
        "claim_filed_at": "2024-01-02T12:00:00Z",
        "features_observed_at": "2024-01-02T11:00:00Z",
        "label_observed_at": "2024-01-10T12:00:00Z",
        "label_evidence_id": "E1",
        "is_fraud": "true",
        "claim_amount": "8000",
        "deductible": "500",
        "tenure_years": "2",
    }
    evidence = {
        "evidence_id": "E1",
        "claim_id": "C1",
        "is_fraud": True,
        "observed_at": row["label_observed_at"],
        "adjudicator": "test-reviewer",
        "method": "human_review",
        "evidence_reference": "test-only-reference",
    }
    return row, evidence


def test_reviewed_labels_must_match_separate_human_evidence(reviewed):
    row, evidence = reviewed
    rows, audit = reviewed_records([row], [evidence], "reviewed_test_v1")
    assert len(rows) == 1 and audit["evidence_cross_checks"] == 1
    assert rows[0]["is_fraud"] is True
    for changed in (
        {**row, "is_fraud": "false"},
        {**row, "features_observed_at": "2024-01-03T00:00:00Z"},
        {**row, "label_evidence_id": "unknown"},
        {**row, "claim_filed_at": "2024-01-02T12:00:00"},
        {**row, "Fraud_Risk_Score": "0.99"},
        {**row, "bodily_injuries": "0.5"},
        {**row, "incident_hour": "24"},
    ):
        accepted, audit = reviewed_records([changed], [evidence], "reviewed_test_v1")
        assert not accepted and audit["rejected_rows"] == 1
    accepted, audit = reviewed_records([row, row], [evidence], "reviewed_test_v1")
    assert not accepted and audit["rejected_rows"] == 2
    accepted, audit = reviewed_records(
        [row, {**row, "claim_id": " C1 "}], [evidence], "reviewed_test_v1"
    )
    assert not accepted and audit["rejected_rows"] == 2


def test_reviewed_csv_import_roundtrip_and_evidence_tampering(reviewed, tmp_path):
    row, evidence = reviewed
    module = runpy.run_path(str(Path(__file__).parents[1] / "scripts/import_reviewed_claims.py"))
    csv_path, evidence_path = tmp_path / "input.csv", tmp_path / "evidence.json"
    csv_path.write_bytes(csv_bytes([row]))
    evidence_path.write_text(json.dumps([evidence]))
    output = tmp_path / "reviewed"
    manifest = module["import_reviewed"](
        csv_path,
        evidence_path,
        output,
        "reviewed_test_v1",
        "test-only-source",
        "test-only-permission",
        "us_auto",
    )
    assert verified_records(output / "manifest.json")[1][0]["is_fraud"] is True
    assert production_blockers(manifest, verified_records(output / "manifest.json")[1])
    (output / "adjudications.json").write_text("[]")
    with pytest.raises(ValueError, match="evidence changed"):
        verified_records(output / "manifest.json")


def test_source_download_rejects_over_limit_and_immutable_source_changes(tmp_path):
    module = runpy.run_path(str(Path(__file__).parents[1] / "scripts/prepare_richer_claims.py"))
    # Exercise the bounded downloader without real network traffic.
    module["download"].__globals__["MAX_BYTES"] = 10
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 11))
    with httpx.Client(transport=transport) as client, pytest.raises(ValueError, match="bounded"):
        module["download"](client, "https://example.org/test")
    path = tmp_path / "original.csv"
    module["store_immutable"](path, b"original")
    with pytest.raises(ValueError, match="changed"):
        module["store_immutable"](path, b"replacement")
