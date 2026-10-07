"""Bounded ratio/CatBoost comparison with fresh policy-disjoint temporal evaluation.

The final holdout is evaluated only after a validation-based decision is frozen.
Use --verify-only to reproduce results without tuning against a consumed holdout.
"""

import argparse
import copy
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
from catboost import CatBoostClassifier
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from improve_fraud_model import export_training
from retrain_models import compact, verify_holdout

from claims.analytics import (
    FEATURES,
    TARGETS,
    AnalyticsService,
    _effects,
    _summarize,
    feature_dict,
    fraud_classification_metrics,
    fraud_operating_points,
    fraud_scores,
    temporal_split,
)
from claims.dataset import ClaimsStore
from claims.fraud_features import (
    FraudFeatureEncoder,
    FraudProbabilityEnsemble,
    file_digest,
    fraud_estimator_probabilities,
    rows_digest,
)
from claims.models import ClaimInput
from claims.settings import Settings

WINDOWS = ("2024-05-13", "2024-09-01", "2024-12-02", "2025-03-14", "2025-06-24")
COHORT_NAMES = (
    "validation_early",
    "validation_late",
    "probability_calibration",
    "threshold_calibration",
    "test",
)
SEEDS = (42, 73)
CONFIGURATIONS = (
    "forest_raw",
    "forest_ratios",
    "boosting_ratios",
    "catboost_raw",
    "catboost_ratios",
)


def fresh_cohorts(rows, excluded_policies):
    groups = [[] for _ in COHORT_NAMES]
    seen = set()
    excluded = {
        "prior_policy": 0,
        "before_validation": 0,
        "invalid_or_duplicate": 0,
        "earlier_repeated_policy": 0,
    }
    for row in rows:
        if row["policy_id"] in excluded_policies:
            excluded["prior_policy"] += 1
            continue
        if row["claim_filed_date"] < WINDOWS[0]:
            excluded["before_validation"] += 1
            continue
        try:
            ClaimInput.model_validate(
                {
                    **{
                        key: row[key]
                        for key in ClaimInput.model_fields
                        if key in row and key not in {"description", "provided_documents"}
                    },
                    "description": "Original structured insurance claim",
                }
            )
            if (
                not row["policy_id"]
                or row["claim_id"] in seen
                or type(row[TARGETS["fraud"]]) is not bool
            ):
                raise ValueError("Invalid identity or label")
        except (ValueError, TypeError, KeyError):
            excluded["invalid_or_duplicate"] += 1
            continue
        seen.add(row["claim_id"])
        index = sum(row["claim_filed_date"] >= boundary for boundary in WINDOWS) - 1
        groups[index].append(row)
    later = set()
    for index in range(len(groups) - 1, -1, -1):
        before = len(groups[index])
        groups[index] = [r for r in groups[index] if r["policy_id"] not in later]
        excluded["earlier_repeated_policy"] += before - len(groups[index])
        groups[index].sort(key=lambda r: (r["claim_filed_date"], r["claim_id"]))
        later.update(r["policy_id"] for r in groups[index])
    return groups, excluded


def estimator(configuration, seed, *, iterations=250):
    if configuration.startswith("forest"):
        return RandomForestClassifier(
            n_estimators=80, max_depth=12, min_samples_leaf=32, random_state=seed, n_jobs=2
        )
    if configuration.startswith("boosting"):
        return HistGradientBoostingClassifier(
            max_iter=160,
            max_leaf_nodes=15,
            min_samples_leaf=40,
            l2_regularization=10,
            random_state=seed,
        )
    return CatBoostClassifier(
        iterations=iterations,
        depth=6,
        learning_rate=0.08,
        loss_function="Logloss",
        eval_metric="Logloss",
        cat_features=[0, 1],
        random_seed=seed,
        thread_count=2,
        has_time=True,
        allow_writing_files=False,
        verbose=False,
    )


def fit_configuration(configuration, rows):
    feats = [feature_dict(r, "fraud") for r in rows]
    y = np.array([r[TARGETS["fraud"]] for r in rows])
    native = configuration.startswith("catboost")
    encoder = FraudFeatureEncoder(
        ratios=configuration.endswith("ratios"), native_categorical=native
    )
    boundary = max(80, int(len(rows) * 0.9))
    encoder.fit(feats[:boundary] if not configuration.startswith("forest") else feats)
    early_x = encoder.transform(feats)
    iterations = []
    for seed in SEEDS:
        model = estimator(configuration, seed)
        if native:
            model.fit(
                early_x[:boundary],
                y[:boundary],
                eval_set=(early_x[boundary:], y[boundary:]),
                early_stopping_rounds=30,
                verbose=False,
            )
            iterations.append(max(1, model.tree_count_))
        elif configuration.startswith("boosting"):
            AnalyticsService._fit_candidate(model, early_x, y)
            iterations.append(max(1, int(model.n_iter_)))
        else:
            iterations.append(80)
    encoder.fit(feats)
    x = encoder.transform(feats)
    models = []
    for seed, count in zip(SEEDS, iterations):
        model = estimator(configuration, seed, iterations=count)
        if configuration.startswith("boosting"):
            model.set_params(early_stopping=False, max_iter=count)
        model.fit(x, y)
        models.append(model)
    return encoder, models, iterations


def validation_metrics(labels, probabilities):
    points = fraud_operating_points(labels, probabilities)
    at50 = points["precision_at_least_50pct"]
    at10 = points["review_at_most_10pct"]
    return {
        "average_precision": float(average_precision_score(labels, probabilities)),
        "recall_at_50pct_precision": at50["recall"] if at50 else 0.0,
        "recall_at_10pct_review": at10["recall"] if at10 else 0.0,
        "rows": len(labels),
        "positives": int(np.sum(labels)),
    }


def validation_decision(results):
    """Require gains on both dates, rather than selecting a tiny accuracy change."""
    baseline = next(r for r in results if r["configuration"] == "forest_raw")
    for result in results:
        result["eligible_for_promotion"] = (
            result["configuration"] != "forest_raw"
            and result["mean"]["recall_at_50pct_precision"]
            >= baseline["mean"]["recall_at_50pct_precision"] + 0.02
            and result["mean"]["average_precision"] >= baseline["mean"]["average_precision"] + 0.01
            and result["mean"]["recall_at_10pct_review"]
            >= baseline["mean"]["recall_at_10pct_review"]
            and all(
                r["average_precision"] >= b["average_precision"]
                for r, b in zip(result["folds"], baseline["folds"])
            )
        )
    eligible = [r for r in results if r["eligible_for_promotion"]]
    challengers = [r for r in results if r["configuration"] != "forest_raw"]
    selected = max(
        eligible or challengers,
        key=lambda r: (
            r["mean"]["recall_at_50pct_precision"],
            r["mean"]["average_precision"],
            r["mean"]["recall_at_10pct_review"],
        ),
    )
    return selected, bool(eligible)


def calibrated_model(configuration, rows, uncertainty, threshold_rows, iterations):
    feats = [feature_dict(r, "fraud") for r in rows]
    y = np.array([r[TARGETS["fraud"]] for r in rows])
    encoder = FraudFeatureEncoder(
        ratios=configuration.endswith("ratios"),
        native_categorical=configuration.startswith("catboost"),
    ).fit(feats)
    x = encoder.transform(feats)
    models = []
    for seed, count in zip(SEEDS, iterations):
        model = estimator(configuration, seed, iterations=count)
        if configuration.startswith("boosting"):
            model.set_params(early_stopping=False, max_iter=count)
        model.fit(x, y)
        if hasattr(model, "n_jobs"):
            model.set_params(n_jobs=1)
        models.append(model)
    trained = {"model": FraudProbabilityEnsemble(models), "vectorizer": encoder}
    cal_feats = [feature_dict(r, "fraud") for r in uncertainty]
    cal_x = encoder.transform(cal_feats)
    cal_y = np.array([r[TARGETS["fraud"]] for r in uncertainty])
    raw = np.clip(trained["model"].predict_proba(cal_x)[:, 1], 1e-8, 1 - 1e-8)
    trained.update(
        sigmoid=LogisticRegression(C=1000, random_state=42).fit(
            np.log(raw / (1 - raw)).reshape(-1, 1), cal_y
        ),
        sigmoid_input="log_odds",
    )
    if trained["sigmoid"].coef_[0, 0] <= 0:
        raise ValueError("Probability calibration reverses fraud ranking")
    threshold_x = encoder.transform([feature_dict(r, "fraud") for r in threshold_rows])
    threshold_y = np.array([r[TARGETS["fraud"]] for r in threshold_rows])
    operating = fraud_operating_points(threshold_y, fraud_scores(trained, threshold_x))
    chosen = operating["precision_at_least_50pct"]
    # A missing precision floor blocks promotion; fallback still allows honest evaluation.
    trained["threshold"] = (chosen or operating["max_f1"])["threshold"]
    trained["categories"] = {
        key: sorted({f[key] for f in feats}) for key in ("claim_type", "state")
    }
    numeric = [key for key in FEATURES["fraud"] if key not in {"claim_type", "state"}]
    trained["numeric_bounds"] = {
        key: [float(min(f[key] for f in feats)), float(max(f[key] for f in feats))]
        for key in numeric
    }
    trained["reference"] = {
        **{
            key: max(trained["categories"][key], key=lambda v: sum(f[key] == v for f in feats))
            for key in ("claim_type", "state")
        },
        **{key: float(np.median([f[key] for f in feats])) for key in numeric},
    }
    trained["training_policy_ids"] = sorted({r["policy_id"] for r in rows})
    trained["feature_engineering"] = {
        "ratios": encoder.ratios,
        "type_medians": encoder.type_medians_,
        "global_median": encoder.global_median_,
        "seeds": list(SEEDS),
    }
    rng = np.random.default_rng(42)
    base_ap = average_precision_score(cal_y, fraud_scores(trained, cal_x))
    importance = []
    for key in FEATURES["fraud"]:
        order = rng.permutation(len(cal_feats))
        shuffled = [{**f, key: cal_feats[int(order[i])][key]} for i, f in enumerate(cal_feats)]
        changed = fraud_scores(trained, encoder.transform(shuffled))
        importance.append((key, float(base_ap - average_precision_score(cal_y, changed))))
    importance.sort(key=lambda pair: -pair[1])
    effects = _effects("fraud", trained, feats, cal_feats, rng)
    trained["explanation"] = {
        "scope": "global_probability_calibration_source_feature_permutation_importance",
        "interpretation": "Source features shuffled and ratios recomputed; associations, not causality",
        "scoring": "average_precision",
        "features": [{"feature": k, "score_drop": v} for k, v in importance],
        "effects": effects,
        "effects_method": "Partial dependence with derived ratios recomputed; not causal",
        "summary": _summarize("fraud", effects, [key for key, _ in importance]),
    }
    return trained, operating, chosen is not None


def test_metrics(trained, rows, operating):
    labels = np.array([r[TARGETS["fraud"]] for r in rows])
    x = trained["vectorizer"].transform([feature_dict(r, "fraud") for r in rows])
    scores = fraud_scores(trained, x)
    return {
        **fraud_classification_metrics(labels, scores, trained["threshold"]),
        "average_precision": float(average_precision_score(labels, scores)),
        "brier": float(brier_score_loss(labels, scores)),
        "operating_points": {
            name: fraud_classification_metrics(labels, scores, point["threshold"])
            if point is not None
            else None
            for name, point in operating.items()
        },
    }


@threadpool_limits.wrap(limits=2)
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-seed", type=int, default=314159)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    artifact_dir = settings.claims_artifact_dir
    service = AnalyticsService(
        settings.claims_data_path, artifact_dir, settings.claims_parquet_path, 600_000, "1GB"
    )
    report_path = artifact_dir / "fraud_feature_experiment.json"
    protocol_path = artifact_dir / "fraud_feature_protocol.json"
    candidate_path = artifact_dir / "claims_models.feature_candidate.joblib"
    if args.verify_only:
        service._bundle = joblib.load(candidate_path)
        print(json.dumps(verify_holdout(service), indent=2))
        return
    if report_path.exists() or protocol_path.exists():
        raise ValueError(
            "This holdout is reserved/consumed; use --verify-only instead of retuning it"
        )
    started = time.monotonic()
    initial = copy.deepcopy(service._bundle)
    if initial is None:
        raise ValueError("Verified incumbent artifact is required")
    protocol = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "incumbent_artifact_sha256": file_digest(artifact_dir / "claims_models.joblib"),
        "cohort_seed": args.cohort_seed,
        "sample_rows": 600_000,
        "training_rows": 100_000,
        "windows": dict(zip(COHORT_NAMES, WINDOWS)),
        "seeds": list(SEEDS),
        "configurations": list(CONFIGURATIONS),
        "minimum_precision": 0.5,
        "review_cap": 0.1,
        "promotion_rule": "Validation mean recall@50% precision +2pp; mean AP +0.01; recall@10% review not worse; AP not worse on either temporal fold",
        "test_used_for_selection": False,
    }
    protocol_path.write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    print(
        "Reconstruct incumbent source sample; reserve new policies before model fitting", flush=True
    )
    original, origin = service._read_rows()
    partitions, _ = temporal_split(original)
    expected_digest = initial["report"]["origin"].get("sample_claim_ids_sha256")
    if origin.get("sample_claim_ids_sha256") != expected_digest:
        raise ValueError("Original source sample changed")
    excluded_policies = {r["policy_id"] for r in original}
    expanded_path = ROOT / "data" / "processed" / "ml" / "fraud_training_expanded.parquet"
    expanded = ClaimsStore(expanded_path, memory_limit="512MB", threads=1)
    try:
        excluded_policies.update(
            r["policy_id"]
            for r in expanded._run(f"SELECT DISTINCT policy_id FROM {expanded.source}")
        )
    finally:
        expanded.close()
    indices = np.random.default_rng(42).permutation(len(partitions[0]))[:100_000]
    training = sorted(
        [partitions[0][int(i)] for i in indices],
        key=lambda r: (r["claim_filed_date"], r["claim_id"]),
    )
    del original, partitions
    source = ClaimsStore(settings.claims_parquet_path, memory_limit="1GB", threads=1)
    try:
        source.connection.execute("SET enable_progress_bar=false")
        fresh = source.sample(600_000, seed=args.cohort_seed)
    finally:
        source.close()
    groups, excluded = fresh_cohorts(fresh, excluded_policies)
    del fresh
    protocol.update(
        excluded_rows=excluded,
        counts=dict(zip(COHORT_NAMES, map(len, groups))),
        excluded_prior_policy_count=len(excluded_policies),
        cohort_rows_sha256={name: rows_digest(rows) for name, rows in zip(COHORT_NAMES, groups)},
    )
    for name, group in zip(COHORT_NAMES, groups):
        if len(group) < 200:
            raise ValueError(f"Insufficient fresh {name} claims")
    dataset_dir = ROOT / "data" / "processed" / "ml"
    holdout_path = dataset_dir / "fraud_feature_holdout.parquet"
    export_training(groups[-1], holdout_path)
    protocol["holdout_parquet_sha256"] = file_digest(holdout_path)
    # Keep final test rows off the candidate-fitting path entirely.
    del groups[-1]
    protocol_path.write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    results = []
    print(json.dumps({"reserved_cohort_counts": protocol["counts"]}), flush=True)
    for configuration in CONFIGURATIONS:
        tick = time.monotonic()
        print(f"Fit {configuration}: two seeds, 100,000 original training claims", flush=True)
        encoder, models, iterations = fit_configuration(configuration, training)
        folds = []
        per_seed = []
        for validation in groups[:2]:
            features = encoder.transform([feature_dict(r, "fraud") for r in validation])
            labels = np.array([r[TARGETS["fraud"]] for r in validation])
            ensemble = FraudProbabilityEnsemble(models)
            folds.append(validation_metrics(labels, ensemble.predict_proba(features)[:, 1]))
            per_seed.append(
                [
                    validation_metrics(labels, fraud_estimator_probabilities(model, features)[:, 1])
                    for model in models
                ]
            )
        mean = {
            key: float(np.mean([f[key] for f in folds]))
            for key in ("average_precision", "recall_at_50pct_precision", "recall_at_10pct_review")
        }
        result = {
            "configuration": configuration,
            "iterations": iterations,
            "folds": folds,
            "per_seed": per_seed,
            "mean": mean,
            "elapsed_seconds": round(time.monotonic() - tick, 2),
        }
        results.append(result)
        report_path.write_text(
            json.dumps({"protocol": protocol, "validation_results": results}, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"configuration": configuration, "mean_validation": mean}), flush=True)
    winner, eligible = validation_decision(results)
    report = {
        "protocol": protocol,
        "validation_results": results,
        "selected_configuration": winner["configuration"],
        "validation_promotion_eligible": eligible,
        "selection_frozen_at": datetime.now(UTC).isoformat(),
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    fit_rows = sorted(
        training + groups[0] + groups[1], key=lambda r: (r["claim_filed_date"], r["claim_id"])
    )
    print(
        f"Refit frozen {winner['configuration']}; calibrate on later disjoint cohorts", flush=True
    )
    trained, operating, precision_feasible = calibrated_model(
        winner["configuration"], fit_rows, groups[2], groups[3], winner["iterations"]
    )
    report["precision_floor_feasible"] = precision_feasible
    # This is the first evaluation on the frozen final cohort, after all decisions.
    snapshot = ClaimsStore(holdout_path, memory_limit="512MB", threads=1)
    try:
        test_rows = snapshot.rows(f"SELECT * FROM {snapshot.source}")
    finally:
        snapshot.close()
    print("Evaluate frozen candidate and incumbent on the new final cohort", flush=True)
    measured = test_metrics(trained, test_rows, operating)
    incumbent = initial["models"]["fraud"]
    incumbent_result = test_metrics(incumbent, test_rows, {})
    report["fresh_holdout_candidate"] = measured
    report["fresh_holdout_incumbent"] = incumbent_result
    labels = np.array([r[TARGETS["fraud"]] for r in test_rows])
    prior = float(np.mean([r[TARGETS["fraud"]] for r in fit_rows]))
    metric = {
        "available": True,
        "selected_model": winner["configuration"],
        "counts": {
            "train": len(training),
            "calibration": sum(map(len, groups)),
            "test": len(test_rows),
        },
        "positive_counts": [
            sum(r[TARGETS["fraud"]] for r in training),
            sum(r[TARGETS["fraud"]] for g in groups for r in g),
            int(labels.sum()),
        ],
        **{
            key: measured[key]
            for key in ("precision", "recall", "f1", "accuracy", "balanced_accuracy")
        },
        "pr_auc_average_precision": measured["average_precision"],
        "baseline_pr_auc": float(labels.mean()),
        "brier_score": measured["brier"],
        "baseline_brier_score": float(brier_score_loss(labels, np.full(len(labels), prior))),
        "majority_accuracy": float(np.mean(~labels)),
        "review_threshold": trained["threshold"],
        "refit_rows": len(fit_rows),
        "calibration_roles": dict(zip(COHORT_NAMES[:4], map(len, groups))),
        "calibration": "Log-odds sigmoid on fresh probability cohort; separate precision-floor threshold cohort",
        "selection": protocol["promotion_rule"],
        "class_weight": None,
        "threshold_cohort_operating_points": operating,
        "heldout_operating_points": measured["operating_points"],
        "global_explanation": trained["explanation"],
    }
    trained["evaluation_cohort"] = {
        "path": str(holdout_path),
        "parquet_sha256": file_digest(holdout_path),
        "rows_sha256": rows_digest(test_rows),
        "source_sample_seed": args.cohort_seed,
        "minimum_filing_date": WINDOWS[-1],
        "protocol_path": str(protocol_path),
    }
    service._bundle["models"]["fraud"] = trained
    service._bundle["report"]["metrics"]["fraud"] = metric
    now = datetime.now(UTC).isoformat()
    service._bundle["report"]["task_trained_at"] = {
        **initial["report"].get("task_trained_at", {}),
        "fraud": now,
    }
    service._bundle["report"]["trained_at"] = now
    joblib.dump(service._bundle, candidate_path)
    check = AnalyticsService(
        settings.claims_data_path, artifact_dir, settings.claims_parquet_path, 600_000, "1GB"
    )
    check._bundle = joblib.load(candidate_path)
    print("Independently verify reloaded artifact and original source labels", flush=True)
    report["verification"] = verify_holdout(check)
    report["promoted"] = eligible and precision_feasible
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if report["promoted"]:
        joblib.dump(initial, artifact_dir / "claims_models.before_feature_experiment.joblib")
        prior_report = (artifact_dir / "retraining_report.json").read_text()
        (artifact_dir / "retraining_report.before_feature_experiment.json").write_text(
            prior_report, encoding="utf-8"
        )
        temporary = artifact_dir / "claims_models.feature_activation.tmp"
        joblib.dump(check._bundle, temporary)
        temporary.replace(artifact_dir / "claims_models.joblib")
        output = {
            "report": compact(check.status()),
            "verification": report["verification"],
            "elapsed_seconds": report["elapsed_seconds"],
            "fraud_feature_report": str(report_path),
        }
        (artifact_dir / "retraining_report.json").write_text(
            json.dumps(output, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "promoted": report["promoted"],
                "selected": winner["configuration"],
                "candidate_fresh_holdout": {
                    k: v for k, v in measured.items() if k != "operating_points"
                },
                "incumbent_fresh_holdout": incumbent_result,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
