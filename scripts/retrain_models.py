"""Retrain from verified source rows, then independently recompute held-out metrics.

Run: uv run python scripts/retrain_models.py --rows 600000
No labels are generated, changed, or imported from Synapt cards.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import average_precision_score, brier_score_loss, mean_absolute_error
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.analytics import (
    AnalyticsService,
    feature_dict,
    fraud_classification_metrics,
    fraud_scores,
    temporal_split,
)
from claims.fraud_features import load_source_evaluation_rows
from claims.settings import Settings


class ReportingAnalyticsService(AnalyticsService):
    def _fit_task(self, task, partitions, split):
        print(f"Fitting {task}", flush=True)
        result = super()._fit_task(task, partitions, split)
        print(f"Finished {task}: {result[1].get('selected_model', 'unavailable')}", flush=True)
        return result


def compact(report):
    return {
        **report,
        "metrics": {
            task: {key: value for key, value in metric.items() if key != "global_explanation"}
            for task, metric in report.get("metrics", {}).items()
        },
    }


@threadpool_limits.wrap(limits=2)
def verify_holdout(service):
    rows, origin = service._read_rows()
    partitions, split = temporal_split(rows)
    report = service.status()
    expected_digest = report["origin"].get("sample_claim_ids_sha256")
    if expected_digest and origin.get("sample_claim_ids_sha256") != expected_digest:
        raise ValueError("Source sampling changed between training and holdout verification")
    verified = {}
    for task, trained in service._bundle["models"].items():
        train = service._task_rows(partitions[0], task, split["calibration_start"])
        test = service._task_rows(partitions[2], task, None)
        evaluation = trained.get("evaluation_cohort") if task == "fraud" else None
        if evaluation:
            test = load_source_evaluation_rows(service, evaluation)
            test_policies = {r["policy_id"] for r in test}
            if test_policies & set(trained["training_policy_ids"]):
                raise ValueError("Fresh fraud test overlaps training policies")
            if any(r["claim_filed_date"] < evaluation["minimum_filing_date"] for r in test):
                raise ValueError("Fresh fraud test precedes frozen temporal boundary")
            if len(test) != report["metrics"][task]["counts"]["test"]:
                raise ValueError("Fresh fraud test count differs from stored report")
        x = trained["vectorizer"].transform([feature_dict(row, task) for row in test])
        y = np.array(
            [
                row[
                    {
                        "amount": "claim_amount",
                        "resolution": "days_to_resolution",
                        "fraud": "is_fraud_flagged_ground_truth",
                    }[task]
                ]
                for row in test
            ]
        )
        prediction = fraud_scores(trained, x) if task == "fraud" else trained["model"].predict(x)
        metric_name = "pr_auc_average_precision" if task == "fraud" else "mae"
        measured = (
            float(average_precision_score(y, prediction))
            if task == "fraud"
            else float(mean_absolute_error(y, prediction))
        )
        expected = report["metrics"][task][metric_name]
        if not np.isclose(measured, expected, rtol=0, atol=1e-9):
            raise ValueError(f"{task} held-out metric differs from stored report")
        cohorts = {}
        for kind in sorted({r["claim_type"] for r in test}):
            mask = np.array([r["claim_type"] == kind for r in test])
            if task == "fraud":
                cohorts[kind] = {
                    "rows": int(mask.sum()),
                    "positives": int(y[mask].sum()),
                    "pr_auc": float(average_precision_score(y[mask], prediction[mask])),
                    "brier": float(brier_score_loss(y[mask], prediction[mask])),
                }
            else:
                cohorts[kind] = {
                    "rows": int(mask.sum()),
                    "mae": float(mean_absolute_error(y[mask], prediction[mask])),
                }
        verified[task] = {
            "recomputed_metric": measured,
            "stored_metric_matches": True,
            "test_rows": len(test),
            "test_claim_ids_sha256": hashlib.sha256(
                "\n".join(sorted(r["claim_id"] for r in test)).encode()
            ).hexdigest(),
            "claim_type_cohorts": cohorts,
        }
        if evaluation:
            verified[task]["source_verified_evaluation_cohort"] = evaluation
            verified[task]["training_policy_overlap"] = 0
        if task == "fraud":
            classification = fraud_classification_metrics(y, prediction, trained["threshold"])
            probability_loss = float(brier_score_loss(y, prediction))
            stored = report["metrics"][task]
            for key in ("precision", "recall", "f1", "accuracy", "balanced_accuracy"):
                if not np.isclose(classification[key], stored[key], rtol=0, atol=1e-9):
                    raise ValueError(f"Fraud held-out {key} differs from stored report")
            if not np.isclose(probability_loss, stored["brier_score"], rtol=0, atol=1e-9):
                raise ValueError("Fraud held-out probability loss differs from stored report")
            operating = {}
            for name, point in stored.get("heldout_operating_points", {}).items():
                if point is None:
                    operating[name] = None
                    continue
                measured_point = fraud_classification_metrics(y, prediction, point["threshold"])
                for key, value in measured_point.items():
                    if not np.isclose(value, point[key], rtol=0, atol=1e-9):
                        raise ValueError(f"Fraud held-out {name}/{key} differs from stored report")
                operating[name] = measured_point
            verified[task].update(
                recomputed_classification_metrics=classification,
                recomputed_brier=probability_loss,
                classification_metrics_match=True,
                recomputed_operating_points=operating,
            )
        if task == "amount":
            medians = {
                kind: float(
                    np.median([r["claim_amount"] for r in train if r["claim_type"] == kind])
                )
                for kind in {r["claim_type"] for r in train}
            }
            fallback = float(np.median([r["claim_amount"] for r in train]))
            simple_predictions = np.array([medians.get(r["claim_type"], fallback) for r in test])
            verified[task]["feature_aware_baseline"] = {
                "model": "Training claim-type median; global training median for unseen types",
                "mae": float(mean_absolute_error(y, simple_predictions)),
                "claim_type_medians": medians,
            }
        elif task == "resolution":
            train_delays = np.array(
                [feature_dict(r, task)["filing_delay_days"] for r in train]
            ).reshape(-1, 1)
            train_target = np.array([r["days_to_resolution"] for r in train])
            simple = LinearRegression().fit(train_delays, train_target)
            test_delays = np.array(
                [feature_dict(r, task)["filing_delay_days"] for r in test]
            ).reshape(-1, 1)
            verified[task]["feature_aware_baseline"] = {
                "model": "Training-fitted filing-delay-only ordinary least-squares regression",
                "mae": float(mean_absolute_error(y, np.maximum(0, simple.predict(test_delays)))),
                "intercept": float(simple.intercept_),
                "filing_delay_coefficient": float(simple.coef_[0]),
            }
    policies = [{r["policy_id"] for r in partition} for partition in partitions]
    if any(policies[i] & policies[j] for i, j in ((0, 1), (0, 2), (1, 2))):
        raise ValueError("Policy leakage found in held-out verification")
    return {
        "strategy": "Reload artifact and source; reconstruct temporal test; recompute predictions",
        "split": split,
        "tasks": verified,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=600_000)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--memory-limit", default="1GB", choices=["512MB", "1GB", "2GB"])
    args = parser.parse_args()
    if not 1000 <= args.rows <= 5_000_000:
        parser.error("--rows must be between 1,000 and 5,000,000")
    settings = Settings()
    artifact_dir = args.artifact_dir or settings.claims_artifact_dir
    service = ReportingAnalyticsService(
        settings.claims_data_path,
        artifact_dir,
        settings.claims_parquet_path,
        args.rows,
        args.memory_limit,
    )
    before = compact(service.status())
    artifact_dir.mkdir(parents=True, exist_ok=True)
    before_path = artifact_dir / "retraining_before.json"
    if not before_path.exists():
        before_path.write_text(json.dumps(before, indent=2), encoding="utf-8")
    started = time.monotonic()
    print(
        f"Training {args.rows:,} source rows; DuckDB {args.memory_limit}, one sampling thread",
        flush=True,
    )
    report = service.train()
    if not report.get("available") or len(service._bundle["models"]) != 3:
        raise RuntimeError(f"Three models required: {compact(report)}")
    service = AnalyticsService(
        settings.claims_data_path,
        artifact_dir,
        settings.claims_parquet_path,
        args.rows,
        args.memory_limit,
    )
    verification = verify_holdout(service)
    output = {
        "report": compact(report),
        "verification": verification,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    path = artifact_dir / "retraining_report.json"
    path.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "report_file": str(path),
                "elapsed_seconds": output["elapsed_seconds"],
                "metrics": compact(report)["metrics"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
