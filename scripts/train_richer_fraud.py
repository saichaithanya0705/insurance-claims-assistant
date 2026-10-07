"""Freeze a richer source's cohorts; compare feature groups; independently verify.

This source-specific experiment cannot overwrite the active production bundle.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.fraud_features import file_digest, rows_digest
from claims.richer_data import MENDELEY_ID, production_blockers, verified_records
from claims.richer_fraud import (
    CONFIGURATIONS,
    ROLE_NAMES,
    SEEDS,
    calibrate,
    choose_configurations,
    fit_models,
    measure,
    raw_validation,
    temporal_cohorts,
)


def verify(bundle):
    manifest, rows = verified_records(bundle["manifest_path"])
    if file_digest(bundle["manifest_path"]) != bundle["manifest_sha256"]:
        raise ValueError("Dataset manifest changed after experiment was frozen")
    lookup = {r["claim_id"]: r for r in rows}
    groups = []
    for role in ROLE_NAMES:
        group = [lookup[key] for key in bundle["cohort_ids"][role]]
        if rows_digest(group) != bundle["protocol"]["cohorts"][role]["rows_sha256"]:
            raise ValueError(f"Original {role} features or labels changed")
        groups.append(group)
    policies = [{r["policy_id"] for r in g} for g in groups]
    if any(policies[i] & policies[j] for i in range(5) for j in range(i + 1, 5)):
        raise ValueError("Policy leakage in source-specific evaluation")
    date_field = bundle["protocol"]["split"].get("date_field", "incident_date")
    if any(
        max(r[date_field] for r in groups[i]) >= min(r[date_field] for r in groups[i + 1])
        for i in range(4)
    ):
        raise ValueError("Date overlap in source-specific evaluation")
    reproduced = {}
    for name, model in bundle["models"].items():
        measured = measure(model, groups[-1])
        for key, value in measured.items():
            if not np.isclose(value, bundle["metrics"][name][key], atol=1e-12, rtol=0):
                raise ValueError(f"Reloaded {name}/{key} differs from saved result")
        reproduced[name] = measured
    return {
        "source_labels_and_features_match": True,
        "metrics_match": True,
        "policy_overlap": 0,
        "test_rows": len(groups[-1]),
        "test_positives": sum(r["is_fraud"] for r in groups[-1]),
        "recomputed_metrics": reproduced,
        "production_blockers": production_blockers(manifest, rows),
    }


@threadpool_limits.wrap(limits=2)
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "data/processed/ml/richer" / MENDELEY_ID / "manifest.json",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "artifacts/models/richer" / MENDELEY_ID
    )
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    artifact = args.output / "benchmark.joblib"
    report_path, protocol_path = args.output / "report.json", args.output / "protocol.json"
    if args.verify_only:
        print(json.dumps(verify(joblib.load(artifact)), indent=2))
        return
    if protocol_path.exists() or artifact.exists():
        raise ValueError("Experiment already reserved/consumed this holdout; use --verify-only")
    started = time.monotonic()
    manifest, rows = verified_records(args.manifest)
    groups, split = temporal_cohorts(rows)
    active = ROOT / "artifacts/models/claims_models.joblib"
    incumbent_sha = file_digest(active)
    protocol = {
        "frozen_at": datetime.now(UTC).isoformat(),
        "source_id": manifest["source_id"],
        "manifest_sha256": file_digest(args.manifest),
        "configurations": list(CONFIGURATIONS),
        "seeds": list(SEEDS),
        "split": split,
        "selection_rule": "Highest selection AP per feature group; recall at >=50% precision on exact ties",
        "test_used_for_selection": False,
        "automatic_production_activation": False,
        "cohorts": {
            name: {
                "rows": len(g),
                "positives": sum(r["is_fraud"] for r in g),
                "rows_sha256": rows_digest(g),
            }
            for name, g in zip(ROLE_NAMES, groups)
        },
        "assessment_fields_intake_availability_verified": False,
    }
    protocol_path.write_text(json.dumps(protocol, indent=2), encoding="utf-8")
    print(
        json.dumps({"cohort_counts": {name: len(g) for name, g in zip(ROLE_NAMES, groups)}}),
        flush=True,
    )
    results = []
    for configuration in CONFIGURATIONS:
        trained = fit_models(configuration, groups[0])
        result = {
            "configuration": configuration,
            "iterations": trained["iterations"],
            "validation": raw_validation(trained, groups[1]),
        }
        results.append(result)
        print(json.dumps(result), flush=True)
    selected = choose_configurations(results)
    report = {
        "protocol": protocol,
        "validation_results": results,
        "selected": {name: item["configuration"] for name, item in selected.items()},
        "selection_frozen_at": datetime.now(UTC).isoformat(),
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    date_field = split.get("date_field", "incident_date")
    fit_rows = sorted(groups[0] + groups[1], key=lambda r: (r[date_field], r["claim_id"]))
    models = {
        name: calibrate(
            fit_models(item["configuration"], fit_rows, fixed_iterations=item["iterations"]),
            groups[2],
            groups[3],
        )
        for name, item in selected.items()
    }
    # First final-test evaluation, after all fitting, calibration and threshold choices.
    metrics = {name: measure(model, groups[-1]) for name, model in models.items()}
    prior = sum(r["is_fraud"] for r in fit_rows) / len(fit_rows)
    prevalence = sum(r["is_fraud"] for r in groups[-1]) / len(groups[-1])
    bundle = {
        "schema_version": 1,
        "scope": "isolated_retrospective_auto_claims_benchmark",
        "manifest_path": str(args.manifest.resolve()),
        "manifest_sha256": protocol["manifest_sha256"],
        "protocol": protocol,
        "models": models,
        "metrics": metrics,
        "cohort_ids": {name: [r["claim_id"] for r in g] for name, g in zip(ROLE_NAMES, groups)},
        "production_eligible": False,
        "production_blockers": production_blockers(manifest, rows),
    }
    joblib.dump(bundle, artifact)
    report.update(
        metrics=metrics,
        majority_baseline={
            "accuracy": 1 - prevalence,
            "recall": 0,
            "average_precision": prevalence,
            "brier": prevalence * (1 - prior) ** 2 + (1 - prevalence) * prior**2,
        },
        training_prior=prior,
        threshold_policies={
            name: {
                "policy": m["threshold_policy"],
                "calibration": m["calibration_status"],
                "tuning_metrics": m["threshold_cohort_metrics"],
            }
            for name, m in models.items()
        },
        verification=verify(joblib.load(artifact)),
        promoted=False,
        production_blockers=bundle["production_blockers"],
    )
    if file_digest(active) != incumbent_sha:
        raise ValueError("Active artifact changed during isolated experiment")
    report.update(
        active_artifact_sha256_unchanged=incumbent_sha,
        artifact_sha256=file_digest(artifact),
        elapsed_seconds=round(time.monotonic() - started, 2),
    )
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "metrics": metrics,
                "majority_baseline": report["majority_baseline"],
                "production_eligible": False,
                "active_artifact_unchanged": True,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
