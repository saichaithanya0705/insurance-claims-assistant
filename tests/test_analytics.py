import hashlib
import json
import runpy
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from claims.analytics import FEATURES, AnalyticsService, feature_dict, temporal_split
from claims.models import ClaimInput


def sample_rows(count=400):
    rows = []
    for i in range(count):
        incident = date(2021, 1, 1) + timedelta(days=i * 3)
        rows.append(
            {
                "claim_id": f"C{i}",
                "policy_id": f"P{i}",
                "claim_type": "auto" if i % 2 else "home",
                "state": "TX",
                "incident_date": incident.isoformat(),
                "claim_filed_date": (incident + timedelta(days=i % 10)).isoformat(),
                "policyholder_tenure_years": i % 20 + 0.5,
                "previous_claims_count": i % 5,
                "deductible": 500,
                "claim_amount": 5000 + (i % 5) * 1000 + (i % 2) * 7000,
                "claim_status": "pending" if i % 7 == 0 else "approved",
                "days_to_resolution": None if i % 7 == 0 else 10 + i % 5,
                "is_fraud_flagged_ground_truth": i % 5 == 4,
            }
        )
    return rows


def write_sample(path, rows):
    sha = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path.write_text(
        json.dumps(
            {
                "rows": rows,
                "metadata": {
                    "dataset": "unit-test-only",
                    "rows_sha256": sha,
                    "row_count": len(rows),
                    "synthetic": True,
                },
            }
        )
    )


@pytest.fixture
def service(tmp_path):
    path = tmp_path / "sample.json"
    write_sample(path, sample_rows())
    return AnalyticsService(path, tmp_path / "models")


def claim():
    return ClaimInput(
        description="Vehicle damage after a collision",
        claim_type="auto",
        state="TX",
        incident_date="2023-01-01",
        claim_filed_date="2023-01-03",
        claim_amount=9000,
        deductible=500,
        previous_claims_count=2,
        policyholder_tenure_years=4,
    )


def test_feature_contract_prevents_target_and_outcome_leakage():
    row = sample_rows(1)[0]
    for task, names in FEATURES.items():
        features = feature_dict(row, task)
        assert set(features) == set(names)
        assert not {
            "claim_id",
            "policy_id",
            "claim_status",
            "days_to_resolution",
            "is_fraud_flagged_ground_truth",
        } & set(features)
    assert "claim_amount" not in feature_dict(row, "amount")
    changed = {
        **row,
        "claim_amount": 999999,
        "claim_status": "denied",
        "days_to_resolution": 900,
        "is_fraud_flagged_ground_truth": True,
    }
    assert feature_dict(row, "amount") == feature_dict(changed, "amount")


def test_temporal_cohorts_and_policies_disjoint():
    rows = sample_rows()
    rows[0]["policy_id"] = rows[-1]["policy_id"]
    rows[300]["policy_id"] = rows[-2]["policy_id"]
    partitions, split = temporal_split(rows)
    train, calibration, test = partitions
    assert max(r["claim_filed_date"] for r in train) < min(
        r["claim_filed_date"] for r in calibration
    )
    assert max(r["claim_filed_date"] for r in calibration) < min(
        r["claim_filed_date"] for r in test
    )
    policies = [{r["policy_id"] for r in p} for p in partitions]
    assert not policies[0] & policies[1]
    assert not policies[0] & policies[2]
    assert not policies[1] & policies[2]
    assert split["policy_overlap"] == 0


def test_untrained_and_missing_data_do_not_fake_predictions(tmp_path):
    service = AnalyticsService(tmp_path / "missing", tmp_path / "artifacts")
    assert service.status()["available"] is False
    assert service.predict(claim())["available"] is False
    assert service.train()["available"] is False


def test_training_persistence_metrics_and_global_explanation(service):
    report = service.train()
    assert report["available"]
    assert report["origin"]["dataset"] == "unit-test-only"
    for task in ("amount", "resolution", "fraud"):
        assert report["metrics"][task]["available"]
        explanation = report["metrics"][task]["global_explanation"]
        assert explanation["scope"] == "global_calibration_permutation_importance"
        assert {x["feature"] for x in explanation["features"]} <= set(FEATURES[task])
    assert report["metrics"]["amount"]["mae"] >= 0
    assert report["metrics"]["amount"]["baseline_mae"] >= 0
    assert 0 <= report["metrics"]["fraud"]["pr_auc_average_precision"] <= 1
    result = service.predict(claim())
    assert result["available"]
    assert 0 <= result["fraud"]["score"] <= 1
    assert (
        result["amount"]["interval"][0]
        <= result["amount"]["estimate"]
        <= result["amount"]["interval"][1]
    )
    loaded = AnalyticsService(service.data_path, service.artifact_dir)
    assert loaded.predict(claim()) == result
    assert loaded.status()["trained_at"] == report["trained_at"]


def test_insufficient_labels_disable_fraud_only(service):
    rows = sample_rows()
    for row in rows:
        row["is_fraud_flagged_ground_truth"] = False
    write_sample(service.data_path, rows)
    report = service.train()
    assert report["available"]
    assert not report["metrics"]["fraud"]["available"]
    assert not service.predict(claim())["fraud"]["available"]


def test_integrity_mismatch_rejected(service):
    payload = json.loads(service.data_path.read_text())
    payload["rows"][0]["claim_amount"] = 1
    service.data_path.write_text(json.dumps(payload))
    report = service.train()
    assert not report["available"]
    assert "SHA256" in report["reason"]


def test_resolution_excludes_unresolved_and_not_yet_observable():
    rows = sample_rows(4)
    rows[1]["claim_status"] = "under_review"
    rows[2]["days_to_resolution"] = 100
    filtered = AnalyticsService._task_rows(rows, "resolution", "2021-01-30")
    assert [r["claim_id"] for r in filtered] == ["C3"]


def test_unseen_category_and_range_warnings(service):
    service.train()
    changed = claim().model_copy(update={"state": "CA", "claim_amount": 900000})
    result = service.predict(changed)
    assert any("unseen state" in warning for warning in result["warnings"])
    assert any("claim_amount outside" in warning for warning in result["warnings"])


def test_fetch_sample_preserves_source_and_hash(tmp_path, monkeypatch):
    module = runpy.run_path(str(Path(__file__).parents[1] / "scripts/fetch_dataset.py"))
    rows = sample_rows(100)
    real_client = httpx.Client

    def handler(request):
        assert request.url.params["dataset"] == "ziadatalabs/FreeInsuranceClaims100M"
        assert request.url.params["length"] == "100"
        return httpx.Response(
            200,
            json={
                "rows": [{"row": row, "truncated_cells": []} for row in rows],
            },
        )

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(handler),
            **kwargs,
        ),
    )
    output = tmp_path / "source.json"
    metadata = module["fetch_sample"](output, count=100)
    assert json.loads(output.read_text())["rows"] == rows
    assert metadata["row_count"] == 100
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())
    assert metadata["rows_sha256"] == digest.hexdigest()
    with pytest.raises(ValueError):
        module["fetch_sample"](output, count=100000000)


def test_failed_download_does_not_write_partial_sample(tmp_path, monkeypatch):
    module = runpy.run_path(str(Path(__file__).parents[1] / "scripts/fetch_dataset.py"))
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(503)),
            **kwargs,
        ),
    )
    monkeypatch.setattr(module["time"], "sleep", lambda duration: None)
    output = tmp_path / "source.json"
    with pytest.raises(httpx.HTTPStatusError):
        module["fetch_sample"](output, count=100)
    assert not output.exists()
