"""Reproducible, leakage-controlled educational statistical models.

Artifacts are locally generated trusted joblib files; never load untrusted files.
"""

import hashlib
import json
import math
import warnings
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
from sklearn import config_context
from sklearn.base import BaseEstimator, RegressorMixin
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    f1_score,
    get_scorer,
    mean_absolute_error,
    precision_recall_curve,
    precision_score,
    recall_score,
)
from threadpoolctl import threadpool_limits

from claims.core.schemas import ClaimInput
from claims.history.dataset import ClaimsStore

# scikit-learn emits one benign threading notice per forest prediction made from a thread pool.
warnings.filterwarnings("ignore", message=r".*sklearn\.utils\.parallel\.delayed.*")

BASE_FEATURES = (
    "claim_type",
    "state",
    "policyholder_tenure_years",
    "previous_claims_count",
    "deductible",
    "filing_delay_days",
    "incident_month",
)
FEATURES = {
    "amount": BASE_FEATURES,
    "resolution": BASE_FEATURES + ("claim_amount",),
    "fraud": BASE_FEATURES + ("claim_amount",),
}


class ClaimTypeMedianRegressor(RegressorMixin, BaseEstimator):
    """Small deterministic fallback that estimates amount by claim type."""

    def __init__(self, claim_type_indices):
        self.claim_type_indices = dict(claim_type_indices)

    def fit(self, x, y):
        self.global_median_ = float(np.median(y))
        self.medians_ = {
            key: float(np.median(y[np.asarray(x[:, index]).astype(bool)]))
            for key, index in self.claim_type_indices.items()
            if np.asarray(x[:, index]).astype(bool).any()
        }
        return self

    def predict(self, x):
        categories = np.full(x.shape[0], None, dtype=object)
        for key, index in self.claim_type_indices.items():
            categories[np.asarray(x[:, index]).astype(bool)] = key
        return np.array([self.medians_.get(category, self.global_median_) for category in categories])
TARGETS = {
    "amount": "claim_amount",
    "resolution": "days_to_resolution",
    "fraud": "is_fraud_flagged_ground_truth",
}
LIMITATIONS = [
    "Educational model trained on synthetic US claims, not validated on real insurance claims.",
    "A bounded random sample of synthetic claims does not establish real-world representativeness.",
    "Amount estimates the submitted historical claim amount, not settlement or entitlement.",
    "Resolution estimates apply only to resolved approved/denied claims; censoring is not modeled.",
    "Fraud score estimates the synthetic dataset flag, not proven fraud or a decision to deny.",
    "Fraud-label observation timestamps are unavailable; point-in-time fraud label validity is unverified.",
    "Empirical intervals have no guaranteed coverage under temporal or real-world distribution shift.",
    "Global feature associations are not explanations of an individual claim and are not causal.",
]


def feature_dict(row: dict, task: str) -> dict:
    incident = date.fromisoformat(str(row["incident_date"])[:10])
    filed = date.fromisoformat(str(row["claim_filed_date"])[:10])
    values = {
        "claim_type": str(row["claim_type"]),
        "state": str(row["state"]),
        "policyholder_tenure_years": float(row["policyholder_tenure_years"]),
        "previous_claims_count": int(row["previous_claims_count"]),
        "deductible": float(row["deductible"]),
        "filing_delay_days": (filed - incident).days,
        "incident_month": incident.month,
    }
    if task != "amount":
        values["claim_amount"] = float(row["claim_amount"])
    return {key: values[key] for key in FEATURES[task]}


def temporal_split(rows: list[dict]) -> tuple[list[list[dict]], dict]:
    """Same-date cohorts stay together; older partitions lose overlapping policies."""
    ordered = sorted(rows, key=lambda r: (r["claim_filed_date"], r["claim_id"]))
    cutoff1 = ordered[int(len(ordered) * 0.6)]["claim_filed_date"]
    cutoff2 = ordered[int(len(ordered) * 0.8)]["claim_filed_date"]
    train = [r for r in ordered if r["claim_filed_date"] < cutoff1]
    calibration = [r for r in ordered if cutoff1 <= r["claim_filed_date"] < cutoff2]
    test = [r for r in ordered if r["claim_filed_date"] >= cutoff2]
    test_policies = {r["policy_id"] for r in test}
    calibration = [r for r in calibration if r["policy_id"] not in test_policies]
    later_policies = test_policies | {r["policy_id"] for r in calibration}
    train = [r for r in train if r["policy_id"] not in later_policies]
    partitions = [train, calibration, test]
    return partitions, {
        "strategy": "60/20/20 filing-date cohorts, repeated policies removed from earlier partitions",
        "calibration_start": cutoff1,
        "test_start": cutoff2,
        "counts": dict(zip(("train", "calibration", "test"), map(len, partitions))),
        "policy_overlap": 0,
    }


def calibration_roles(rows: list[dict]) -> tuple[list[list[dict]], list[str]]:
    """Keep tuning, uncertainty calibration and threshold labels in distinct date cohorts."""
    ordered = sorted(rows, key=lambda r: (r["claim_filed_date"], r["claim_id"]))
    first = ordered[len(ordered) // 2]["claim_filed_date"]
    second = ordered[len(ordered) * 3 // 4]["claim_filed_date"]
    groups = [
        [r for r in ordered if r["claim_filed_date"] < first],
        [r for r in ordered if first <= r["claim_filed_date"] < second],
        [r for r in ordered if r["claim_filed_date"] >= second],
    ]
    later = set()
    for i in (2, 1, 0):
        groups[i] = [r for r in groups[i] if r["policy_id"] not in later]
        later.update(r["policy_id"] for r in groups[i])
    return groups, [first, second]


TASK_NOUN = {
    "amount": "claim amount (USD)",
    "resolution": "days to resolution",
    "fraud": "fraud-flag score",
}
FEATURE_LABEL = {
    "claim_type": "claim type",
    "state": "state",
    "policyholder_tenure_years": "policyholder tenure",
    "previous_claims_count": "previous claims",
    "deductible": "deductible",
    "filing_delay_days": "filing delay",
    "incident_month": "incident month",
    "claim_amount": "claimed amount",
}


def fraud_scores(trained: dict, x) -> np.ndarray:
    """New artifacts calibrate log odds; old probability-input artifacts remain loadable."""
    raw = trained["model"].predict_proba(x)[:, 1]
    if trained.get("sigmoid") is None:
        return raw
    if trained.get("sigmoid_input") == "log_odds":
        raw = np.clip(raw, 1e-8, 1 - 1e-8)
        raw = np.log(raw / (1 - raw))
    return trained["sigmoid"].predict_proba(raw.reshape(-1, 1))[:, 1]


def fraud_classification_metrics(labels, scores, threshold: float) -> dict:
    """Keep review usefulness and workload separate from probability quality."""
    predicted = np.asarray(scores) >= threshold
    labels = np.asarray(labels, dtype=bool)
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "f1": float(f1_score(labels, predicted, zero_division=0)),
        "accuracy": float(accuracy_score(labels, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(labels, predicted)),
        "review_fraction": float(np.mean(predicted)),
        "review_count": int(predicted.sum()),
        "true_positives": int(np.sum(labels & predicted)),
        "false_positives": int(np.sum(~labels & predicted)),
        "false_negatives": int(np.sum(labels & ~predicted)),
        "true_negatives": int(np.sum(~labels & ~predicted)),
    }


def fraud_operating_points(labels, scores) -> dict:
    """Choose thresholds only from a separate naturally imbalanced tuning cohort.

    Precision floors and workload caps are tuning-cohort estimates, not promises
    about unseen data. The terminal no-review point has no score threshold and is
    excluded, including when no threshold meets a precision constraint.
    """
    labels, scores = np.asarray(labels), np.asarray(scores, dtype=float)
    if (
        labels.ndim != 1 or scores.shape != labels.shape or not len(labels)
        or not np.isin(labels, [0, 1]).all() or len(np.unique(labels)) != 2
        or not np.isfinite(scores).all() or np.any((scores < 0) | (scores > 1))
    ):
        raise ValueError("Binary labels and finite probabilities for both classes are required")
    precision, recall, thresholds = precision_recall_curve(labels, scores)
    precision, recall = precision[:-1], recall[:-1]
    f1 = np.divide(2 * precision * recall, precision + recall,
                   out=np.zeros_like(precision), where=(precision + recall) > 0)
    sorted_scores = np.sort(scores)
    workload = (len(scores) - np.searchsorted(sorted_scores, thresholds, side="left")) / len(scores)

    def point(index):
        return fraud_classification_metrics(labels, scores, float(thresholds[index]))

    points = {"max_f1": point(int(np.argmax(f1)))}
    for floor in (0.5, 0.7):
        eligible = np.flatnonzero((precision >= floor) & (recall > 0))
        best = max(eligible, key=lambda i: (recall[i], precision[i])) if len(eligible) else None
        points[f"precision_at_least_{int(floor * 100)}pct"] = (
            point(int(best)) if best is not None else None
        )
    for cap in (0.05, 0.10):
        eligible = np.flatnonzero(workload <= cap)
        best = max(eligible, key=lambda i: (recall[i], precision[i])) if len(eligible) else None
        points[f"review_at_most_{int(cap * 100)}pct"] = (
            point(int(best)) if best is not None else None
        )
    return points


def predict_function(task: str, trained: dict):
    if task == "fraud":
        return lambda x: fraud_scores(trained, x)
    return lambda x: trained["model"].predict(x)


def _effects(task: str, trained: dict, train_feats: list, cal_feats: list, rng) -> list[dict]:
    """Direction of each feature's effect via partial dependence on a calibration subsample."""
    predict = predict_function(task, trained)
    vectorizer = trained["vectorizer"]
    if len(cal_feats) > 2000:
        cal_feats = [cal_feats[i] for i in rng.choice(len(cal_feats), 2000, replace=False)]
    base = float(np.mean(predict(vectorizer.transform(cal_feats))))
    curves = {}
    for key in FEATURES[task]:
        if key in ("claim_type", "state"):
            values = sorted({f[key] for f in train_feats})
        else:
            column = np.array([f[key] for f in train_feats], dtype=float)
            unique = np.unique(column)
            values = (
                [float(v) for v in unique]
                if len(unique) <= 12
                else sorted({float(np.quantile(column, q)) for q in (0.1, 0.3, 0.5, 0.7, 0.9)})
            )
        curves[key] = (
            values,
            [
                float(np.mean(predict(vectorizer.transform([{**f, key: v} for f in cal_feats]))))
                for v in values
            ],
        )
    spreads = {key: max(means) - min(means) for key, (_, means) in curves.items()}
    strongest = max(spreads.values())
    effects = []
    for key, (values, means) in curves.items():
        spread = spreads[key]
        # An effect is reported only if it is material next to the model's strongest feature
        # and to the overall level of the prediction; synthetic noise is otherwise listed as signal.
        little = spread < 0.10 * strongest or spread < 0.01 * max(abs(base), 1e-9)
        if key in ("claim_type", "state"):
            order = [int(i) for i in np.argsort(means)]
            # Up to three highest then three lowest categories, without repeats.
            shown = list(dict.fromkeys(order[::-1][:3] + order[:3]))
            points = [{"value": values[i], "mean_prediction": round(means[i], 4)} for i in shown]
            extremes = {
                "highest": {
                    "value": values[order[-1]],
                    "mean_prediction": round(means[order[-1]], 4),
                },
                "lowest": {"value": values[order[0]], "mean_prediction": round(means[order[0]], 4)},
            }
            direction = "little_effect" if little else "varies_by_category"
            kind = "categorical"
        else:
            tolerance = 0.15 * spread
            diffs = np.diff(means)
            if little:
                direction = "little_effect"
            elif means[-1] > means[0] and all(d >= -tolerance for d in diffs):
                direction = "higher_values_increase"
            elif means[-1] < means[0] and all(d <= tolerance for d in diffs):
                direction = "higher_values_decrease"
            else:
                direction = "non_monotonic"
            points = [
                {"value": round(v, 2), "mean_prediction": round(m, 4)}
                for v, m in zip(values, means)
            ]
            kind = "numeric"
            extremes = {}
        effects.append(
            {
                "feature": key,
                "kind": kind,
                "direction": direction,
                "spread": round(spread, 4),
                "points": points,
                **extremes,
            }
        )
    return effects


def _summarize(task: str, effects: list, importance_order: list) -> list[str]:
    """Plain-language findings, most important feature first; associations only."""
    by_key = {e["feature"]: e for e in effects}
    unit = {"amount": "USD", "resolution": "days", "fraud": "score"}[task]
    lines = []
    for key in importance_order:
        effect = by_key[key]
        label = FEATURE_LABEL[key]
        pts = effect["points"]
        if effect["direction"] == "little_effect":
            continue
        if effect["kind"] == "categorical":
            lines.append(
                f"{label}: highest predicted {TASK_NOUN[task]} for {effect['highest']['value']} "
                f"({effect['highest']['mean_prediction']:,.2f} {unit}), lowest for "
                f"{effect['lowest']['value']} ({effect['lowest']['mean_prediction']:,.2f} {unit})."
            )
        elif effect["direction"] == "non_monotonic":
            peak = max(pts, key=lambda p: p["mean_prediction"])
            lines.append(
                f"{label}: no steady direction; predicted {TASK_NOUN[task]} peaks near "
                f"{peak['value']:g} ({peak['mean_prediction']:,.2f} {unit})."
            )
        else:
            word = "higher" if effect["direction"] == "higher_values_increase" else "lower"
            lines.append(
                f"{label}: larger values go with {word} predicted {TASK_NOUN[task]} "
                f"({pts[0]['mean_prediction']:,.2f} to {pts[-1]['mean_prediction']:,.2f} {unit} "
                f"from {pts[0]['value']:g} to {pts[-1]['value']:g})."
            )
        if len(lines) == 5:
            break
    return lines


class AnalyticsService:
    def __init__(
        self,
        data_path: Path,
        artifact_dir: Path,
        parquet_path: Path | None = None,
        train_rows: int = 200_000,
        memory_limit: str = "3GB",
    ):
        self.data_path, self.artifact_dir = Path(data_path), Path(artifact_dir)
        self.parquet_path = Path(parquet_path) if parquet_path else None
        self.train_rows, self.memory_limit = train_rows, memory_limit
        self._bundle = None
        self._load_error = None
        artifact = self.artifact_dir / "claims_models.joblib"
        if artifact.exists():
            try:
                self._bundle = joblib.load(artifact)
                if self._bundle.get("schema_version") != 1:
                    self._bundle = None
                    self._load_error = "Unsupported model artifact schema"
            except (OSError, ValueError, EOFError, KeyError):
                self._load_error = "Local model artifact could not be loaded; retrain it"

    def _has_parquet(self) -> bool:
        return bool(self.parquet_path and self.parquet_path.is_file())

    def status(self) -> dict:
        if self._bundle is None:
            return {
                "available": False,
                "reason": self._load_error or "Models have not been trained",
                "data_present": self._has_parquet() or self.data_path.exists(),
                "limitations": LIMITATIONS,
            }
        return {"available": bool(self._bundle["models"]), **self._bundle["report"]}

    def _read_rows(self) -> tuple[list[dict], dict]:
        if self._has_parquet():
            # Parallel reservoir sampling can select different rows despite REPEATABLE(seed).
            # A single scanner makes the saved holdout reconstructible across independent runs.
            store = ClaimsStore(self.parquet_path, memory_limit=self.memory_limit, threads=1)
            try:
                rows = store.sample(self.train_rows, seed=42)
                metadata = store.fingerprint() | {
                    "sampling": f"Uniform reservoir sample of {len(rows):,} of "
                    f"{store.row_count():,} rows, seed 42",
                    "sample_rows": len(rows),
                    "sample_claim_ids_sha256": hashlib.sha256(
                        "\n".join(sorted(row["claim_id"] for row in rows)).encode()
                    ).hexdigest(),
                    "sampling_threads": 1,
                }
            finally:
                store.close()
            return rows, metadata
        payload = json.loads(self.data_path.read_text())
        rows, metadata = payload["rows"], payload["metadata"]
        digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())
        if metadata.get("rows_sha256") != digest.hexdigest():
            raise ValueError("Source rows SHA256 does not match provenance metadata")
        return rows, metadata

    def train(self) -> dict:
        try:
            source_rows, origin = self._read_rows()
        except (OSError, ValueError, KeyError, TypeError) as error:
            return {"available": False, "reason": str(error), "limitations": LIMITATIONS}
        valid, seen = [], set()
        for row in source_rows:
            try:
                ClaimInput.model_validate(
                    {
                        **{
                            key: row[key]
                            for key in (
                                "claim_type",
                                "state",
                                "incident_date",
                                "claim_filed_date",
                                "claim_amount",
                                "deductible",
                                "previous_claims_count",
                                "policyholder_tenure_years",
                            )
                        },
                        "description": "Historical structured claim record",
                    }
                )
                if not row["policy_id"] or row["claim_id"] in seen:
                    continue
                seen.add(row["claim_id"])
                valid.append(row)
            except (ValueError, KeyError, TypeError):
                continue
        if len(valid) < 150:
            return {
                "available": False,
                "reason": "At least 150 valid unique claims required",
                "valid_rows": len(valid),
                "origin": origin,
                "limitations": LIMITATIONS,
            }
        partitions, split = temporal_split(valid)
        models, metrics = {}, {}
        for task in TARGETS:
            result, metric = self._fit_task(task, partitions, split)
            metrics[task] = metric
            if result is not None:
                models[task] = result
        report = {
            "trained_at": datetime.now(UTC).isoformat(),
            "origin": origin,
            "valid_rows": len(valid),
            "excluded_rows": len(source_rows) - len(valid),
            "split": split,
            "metrics": metrics,
            "limitations": LIMITATIONS,
            "feature_contracts": FEATURES,
        }
        self._bundle = {"schema_version": 1, "models": models, "report": report}
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        temp = self.artifact_dir / "claims_models.tmp"
        joblib.dump(self._bundle, temp)
        temp.replace(self.artifact_dir / "claims_models.joblib")
        return self.status()

    @staticmethod
    def _task_rows(rows: list[dict], task: str, label_deadline: str | None) -> list[dict]:
        usable = []
        for row in rows:
            target = row.get(TARGETS[task])
            if task == "fraud":
                if type(target) is not bool:
                    continue
            elif not isinstance(target, (int, float)) or not math.isfinite(target) or target < 0:
                continue
            if task == "resolution":
                if row.get("claim_status") not in {"approved", "denied"}:
                    continue
                resolved = date.fromisoformat(row["claim_filed_date"]) + timedelta(days=target)
                if resolved > datetime.now(UTC).date():
                    continue
                if label_deadline and resolved >= date.fromisoformat(label_deadline):
                    continue
            usable.append(row)
        return usable

    @threadpool_limits.wrap(limits=2)
    def _fit_task(self, task: str, partitions: list[list[dict]], split: dict):
        deadlines = [split["calibration_start"], split["test_start"], None]
        task_rows = [self._task_rows(rows, task, end) for rows, end in zip(partitions, deadlines)]
        counts = dict(zip(("train", "calibration", "test"), map(len, task_rows)))
        if counts["train"] < 80 or min(counts["calibration"], counts["test"]) < 20:
            return None, {
                "available": False,
                "counts": counts,
                "reason": "Insufficient eligible temporal partitions",
            }
        feats = [[feature_dict(r, task) for r in rows] for rows in task_rows]
        vectorizer = DictVectorizer(sparse=False)
        x_train = vectorizer.fit_transform(feats[0])
        x_cal = vectorizer.transform(feats[1])
        x_test = vectorizer.transform(feats[2])
        y_train, y_cal, y_test = [np.array([r[TARGETS[task]] for r in rows]) for rows in task_rows]
        role_rows, role_dates = calibration_roles(task_rows[1])
        role_rows = [
            self._task_rows(rows, task, end)
            for rows, end in zip(role_rows, [*role_dates, split["test_start"]])
        ]
        if task != "fraud":
            # Regression has no threshold decision. Use the later half of calibration for
            # uncertainty, with labels observable at test start; an earlier artificial
            # deadline would censor slower claims and narrow the interval spuriously.
            raw_roles, _ = calibration_roles(task_rows[1])
            role_rows[1] = self._task_rows(raw_roles[1] + raw_roles[2], task, split["test_start"])
            role_rows[2] = []
        role_counts = dict(zip(("selection", "uncertainty", "threshold"), map(len, role_rows)))
        if task != "fraud":
            role_counts.pop("threshold")
        if min(role_counts.values()) < 5:
            return None, {
                "available": False,
                "counts": counts,
                "calibration_roles": role_counts,
                "reason": "Insufficient disjoint temporal calibration cohorts",
            }
        x_select, x_uncertainty, x_threshold = [
            vectorizer.transform([feature_dict(r, task) for r in rows])
            if rows
            else np.empty((0, x_train.shape[1]))
            for rows in role_rows
        ]
        y_select, y_uncertainty, y_threshold = [
            np.array([r[TARGETS[task]] for r in rows]) for rows in role_rows
        ]
        numeric_keys = [key for key in FEATURES[task] if key not in {"claim_type", "state"}]
        common = {
            "vectorizer": vectorizer,
            "categories": {
                key: sorted({r[key] for r in task_rows[0]}) for key in ("claim_type", "state")
            },
            "numeric_bounds": {
                key: [
                    float(min(f[key] for f in feats[0])),
                    float(max(f[key] for f in feats[0])),
                ]
                for key in numeric_keys
            },
            # "Typical claim" used for per-claim ablation explanations.
            "reference": {
                **{
                    key: Counter(f[key] for f in feats[0]).most_common(1)[0][0]
                    for key in ("claim_type", "state")
                },
                **{key: float(np.median([f[key] for f in feats[0]])) for key in numeric_keys},
            },
        }
        if task == "fraud":
            positive_counts = [int(y.sum()) for y in (y_train, y_cal, y_test)]
            negative_counts = [int(len(y) - y.sum()) for y in (y_train, y_cal, y_test)]
            if min(positive_counts) < 5 or min(negative_counts) < 5:
                return None, {
                    "available": False,
                    "counts": counts,
                    "positive_counts": positive_counts,
                    "reason": "Each partition needs at least five positive and negative labels",
                }
            if any(len(np.unique(y)) < 2 for y in (y_select, y_uncertainty, y_threshold)):
                return None, {
                    "available": False,
                    "counts": counts,
                    "reason": "Disjoint fraud calibration cohorts need both classes",
                }
            candidates = self._fraud_candidates()
            candidate_scores = {}
            for name, candidate in candidates.items():
                self._fit_candidate(candidate, x_train, y_train)
                probabilities = candidate.predict_proba(x_select)[:, 1]
                operating = fraud_operating_points(y_select, probabilities)
                candidate_scores[name] = {
                    "pr_auc": float(average_precision_score(y_select, probabilities)),
                    "brier": float(brier_score_loss(y_select, probabilities)),
                    "recall_at_50pct_precision": (
                        operating["precision_at_least_50pct"]["recall"]
                        if operating["precision_at_least_50pct"] else 0.0
                    ),
                }
            selected = max(
                candidate_scores,
                key=lambda name: (
                    candidate_scores[name]["pr_auc"],
                    -candidate_scores[name]["brier"],
                ),
            )
            model = candidates[selected]
            # Candidate selection used only the earlier training block and a later
            # calibration slice. Refit the winner on both before probability and
            # threshold calibration; the old pipeline left the selection rows unused.
            self._refit_selected(model, x_train, y_train, x_select, y_select)
            raw_uncertainty = np.clip(model.predict_proba(x_uncertainty)[:, 1], 1e-8, 1 - 1e-8)
            sigmoid = (
                LogisticRegression(C=1000, random_state=42).fit(
                    np.log(raw_uncertainty / (1 - raw_uncertainty)).reshape(-1, 1), y_uncertainty
                )
                if selected != "prior_baseline"
                else None
            )
            common.update(model=model, sigmoid=sigmoid, sigmoid_input="log_odds")
            threshold_scores = fraud_scores(common, x_threshold)
            operating_points = fraud_operating_points(y_threshold, threshold_scores)
            threshold = operating_points["max_f1"]["threshold"]
            scores = fraud_scores(common, x_test)
            predicted = scores >= threshold
            baseline = candidates["prior_baseline"]
            baseline_scores = baseline.predict_proba(x_test)[:, 1]
            metric = {
                "available": True,
                "counts": counts,
                "positive_counts": positive_counts,
                "precision": float(precision_score(y_test, predicted, zero_division=0)),
                "recall": float(recall_score(y_test, predicted, zero_division=0)),
                "pr_auc_average_precision": float(average_precision_score(y_test, scores)),
                "baseline_pr_auc": float(average_precision_score(y_test, baseline_scores)),
                "brier_score": float(brier_score_loss(y_test, scores)),
                "baseline_brier_score": float(brier_score_loss(y_test, baseline_scores)),
                "f1": float(f1_score(y_test, predicted, zero_division=0)),
                "accuracy": float(accuracy_score(y_test, predicted)),
                "majority_accuracy": float(accuracy_score(y_test, baseline.predict(x_test))),
                "balanced_accuracy": float(balanced_accuracy_score(y_test, predicted)),
                "selected_model": selected,
                "candidate_selection_scores": candidate_scores,
                "selection": "Highest selection-cohort average precision, Brier tie-break; test untouched",
                "review_threshold": threshold,
                "calibration": "Log-odds sigmoid on uncertainty cohort; F1 threshold on a later disjoint cohort",
                "class_weight": model.get_params().get("class_weight"),
                "threshold_selection": "Exact observed-score precision-recall curve on threshold cohort",
                "threshold_cohort_operating_points": operating_points,
                "heldout_operating_points": {
                    name: fraud_classification_metrics(y_test, scores, point["threshold"])
                    if point is not None else None
                    for name, point in operating_points.items()
                },
            }
            common.update(threshold=threshold)
            scoring = "average_precision"
        else:
            candidates = {
                "histogram_boosting_absolute_error": HistGradientBoostingRegressor(
                    loss="absolute_error",
                    max_iter=160,
                    max_leaf_nodes=15,
                    min_samples_leaf=40,
                    l2_regularization=10,
                    random_state=42,
                ),
                "random_forest": RandomForestRegressor(
                    n_estimators=80,
                    max_depth=12,
                    min_samples_leaf=32,
                    random_state=42,
                    n_jobs=2,
                ),
                "median_baseline": DummyRegressor(strategy="median"),
                "claim_type_median": ClaimTypeMedianRegressor(
                    {
                        category: vectorizer.vocabulary_[f"claim_type={category}"]
                        for category in common["categories"]["claim_type"]
                        if f"claim_type={category}" in vectorizer.vocabulary_
                    }
                ),
            }
            candidate_maes = {}
            for name, candidate in candidates.items():
                self._fit_candidate(candidate, x_train, y_train)
                candidate_maes[name] = float(
                    mean_absolute_error(y_select, candidate.predict(x_select))
                )
            selected = min(
                candidate_maes,
                key=lambda name: (candidate_maes[name], name != "median_baseline"),
            )
            model, baseline = candidates[selected], candidates["median_baseline"]
            self._refit_selected(model, x_train, y_train, x_select, y_select)
            residuals = np.abs(y_uncertainty - model.predict(x_uncertainty))
            quantile = min(1, math.ceil((len(residuals) + 1) * 0.9) / len(residuals))
            radius = float(np.quantile(residuals, quantile, method="higher"))
            prediction = model.predict(x_test)
            metric = {
                "available": True,
                "counts": counts,
                "selected_model": selected,
                "selection": "Lowest MAE on selection cohort; separate interval calibration; test untouched",
                "mae": float(mean_absolute_error(y_test, prediction)),
                "baseline_mae": float(mean_absolute_error(y_test, baseline.predict(x_test))),
                "candidate_calibration_mae": min(
                    v for k, v in candidate_maes.items() if k != "median_baseline"
                ),
                "baseline_calibration_mae": candidate_maes["median_baseline"],
                "candidate_selection_maes": candidate_maes,
                "empirical_interval_radius": radius,
                "heldout_interval_coverage": float(np.mean(np.abs(y_test - prediction) <= radius)),
                "interval_label": "90% calibration residual interval; no guaranteed future coverage",
            }
            common.update(model=model, radius=radius)
            scoring = "neg_mean_absolute_error"
        metric["calibration_roles"] = role_counts
        metric["calibration_role_boundaries"] = role_dates
        metric["refit_rows"] = len(y_train) + len(y_select)
        scorer = get_scorer(scoring)
        reference_score = scorer(model, x_cal, y_cal)
        feature_names = vectorizer.get_feature_names_out()
        rng = np.random.default_rng(42)
        grouped = {}
        for key in FEATURES[task]:
            columns = [i for i, name in enumerate(feature_names) if name.split("=")[0] == key]
            drops = []
            for _ in range(3):
                shuffled = x_cal.copy()
                permutation = rng.permutation(len(x_cal))
                # Shuffle complete one-hot groups together to preserve valid category vectors.
                shuffled[:, columns] = x_cal[permutation][:, columns]
                drops.append(reference_score - scorer(model, shuffled, y_cal))
            grouped[key] = float(np.mean(drops))
        ranked = sorted(grouped.items(), key=lambda pair: -pair[1])
        effects = _effects(task, common, feats[0], feats[1], rng)
        explanation = {
            "scope": "global_calibration_permutation_importance",
            "interpretation": "Drop in calibration scoring when shuffled; associations, not causality or local contribution",
            "scoring": scoring,
            "features": [{"feature": key, "score_drop": round(value, 6)} for key, value in ranked],
            "effects": effects,
            "effects_method": "Partial dependence on a calibration subsample: mean predicted "
            f"{TASK_NOUN[task]} when one feature is set to each value for every claim; "
            "associations in the model, not causal effects",
            "summary": _summarize(task, effects, [k for k, _ in ranked]),
        }
        common["explanation"] = explanation
        metric["global_explanation"] = explanation
        if hasattr(model, "n_jobs"):
            model.set_params(n_jobs=1)  # single-claim predictions are faster without a thread pool
        return common, metric

    @staticmethod
    def _fraud_candidates():
        """Weight only the fit data; calibration and test retain natural prevalence."""
        boosting = {
            "max_iter": 160, "max_leaf_nodes": 15, "min_samples_leaf": 40,
            "l2_regularization": 10, "random_state": 42,
        }
        forest = {
            "n_estimators": 80, "max_depth": 12, "min_samples_leaf": 32,
            "random_state": 42, "n_jobs": 2,
        }
        return {
            "histogram_boosting": HistGradientBoostingClassifier(**boosting),
            "histogram_boosting_balanced": HistGradientBoostingClassifier(
                **boosting, class_weight="balanced"
            ),
            "random_forest": RandomForestClassifier(**forest),
            "random_forest_balanced": RandomForestClassifier(**forest, class_weight="balanced"),
            "random_forest_balanced_subsample": RandomForestClassifier(
                **forest, class_weight="balanced_subsample"
            ),
            "prior_baseline": DummyClassifier(strategy="prior"),
        }

    @staticmethod
    def _fit_candidate(candidate, x_train, y_train):
        """Fit candidates with a chronological validation tail when supported.

        HistGradientBoosting's default ``validation_fraction`` is a random slice of
        the training data. That is inappropriate for this temporal benchmark. A
        chronological tail controls early stopping while preserving the separate
        calibration selection and final test cohorts.
        """
        if isinstance(candidate, (HistGradientBoostingRegressor, HistGradientBoostingClassifier)):
            boundary = max(80, int(len(y_train) * 0.9))
            if boundary < len(y_train):
                with config_context(enable_metadata_routing=True):
                    candidate.set_fit_request(X_val=True, y_val=True)
                    candidate.fit(
                        x_train[:boundary], y_train[:boundary],
                        X_val=x_train[boundary:], y_val=y_train[boundary:],
                    )
                return
        candidate.fit(x_train, y_train)

    @staticmethod
    def _refit_selected(model, x_train, y_train, x_select, y_select):
        """Use the model-selection rows in the final fit without touching test data."""
        x_fit = np.vstack((x_train, x_select))
        y_fit = np.concatenate((y_train, y_select))
        if isinstance(model, (HistGradientBoostingRegressor, HistGradientBoostingClassifier)):
            # Preserve the iteration count selected by the chronological early-stop
            # pass, but disable another random validation split during the final fit.
            model.set_params(early_stopping=False, max_iter=max(1, int(model.n_iter_)))
        model.fit(x_fit, y_fit)

    @threadpool_limits.wrap(limits=2)
    def predict(self, claim: ClaimInput) -> dict:
        if self._bundle is None or not self._bundle["models"]:
            return {
                "available": False,
                "reason": self.status().get("reason", "No eligible models"),
                "limitations": LIMITATIONS,
            }
        if claim.claim_type is None:
            return {"available": False, "reason": "A validated claim type is required"}
        row = claim.model_dump(mode="json")
        output = {
            "available": True,
            "origin": self._bundle["report"]["origin"],
            "limitations": LIMITATIONS,
            "warnings": [],
            "confidence_distinction": "Statistical scores and residual intervals are independent of Synapt retrieval confidence",
        }
        for task in TARGETS:
            trained = self._bundle["models"].get(task)
            if trained is None:
                output[task] = {
                    "available": False,
                    "reason": self._bundle["report"]["metrics"][task]["reason"],
                }
                continue
            features = feature_dict(row, task)
            for key, categories in trained["categories"].items():
                if row[key] not in categories:
                    output["warnings"].append(f"{task}: unseen {key} category {row[key]}")
            for key, (lower, upper) in trained["numeric_bounds"].items():
                if not lower <= features[key] <= upper:
                    output["warnings"].append(f"{task}: {key} outside training sample range")
            vector = trained["vectorizer"].transform([features])
            if task == "fraud":
                score = float(fraud_scores(trained, vector)[0])
                result = {
                    "available": True,
                    "score": round(score, 6),
                    "review_threshold": trained["threshold"],
                    "review_signal": score >= trained["threshold"],
                    "meaning": "Estimated synthetic fraud-flag risk; not proven fraud",
                }
            else:
                estimate = max(0, float(trained["model"].predict(vector)[0]))
                radius = trained["radius"]
                result = {
                    "available": True,
                    "estimate": round(estimate, 2),
                    "unit": "USD" if task == "amount" else "days",
                    "interval": [round(max(0, estimate - radius), 2), round(estimate + radius, 2)],
                    "interval_label": "90% empirical calibration residual interval; future coverage unverified",
                }
            result["global_explanation"] = trained["explanation"]
            result["local_explanation"] = self._local_explanation(task, trained, features)
            output[task] = result
        output["warnings"] = sorted(set(output["warnings"]))
        return output

    @staticmethod
    def _local_explanation(task: str, trained: dict, features: dict) -> dict | None:
        """Why this claim's estimate differs from a typical claim, one feature at a time.

        Each feature is replaced in turn by the training-set typical value (most common category
        or median) and the model is re-scored. The effect is the change in the estimate caused by
        that substitution. It is not additive, not causal, and depends on the other features.
        """
        reference = trained.get("reference")
        if not reference:
            return None  # artifact trained before local explanations existed
        keys = list(FEATURES[task])
        rows = [features] + [{**features, key: reference[key]} for key in keys]
        values = predict_function(task, trained)(trained["vectorizer"].transform(rows))
        contributions = [
            {
                "feature": key,
                "value": features[key],
                "typical_value": reference[key],
                "effect": round(float(values[0] - values[i + 1]), 4),
            }
            for i, key in enumerate(keys)
            if features[key] != reference[key]
        ]
        contributions.sort(key=lambda item: -abs(item["effect"]))
        return {
            "method": "One-at-a-time substitution of a typical claim's value; not additive or causal",
            "unit": {"amount": "USD", "resolution": "days", "fraud": "score"}[task],
            "contributions": contributions[:6],
        }
