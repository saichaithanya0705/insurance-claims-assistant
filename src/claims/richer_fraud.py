"""Retrospective source-specific fraud benchmarks; never activates production models."""

import numpy as np
from catboost import CatBoostClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss

from claims.analytics import fraud_classification_metrics, fraud_operating_points, fraud_scores
from claims.fraud_features import FraudProbabilityEnsemble, fraud_estimator_probabilities
from claims.richer_data import (
    ASSESSMENT_CATEGORICAL,
    BASE_CATEGORICAL,
    BASE_NUMERIC,
    INCIDENT_CATEGORICAL,
    INCIDENT_NUMERIC,
)

SEEDS = (42, 73)
CONFIGURATIONS = (
    "base_forest",
    "base_catboost",
    "incident_forest",
    "incident_catboost",
    "assessment_forest",
    "assessment_catboost",
)
ROLE_NAMES = ("training", "selection", "probability", "threshold", "test")


def temporal_cohorts(rows):
    date_field = (
        "claim_filed_date" if all(r.get("claim_filed_date") for r in rows) else "incident_date"
    )
    dates = sorted({r[date_field] for r in rows})
    if len(dates) < 20:
        raise ValueError("At least 20 incident dates are required for five separate cohorts")
    cutoffs = [dates[int(len(dates) * fraction)] for fraction in (0.5, 0.6, 0.7, 0.8)]
    groups = [[] for _ in ROLE_NAMES]
    for row in rows:
        groups[sum(row[date_field] >= cutoff for cutoff in cutoffs)].append(row)
    later_policies = set()
    purged = 0
    immature = 0
    for index in range(4, -1, -1):
        retained = [r for r in groups[index] if r["policy_id"] not in later_policies]
        purged += len(groups[index]) - len(retained)
        if index < 4 and date_field == "claim_filed_date":
            mature = [
                r
                for r in retained
                if r.get("label_observed_at") and r["label_observed_at"][:10] < cutoffs[index]
            ]
            immature += len(retained) - len(mature)
            retained = mature
        groups[index] = sorted(retained, key=lambda r: (r[date_field], r["claim_id"]))
        later_policies.update(r["policy_id"] for r in retained)
        if (
            len(retained) < 30
            or min(sum(r["is_fraud"] for r in retained), sum(not r["is_fraud"] for r in retained))
            < 5
        ):
            raise ValueError(f"Insufficient independent labels in {ROLE_NAMES[index]} cohort")
    return groups, {
        "date_field": date_field,
        "incident_date_cutoffs": cutoffs,
        "policy_rows_purged": purged,
        "immature_label_rows_purged": immature,
        "strategy": (
            "Filing-date cohorts; labels observed before next cohort boundary"
            if date_field == "claim_filed_date"
            else "Retrospective incident-date ordering; filing/label observation dates unavailable"
        ),
    }


class RichFeatureEncoder:
    """Explicit allowlists, training-only imputation and preserved missing indicators."""

    def __init__(self, group, *, native=False):
        if group not in {"base", "incident", "assessment"}:
            raise ValueError("Unknown source feature group")
        self.group, self.native = group, native
        self.numeric = list(BASE_NUMERIC) + (list(INCIDENT_NUMERIC) if group != "base" else [])
        self.categorical = list(BASE_CATEGORICAL) + (
            list(INCIDENT_CATEGORICAL) if group != "base" else []
        )
        if group == "assessment":
            self.categorical += list(ASSESSMENT_CATEGORICAL)

    def fit(self, rows):
        if not rows:
            raise ValueError("Training rows required")
        self.medians = {}
        for key in self.numeric:
            values = [float(r[key]) for r in rows if r.get(key) is not None]
            if not values or not np.isfinite(values).all():
                raise ValueError(f"Training feature {key} has no valid observations")
            self.medians[key] = float(np.median(values))
        if not self.native:
            self.vectorizer = DictVectorizer(sparse=False).fit(self._features(rows))
        return self

    def _features(self, rows):
        features = []
        for row in rows:
            result = {}
            for key in self.categorical:
                value = row.get(key)
                if value is not None and (not isinstance(value, str) or not value):
                    raise ValueError(f"Invalid category {key}")
                result[key] = "__missing__" if value is None else value
            for key in self.numeric:
                value = row.get(key)
                result[f"{key}_missing"] = int(value is None)
                result[key] = self.medians[key] if value is None else float(value)
                if not np.isfinite(result[key]) or result[key] < 0:
                    raise ValueError(f"Invalid numeric feature {key}")
            features.append(result)
        return features

    def transform(self, rows):
        features = self._features(rows)
        if not self.native:
            return self.vectorizer.transform(features)
        numeric = self.numeric + [f"{key}_missing" for key in self.numeric]
        return np.array(
            [[f[k] for k in self.categorical + numeric] for f in features], dtype=object
        )


def new_estimator(configuration, seed, *, iterations=200):
    if configuration.endswith("forest"):
        return RandomForestClassifier(
            n_estimators=120, max_depth=6, min_samples_leaf=5, random_state=seed, n_jobs=2
        )
    group = configuration.split("_")[0]
    encoder = RichFeatureEncoder(group, native=True)
    return CatBoostClassifier(
        iterations=iterations,
        depth=4,
        learning_rate=0.05,
        loss_function="Logloss",
        random_seed=seed,
        thread_count=2,
        has_time=True,
        allow_writing_files=False,
        verbose=False,
        cat_features=list(range(len(encoder.categorical))),
    )


def fit_models(configuration, rows, *, fixed_iterations=None):
    encoder = RichFeatureEncoder(
        configuration.split("_")[0], native=configuration.endswith("catboost")
    )
    y = np.array([r["is_fraud"] for r in rows])
    iterations = []
    if fixed_iterations is None and encoder.native:
        boundary = int(len(rows) * 0.9)
        # Keep same-day records together in the early-stop temporal tail.
        date_field = (
            "claim_filed_date" if all(r.get("claim_filed_date") for r in rows) else "incident_date"
        )
        tail_date = rows[boundary][date_field]
        boundary = next(i for i, r in enumerate(rows) if r[date_field] == tail_date)
        encoder.fit(rows[:boundary])
        x = encoder.transform(rows)
        for seed in SEEDS:
            model = new_estimator(configuration, seed)
            model.fit(
                x[:boundary],
                y[:boundary],
                eval_set=(x[boundary:], y[boundary:]),
                early_stopping_rounds=25,
                verbose=False,
            )
            iterations.append(max(1, model.tree_count_))
    else:
        iterations = fixed_iterations or [120] * len(SEEDS)
    encoder.fit(rows)
    x = encoder.transform(rows)
    models = []
    for seed, count in zip(SEEDS, iterations):
        model = new_estimator(configuration, seed, iterations=count)
        model.fit(x, y)
        if hasattr(model, "n_jobs"):
            model.set_params(n_jobs=1)
        models.append(model)
    return {
        "model": FraudProbabilityEnsemble(models),
        "vectorizer": encoder,
        "configuration": configuration,
        "iterations": iterations,
    }


def raw_validation(trained, rows):
    x = trained["vectorizer"].transform(rows)
    y = np.array([r["is_fraud"] for r in rows])
    p = trained["model"].predict_proba(x)[:, 1]
    point = fraud_operating_points(y, p)["precision_at_least_50pct"]
    return {
        "average_precision": float(average_precision_score(y, p)),
        "recall_at_50pct_precision": point["recall"] if point else 0,
        "per_seed_average_precision": [
            float(average_precision_score(y, fraud_estimator_probabilities(m, x)[:, 1]))
            for m in trained["model"].models
        ],
    }


def choose_configurations(results):
    rank = lambda result: (
        result["validation"]["average_precision"],
        result["validation"]["recall_at_50pct_precision"],
    )
    base = max((r for r in results if r["configuration"].startswith("base_")), key=rank)
    incident = max((r for r in results if r["configuration"].startswith("incident_")), key=rank)
    assessment = max((r for r in results if r["configuration"].startswith("assessment_")), key=rank)
    return {"base": base, "incident": incident, "assessment": assessment}


def calibrate(trained, probability_rows, threshold_rows):
    x = trained["vectorizer"].transform(probability_rows)
    y = np.array([r["is_fraud"] for r in probability_rows])
    p = np.clip(trained["model"].predict_proba(x)[:, 1], 1e-8, 1 - 1e-8)
    sigmoid = LogisticRegression(C=1, random_state=42).fit(np.log(p / (1 - p)).reshape(-1, 1), y)
    # Calibration must not flip an uninformative or negatively ranked learner.
    if sigmoid.coef_[0, 0] > 0:
        trained.update(sigmoid=sigmoid, sigmoid_input="log_odds")
        trained["calibration_status"] = "positive-slope log-odds sigmoid"
    else:
        trained["calibration_status"] = "nonpositive sigmoid slope; retained uncalibrated scores"
    ty = np.array([r["is_fraud"] for r in threshold_rows])
    tx = trained["vectorizer"].transform(threshold_rows)
    points = fraud_operating_points(ty, fraud_scores(trained, tx))
    floor = points["precision_at_least_50pct"]
    trained["threshold"] = (floor or points["max_f1"])["threshold"]
    trained["threshold_policy"] = (
        "recall at >=50% tuning precision"
        if floor
        else "infeasible precision floor; maximum F1 fallback"
    )
    trained["threshold_cohort_metrics"] = floor or points["max_f1"]
    return trained


def measure(trained, rows):
    x = trained["vectorizer"].transform(rows)
    y = np.array([r["is_fraud"] for r in rows])
    p = fraud_scores(trained, x)
    return {
        **fraud_classification_metrics(y, p, trained["threshold"]),
        "average_precision": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
    }
