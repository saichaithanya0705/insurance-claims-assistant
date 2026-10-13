import itertools
import runpy
from pathlib import Path

import numpy as np
import pytest
from sklearn.metrics import f1_score

from claims.ml.analytics import (
    AnalyticsService,
    fraud_classification_metrics,
    fraud_operating_points,
)


def test_operating_threshold_matches_exhaustive_search_including_tied_scores():
    labels = np.array([0, 0, 1, 0, 1, 1, 0, 1])
    scores = np.array([0.10, 0.11, 0.115, 0.12, 0.125, 0.13, 0.13, 0.9])
    points = fraud_operating_points(labels, scores)
    expected = max(f1_score(labels, scores >= threshold) for threshold in np.unique(scores))
    assert points["max_f1"]["f1"] == pytest.approx(expected)
    at50 = points["precision_at_least_50pct"]
    assert at50["precision"] >= 0.5
    assert at50 == fraud_classification_metrics(labels, scores, at50["threshold"])
    for name, cap in (("review_at_most_5pct", 0.05), ("review_at_most_10pct", 0.10)):
        assert points[name] is None or points[name]["review_fraction"] <= cap


def test_tied_uninformative_scores_cannot_claim_high_precision_or_zero_workload():
    points = fraud_operating_points([0, 0, 0, 1], [0.25] * 4)
    assert points["precision_at_least_50pct"] is None
    assert points["precision_at_least_70pct"] is None
    assert points["review_at_most_5pct"] is None
    assert points["max_f1"]["recall"] == 1
    assert points["max_f1"]["precision"] == 0.25


@pytest.mark.parametrize("labels,scores", [
    ([0, 1], [0, float("nan")]), ([0, 1], [0, 1.1]),
    ([0, 1], [0]), ([1, 1], [0.1, 0.2]), ([0, 2], [0.1, 0.2]),
])
def test_operating_point_validation_rejects_malformed_probabilities(labels, scores):
    with pytest.raises(ValueError):
        fraud_operating_points(labels, scores)


def test_weight_candidates_do_not_replace_the_unweighted_baseline():
    candidates = AnalyticsService._fraud_candidates()
    assert candidates["random_forest"].class_weight is None
    assert candidates["random_forest_balanced"].class_weight == "balanced"
    assert candidates["random_forest_balanced_subsample"].class_weight == "balanced_subsample"
    assert candidates["histogram_boosting_balanced"].class_weight == "balanced"
    assert "prior_baseline" in candidates


def test_expansion_keeps_labels_and_excludes_future_policies_and_duplicate_ids():
    module = runpy.run_path(str(Path(__file__).parents[1] / "scripts/improve_fraud_model.py"))
    base_row = {
        "claim_id": "old", "policy_id": "p-old", "claim_type": "auto", "state": "TX",
        "incident_date": "2023-01-01", "claim_filed_date": "2023-01-02",
        "policyholder_tenure_years": 2.0, "previous_claims_count": 0,
        "deductible": 500.0, "claim_amount": 8000.0, "claim_status": "approved",
        "days_to_resolution": 10.0, "is_fraud_flagged_ground_truth": False,
    }
    calibration = [{**base_row, "claim_id": "cal", "policy_id": "p-cal"}]
    test = [{**base_row, "claim_id": "test", "policy_id": "p-test"}]
    additional = [
        dict(base_row),
        {**base_row, "claim_id": "policy-conflict", "policy_id": "p-test"},
        {**base_row, "claim_id": "future", "claim_filed_date": "2025-01-01"},
        {**base_row, "claim_id": "valid", "policy_id": "p-valid",
         "is_fraud_flagged_ground_truth": True},
        {**base_row, "claim_id": "invalid-label", "is_fraud_flagged_ground_truth": "true"},
    ]
    expanded, excluded = module["expand_training"](
        [base_row], additional, calibration, test, "2024-05-13"
    )
    assert {r["claim_id"] for r in expanded} == {"old", "valid"}
    assert expanded[-1]["is_fraud_flagged_ground_truth"] is True
    assert excluded == {"duplicate": 1, "policy_overlap": 1, "future": 1, "invalid": 1}
    groups = [expanded, calibration, test]
    for first, second in itertools.combinations(groups, 2):
        assert not {r["policy_id"] for r in first} & {r["policy_id"] for r in second}


def test_parquet_export_round_trips_original_records(tmp_path):
    import duckdb

    module = runpy.run_path(str(Path(__file__).parents[1] / "scripts/improve_fraud_model.py"))
    path = tmp_path / "expanded.parquet"
    module["export_training"]([{"claim_id": "C1", "is_fraud_flagged_ground_truth": True}], path)
    with duckdb.connect() as connection:
        rows = connection.execute("SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
    assert rows == [("C1", True)]
    assert not list(tmp_path.glob("*.tmp"))
