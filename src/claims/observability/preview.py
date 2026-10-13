"""What an investigation that is still running has produced so far, in a small shape the page can show as each part lands.

An investigation takes about 20 s, and its parts finish at different times: retrieval first (passages, procedures, the closest past
claims, the exact past-claim figures), then the findings, the priority and last the recommended actions. Each of those stages saves
what it produced (`InvestigationService._save_partial`), and this module turns the saved run, already filtered for the viewer's role,
into the few facts worth showing early. Nothing here is a verdict: the brief is not ready, not validated and not judged until the
run ends, and the page says so.
"""

STAGE_ORDER = ("classify", "retrieve", "investigate", "risk", "recommend", "validate", "supervise", "judge", "review")


def _headline(cohort: dict | None) -> str | None:
    """One sentence about the exact past-claim figures, from the group the cohort panel leads with."""
    if not cohort:
        return None
    if not cohort.get("available"):
        return cohort.get("reason")
    rows = cohort.get("cohorts") or []
    lead = next((r for r in rows if r.get("sufficient")), rows[0] if rows else None)
    if not lead or not isinstance(lead.get("claims"), int):
        return None
    same = {"exact": "the same description", "type_amount_history": "the same type, amount and history", "type": "the same claim type"}
    parts = [f"{lead['claims']:,} past claims with {same.get(lead.get('key'), 'similar details')}"]
    if isinstance(lead.get("approved_share"), int | float):
        parts.append(f"{lead['approved_share'] * 100:.1f}% approved")
    if isinstance(lead.get("median_days"), int | float):
        parts.append(f"median {lead['median_days']:g} days to settle")
    return ", ".join(parts)


def _query_state(query_agent: dict | None) -> dict | None:
    if not query_agent:
        return None
    if query_agent.get("pending"):
        return {"state": "pending", "question": query_agent.get("question")}
    part = query_agent.get("part") or {}
    if query_agent.get("available") and part.get("text"):
        return {"state": "answered", "question": query_agent.get("question"), "answer": str(part["text"])[:600]}
    return {"state": "unavailable", "question": query_agent.get("question")}


def preview_of(run: dict) -> dict:
    """The parts of ``run`` (already presented for this viewer) that exist yet. A part that has not landed is None."""
    done = [t.get("stage") for t in run.get("trace") or []]
    out = {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "stages": [s for s in STAGE_ORDER if s in done],
        "claim_type": (run.get("classification") or {}).get("claim_type") or (run.get("claim") or {}).get("claim_type"),
        "retrieval": None,
        "findings": None,
        "priority": None,
        "recommendations": None,
    }
    if "retrieve" in done:
        evidence = run.get("evidence") or []
        procedures = [
            str(e.get("title", "")).replace("Knowledge graph procedure: ", "")
            for e in evidence
            if str(e.get("source_id", "")).startswith("graph:procedure:")
        ]
        passages = [
            e for e in evidence if e.get("provenance") in ("synapt", "retrieved_source") and not str(e.get("source_id", "")).startswith("graph:")
        ]
        similar = [c for c in run.get("similar_cases") or [] if not c.get("open_case")]
        out["retrieval"] = {
            "passages": len(passages),
            "procedures": procedures,
            "similar_cases": [
                {k: c.get(k) for k in ("claim_type", "state", "claim_amount", "claim_status", "days_to_resolution")} for c in similar[:3]
            ],
            "similar_total": len(similar),
            "cohort": _headline(run.get("cohort")),
            "query_agent": _query_state(run.get("query_agent")),
        }
    if "investigate" in done:
        out["findings"] = [{"kind": f.get("kind"), "text": f.get("text")} for f in (run.get("findings") or [])[:12]]
    if "risk" in done and run.get("priority"):
        priority = run["priority"]
        out["priority"] = {
            "tier": priority.get("tier"),
            "score": priority.get("score"),
            "reasons": [c.get("reason") for c in priority.get("components") or []][:5],
        }
    if "recommend" in done:
        out["recommendations"] = [{"action": r.get("action"), "reason": r.get("reason")} for r in (run.get("recommendations") or [])[:8]]
    return out
