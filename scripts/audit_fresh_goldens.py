"""Fresh live Synapt/author goldens in an isolated DB, without 100M-row scans or model loads."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from claims.core.demo_cases import DEMO_CASES
from claims.core.settings import Settings
from claims.evaluation.service import EvaluationService
from claims.investigation.workflow import InvestigationService
from claims.ml.analytics import AnalyticsService
from claims.synapt.adapter import build_synapt_adapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("artifacts/evaluation/audit-2026-10-07/fresh"))
    args = parser.parse_args()
    settings = Settings()
    if settings.agent_mode != "live":
        raise SystemExit("Fresh live goldens require live agents (Synapt is always live)")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    settings = settings.model_copy(update={
        "claims_database_path": args.output_dir / f"fresh-{uuid4()}.sqlite",
        "claims_data_path": args.output_dir / "missing-data.json",
        "claims_parquet_path": args.output_dir / "missing-data.parquet",
        "claims_artifact_dir": args.output_dir / "missing-models",
        "judge_mode": "off",
    })
    analytics = AnalyticsService(settings.claims_data_path, settings.claims_artifact_dir,
                                 settings.claims_parquet_path, settings.claims_train_rows,
                                 settings.claims_duckdb_memory)
    service = InvestigationService(settings, build_synapt_adapter(settings), analytics)
    started = time.monotonic()

    class RecordingService:
        store = service.store

        def create(self, claim, filters):
            run = service.create(claim, filters)
            index = len(list(args.output_dir.glob("case-*.json")))
            name = next((d["id"] for d in DEMO_CASES
                         if d["claim"]["description"] == claim.description), f"case-{index}")
            (args.output_dir / f"case-{name}.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
            print(json.dumps({"case": name, "status": run["status"],
                              "validation": run.get("validation")}), flush=True)
            return run

    try:
        report = EvaluationService(RecordingService(), settings).run()
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report["scope"] = (
            "Fresh live Synapt retrieval and live authored synthetic briefs; deterministic "
            "golden checks and availability guards. No real dataset scan, ML predictions, "
            "DeepEval calls, handler acceptance or Synapt writes."
        )
        (args.output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: report[k] for k in ("passed", "total", "overall_passed", "elapsed_seconds")}), flush=True)
    finally:
        service.close()


if __name__ == "__main__":
    main()
