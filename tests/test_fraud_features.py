import copy
import itertools
import runpy
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pytest

from claims.ml.analytics import feature_dict
from claims.ml.fraud_features import (
    FraudFeatureEncoder,
    FraudProbabilityEnsemble,
    file_digest,
    load_source_evaluation_rows,
    rows_digest,
)


@pytest.fixture
def experiment():
    return runpy.run_path(str(Path(__file__).parents[1] / "scripts/experiment_fraud_features.py"))


@pytest.fixture
def row():
    return {
        "claim_id": "C1",
        "policy_id": "P1",
        "claim_type": "auto",
        "state": "TX",
        "incident_date": "2024-05-01",
        "claim_filed_date": "2024-06-01",
        "policyholder_tenure_years": 2.0,
        "previous_claims_count": 0,
        "deductible": 500.0,
        "claim_amount": 8000.0,
        "claim_status": "approved",
        "days_to_resolution": 10.0,
        "is_fraud_flagged_ground_truth": False,
    }


@pytest.mark.parametrize("native", [False, True])
def test_ratios_use_training_statistics_ignore_outcomes_and_recompute(native, row):
    features = [feature_dict(row, "fraud"), feature_dict({**row, "claim_amount": 12000}, "fraud")]
    encoder = FraudFeatureEncoder(native_categorical=native).fit(features)
    future = {
        **features[0],
        "claim_amount": 100000,
        "deductible": 0,
        "claim_id": "unseen",
        "claim_status": "denied",
        "is_fraud_flagged_ground_truth": True,
    }
    transformed = encoder.transform([future])
    names = list(encoder.get_feature_names_out())
    assert float(transformed[0, names.index("amount_to_type_median")]) == 10
    assert float(transformed[0, names.index("amount_to_deductible")]) == 100000
    assert encoder.type_medians_ == {"auto": 10000}
    changed_outcome = {**future, "is_fraud_flagged_ground_truth": False, "claim_status": "approved"}
    np.testing.assert_array_equal(transformed, encoder.transform([changed_outcome]))
    future["claim_amount"] = 50000
    assert float(encoder.transform([future])[0, names.index("amount_to_type_median")]) == 5
    future["claim_type"] = "unseen"
    assert float(encoder.transform([future])[0, names.index("amount_to_type_median")]) == 5


def test_encoder_rejects_missing_and_nonfinite_inputs(row):
    feature = feature_dict(row, "fraud")
    for invalid in ({**feature, "claim_amount": float("nan")}, {**feature, "deductible": -1}, {}):
        with pytest.raises(ValueError):
            FraudFeatureEncoder().fit([invalid])


def test_new_cohorts_exclude_prior_policies_and_are_disjoint(experiment, row):
    dates = ["2024-06-01", "2024-10-01", "2025-01-01", "2025-04-01", "2025-08-01"]
    rows = [
        {**row, "claim_id": str(i), "policy_id": str(i), "claim_filed_date": date}
        for i, date in enumerate(dates)
    ]
    rows += [
        {**row, "claim_id": "repeated", "policy_id": "4"},
        {**row, "claim_id": "prior", "policy_id": "prior"},
        {**row, "claim_id": "bad-label", "is_fraud_flagged_ground_truth": "true"},
    ]
    groups, excluded = experiment["fresh_cohorts"](rows, {"prior"})
    assert [len(group) for group in groups] == [1] * 5
    assert excluded["prior_policy"] == 1
    assert excluded["invalid_or_duplicate"] == 1
    assert excluded["earlier_repeated_policy"] == 1
    for first, second in itertools.combinations(groups, 2):
        assert not {r["policy_id"] for r in first} & {r["policy_id"] for r in second}


def test_promotion_requires_meaningful_validation_gain_on_both_dates(experiment):
    keys = ("average_precision", "recall_at_50pct_precision", "recall_at_10pct_review")

    def result(name, values, folds):
        return {
            "configuration": name,
            "mean": dict(zip(keys, values)),
            "folds": [{"average_precision": value} for value in folds],
        }

    baseline = result("forest_raw", (0.30, 0.30, 0.40), (0.30, 0.30))
    tiny = result("forest_ratios", (0.305, 0.305, 0.40), (0.305, 0.305))
    worse_fold = result("catboost_raw", (0.33, 0.35, 0.42), (0.29, 0.37))
    winner, eligible = experiment["validation_decision"]([baseline, tiny, worse_fold])
    assert not eligible
    improved = result("catboost_ratios", (0.32, 0.33, 0.41), (0.31, 0.33))
    winner, eligible = experiment["validation_decision"]([baseline, tiny, improved])
    assert eligible and winner["configuration"] == "catboost_ratios"


@pytest.mark.parametrize(
    "probabilities", [[[float("nan"), 0.2]], [[0.2, 0.9]], [[-0.1, 1.1]], [[1]]]
)
def test_ensemble_rejects_malformed_probabilities(probabilities):
    class InvalidEstimator:
        def predict_proba(self, x):
            return np.array(probabilities)

    with pytest.raises(ValueError):
        FraudProbabilityEnsemble([InvalidEstimator()]).predict_proba([[0]])


def test_native_catboost_encoder_and_ensemble_survive_artifact_reload(experiment, row, tmp_path):
    rows = [
        {**row, "claim_amount": 1000 + i * 100, "state": "TX" if i % 2 else "CA"} for i in range(80)
    ]
    encoder = FraudFeatureEncoder(native_categorical=True).fit(
        [feature_dict(r, "fraud") for r in rows]
    )
    x = encoder.transform([feature_dict(r, "fraud") for r in rows])
    model = experiment["estimator"]("catboost_ratios", 42, iterations=5)
    model.fit(x, np.array([i % 3 == 0 for i in range(80)]))
    bundle = {"vectorizer": encoder, "model": FraudProbabilityEnsemble([model])}
    path = tmp_path / "model.joblib"
    joblib.dump(bundle, path)
    restored = joblib.load(path)
    np.testing.assert_allclose(bundle["model"].predict_proba(x), restored["model"].predict_proba(x))


def test_frozen_holdout_detects_label_changes_even_with_valid_file_hash(experiment, row, tmp_path):
    export = experiment["export_training"]
    original = tmp_path / "source.parquet"
    holdout = tmp_path / "holdout.parquet"
    export([row], original)
    export([row], holdout)
    metadata = {
        "path": str(holdout),
        "parquet_sha256": file_digest(holdout),
        "rows_sha256": rows_digest([row]),
    }
    service = SimpleNamespace(parquet_path=original)
    assert load_source_evaluation_rows(service, metadata) == [row]
    altered = copy.deepcopy(row)
    altered["is_fraud_flagged_ground_truth"] = True
    export([altered], holdout)
    metadata.update(parquet_sha256=file_digest(holdout), rows_sha256=rows_digest([altered]))
    with pytest.raises(ValueError, match="original source"):
        load_source_evaluation_rows(service, metadata)
