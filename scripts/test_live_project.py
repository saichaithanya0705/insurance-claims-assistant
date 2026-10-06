"""Explicit live evaluator using synthetic claims, a separate DB and no remote writes."""

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from claims.api import app as default_app
from claims.api import create_app
from claims.demo import DEMO_CASES
from claims.models import ClaimInput
from claims.settings import Settings


def main(resume=False):
    settings = Settings()
    if settings.synapt_mode != "live" or settings.agent_mode != "live":
        raise SystemExit("This test requires live Synapt and live agents.")
    if settings.llm_base_url != "https://integrate.api.nvidia.com/v1":
        raise SystemExit("This evaluator sends synthetic claims only to NVIDIA.")
    default_app.state.service.close()
    settings.claims_database_path = Path(f"data/runtime/evaluator-{uuid4()}.sqlite")
    target = Path("artifacts/evaluation/live-2026-10-06")
    target.mkdir(parents=True, exist_ok=True)
    cases = list(DEMO_CASES)
    base = DEMO_CASES[0]["claim"]
    for kind, description, documents in [
        (
            "renters",
            "Water damaged a tenant's personal belongings. Ownership and item amounts need clarification.",
            ["incident statement"],
        ),
        (
            "business",
            "A fire damaged office equipment. The claimed figure is an estimate; accounting evidence is pending.",
            ["incident statement"],
        ),
        (
            "property",
            "A storm damaged the detached garage roof. Photographs and an itemized repair estimate are available.",
            ["incident statement", "damage photographs", "repair estimate"],
        ),
    ]:
        cases.append(
            {
                "id": kind,
                "claim": base
                | {"claim_type": kind, "description": description, "provided_documents": documents},
            }
        )
    for case in cases:
        ClaimInput.model_validate(case["claim"])
    report = {
        "provider_id": settings.synapt_provider_id,
        "synapt_mode": "live",
        "agent_mode": "live",
        "model": settings.llm_model,
        "database": str(settings.claims_database_path),
        "cases": [],
        "api_checks": {},
    }
    if resume:
        report = json.loads((target / "report.json").read_text(encoding="utf-8"))
        if report["provider_id"] != settings.synapt_provider_id:
            raise SystemExit("Resume provider differs from current configuration.")
        settings.claims_database_path = Path(report["database"])
    started = time.monotonic()
    app = create_app(settings)
    key = settings.claims_api_key.get_secret_value()
    headers = {"X-Claims-Api-Key": key} if key else {}
    replay_id = next(
        (c["run_id"] for c in report["cases"] if c["checks"].get("review_accepted")), None
    )
    with TestClient(app, headers=headers) as client:
        report["api_checks"]["initially_unverified"] = not client.get("/api/health").json()[
            "synapt_live_verified"
        ]
        report["model_status"] = client.get("/api/models/status").json()
        for case in cases:
            if any(c["case"] == case["id"] for c in report["cases"]):
                continue
            begin = time.monotonic()
            response = client.post("/api/investigations", json={"claim": case["claim"]})
            response.raise_for_status()
            run = response.json()
            (target / f"case-{case['id']}.json").write_text(
                json.dumps(run, indent=2), encoding="utf-8"
            )
            ids = {e["source_id"] for e in run.get("evidence", [])}
            cited = run.get("findings", []) + run.get("recommendations", [])
            checks = {
                "reached_review": run["status"] in ("awaiting_review", "needs_manual_review"),
                "live_source_evidence": any(
                    e["provenance"] == "synapt" and e["provider_id"] == settings.synapt_provider_id
                    for e in run.get("evidence", [])
                ),
                "no_fixture_evidence": all(
                    e["provenance"] != "synthetic_fixture" for e in run.get("evidence", [])
                ),
                "citations_resolve": bool(cited)
                and all(s in ids for item in cited for s in item["source_ids"]),
                "recommendations_cited": bool(run.get("recommendations"))
                and all(item["source_ids"] for item in run.get("recommendations", [])),
                "human_gate": run.get("review") is None,
                "mode_truthful": run.get("mode") == "live" and run.get("agent_mode") == "live",
            }
            if case["id"] == "unknown":
                checks["ambiguous_abstention"] = (
                    run.get("classification", {}).get("needs_review") is True
                    and run.get("validation", {}).get("passed") is False
                )
            if case["id"] == "theft-gap":
                checks["missing_evidence_surfaced"] = any(
                    f["kind"] == "gap" for f in run.get("findings", [])
                )
            if case["id"] == "home-conflict":
                checks["contradiction_surfaced"] = any(
                    f["kind"] == "contradiction" for f in run.get("findings", [])
                )
            if run["status"] in ("awaiting_review", "needs_manual_review"):
                decision = {
                    "decision": "accept_brief",
                    "note": "Synthetic evaluator: source identities and review boundaries inspected.",
                }
                review = client.post(f"/api/investigations/{run['run_id']}/review", json=decision)
                if run.get("validation", {}).get("passed"):
                    checks["review_accepted"] = (
                        review.status_code == 200 and review.json()["status"] == "reviewed"
                    )
                    checks["duplicate_review_blocked"] = (
                        client.post(
                            f"/api/investigations/{run['run_id']}/review", json=decision
                        ).status_code
                        == 409
                    )
                    replay_id = replay_id or run["run_id"]
                else:
                    checks["invalid_acceptance_blocked"] = review.status_code == 409
                    revision = client.post(
                        f"/api/investigations/{run['run_id']}/review",
                        json={
                            "decision": "request_revision",
                            "note": "Clarify ambiguous category and evidence before accepting.",
                        },
                    )
                    checks["revision_allowed"] = (
                        revision.status_code == 200
                        and revision.json()["status"] == "revision_requested"
                    )
            feedback = client.post(
                f"/api/investigations/{run['run_id']}/feedback",
                json={
                    "rating": 4,
                    "note": "Synthetic evaluator feedback; candidate lesson requires review.",
                },
            )
            checks["local_feedback_saved"] = feedback.status_code == 200
            summary = {
                "case": case["id"],
                "run_id": run["run_id"],
                "status": run["status"],
                "validation": run.get("validation"),
                "elapsed_seconds": round(time.monotonic() - begin, 2),
                "checks": checks,
                "passed": all(checks.values()),
            }
            report["cases"].append(summary)
            (target / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(summary), flush=True)
        report["api_checks"]["health_verified_after_retrieval"] = client.get("/api/health").json()[
            "synapt_live_verified"
        ]
        report["api_checks"]["integration_verified_after_retrieval"] = client.get(
            "/api/integration/status"
        ).json()["live_verified"]
        report["api_checks"]["bad_dates_rejected"] = (
            client.post(
                "/api/investigations", json={"claim": base | {"claim_filed_date": "2020-01-01"}}
            ).status_code
            == 422
        )
        report["api_checks"]["missing_run_404"] = (
            client.get("/api/investigations/nonexistent").status_code == 404
        )
        search = client.post(
            "/api/search",
            json={
                "claim": base,
                "filters": {"claim_type": "auto", "state": "TX", "claim_status": "approved"},
            },
        )
        report["api_checks"]["live_filtered_search"] = (
            search.status_code == 200 and search.json().get("mode") == "live"
        )
        if search.status_code == 200:
            matched = search.json()["similar_cases"]
            report["api_checks"]["all_search_filters_respected"] = bool(matched) and all(
                c["claim_type"] == "auto" and c["state"] == "TX" and c["claim_status"] == "approved"
                for c in matched
            )
            report["search"] = {
                "similar_cases": search.json()["similar_cases"],
                "semantic_case_matches": search.json()["semantic_case_matches"],
                "warnings": search.json()["warnings"],
            }
        predictions = client.post("/api/predictions", json=base)
        report["api_checks"]["prediction_endpoint"] = (
            predictions.status_code == 200 and predictions.json().get("available") is True
        )
        report["predictions"] = predictions.json()
        lessons = client.get("/api/feedback/lessons").json()
        report["api_checks"]["lessons_review_gated"] = "no automatic" in lessons["promotion"]
        rows = app.state.service.store.connection.execute("SELECT kind,body FROM audit").fetchall()
        secrets = [
            settings.synapt_password.get_secret_value(),
            settings.synapt_username,
            settings.llm_api_key.get_secret_value(),
        ]
        report["api_checks"]["audit_credentials_absent"] = not any(
            secret and secret in row["body"] for secret in secrets for row in rows
        )
        report["model_outputs"] = sum(row["kind"] == "model_output" for row in rows)
        report["model_failures"] = sum(row["kind"] == "model_failure" for row in rows)
    replay_app = create_app(settings)
    with TestClient(replay_app, headers=headers) as client:
        report["api_checks"]["review_persists_after_restart"] = (
            bool(replay_id)
            and client.get(f"/api/investigations/{replay_id}").json()["status"] == "reviewed"
        )
    report["elapsed_seconds_this_invocation"] = round(time.monotonic() - started, 2)
    report["sum_case_elapsed_seconds"] = round(
        sum(c["elapsed_seconds"] for c in report["cases"]), 2
    )
    report["passed"] = sum(c["passed"] for c in report["cases"])
    report["total"] = len(cases)
    report["scope"] = (
        "Live source retrieval, schema/citation/behavior gates and local persistence; not proof of semantic accuracy, production scale, coverage or fraud. No Synapt ingestion/feedback mutations."
    )
    (target / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "total": report["total"],
                "api_checks": report["api_checks"],
                "elapsed_seconds_this_invocation": report["elapsed_seconds_this_invocation"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue the evaluator checkpoint without repeating completed provider calls.",
    )
    main(parser.parse_args().resume)
