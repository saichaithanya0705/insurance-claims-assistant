"""Explain how a saved brief was generated and how it was evaluated.

Everything here is derived from what the run already stored (the brief, its evidence, its scores)
plus, when available, the recorded trace of how it was produced. Nothing is re-run and nothing is
invented: where a fact was not recorded (a run saved before span tracing existed has no retrieval
internals) the section says so rather than guessing.

The audience decides what is shown. A handler gets the plain-language account of the method, the
sources behind each statement and the checks the brief went through. An administrator additionally
gets model names, token counts and the technical retrieval detail.
"""

import re

from claims.judge import PASS_SCORE

STAGES = (
    ("classify", "Classify the claim"),
    ("retrieve", "Retrieve evidence and comparable claims"),
    ("investigate", "Investigate: compare the claim with the evidence"),
    ("risk", "Estimate and prioritise"),
    ("recommend", "Recommend next steps"),
    ("validate", "Validate the brief"),
    ("judge", "Independent review"),
    ("review", "Handler review"),
)

# What is rule-based and what is learned: shown on every stage so a reader knows where a person,
# a rule, a statistical model or a language model made the call.
BOUNDARIES = (
    "The brief never approves, denies or pays a claim, and never states that fraud is proven.",
    "Every finding and recommendation must cite a source that was actually supplied.",
    (
        "Similar historical claims and their outcomes are comparison evidence only; they do not "
        "establish coverage or decide this claim."
    ),
    (
        "Document names in the intake are claimant-reported availability; no document content "
        "was received, extracted or reviewed."
    ),
    (
        "A person reviews the brief. Accepting it records that the brief is usable, not a "
        "decision on the claim."
    ),
)

# The queue-priority policy, in the words priority.py implements. Each factor is matched to the
# components a run actually earned so the page can show what applied and what did not.
PRIORITY_RUBRIC = (
    ("amount", "Claimed amount", 30, "$10k earns 8, $25k earns 15, $50k earns 25, $100k or more 30", r"^Claimed amount"),
    ("delay", "Filing delay", 15, "More than 14 days earns 10; more than 30 days earns 15", r"filing delay"),
    ("prior", "Previous claims", 15, "Three or more earns 10; five or more earns 15", r"previous claims"),
    ("contradiction", "Conflicting evidence", 15, "A supported contradiction finding earns 15", r"^Conflicting evidence"),
    ("gaps", "Evidence gaps", 10, "5 points per supported gap, up to 10", r"evidence gap"),
    ("fraud_model", "Fraud-flag model signal", 15, "The score is above the model's review threshold", r"fraud-flag model"),
    ("similar_flagged", "Similar claims carrying the dataset fraud flag", 10, "Two or more of the closest comparable claims", r"historical claims carry the dataset"),
    ("category", "Uncertain category", 5, "The claim category needed manual confirmation", r"category is uncertain"),
)
TIERS = (("critical", 60), ("high", 40), ("medium", 20), ("low", 0))
DEFAULT_FILTERS = {
    "claim_type": None,
    "state": None,
    "claim_status": None,
    "min_amount": 0,
    "max_amount": 1_000_000_000,
    "min_previous_claims": 0,
    "max_previous_claims": 1000,
}

METHODS = (
    (
        "keyword",
        "Keyword match",
        (
            "Term-frequency match between the new claim's descriptors and each past claim's. "
            "There is deliberately no rarity weighting, so near-identical claims stay on top."
        ),
    ),
    (
        "feature",
        "Numeric similarity",
        (
            "Same claim type (+2), same state (+1), and closeness of the claimed amount (on a log "
            "scale) and of the prior-claims count."
        ),
    ),
    (
        "semantic",
        "Semantic rank",
        (
            "The knowledge store's own ranking of historical claim cards by meaning. It carries "
            "half weight because the store holds only a sample of the history."
        ),
    ),
)

_METADATA = re.compile(
    r"^(?:#|source_id:|source_url:|provenance:|attribution:|claim_id:|policy_id:|provider_id:|"
    r"Educational decision support only\.)",
    re.IGNORECASE,
)


def _clean(text, audience):
    """Handlers never see vendor or provider names; the same rules present_run applies."""
    if audience == "admin" or not isinstance(text, str):
        return text
    if re.search(r"Optional Synapt .*lacks supported provenance", text, re.IGNORECASE):
        return "Some retrieved material could not be linked to a supported source and was excluded."
    return re.sub(r"\bSynapt\b", "retrieved source", text, flags=re.IGNORECASE)


def _excerpt(text, limit=240):
    """The first narrative paragraph of a passage, unchanged apart from truncation."""
    for paragraph in re.split(r"\r?\n\s*\r?\n|\r?\n", text or ""):
        paragraph = paragraph.strip()
        if len(paragraph.split()) >= 8 and not _METADATA.match(paragraph):
            return paragraph if len(paragraph) <= limit else paragraph[: limit - 1].rstrip() + "…"
    return None


def _title(evidence):
    title = re.sub(r"\.(?:json|txt|md|pdf)$", "", evidence.get("title") or "", flags=re.IGNORECASE)
    title = re.sub(r"[_/]+", " ", title)
    title = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "", title, flags=re.IGNORECASE).strip()
    return title or "Retrieved source passage"


def source_info(evidence, audience="admin"):
    """Category, label and excerpt for one evidence item; vendor names only for administrators."""
    source_id = evidence["source_id"]
    provenance = evidence.get("provenance")
    if source_id == "claim:input":
        category, label = "claim", "Submitted claim"
    elif source_id.startswith("history:"):
        category, label = "history", f"Comparable claim {source_id[8:]}"
    elif provenance == "handler_lesson":
        category, label = "lesson", _title(evidence)
    else:
        category, label = "procedure", _title(evidence)
    if audience != "admin" and provenance == "synapt":
        provenance = "retrieved_source"
    excerpt = _excerpt(evidence.get("text")) if category in ("procedure", "lesson") else None
    return {
        "source_id": source_id,
        "label": _clean(label, audience),
        "category": category,
        "provenance": provenance,
        "excerpt": _clean(excerpt, audience),
    }


def _span(trace, name):
    return next((s for s in (trace or {}).get("spans", []) if s["name"] == name), None)


def _spans(trace, name):
    return [s for s in (trace or {}).get("spans", []) if s["name"] == name]


def grounding(run):
    """Deterministic citation coverage: how much of the brief points back to supplied evidence."""
    evidence = run.get("evidence") or []
    findings = run.get("findings") or []
    recommendations = run.get("recommendations") or []
    ids = {e["source_id"] for e in evidence}
    substantive = [f for f in findings if f.get("kind") != "limitation"]
    items = findings + recommendations
    citations = [source for item in items for source in item.get("source_ids", [])]
    cited = {source for source in citations if source in ids}
    external = ids - {"claim:input"}
    return {
        "findings": len(findings),
        "substantive_findings": len(substantive),
        "substantive_cited": sum(bool(f.get("source_ids")) for f in substantive),
        "recommendations": len(recommendations),
        "recommendations_cited": sum(bool(r.get("source_ids")) for r in recommendations),
        "citations": len(citations),
        "citations_resolved": sum(source in ids for source in citations),
        "sources_available": len(ids),
        "sources_cited": len(cited),
        "external_sources_available": len(external),
        "external_sources_cited": len(cited & external),
        "uncited_sources": sorted(ids - cited),
    }


def lineage(run, audience="admin"):
    """For every finding and recommendation: the sources behind it and who produced it."""
    by_id = {e["source_id"]: source_info(e, audience) for e in run.get("evidence") or []}
    method = "ai" if run.get("agent_mode") == "live" else "rules"

    def sources_of(item):
        return [
            by_id.get(source) or {"source_id": source, "label": source, "category": "unknown"}
            for source in item.get("source_ids", [])
        ]

    rows = []
    for index, finding in enumerate(run.get("findings") or []):
        sources = sources_of(finding)
        rows.append(
            {
                "type": "finding",
                "index": index,
                "kind": finding["kind"],
                "text": _clean(finding["text"], audience),
                "stage": "investigate",
                "method": method,
                "sources": sources,
                "unsupported": finding["kind"] != "limitation" and not sources,
            }
        )
    for index, rec in enumerate(run.get("recommendations") or []):
        sources = sources_of(rec)
        rows.append(
            {
                "type": "recommendation",
                "index": index,
                "kind": rec["action"],
                "text": _clean(rec["reason"], audience),
                "stage": "recommend",
                "method": method,
                "sources": sources,
                "unsupported": not sources,
            }
        )
    return rows


def retrieval(run, trace, audience):
    cases = run.get("similar_cases") or []
    search = _span(trace, "history.search")
    attributes = (search or {}).get("attributes") or {}
    ranked = {r["claim_id"]: r for r in attributes.get("ranked") or []}
    weights = attributes.get("weights") or {"keyword": 1.0, "feature": 1.0, "semantic": 0.5}
    filters = {
        key: value
        for key, value in (run.get("filters") or {}).items()
        if key in DEFAULT_FILTERS and value != DEFAULT_FILTERS[key]
    }
    status_filter = (run.get("filters") or {}).get("claim_status")
    rows = []
    for position, case in enumerate(cases, 1):
        parts = ranked.get(case["claim_id"])
        rows.append(
            {
                "rank": position,
                "claim_id": case["claim_id"],
                "claim_type": case.get("claim_type"),
                "state": case.get("state"),
                "claim_amount": case.get("claim_amount"),
                "outcome": case.get("claim_status"),
                "surfaced_by": case.get("surfaced_by"),
                "total": case.get("similarity_score"),
                "keyword_rank": (parts or {}).get("keyword_rank"),
                "feature_rank": (parts or {}).get("feature_rank"),
                "semantic_rank": case.get("semantic_rank"),
                "points": None
                if parts is None
                else {
                    "keyword": parts["keyword_points"],
                    "feature": parts["feature_points"],
                    "semantic": parts["semantic_points"],
                },
                "reasons": [_clean(r, audience) for r in case.get("match_reasons") or []],
                "differences": case.get("differences") or [],
            }
        )
    semantic = {
        key: attributes.get(key)
        for key in ("semantic_candidates", "semantic_eligible", "semantic_in_results")
        if attributes.get(key) is not None
    }
    provenance: dict = {}
    for item in run.get("evidence") or []:
        label = source_info(item, audience)["category"]
        provenance[label] = provenance.get(label, 0) + 1
    result = {
        "recorded": search is not None,
        "pool": (
            f"Claims with status {status_filter.replace('_', ' ')} that were already on file "
            "before this claim (they have no outcome yet)"
            if status_filter in ("pending", "under_review")
            else f"Claims settled as {status_filter} and closed before this claim was filed"
            if status_filter
            else "Settled claims (approved or denied) of the same type, closed before this claim was filed"
        ),
        "filters": filters,
        "methods": [
            {"id": key, "name": name, "weight": weights.get(key), "how": how}
            for key, name, how in METHODS
        ],
        "formula": "score = 1/(60 + keyword rank) + 1/(60 + numeric rank) + 0.5/(60 + semantic rank)",
        "candidates": {
            "sql_candidates": attributes.get("sql_candidates"),
            "semantic_added": attributes.get("semantic_added"),
            "pool_size": attributes.get("pool_size"),
            "top_k": attributes.get("top_k"),
        }
        if search
        else None,
        "semantic": semantic or None,
        "ranked": rows,
        "evidence_by_category": provenance,
        "note": None
        if search
        else "Per-method ranks were not recorded for this run (it was saved before tracing "
        "existed); only the combined score is available.",
    }
    if audience == "admin":
        queries = [
            {
                "purpose": s["attributes"].get("purpose"),
                "tool": s["attributes"].get("tool"),
                "query": s["attributes"].get("query"),
                "top_k": s["attributes"].get("top_k"),
                "duration_ms": s["duration_ms"],
            }
            for s in _spans(trace, "synapt.call_tool")
        ]
        result["knowledge_queries"] = queries
    return result


def priority(run):
    data = run.get("priority") or {}
    components = data.get("components") or []
    earned = {key: 0 for key, *_ in PRIORITY_RUBRIC}
    unmatched = []
    for component in components:
        for key, _, _, _, pattern in PRIORITY_RUBRIC:
            if re.search(pattern, component.get("reason", ""), re.IGNORECASE):
                earned[key] += component["points"]
                break
        else:
            unmatched.append(component)
    score = data.get("score")
    next_tier = None
    if isinstance(score, int):
        above = [(name, floor) for name, floor in reversed(TIERS) if floor > score]
        if above:
            next_tier = {"tier": above[0][0], "points_needed": above[0][1] - score}
    return {
        "score": score,
        "tier": data.get("tier"),
        "service_urgency": data.get("service_urgency"),
        "investigation_priority": data.get("investigation_priority"),
        "tiers": [{"tier": name, "from": floor} for name, floor in TIERS],
        "next_tier": next_tier,
        "factors": [
            {
                "id": key,
                "label": label,
                "max_points": maximum,
                "rule": rule,
                "points": earned[key],
                "applied": earned[key] > 0,
            }
            for key, label, maximum, rule, _ in PRIORITY_RUBRIC
        ],
        "components": components,
        "unmatched_components": unmatched,
        "policy": data.get("policy"),
    }


def estimates(run, audience="admin"):
    predictions = run.get("predictions") or {}
    if not predictions.get("available"):
        return {
            "available": False,
            "reason": _clean(predictions.get("reason"), audience)
            or "No model estimates were produced.",
            "tasks": [],
        }
    tasks = []
    for key, title, unit in (("amount", "Claim amount", "USD"), ("resolution", "Resolution time", "days"), ("fraud", "Dataset fraud-flag risk", "score")):
        item = predictions.get(key) or {}
        local = item.get("local_explanation") or {}
        glob = item.get("global_explanation") or {}
        tasks.append(
            {
                "id": key,
                "title": title,
                "available": bool(item.get("available")),
                "reason": _clean(item.get("reason"), audience),
                "unit": unit,
                "estimate": item.get("estimate"),
                "interval": item.get("interval"),
                "score": item.get("score"),
                "review_threshold": item.get("review_threshold"),
                "review_signal": item.get("review_signal"),
                "drivers": (local.get("contributions") or [])[:5],
                "driver_method": _clean(local.get("method"), audience),
                "learned": [_clean(line, audience) for line in (glob.get("summary") or [])[:4]],
                "learned_method": _clean(glob.get("effects_method"), audience),
                "important_features": (glob.get("features") or [])[:5],
            }
        )
    return {
        "available": True,
        "tasks": tasks,
        "warnings": [_clean(w, audience) for w in predictions.get("warnings") or []],
        "limitations": [_clean(x, audience) for x in predictions.get("limitations") or []],
        "note": _clean(predictions.get("confidence_distinction"), audience),
    }


def evaluation(run, audience, suite=None):
    from claims.workflow import validate_brief

    saved = run.get("validation") or {}
    try:
        recomputed = validate_brief(run)
    except (KeyError, TypeError):
        recomputed = None
    checks = saved.get("checks") or (recomputed or {}).get("checks") or []
    judge = run.get("judge") or {}
    review = run.get("review")
    status = run.get("status")
    layers = [
        {
            "id": "validation",
            "title": "Mechanical validation",
            "kind": "rules",
            "gate": True,
            "summary": "Deterministic checks, no AI. A brief that fails them cannot be accepted.",
            "state": "passed" if saved.get("passed") else "failed" if saved else "unavailable",
            "checks": checks,
            "issues": saved.get("issues") or [],
            "scope": saved.get("scope"),
            "rechecked": None
            if recomputed is None
            else {
                "matches_saved": recomputed["passed"] == saved.get("passed"),
                "source": "recomputed from the saved brief",
            },
            "checks_source": "recorded" if saved.get("checks") else "recomputed from the saved brief",
        },
        {
            "id": "grounding",
            "title": "Evidence grounding",
            "kind": "rules",
            "gate": False,
            "summary": "How much of the brief points back to supplied evidence. Coverage is "
            "counted, not judged: a citation proves a source was named, not that it supports the claim.",
            "metrics": grounding(run),
        },
        {
            "id": "judge",
            "title": "Independent AI review",
            "kind": "ai",
            "gate": False,
            "summary": "A second, different language model reads the brief against its evidence. "
            "It is advisory and probabilistic.",
            "state": judge.get("status") or "unavailable",
            "passed": judge.get("passed"),
            "grounded": judge.get("grounded"),
            "boundary_respected": judge.get("boundary_respected"),
            "recommendations_supported": judge.get("recommendations_supported"),
            "score": judge.get("score"),
            "issues": [_clean(i, audience) for i in judge.get("issues") or []],
            "verdict": _clean(judge.get("summary"), audience),
            "reason": _clean(judge.get("reason"), audience),
            "criteria": f"Passes when the brief is grounded, stays inside the decision boundary, "
            f"its recommendations follow from the findings, no issue is raised and the quality "
            f"score is at least {PASS_SCORE:.2f}.",
            **(
                {"model": judge.get("model"), "independent": judge.get("independent")}
                if audience == "admin"
                else {}
            ),
        },
        {
            "id": "human",
            "title": "Handler review",
            "kind": "human",
            "gate": True,
            "summary": "A person decides whether the brief is usable. This never approves or "
            "denies the claim itself.",
            "state": "accepted"
            if review and review.get("decision") == "accept_brief"
            else "revision_requested"
            if review
            else "awaiting" if status in ("awaiting_review", "needs_manual_review") else "unavailable",
            "decision": (review or {}).get("decision"),
            "note": (review or {}).get("note"),
        },
    ]
    if audience == "admin" and suite:
        layers.append(
            {
                "id": "suite",
                "title": "System evaluation suite",
                "kind": "rules",
                "gate": False,
                "summary": "Golden claims run end to end on demand. This is a regression check on "
                "the system, not a score for this brief.",
                "state": suite.get("status"),
                "passed": suite.get("passed"),
                "total": suite.get("total"),
                "judge_status": suite.get("judge_status"),
                "judge_passed_metrics": suite.get("judge_passed_metrics"),
                "judge_expected_metrics": suite.get("judge_expected_metrics"),
                "scope": suite.get("scope"),
            }
        )
    return {"layers": layers}


def _stage_view(run, trace, audience):
    live = run.get("agent_mode") == "live"
    judge = run.get("judge") or {}
    evidence = run.get("evidence") or []
    findings = run.get("findings") or []
    recommendations = run.get("recommendations") or []
    classification = run.get("classification") or {}
    priority_data = run.get("priority") or {}
    validation = run.get("validation") or {}
    checks = validation.get("checks") or []
    by_kind: dict = {}
    for finding in findings:
        by_kind[finding["kind"]] = by_kind.get(finding["kind"], 0) + 1
    categories: dict = {}
    for item in evidence:
        category = source_info(item, audience)["category"]
        categories[category] = categories.get(category, 0) + 1
    names = {"claim": "submitted claim", "procedure": "procedure passages", "history": "comparable claims", "lesson": "reviewed handler lessons"}
    timings = {s["stage"]: s for s in ((trace or {}).get("summary") or {}).get("stages", [])}
    judge_state = judge.get("status")
    copy = {
        "classify": {
            "kind": "ai" if live else "rules",
            "what": "Decides which kind of claim this is, or abstains when the category is ambiguous.",
            "how": "A language model returns a category (or abstains) in a fixed schema; an ambiguous answer blocks acceptance."
            if live
            else "The category you submitted is used. Without one, keyword rules pick a category or abstain.",
            "inputs": ["Submitted claim description and fields"],
            "outputs": [
                f"Claim type: {classification.get('claim_type') or 'undetermined'}",
                "Category needs manual review" if classification.get("needs_review") else "Category accepted",
            ],
        },
        "retrieve": {
            "kind": "search",
            "what": "Finds the handling procedures that apply and the most comparable historical claims.",
            "how": "Procedures come from the knowledge store. Comparable claims come from the 100-million-claim history: exact filters first, then keyword, numeric and semantic ranking fused by reciprocal rank.",
            "inputs": ["Claim type, state, amount, history", "Search filters"],
            "outputs": [f"{count} {names.get(name, name)}" for name, count in categories.items()],
        },
        "investigate": {
            "kind": "ai" if live else "rules",
            "what": "Compares the claim with the evidence and lists facts, gaps, contradictions and limitations.",
            "how": "A language model reads the claim, the evidence and the comparable claims and must cite a supplied source for every substantive finding."
            if live
            else "Fixed rules compare the documents the procedures request with the documents reported, flag explicit contradictions and always state the standing limitation.",
            "inputs": ["Claim", "Retrieved evidence", "Comparable claims"],
            "outputs": [f"{n} {kind.replace('_', ' ')}" + ("s" if n != 1 else "") for kind, n in by_kind.items()],
        },
        "risk": {
            "kind": "statistics",
            "what": "Estimates amount, resolution time and a fraud-flag score, and scores handling priority.",
            "how": "Three trained statistical models produce the estimates. A transparent point rule turns stated factors into a 0 to 100 priority. Neither decides the claim.",
            "inputs": ["Claim fields", "Findings", "Comparable claims"],
            "outputs": [
                f"Priority {priority_data.get('tier', 'unscored')} ({priority_data.get('score', '—')}/100)",
                "Model estimates available" if (run.get("predictions") or {}).get("available") else "Model estimates unavailable",
            ],
        },
        "recommend": {
            "kind": "ai" if live else "rules",
            "what": "Proposes what the handler should do next.",
            "how": "A language model chooses actions from a fixed list and must give a reason and citations."
            if live
            else "A rule requests focused evidence for each gap or contradiction and always asks the handler to verify policy terms.",
            "inputs": ["Findings", "Evidence", "Estimates"],
            "outputs": [f"{len(recommendations)} recommended action" + ("s" if len(recommendations) != 1 else "")],
        },
        "validate": {
            "kind": "rules",
            "what": "Checks the brief mechanically before anyone relies on it.",
            "how": "Deterministic rules verify schema, that every citation resolves to supplied evidence, that no decision language appears and that no document content is claimed.",
            "inputs": ["Findings", "Recommendations", "Evidence"],
            "outputs": [f"{sum(c.get('passed', False) for c in checks)} of {len(checks)} checks passed"] if checks else ["Passed" if validation.get("passed") else "Needs attention"],
        },
        "judge": {
            "kind": "ai" if judge_state not in (None, "skipped") else "off",
            "what": "A second model reviews the brief against its own evidence.",
            "how": "A different model from the author reads the brief and the evidence and reports whether it is grounded, stays in bounds and supports its recommendations. It runs in the background and is advisory."
            if judge_state not in (None, "skipped")
            else "Not run for this brief.",
            "inputs": ["Claim", "Evidence", "Findings", "Recommendations"],
            "outputs": [
                {
                    "completed": "Concerns flagged" if judge.get("passed") is False else "No concerns raised",
                    "pending": "Review in progress",
                    "failed": "Review could not complete",
                    "skipped": "Not run",
                }.get(judge_state, "Unavailable")
            ],
        },
        "review": {
            "kind": "human",
            "what": "A person decides whether the brief is usable.",
            "how": "The workflow pauses until a handler accepts the brief or requests a revision. Neither decision approves or denies the claim.",
            "inputs": ["The complete brief"],
            "outputs": [
                "Accepted by a handler"
                if (run.get("review") or {}).get("decision") == "accept_brief"
                else "Revision requested"
                if run.get("review")
                else "Waiting for a handler"
            ],
        },
    }
    out = []
    for key, title in STAGES:
        timing = timings.get(key)
        entry = {"stage": key, "title": title, **copy[key]}
        entry["duration_ms"] = None if timing is None else timing["duration_ms"]
        entry["status"] = (
            "skipped"
            if key == "judge" and judge_state == "skipped"
            else "waiting"
            if key == "review" and not run.get("review")
            else "pending"
            if key == "judge" and judge_state == "pending"
            else "complete"
        )
        out.append(entry)
    return out


def explain_run(run, trace=None, audience="user", suite=None):
    """The complete explanation of one saved run for the given audience ("user" or "admin")."""
    if audience not in ("user", "admin"):
        raise ValueError("audience must be 'user' or 'admin'")
    live = run.get("agent_mode") == "live"
    findings = run.get("findings") or []
    recommendations = run.get("recommendations") or []
    evidence = run.get("evidence") or []
    priority_data = run.get("priority") or {}
    summary = (trace or {}).get("summary")
    result = {
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "generation": "ai" if live else "rules",
        "headline": (
            f"{len(findings)} finding{'s' if len(findings) != 1 else ''} and "
            f"{len(recommendations)} recommendation{'s' if len(recommendations) != 1 else ''} "
            f"drawn from {len(evidence)} source{'s' if len(evidence) != 1 else ''}"
            + (
                f"; handling priority {priority_data.get('tier')} ({priority_data.get('score')}/100)."
                if priority_data.get("tier")
                else "."
            )
        ),
        "pipeline": _stage_view(run, trace, audience),
        "lineage": lineage(run, audience),
        "retrieval": retrieval(run, trace, audience),
        "priority": priority(run),
        "estimates": estimates(run, audience),
        "evaluation": evaluation(run, audience, suite),
        "boundaries": list(BOUNDARIES),
        "timeline": None
        if not summary
        else {
            "source": trace.get("source"),
            "total_ms": summary["duration_ms"],
            "stages": summary["stages"],
        },
        "limitations": [
            _clean(f["text"], audience) for f in findings if f.get("kind") == "limitation"
        ],
    }
    if audience == "admin":
        result["technical"] = {
            "mode": run.get("mode"),
            "agent_mode": run.get("agent_mode"),
            "trace_source": (trace or {}).get("source"),
            "llm": None if not summary else summary["llm"],
            "classification_method": (run.get("classification") or {}).get("method"),
        }
    return result
