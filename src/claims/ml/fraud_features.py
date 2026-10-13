"""Training-only fraud feature statistics and independently verifiable cohorts."""

import hashlib
import json
from pathlib import Path

import numpy as np
from sklearn.feature_extraction import DictVectorizer

from claims.history.dataset import COLUMNS, ClaimsStore
from claims.ml.analytics import FEATURES

RATIO_FEATURES = ("amount_to_deductible", "amount_to_type_median")


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows_digest(rows):
    return hashlib.sha256(
        json.dumps(
            sorted(rows, key=lambda r: r["claim_id"]),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


class FraudFeatureEncoder:
    """Derive ratios without labels; recompute them for every inference/ablation.

    Inputs stay within the established pre-outcome feature contract. CatBoost
    receives original category strings; sklearn models receive one-hot columns.
    """

    def __init__(self, *, ratios=True, native_categorical=False):
        self.ratios = ratios
        self.native_categorical = native_categorical

    def fit(self, features):
        self._validate(features)
        amounts = np.array([row["claim_amount"] for row in features], dtype=float)
        self.global_median_ = float(np.median(amounts))
        self.type_medians_ = {
            kind: float(np.median([r["claim_amount"] for r in features if r["claim_type"] == kind]))
            for kind in sorted({r["claim_type"] for r in features})
        }
        self.numeric_names_ = [k for k in FEATURES["fraud"] if k not in {"claim_type", "state"}]
        if self.ratios:
            self.numeric_names_ += list(RATIO_FEATURES)
        if not self.native_categorical:
            self.vectorizer_ = DictVectorizer(sparse=False).fit(self._derive(features))
        return self

    @staticmethod
    def _validate(features):
        if not len(features):
            raise ValueError("At least one valid feature row is required")
        for row in features:
            if any(key not in row for key in FEATURES["fraud"]):
                raise ValueError("Missing pre-outcome fraud input")
            for key in FEATURES["fraud"]:
                if key in {"claim_type", "state"}:
                    if not isinstance(row[key], str) or not row[key]:
                        raise ValueError("Nonempty categorical fraud inputs are required")
                elif not np.isfinite(float(row[key])) or float(row[key]) < 0:
                    raise ValueError("Finite nonnegative numeric fraud inputs are required")

    def _derive(self, features):
        self._validate(features)
        output = []
        for row in features:
            # Ignore every non-feature field, including identifiers and outcome labels.
            derived = {key: row[key] for key in FEATURES["fraud"]}
            if self.ratios:
                derived["amount_to_deductible"] = row["claim_amount"] / max(row["deductible"], 1.0)
                median = self.type_medians_.get(row["claim_type"], self.global_median_)
                derived["amount_to_type_median"] = row["claim_amount"] / max(median, 1.0)
            output.append(derived)
        return output

    def transform(self, features):
        derived = self._derive(features)
        if self.native_categorical:
            return np.array(
                [
                    [row["claim_type"], row["state"]]
                    + [float(row[key]) for key in self.numeric_names_]
                    for row in derived
                ],
                dtype=object,
            )
        return self.vectorizer_.transform(derived)

    def get_feature_names_out(self):
        if self.native_categorical:
            return np.array(["claim_type", "state"] + self.numeric_names_)
        return self.vectorizer_.get_feature_names_out()


class FraudProbabilityEnsemble:
    """Average two fixed seeds before independent sigmoid calibration."""

    def __init__(self, models):
        if not models:
            raise ValueError("At least one fraud estimator is required")
        self.models = models

    def predict_proba(self, x):
        predictions = [fraud_estimator_probabilities(model, x) for model in self.models]
        if any(
            p.shape != (len(x), 2)
            or not np.isfinite(p).all()
            or np.any((p < 0) | (p > 1))
            or not np.allclose(p.sum(axis=1), 1)
            for p in predictions
        ):
            raise ValueError("Fraud estimator returned invalid class probabilities")
        return np.mean(predictions, axis=0)


def fraud_estimator_probabilities(model, x):
    """Keep native CatBoost prediction bounded, including explanation requests."""
    kwargs = {"thread_count": 2} if type(model).__module__.startswith("catboost") else {}
    return np.asarray(model.predict_proba(x, **kwargs), dtype=float)


def load_source_evaluation_rows(service, evaluation):
    """Verify a frozen new holdout against original source rows, not stored scores."""
    path = Path(evaluation["path"])
    if file_digest(path) != evaluation["parquet_sha256"]:
        raise ValueError("Fraud evaluation Parquet digest differs from frozen cohort")
    snapshot = ClaimsStore(path, memory_limit="512MB", threads=1)
    try:
        snapshot.connection.execute("SET enable_progress_bar=false")
        expected = snapshot.rows(f"SELECT {', '.join(COLUMNS)} FROM {snapshot.source}")
    finally:
        snapshot.close()
    if not expected:
        raise ValueError("Fraud evaluation cohort is empty")
    if len(expected) != len({r["claim_id"] for r in expected}):
        raise ValueError("Fraud evaluation contains duplicate claim IDs")
    source = ClaimsStore(service.parquet_path, memory_limit="1GB", threads=1)
    try:
        source.connection.execute("SET enable_progress_bar=false")
        source.connection.execute("CREATE TEMP TABLE evaluation_ids (claim_id VARCHAR PRIMARY KEY)")
        source.connection.executemany(
            "INSERT INTO evaluation_ids VALUES (?)", [(r["claim_id"],) for r in expected]
        )
        columns = ", ".join(f"claims.{key}" for key in COLUMNS)
        actual = source.rows(
            f"SELECT {columns} FROM {source.source} AS claims JOIN evaluation_ids USING (claim_id)"
        )
    finally:
        source.close()
    if (
        rows_digest(actual) != rows_digest(expected)
        or rows_digest(actual) != evaluation["rows_sha256"]
    ):
        raise ValueError("Fraud evaluation claims or labels differ from original source")
    return sorted(actual, key=lambda r: (r["claim_filed_date"], r["claim_id"]))
