"""Reproducible, leakage-controlled educational statistical models.

Artifacts are locally generated trusted joblib files; never load untrusted files.
"""

import hashlib
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    get_scorer,
    mean_absolute_error,
    precision_score,
    recall_score,
)

from claims.models import ClaimInput

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
TARGETS = {
    "amount": "claim_amount",
    "resolution": "days_to_resolution",
    "fraud": "is_fraud_flagged_ground_truth",
}
LIMITATIONS = [
    "Educational model trained on synthetic US claims, not validated on real insurance claims.",
    "A bounded contiguous sample does not establish population representativeness.",
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


class AnalyticsService:
    def __init__(self, data_path: Path, artifact_dir: Path):
        self.data_path, self.artifact_dir = Path(data_path), Path(artifact_dir)
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

    def status(self) -> dict:
        if self._bundle is None:
            return {
                "available": False,
                "reason": self._load_error or "Models have not been trained",
                "data_present": self.data_path.exists(),
                "limitations": LIMITATIONS,
            }
        return {"available": bool(self._bundle["models"]), **self._bundle["report"]}

    def _read_rows(self) -> tuple[list[dict], dict]:
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
        vectorizer = DictVectorizer(sparse=False)
        x_train = vectorizer.fit_transform([feature_dict(r, task) for r in task_rows[0]])
        x_cal = vectorizer.transform([feature_dict(r, task) for r in task_rows[1]])
        x_test = vectorizer.transform([feature_dict(r, task) for r in task_rows[2]])
        y_train, y_cal, y_test = [np.array([r[TARGETS[task]] for r in rows]) for rows in task_rows]
        common = {
            "vectorizer": vectorizer,
            "categories": {
                key: sorted({r[key] for r in task_rows[0]}) for key in ("claim_type", "state")
            },
            "numeric_bounds": {
                key: [
                    float(min(feature_dict(r, task)[key] for r in task_rows[0])),
                    float(max(feature_dict(r, task)[key] for r in task_rows[0])),
                ]
                for key in FEATURES[task]
                if key not in {"claim_type", "state"}
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
            model = RandomForestClassifier(
                n_estimators=100, min_samples_leaf=8, random_state=42, n_jobs=1
            )
            model.fit(x_train, y_train)
            raw_cal = model.predict_proba(x_cal)[:, 1]
            sigmoid = LogisticRegression(C=1, random_state=42)
            sigmoid.fit(raw_cal.reshape(-1, 1), y_cal)
            scores = sigmoid.predict_proba(model.predict_proba(x_test)[:, 1].reshape(-1, 1))[:, 1]
            cal_scores = sigmoid.predict_proba(raw_cal.reshape(-1, 1))[:, 1]
            thresholds = np.linspace(0.02, 0.98, 49)
            threshold = float(max(thresholds, key=lambda t: f1_score(y_cal, cal_scores >= t)))
            predicted = scores >= threshold
            baseline = DummyClassifier(strategy="prior").fit(x_train, y_train)
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
                "review_threshold": threshold,
                "calibration": "Sigmoid fit on temporal calibration partition; not independently calibrated",
            }
            common.update(model=model, sigmoid=sigmoid, threshold=threshold)
            scoring = "average_precision"
        else:
            candidate = RandomForestRegressor(
                n_estimators=100, min_samples_leaf=8, random_state=42, n_jobs=1
            ).fit(x_train, y_train)
            baseline = DummyRegressor(strategy="median").fit(x_train, y_train)
            candidate_mae = mean_absolute_error(y_cal, candidate.predict(x_cal))
            baseline_cal_mae = mean_absolute_error(y_cal, baseline.predict(x_cal))
            model = candidate if candidate_mae < baseline_cal_mae else baseline
            residuals = np.abs(y_cal - model.predict(x_cal))
            radius = float(np.quantile(residuals, 0.9, method="higher"))
            prediction = model.predict(x_test)
            metric = {
                "available": True,
                "counts": counts,
                "selected_model": "random_forest" if model is candidate else "median_baseline",
                "selection": "Lower MAE on calibration partition; test never used for selection",
                "mae": float(mean_absolute_error(y_test, prediction)),
                "baseline_mae": float(mean_absolute_error(y_test, baseline.predict(x_test))),
                "candidate_calibration_mae": float(candidate_mae),
                "baseline_calibration_mae": float(baseline_cal_mae),
                "empirical_interval_radius": radius,
                "heldout_interval_coverage": float(np.mean(np.abs(y_test - prediction) <= radius)),
                "interval_label": "90% calibration residual interval; no guaranteed future coverage",
            }
            common.update(model=model, radius=radius)
            scoring = "neg_mean_absolute_error"
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
        explanation = {
            "scope": "global_calibration_permutation_importance",
            "interpretation": "Drop in calibration scoring when shuffled; associations, not causality or local contribution",
            "scoring": scoring,
            "features": [
                {"feature": key, "score_drop": round(value, 6)}
                for key, value in sorted(grouped.items(), key=lambda pair: -pair[1])
            ],
        }
        common["explanation"] = explanation
        metric["global_explanation"] = explanation
        return common, metric

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
                raw = trained["model"].predict_proba(vector)[:, 1].reshape(-1, 1)
                score = float(trained["sigmoid"].predict_proba(raw)[0, 1])
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
            output[task] = result
        output["warnings"] = sorted(set(output["warnings"]))
        return output
