"""Replay saved briefs through deterministic evals and optional real provider judges.

No training, corpus writes, handler acceptance or real dataset scans. Live mode sends
only the saved synthetic briefs and their recorded evidence to the configured provider.
This validates evaluators; it does not certify current retrieval or regenerate briefs.
"""

import argparse
import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from claims.core.demo_cases import DEMO_CASES
from claims.core.settings import Settings
from claims.evaluation.judge import LLMJudge
from claims.evaluation.service import EvaluationService
from claims.storage.run_store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("artifacts/evaluation/audit-2026-10-07"))
    parser.add_argument("--live", action="store_true", help="Run real DeepEval and inline judges")
    parser.add_argument("--resume", action="store_true",
                        help="Reuse completed metrics from the latest local audit checkpoint")
    args = parser.parse_args()
    settings = Settings()
    outputs = []
    for demo in DEMO_CASES:
        candidates = [args.snapshot_dir / f"browser-eval-{demo['id']}.json",
                      args.snapshot_dir / f"case-{demo['id']}.json"]
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            raise SystemExit(f"Missing synthetic brief for {demo['id']}")
        output = json.loads(path.read_text(encoding="utf-8"))
        if output.get("claim", {}).get("description") != demo["claim"]["description"]:
            raise SystemExit(f"Snapshot does not match the demo input for {demo['id']}")
        outputs.append(output)
    if args.live and not (settings.deepeval_model and settings.llm_api_key.get_secret_value()):
        raise SystemExit("Live evaluation requires configured model and API key")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    databases = list(args.output_dir.glob("audit-*.sqlite")) if args.resume else []
    audit_path = (max(databases, key=lambda p: p.stat().st_mtime) if databases
                  else args.output_dir / f"audit-{uuid4()}.sqlite")
    prior_results = []
    if databases:
        with sqlite3.connect(audit_path) as connection:
            prior_results = [json.loads(row[0]) for row in connection.execute(
                "SELECT body FROM audit WHERE kind='judge_metric_result' ORDER BY id")]
    store = Store(audit_path)

    class Replay:
        def __init__(self):
            self.store = store
            self.outputs = iter(outputs)

        def create(self, claim, filters):
            return next(self.outputs)

    started = time.monotonic()
    try:
        class ResumableEvaluation(EvaluationService):
            def _judge(self, runs):
                return super()._judge(runs, prior_results=prior_results)

        evaluation = ResumableEvaluation(Replay(), settings)
        report = evaluation.run(judge=args.live)
        report["snapshot_directory"] = str(args.snapshot_dir.resolve())
        report["reused_completed_metrics"] = sum(
            r.get("status") == "completed" for r in prior_results)
        report["scope"] = (
            "Saved synthetic-brief evaluator replay; live judge calls when requested. "
            "Not a fresh retrieval, current corpus verification or real-world accuracy measurement."
        )
        report["inline_judges"] = []
        (args.output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        if args.live:
            judge = LLMJudge(settings, store.event)
            for demo, output in zip(DEMO_CASES, outputs, strict=True):
                verdict = judge.evaluate(output, output["run_id"])
                report["inline_judges"].append({"case": demo["id"], **verdict})
                (args.output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(json.dumps({"case": demo["id"], "inline_status": verdict["status"],
                                  "passed": verdict.get("passed"), "score": verdict.get("score")}), flush=True)
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        (args.output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({k: report.get(k) for k in (
            "passed", "total", "judge_status", "judge_completed_metrics", "judge_passed_metrics",
            "judge_quality_passed", "overall_passed", "elapsed_seconds")}), flush=True)
    finally:
        store.close()


if __name__ == "__main__":
    main()
