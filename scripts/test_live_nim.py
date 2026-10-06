"""Explicit NVIDIA-only live API validation on synthetic fixtures. Never runs in pytest."""

import argparse
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from claims.api import create_app
from claims.models import ReviewDecision
from claims.settings import Settings


def main(judge=False):
    settings = Settings()
    if settings.agent_mode != "live" or settings.synapt_mode != "fixture":
        raise SystemExit("This test requires AGENT_MODE=live and SYNAPT_MODE=fixture")
    if settings.llm_base_url != "https://integrate.api.nvidia.com/v1":
        raise SystemExit("This test sends synthetic scenarios only to the NVIDIA hosted endpoint")
    app = create_app(settings)
    started = time.perf_counter()
    with TestClient(app) as client:
        audit_before = app.state.service.store.connection.execute(
            "SELECT COALESCE(MAX(id),0) FROM audit"
        ).fetchone()[0]
        key = settings.claims_api_key.get_secret_value()
        headers = {"X-Claims-Api-Key": key} if key else {}
        response = client.post("/api/evaluations/run", json={"judge": judge}, headers=headers)
        response.raise_for_status()
        evaluation = response.json()
        summaries = []
        service = app.state.service
        for case in evaluation["cases"]:
            run = service.store.get(case["run_id"])
            review_status = "not_accepted"
            if run.get("validation", {}).get("passed"):
                decision = ReviewDecision(
                    decision="accept_brief",
                    note="Synthetic live test: verified source IDs and displayed limitations",
                )
                reviewed = client.post(
                    f"/api/investigations/{run['run_id']}/review",
                    json=decision.model_dump(),
                    headers=headers,
                )
                reviewed.raise_for_status()
                review_status = reviewed.json()["status"]
                duplicate = client.post(
                    f"/api/investigations/{run['run_id']}/review",
                    json=decision.model_dump(),
                    headers=headers,
                )
                if duplicate.status_code != 409:
                    raise RuntimeError("Duplicate review was not blocked")
            elif run["status"] != "failed":
                blocked = client.post(
                    f"/api/investigations/{run['run_id']}/review",
                    json={"decision": "accept_brief", "note": "Synthetic rejection check"},
                    headers=headers,
                )
                if blocked.status_code != 409:
                    raise RuntimeError("Invalid brief acceptance was not blocked")
            summaries.append(
                {
                    "case": case["case"],
                    "run_id": run["run_id"],
                    "status": run["status"],
                    "checks": case["checks"],
                    "validation": run.get("validation"),
                    "classification": run.get("classification"),
                    "review_test": review_status,
                }
            )
        rows = service.store.connection.execute(
            "SELECT kind,body FROM audit WHERE id>? AND kind IN ('model_output','model_failure','model_prompt') ORDER BY id",
            (audit_before,),
        ).fetchall()
        outputs = [json.loads(row["body"]) for row in rows if row["kind"] == "model_output"]
        failures = [json.loads(row["body"]) for row in rows if row["kind"] == "model_failure"]
        if any(settings.llm_api_key.get_secret_value() in row["body"] for row in rows):
            raise RuntimeError("Credential appeared in local model audit")
        report = {
            "model": settings.llm_model,
            "synapt_mode": "fixture",
            "agent_mode": "live",
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "evaluation": evaluation,
            "cases": summaries,
            "model_outputs_in_audit": len(outputs),
            "model_failures_in_audit": len(failures),
            "usage": {
                field: sum(o.get("usage", {}).get(field, 0) for o in outputs)
                for field in ("prompt_tokens", "completion_tokens", "total_tokens")
            },
            "credential_in_audit": False,
            "synapt_network_calls": 0,
            "scope": "Live NVIDIA inference on synthetic fixture evidence; no live Synapt retrieval or real-world accuracy claim.",
        }
        target = Path("data/runtime/live_nim_validation.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--judge", action="store_true", help="Also execute the configured DeepEval judge"
    )
    main(parser.parse_args().judge)
