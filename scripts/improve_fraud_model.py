"""Compare class weights and training sizes on fixed temporal validation cohorts.

Run: uv run python scripts/improve_fraud_model.py
Only the fraud artifact is updated. Original labels and all regression models are preserved.
"""

import argparse
import copy
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import average_precision_score, brier_score_loss
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from retrain_models import compact, verify_holdout

from claims.analytics import (
    TARGETS,
    AnalyticsService,
    calibration_roles,
    feature_dict,
    fraud_classification_metrics,
    fraud_operating_points,
    fraud_scores,
    temporal_split,
)
from claims.dataset import ClaimsStore
from claims.models import ClaimInput
from claims.settings import Settings


def claim_digest(rows):
    return hashlib.sha256("\n".join(sorted(r["claim_id"] for r in rows)).encode()).hexdigest()


def expand_training(base, supplemental, calibration, test, cutoff):
    """Admit unique pre-cutoff source claims with no evaluation-policy overlap."""
    reserved_policies = {r["policy_id"] for r in calibration + test}
    seen = {r["claim_id"] for r in base + calibration + test}
    admitted = list(base)
    excluded = {"future": 0, "policy_overlap": 0, "duplicate": 0, "invalid": 0}
    for row in supplemental:
        if row["claim_filed_date"] >= cutoff:
            excluded["future"] += 1
        elif row["policy_id"] in reserved_policies:
            excluded["policy_overlap"] += 1
        elif row["claim_id"] in seen:
            excluded["duplicate"] += 1
        else:
            try:
                ClaimInput.model_validate({
                    **{key: row[key] for key in ClaimInput.model_fields
                       if key in row and key not in {"description", "provided_documents"}},
                    "description": "Original structured source claim",
                })
                if not row["policy_id"] or type(row[TARGETS["fraud"]]) is not bool:
                    raise ValueError("Invalid policy or fraud label")
            except (ValueError, KeyError, TypeError):
                excluded["invalid"] += 1
                continue
            admitted.append(row)
            seen.add(row["claim_id"])
    admitted.sort(key=lambda r: (r["claim_filed_date"], r["claim_id"]))
    return admitted, excluded


def evaluate_candidate(service, name, rows, x_select, y_select, vectorizer):
    candidate = service._fraud_candidates()[name]
    x = vectorizer.transform([feature_dict(r, "fraud") for r in rows])
    y = np.array([r[TARGETS["fraud"]] for r in rows])
    started = time.monotonic()
    print(f"Fit {name}: {len(rows):,} rows ({int(y.sum()):,} flagged)", flush=True)
    service._fit_candidate(candidate, x, y)
    probabilities = candidate.predict_proba(x_select)[:, 1]
    operating = fraud_operating_points(y_select, probabilities)
    at50 = operating["precision_at_least_50pct"]
    result = {
        "name": name, "train_rows": len(rows), "train_positive_rows": int(y.sum()),
        "selection_average_precision": float(average_precision_score(y_select, probabilities)),
        "selection_raw_brier": float(brier_score_loss(y_select, probabilities)),
        "selection_recall_at_50pct_precision": at50["recall"] if at50 else 0.0,
        "selection_operating_points": operating,
        "elapsed_seconds": round(time.monotonic() - started, 2),
    }
    print(json.dumps({k: v for k, v in result.items() if k != "selection_operating_points"}), flush=True)
    return result


def experiment_rank(result):
    # Keep the decision rule fixed before any new holdout predictions are computed.
    return (result["selection_average_precision"], -result["train_rows"],
            -result["selection_raw_brier"])


class SelectedFraudService(AnalyticsService):
    def _fraud_candidates(self):
        candidates = super()._fraud_candidates()
        if not hasattr(self, "selected_candidate"):
            return candidates
        return {name: candidates[name] for name in (self.selected_candidate, "prior_baseline")}


def export_training(rows, path):
    """Keep a Parquet copy of the original training records, never generated cards."""
    import duckdb

    path.parent.mkdir(parents=True, exist_ok=True)
    json_path = path.with_suffix(".jsonl.tmp")
    parquet_temp = path.with_suffix(".parquet.tmp")
    try:
        with json_path.open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
        with duckdb.connect() as connection:
            connection.execute("SET memory_limit='512MB'")
            connection.execute("SET threads=1")
            destination = parquet_temp.as_posix().replace("'", "''")
            connection.execute(
                "COPY (SELECT * FROM read_json_auto(?, format='newline_delimited')) "
                f"TO '{destination}' (FORMAT PARQUET, COMPRESSION ZSTD)",
                [str(json_path)],
            )
        parquet_temp.replace(path)
    finally:
        json_path.unlink(missing_ok=True)
        parquet_temp.unlink(missing_ok=True)


@threadpool_limits.wrap(limits=2)
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--additional-rows", type=int, default=600_000)
    args = parser.parse_args()
    if not 1_000 <= args.additional_rows <= 1_000_000:
        parser.error("--additional-rows must be 1,000..1,000,000")
    settings = Settings()
    artifact_dir = settings.claims_artifact_dir
    path = artifact_dir / "fraud_improvement_report.json"
    service = SelectedFraudService(settings.claims_data_path, artifact_dir,
                                   settings.claims_parquet_path, 600_000, "1GB")
    if service._bundle is None:
        raise ValueError("A verified baseline artifact is required")
    initial_bundle = copy.deepcopy(service._bundle)
    joblib.dump(initial_bundle, artifact_dir / "claims_models.before_fraud_improvement.joblib")
    baseline_report = artifact_dir / "retraining_report.before_fraud_improvement.json"
    baseline_report.write_text((artifact_dir / "retraining_report.json").read_text(), encoding="utf-8")
    started = time.monotonic()
    print("Reconstruct original 600,000 source rows and fixed evaluation cohorts", flush=True)
    rows, origin = service._read_rows()
    expected = initial_bundle["report"]["origin"].get("sample_claim_ids_sha256")
    if expected != origin.get("sample_claim_ids_sha256"):
        raise ValueError("Baseline source sample changed")
    partitions, split = temporal_split(rows)
    base, calibration, test = partitions
    roles, _ = calibration_roles(calibration)
    selection = roles[0]
    vectorizer = DictVectorizer(sparse=False)
    vectorizer.fit([feature_dict(r, "fraud") for r in base])
    x_select = vectorizer.transform([feature_dict(r, "fraud") for r in selection])
    y_select = np.array([r[TARGETS["fraud"]] for r in selection])
    comparisons = []
    # Compare all weights at exactly the same original training size first.
    for name in service._fraud_candidates():
        comparisons.append(evaluate_candidate(service, name, base, x_select, y_select, vectorizer))
    report = {
        "decision_rule": "Highest selection-cohort average precision; smaller fit on exact ties; raw Brier last",
        "evaluation": "Fixed original chronological, policy-disjoint cohorts; natural class ratios",
        "prior_metrics": compact(initial_bundle["report"])["metrics"]["fraud"],
        "weight_comparisons": comparisons,
        "original_source": origin,
    }
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    top_names = [r["name"] for r in sorted(comparisons, key=experiment_rank, reverse=True)
                 if r["name"] != "prior_baseline"][:2]
    print(f"Fetch {args.additional_rows:,} additional source rows, seed 142", flush=True)
    store = ClaimsStore(settings.claims_parquet_path, memory_limit="1GB", threads=1)
    try:
        supplemental = store.sample(args.additional_rows, seed=142)
    finally:
        store.close()
    expanded, excluded = expand_training(base, supplemental, calibration, test, split["calibration_start"])
    del supplemental
    report["additional_source_sample_rows"] = args.additional_rows
    report["additional_source_seed"] = 142
    report["expanded_training_rows"] = len(expanded)
    report["added_unique_training_rows"] = len(expanded) - len(base)
    report["expanded_training_ids_sha256"] = claim_digest(expanded)
    report["excluded_additional_rows"] = excluded
    report["expanded_training_positive_rows"] = sum(r[TARGETS["fraud"]] for r in expanded)
    dataset_path = ROOT / "data" / "processed" / "ml" / "fraud_training_expanded.parquet"
    export_training(expanded, dataset_path)
    report["expanded_training_parquet"] = str(dataset_path)
    small_indices = np.random.default_rng(42).permutation(len(base))[:min(100_000, len(base))]
    small = sorted([base[int(i)] for i in small_indices],
                   key=lambda r: (r["claim_filed_date"], r["claim_id"]))
    curve = [r for r in comparisons if r["name"] in top_names]
    for name in top_names:
        curve.append(evaluate_candidate(service, name, small, x_select, y_select, vectorizer))
        curve.append(evaluate_candidate(service, name, expanded, x_select, y_select, vectorizer))
    report["learning_curve"] = curve
    winner = max(comparisons + curve, key=experiment_rank)
    report["selected_experiment"] = winner
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    chosen_rows = (expanded if winner["train_rows"] == len(expanded)
                   else base if winner["train_rows"] == len(base) else small)
    service.selected_candidate = winner["name"]
    final_partitions = [chosen_rows, calibration, test]
    final_split = {**split, "counts": {"train": len(chosen_rows), "calibration": len(calibration),
                                      "test": len(test)}}
    print("Refit selected configuration; calibrate probabilities and thresholds on later disjoint cohorts", flush=True)
    trained, metric = service._fit_task("fraud", final_partitions, final_split)
    if trained is None:
        raise ValueError("Selected configuration failed final fitting")
    metric["experiment"] = {
        "report_file": str(path), "training_rows_before_selection_refit": len(chosen_rows),
        "training_claim_ids_sha256": claim_digest(chosen_rows),
        "expanded_source_seed": 142,
        "added_rows_used": len(expanded) - len(base) if chosen_rows is expanded else 0,
    }
    # Compare to the frozen previous artifact on the same holdout, after selection is complete.
    test_feats = [feature_dict(r, "fraud") for r in test]
    test_labels = np.array([r[TARGETS["fraud"]] for r in test])
    old = initial_bundle["models"]["fraud"]
    old_scores = fraud_scores(old, old["vectorizer"].transform(test_feats))
    report["prior_holdout_recomputed"] = {
        **fraud_classification_metrics(test_labels, old_scores, old["threshold"]),
        "average_precision": float(average_precision_score(test_labels, old_scores)),
    }
    service._bundle["models"]["fraud"] = trained
    service._bundle["report"]["metrics"]["fraud"] = metric
    now = datetime.now(UTC).isoformat()
    service._bundle["report"]["task_trained_at"] = {
        "amount": initial_bundle["report"]["trained_at"],
        "resolution": initial_bundle["report"]["trained_at"], "fraud": now,
    }
    service._bundle["report"]["trained_at"] = now
    temporary = artifact_dir / "claims_models.fraud_candidate.joblib"
    joblib.dump(service._bundle, temporary)
    # A reload must reproduce independent source-based verification before activation.
    check = AnalyticsService(settings.claims_data_path, artifact_dir,
                             settings.claims_parquet_path, 600_000, "1GB")
    check._bundle = joblib.load(temporary)
    print("Independently reload candidate and reconstruct original source holdout", flush=True)
    verification = verify_holdout(check)
    report["final_metrics"] = compact(service.status())["metrics"]["fraud"]
    report["verification"] = verification
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    retraining = {"report": compact(service.status()), "verification": verification,
                  "elapsed_seconds": report["elapsed_seconds"], "fraud_improvement_report": str(path)}
    (artifact_dir / "retraining_report.json").write_text(json.dumps(retraining, indent=2), encoding="utf-8")
    temporary.replace(artifact_dir / "claims_models.joblib")
    print(json.dumps({"report_file": str(path), "selected_model": winner["name"],
                      "selected_training_rows": len(chosen_rows),
                      "heldout_average_precision": metric["pr_auc_average_precision"],
                      "precision": metric["precision"], "recall": metric["recall"]}), flush=True)


if __name__ == "__main__":
    main()
