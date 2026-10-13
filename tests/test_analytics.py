import hashlib
import json
import runpy
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from claims.core.schemas import ClaimInput
from claims.ml.analytics import (
    FEATURES,
    AnalyticsService,
    calibration_roles,
    feature_dict,
    temporal_split,
)


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


def test_explanations_state_direction_not_just_importance(service):
    report = service.train()
    explanation = report["metrics"]["amount"]["global_explanation"]
    effects = {e["feature"]: e for e in explanation["effects"]}
    kind = effects["claim_type"]
    # In the test data auto claims are $7,000 larger than home claims.
    assert kind["kind"] == "categorical" and kind["direction"] == "varies_by_category"
    assert kind["highest"]["value"] == "auto" and kind["lowest"]["value"] == "home"
    assert kind["highest"]["mean_prediction"] > kind["lowest"]["mean_prediction"] + 3000
    assert [p["value"] for p in kind["points"]] == ["auto", "home"]  # two categories, no repeats
    assert any(
        line.startswith("claim type: highest predicted claim amount (USD) for auto")
        and "lowest for home" in line
        for line in explanation["summary"]
    )
    assert "not causal" in explanation["effects_method"]
    # A feature with no real effect is not presented as a finding.
    assert effects["deductible"]["direction"] == "little_effect"
    assert not any(line.startswith("deductible") for line in explanation["summary"])
    for task in ("amount", "resolution", "fraud"):
        for effect in report["metrics"][task]["global_explanation"]["effects"]:
            assert effect["direction"] in {
                "higher_values_increase",
                "higher_values_decrease",
                "non_monotonic",
                "varies_by_category",
                "little_effect",
            }


def test_each_prediction_explains_what_moved_it_from_a_typical_claim(service):
    service.train()
    result = service.predict(claim())
    for task, unit in (("amount", "USD"), ("resolution", "days"), ("fraud", "score")):
        local = result[task]["local_explanation"]
        assert local["unit"] == unit and "not additive or causal" in local["method"]
        effects = [c["effect"] for c in local["contributions"]]
        assert effects == sorted(effects, key=abs, reverse=True) and len(effects) <= 6
        for item in local["contributions"]:
            assert item["value"] != item["typical_value"]
    # Previous-claims history is the only thing changed: its contribution must be reported.
    changed = service.predict(claim().model_copy(update={"previous_claims_count": 4}))
    assert changed["fraud"]["local_explanation"] != result["fraud"]["local_explanation"]


def test_artifacts_trained_before_local_explanations_still_predict(service):
    service.train()
    for trained in service._bundle["models"].values():
        trained.pop("reference")
    result = service.predict(claim())
    assert result["available"] and result["amount"]["local_explanation"] is None


def test_calibration_decisions_use_disjoint_dates_and_policies():
    rows = sample_rows(100)
    rows[0]["policy_id"] = rows[-1]["policy_id"]
    rows[60]["policy_id"] = rows[-2]["policy_id"]
    groups, boundaries = calibration_roles(rows)
    assert max(r["claim_filed_date"] for r in groups[0]) < boundaries[0]
    assert min(r["claim_filed_date"] for r in groups[1]) >= boundaries[0]
    assert max(r["claim_filed_date"] for r in groups[1]) < boundaries[1]
    assert min(r["claim_filed_date"] for r in groups[2]) >= boundaries[1]
    policies = [{r["policy_id"] for r in group} for group in groups]
    assert not policies[0] & (policies[1] | policies[2])
    assert not policies[1] & policies[2]


def test_test_outcomes_cannot_choose_model_or_interval(service):
    partitions, split = temporal_split(sample_rows())
    trained, metrics = service._fit_task("amount", partitions, split)
    changed = [
        partitions[0],
        partitions[1],
        [{**row, "claim_amount": row["claim_amount"] * 100} for row in partitions[2]],
    ]
    changed_trained, changed_metrics = service._fit_task("amount", changed, split)
    assert metrics["selected_model"] == changed_metrics["selected_model"]
    assert metrics["candidate_selection_maes"] == pytest.approx(
        changed_metrics["candidate_selection_maes"], abs=1e-8
    )
    assert trained["radius"] == pytest.approx(changed_trained["radius"], abs=1e-8)
    assert metrics["mae"] != changed_metrics["mae"]


def test_selected_model_is_refit_on_selection_rows_and_hgb_uses_temporal_tail(service):
    partitions, split = temporal_split(sample_rows())
    trained, metric = service._fit_task("amount", partitions, split)
    assert metric["refit_rows"] == len(partitions[0]) + metric["calibration_roles"]["selection"]
    model = trained["model"]
    # The final fit is deliberately fixed-iteration: random internal validation is
    # not allowed after model selection.
    assert getattr(model, "early_stopping", None) is False


def test_amount_selection_includes_claim_type_median_candidate(service):
    partitions, split = temporal_split(sample_rows())
    _, metric = service._fit_task("amount", partitions, split)
    assert "claim_type_median" in metric["candidate_selection_maes"]


def test_constant_regression_target_prefers_simple_baseline(service):
    rows = [{**row, "claim_amount": 1200} for row in sample_rows()]
    partitions, split = temporal_split(rows)
    _, metrics = service._fit_task("amount", partitions, split)
    assert metrics["selected_model"] == "median_baseline"
    assert metrics["mae"] == 0


def test_fraud_metrics_disclose_imbalanced_baseline(service):
    report = service.train()
    metric = report["metrics"]["fraud"]
    assert 0 <= metric["balanced_accuracy"] <= 1
    assert metric["majority_accuracy"] > 0.5
    assert set(metric["calibration_roles"]) == {"selection", "uncertainty", "threshold"}
    assert "prior_baseline" in metric["candidate_selection_scores"]


def test_fraud_test_labels_cannot_select_weights_or_review_threshold(service):
    partitions, split = temporal_split(sample_rows())
    trained, metric = service._fit_task("fraud", partitions, split)
    changed = [partitions[0], partitions[1], [
        {**row, "is_fraud_flagged_ground_truth": not row["is_fraud_flagged_ground_truth"]}
        for row in partitions[2]
    ]]
    other, changed_metric = service._fit_task("fraud", changed, split)
    assert metric["selected_model"] == changed_metric["selected_model"]
    assert metric["candidate_selection_scores"].keys() == changed_metric["candidate_selection_scores"].keys()
    for name, scores in metric["candidate_selection_scores"].items():
        # Parallel forest reductions may differ in the last floating-point bit.
        # Assert outcome isolation at a tight tolerance instead of bit identity.
        assert scores == pytest.approx(changed_metric["candidate_selection_scores"][name], abs=1e-12, rel=0)
    assert trained["threshold"] == pytest.approx(other["threshold"])
    for name, point in metric["threshold_cohort_operating_points"].items():
        other_point = changed_metric["threshold_cohort_operating_points"][name]
        if point is None:
            assert other_point is None
        else:
            assert point == pytest.approx(other_point, abs=1e-12, rel=0)
    assert metric["recall"] != changed_metric["recall"]


def test_independent_holdout_reconstruction_and_feature_aware_baselines(service):
    service.train()
    module = runpy.run_path(str(Path(__file__).parents[1] / "scripts/retrain_models.py"))
    verified = module["verify_holdout"](service)
    assert all(task["stored_metric_matches"] for task in verified["tasks"].values())
    assert verified["tasks"]["amount"]["feature_aware_baseline"]["mae"] >= 0
    assert verified["tasks"]["resolution"]["feature_aware_baseline"]["mae"] >= 0
    assert set(verified["tasks"]["amount"]["claim_type_cohorts"]) == {"auto", "home"}
