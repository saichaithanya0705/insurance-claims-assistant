"""How a brief was generated and evaluated: lineage, ranking, priority, checks and audience rules."""

import copy
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from claims.api.main import create_app
from claims.core.demo_cases import DEMO_CASES
from claims.core.schemas import ClaimInput
from claims.core.settings import Settings
from claims.evaluation.judge import PASS_SCORE
from claims.investigation import priority
from claims.investigation.workflow import VALIDATION_CHECKS, validate_brief
from claims.observability import explain


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        claims_database_path=tmp_path / "runtime.sqlite",
        claims_data_path=tmp_path / "absent.json",
        claims_artifact_dir=tmp_path / "models",
        claims_search_enabled=False,
    )


@pytest.fixture
def explained(settings):
    """(raw run, admin explanation, handler explanation) for a fixture-mode theft claim."""
    app = create_app(settings)
    with TestClient(app) as client:
        run = client.post("/api/investigations", json={"claim": DEMO_CASES[1]["claim"]}).json()
        admin = client.get(f"/api/investigations/{run['run_id']}/explanation").json()
        raw = app.state.service.store.get(run["run_id"])
    user = explain.explain_run(raw, None, "user")
    return raw, admin, user


def test_the_pipeline_walks_every_stage_with_its_method_and_outputs(explained):
    _, admin, _ = explained
    assert [s["stage"] for s in admin["pipeline"]] == [name for name, _ in explain.STAGES]
    kinds = {s["stage"]: s["kind"] for s in admin["pipeline"]}
    # Fixture mode: rules write the brief, a person gates it, models only estimate.
    assert kinds == {
        "classify": "rules", "retrieve": "search", "investigate": "rules", "risk": "statistics",
        "recommend": "rules", "validate": "rules", "supervise": "off", "judge": "off", "review": "human",
    }
    assert admin["generation"] == "rules"
    retrieve = next(s for s in admin["pipeline"] if s["stage"] == "retrieve")
    assert any("comparable claims" in line for line in retrieve["outputs"])
    assert all(s["duration_ms"] is not None for s in admin["pipeline"][:-1])  # a recorded trace
    judge = next(s for s in admin["pipeline"] if s["stage"] == "judge")
    assert judge["status"] == "skipped"
    assert next(s for s in admin["pipeline"] if s["stage"] == "review")["status"] == "waiting"
    assert "finding" in admin["headline"] and "priority" in admin["headline"]


def test_every_finding_and_recommendation_traces_to_its_sources(explained):
    raw, admin, _ = explained
    rows = admin["lineage"]
    assert len(rows) == len(raw["findings"]) + len(raw["recommendations"])
    known = {e["source_id"] for e in raw["evidence"]}
    for row in rows:
        assert all(source["source_id"] in known for source in row["sources"])
        if row["type"] == "finding" and row["kind"] != "limitation":
            assert row["sources"] and not row["unsupported"]
    gap = next(r for r in rows if r["kind"] == "gap")
    assert any(s["category"] == "procedure" for s in gap["sources"])
    assert any(s["category"] == "claim" and s["label"] == "Submitted claim" for s in gap["sources"])
    assert gap["method"] == "rules" and gap["stage"] == "investigate"


def test_an_uncited_substantive_statement_is_flagged_not_hidden():
    run = {
        "agent_mode": "live",
        "evidence": [{"source_id": "claim:input", "title": "x", "text": "t", "provenance": "user_input"}],
        "findings": [
            {"kind": "fact", "text": "Unsupported claim.", "source_ids": []},
            {"kind": "limitation", "text": "Nothing is known.", "source_ids": []},
        ],
        "recommendations": [{"action": "Escalate to handler review", "reason": "Why.", "source_ids": ["gone"]}],
    }
    rows = explain.lineage(run, "admin")
    assert [r["unsupported"] for r in rows] == [True, False, False]
    assert rows[2]["sources"][0]["category"] == "unknown"  # a citation that resolves to nothing
    assert all(r["method"] == "ai" for r in rows)
    metrics = explain.grounding(run)
    assert metrics["substantive_findings"] == 1 and metrics["substantive_cited"] == 0
    assert metrics["citations"] == 1 and metrics["citations_resolved"] == 0
    assert metrics["sources_available"] == 1 and metrics["sources_cited"] == 0
    assert metrics["uncited_sources"] == ["claim:input"]


def test_retrieval_shows_each_methods_contribution_and_the_candidate_pool(explained):
    raw, admin, _ = explained
    retrieval = admin["retrieval"]
    assert retrieval["recorded"] and retrieval["note"] is None
    assert [m["id"] for m in retrieval["methods"]] == ["keyword", "feature", "semantic"]
    assert [m["weight"] for m in retrieval["methods"]] == [1.0, 1.0, 0.5]
    assert retrieval["candidates"]["pool_size"] >= len(raw["similar_cases"])
    assert len(retrieval["ranked"]) == len(raw["similar_cases"]) > 0
    for row, case in zip(retrieval["ranked"], raw["similar_cases"], strict=True):
        assert row["claim_id"] == case["claim_id"]
        parts = row["points"]
        assert sum(parts.values()) == pytest.approx(row["total"], abs=2e-6)
        assert row["keyword_rank"] >= 1 and row["feature_rank"] >= 1
    assert retrieval["ranked"][0]["rank"] == 1
    assert "settled" in retrieval["pool"].lower()
    assert retrieval["evidence_by_category"]["claim"] == 1
    assert retrieval["knowledge_queries"] == []  # fixture knowledge store: nothing was queried


def test_filters_are_reported_only_when_they_differ_from_the_defaults():
    run = {"filters": {"claim_type": "auto", "state": None, "claim_status": "pending",
                       "min_amount": 1000, "max_amount": 1_000_000_000,
                       "min_previous_claims": 0, "max_previous_claims": 1000}}
    shown = explain.retrieval(run, None, "admin")
    assert shown["filters"] == {"claim_type": "auto", "claim_status": "pending", "min_amount": 1000}
    assert "no outcome yet" in shown["pool"]
    assert shown["note"] and not shown["recorded"] and shown["candidates"] is None


def test_a_run_saved_before_tracing_still_explains_what_it_can(explained):
    raw, _, _ = explained
    legacy = copy.deepcopy(raw)
    del legacy["validation"]["checks"]
    result = explain.explain_run(legacy, None, "admin")
    assert result["retrieval"]["note"] and result["timeline"] is None
    assert all(row["points"] is None for row in result["retrieval"]["ranked"])
    assert all(row["total"] is not None for row in result["retrieval"]["ranked"])
    validation = result["evaluation"]["layers"][0]
    assert validation["checks_source"] == "recomputed from the saved brief"
    assert [c["id"] for c in validation["checks"]] == list(VALIDATION_CHECKS)
    assert validation["rechecked"]["matches_saved"] is True


def test_priority_explains_applied_factors_and_the_distance_to_the_next_tier():
    claim = ClaimInput(
        description="Water damage after a pipe burst in the kitchen.", claim_type="home", state="FL",
        incident_date=date(2026, 1, 1), claim_filed_date=date(2026, 3, 1), claim_amount=120_000,
        deductible=1000, previous_claims_count=5, policyholder_tenure_years=2,
    )
    findings = [{"kind": "contradiction", "text": "c", "source_ids": ["claim:input"]},
                {"kind": "gap", "text": "g", "source_ids": ["claim:input"]}]
    scored = priority.score_priority(claim, findings, {"available": False}, [], {"needs_review": False})
    result = explain.priority({"priority": scored})
    assert result["score"] == scored["score"] == 30 + 15 + 15 + 15 + 5 == 80
    assert not result["unmatched_components"]
    applied = {f["id"]: f["points"] for f in result["factors"] if f["applied"]}
    assert applied == {"amount": 30, "delay": 15, "prior": 15, "contradiction": 15, "gaps": 5}
    assert next(f for f in result["factors"] if f["id"] == "fraud_model")["applied"] is False
    assert result["next_tier"] is None  # already critical
    low = explain.priority({"priority": {"score": 15, "tier": "low", "components": []}})
    assert low["next_tier"] == {"tier": "medium", "points_needed": 5}


def test_every_priority_component_maps_to_a_rubric_factor():
    """The rubric mirrors priority.py in words; this fails if either side drifts."""
    claim = ClaimInput(
        description="Collision on the highway with extensive damage.", claim_type="auto", state="TX",
        incident_date=date(2026, 1, 1), claim_filed_date=date(2026, 3, 1), claim_amount=60_000,
        deductible=500, previous_claims_count=3, policyholder_tenure_years=1,
    )
    findings = [{"kind": "contradiction", "text": "c", "source_ids": ["claim:input"]},
                {"kind": "gap", "text": "g", "source_ids": ["claim:input"]}]
    predictions = {"available": True, "fraud": {"review_signal": True}}
    similar = [{"dataset_fraud_flag": True}, {"dataset_fraud_flag": True}]
    scored = priority.score_priority(claim, findings, predictions, similar, {"needs_review": True})
    result = explain.priority({"priority": scored})
    assert not result["unmatched_components"]
    assert {f["id"] for f in result["factors"] if f["applied"]} == {f["id"] for f in result["factors"]}
    assert sum(f["points"] for f in result["factors"]) == sum(c["points"] for c in scored["components"])
    assert [(t["tier"], t["from"]) for t in result["tiers"]] == list(priority.TIERS)
    assert tuple(explain.TIERS) == tuple(priority.TIERS)


def test_the_judge_pass_threshold_is_the_one_the_judge_uses():
    assert explain.PASS_SCORE == PASS_SCORE == 0.7


def test_validation_reports_one_row_per_rule_and_matches_the_issue_list(explained):
    raw, admin, _ = explained
    layer = admin["evaluation"]["layers"][0]
    assert layer["id"] == "validation" and layer["state"] == "passed" and layer["gate"]
    assert [c["id"] for c in layer["checks"]] == list(VALIDATION_CHECKS)
    assert all(c["passed"] and c["failed"] == 0 and c["inspected"] >= 1 for c in layer["checks"])
    assert layer["checks_source"] == "recorded" and layer["rechecked"]["matches_saved"]
    # A decision phrase in a recommended action fails the rules that cover it (the action rule and
    # the generated-text rule both scan it) and no unrelated rule.
    broken = copy.deepcopy(raw)
    broken["recommendations"][0]["action"] = "Approve claim now"
    result = validate_brief(broken)
    failed = [c["id"] for c in result["checks"] if not c["passed"]]
    assert failed == ["action_boundary", "text_boundary"] and result["passed"] is False
    assert result["issues"] == [
        "A recommendation crosses the handler decision boundary.",
        "Generated text crosses the handler decision boundary.",
    ]


def test_failed_checks_count_each_offending_item():
    state = {
        "evidence": [{"source_id": "claim:input"}],
        "findings": [
            {"kind": "fact", "text": "a", "source_ids": []},
            {"kind": "gap", "text": "b", "source_ids": ["nowhere"]},
        ],
        "recommendations": [],
        "classification": {"needs_review": True},
    }
    checks = {c["id"]: c for c in validate_brief(state)["checks"]}
    assert checks["evidence_retrieved"]["failed"] == 1
    assert checks["findings_cited"]["inspected"] == 2 and checks["findings_cited"]["failed"] == 1
    assert checks["citations_resolve"]["inspected"] == 1 and checks["citations_resolve"]["failed"] == 1
    assert checks["classification_confident"]["passed"] is False
    assert checks["recommendations_cited"]["inspected"] == 0 and checks["recommendations_cited"]["passed"]


def test_the_independent_review_is_reported_with_its_pass_criteria(explained):
    raw, _, _ = explained
    run = copy.deepcopy(raw)
    run["judge"] = {"status": "completed", "passed": False, "grounded": True, "boundary_respected": True,
                    "recommendations_supported": False, "score": 0.55, "issues": ["Recommendation 2 is unsupported."],
                    "summary": "Mostly grounded.", "model": "judge-model", "independent": True}
    run["review"] = {"decision": "request_revision", "note": "Needs another look"}
    admin = {layer["id"]: layer for layer in explain.explain_run(run, None, "admin")["evaluation"]["layers"]}
    assert admin["judge"]["passed"] is False and admin["judge"]["score"] == 0.55
    assert admin["judge"]["model"] == "judge-model" and admin["judge"]["independent"] is True
    assert "0.70" in admin["judge"]["criteria"]
    assert admin["human"]["state"] == "revision_requested" and admin["human"]["note"] == "Needs another look"
    user = {layer["id"]: layer for layer in explain.explain_run(run, None, "user")["evaluation"]["layers"]}
    assert "model" not in user["judge"] and "independent" not in user["judge"]
    assert user["judge"]["issues"] == ["Recommendation 2 is unsupported."]
    assert "suite" not in user


def test_the_system_evaluation_suite_is_shown_to_administrators_only(explained):
    raw, _, _ = explained
    suite = {"status": "completed", "passed": 4, "total": 4, "judge_status": "not_run", "scope": "regression"}
    layers = {layer["id"]: layer for layer in explain.explain_run(raw, None, "admin", suite)["evaluation"]["layers"]}
    assert layers["suite"]["passed"] == 4 and layers["suite"]["total"] == 4
    assert "suite" not in {layer["id"] for layer in explain.explain_run(raw, None, "user", suite)["evaluation"]["layers"]}


def test_handlers_never_see_vendor_names_models_or_technical_internals(explained):
    raw, _, _ = explained
    run = copy.deepcopy(raw)
    run["agent_mode"] = "live"
    run["evidence"][0]["provenance"] = "synapt"
    run["findings"].insert(0, {"kind": "limitation", "source_ids": [],
                               "text": "Optional Synapt trident_search response lacks supported provenance."})
    run["findings"].append({"kind": "limitation", "source_ids": [], "text": "Synapt returned no supporting evidence."})
    run["similar_cases"][0]["match_reasons"] = ["Related in meaning: Synapt ranked this claim card #2"]
    run["judge"] = {"status": "completed", "passed": True, "score": 0.9, "model": "openai/gpt-oss-20b",
                    "independent": True, "summary": "Synapt passages support the findings.", "issues": []}
    trace = {"source": "recorded", "summary": {"duration_ms": 12.0, "stages": [], "llm": {"calls": 3, "tokens": {"total": 99}}},
             "spans": [{"name": "synapt.call_tool", "duration_ms": 5.0,
                        "attributes": {"purpose": "claim_cards", "tool": "trident_get_chunks", "query": "q", "top_k": 20}}]}
    run["predictions"] = {
        "available": True,
        "confidence_distinction": "Statistical scores are independent of Synapt retrieval confidence",
        "warnings": ["Synapt rank is not used for this estimate"],
        "limitations": ["Synapt cards are only a sample"],
        "amount": {
            "available": True, "estimate": 1.0, "interval": [0.0, 2.0],
            "local_explanation": {"method": "Synapt-free substitution", "contributions": []},
            "global_explanation": {"summary": ["Synapt does not move this estimate"], "effects_method": "Synapt n/a", "features": []},
        },
    }
    user = json.dumps(explain.explain_run(run, trace, "user"))
    for forbidden in ("Synapt", "synapt", "gpt-oss", "trident", "nvidia", "technical", "knowledge_queries"):
        assert forbidden not in user, forbidden
    assert "retrieved source" in user
    admin = explain.explain_run(run, trace, "admin")
    assert "Synapt ranked" in json.dumps(admin)
    assert admin["technical"]["llm"]["tokens"]["total"] == 99
    assert admin["retrieval"]["knowledge_queries"][0]["tool"] == "trident_get_chunks"


def test_estimates_report_drivers_without_claiming_causes():
    run = {"predictions": {"available": True, "limitations": ["synthetic data"], "warnings": ["w"],
           "amount": {"available": True, "estimate": 5000.0, "interval": [4000.0, 6000.0],
                      "local_explanation": {"method": "One-at-a-time substitution; not causal",
                                            "contributions": [{"feature": "claim_type", "value": "auto", "typical_value": "home", "effect": -900.0}] * 7},
                      "global_explanation": {"summary": ["a", "b", "c", "d", "e"], "effects_method": "Partial dependence",
                                             "features": [{"feature": "claim_type", "score_drop": 0.2}]}},
           "resolution": {"available": False, "reason": "not trained"},
           "fraud": {"available": True, "score": 0.2, "review_threshold": 0.4, "review_signal": False}}}
    result = explain.estimates(run)
    amount = next(t for t in result["tasks"] if t["id"] == "amount")
    assert len(amount["drivers"]) == 5 and len(amount["learned"]) == 4
    assert "not causal" in amount["driver_method"]
    assert next(t for t in result["tasks"] if t["id"] == "resolution")["reason"] == "not trained"
    assert next(t for t in result["tasks"] if t["id"] == "fraud")["review_signal"] is False
    unavailable = explain.estimates({"predictions": {"available": False, "reason": "No models"}})
    assert unavailable == {"available": False, "reason": "No models", "tasks": []}


def test_the_decision_boundary_is_always_stated(explained):
    _, admin, user = explained
    assert admin["boundaries"] == user["boundaries"] and len(admin["boundaries"]) >= 4
    assert any("never approves, denies or pays" in line for line in admin["boundaries"])
    with pytest.raises(ValueError):
        explain.explain_run({}, None, "nobody")
