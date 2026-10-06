import re
import sqlite3
import threading
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from claims.agents import Agents
from claims.models import ClaimInput, ReviewDecision, SearchFilters
from claims.retrieval import HistoricalRetriever
from claims.store import Store


class InvestigationState(TypedDict, total=False):
    run_id: str
    status: str
    mode: str
    agent_mode: str
    claim: dict
    filters: dict
    classification: dict
    similar_cases: list
    evidence: list
    findings: list
    recommendations: list
    priority: dict
    predictions: dict
    validation: dict
    review: dict | None
    trace: list
    error: str


def validate_brief(state):
    ids = {e["source_id"] for e in state["evidence"]}
    issues = []
    if ids <= {"claim:input"}:
        issues.append("No external evidence was retrieved; manual investigation required.")
    for finding in state["findings"]:
        if finding["kind"] != "limitation" and not finding["source_ids"]:
            issues.append("A substantive finding has no citation.")
        if any(source not in ids for source in finding["source_ids"]):
            issues.append("A finding cites an unknown source.")
        # Intake contains document names, never uploaded document content. Catch
        # explicit received-content claims deterministically rather than relying
        # only on the model's availability instruction.
        text = finding["text"].lower()
        if (
            finding["kind"] == "fact"
            and re.search(
                r"\b(?:provided|submitted|uploaded|attached|reviewed|verified)\b.{0,100}\b(?:documents?|repair estimate|incident statement|photos|police report)\b",
                text,
            )
            and not re.search(
                r"\b(?:reported|reports|names only|not|no|unverified|availability)\b", text
            )
        ):
            issues.append(
                "Document names describe reported availability only; document content was not received or reviewed."
            )
    for recommendation in state["recommendations"]:
        if not recommendation["source_ids"] or any(
            source not in ids for source in recommendation["source_ids"]
        ):
            issues.append("A recommendation has missing or unknown citations.")
        words = recommendation["action"].lower()
        if any(
            term in words
            for term in (
                "approve claim",
                "deny claim",
                "reject claim",
                "send payment",
                "proven fraud",
            )
        ):
            issues.append("A recommendation crosses the handler decision boundary.")
    if state["classification"]["needs_review"]:
        issues.append("Claim classification needs manual review.")
    # Mechanical checks catch explicit boundary crossings in every generated field;
    # they do not establish semantic truth or replace handler review.
    generated_texts = [f["text"] for f in state["findings"]] + [
        r["action"] + " " + r["reason"] for r in state["recommendations"]
    ]
    unsafe = r"\b(?:approve|deny|reject)\s+(?:the\s+)?claim\b|\bsend\s+(?:the\s+)?payment\b|\bproven\s+fraud\b"
    for text in generated_texts:
        # Common explicit prohibitions are valid discussion of the boundary.
        text = re.sub(
            r"\b(?:do not|never|cannot|must not|does not)\s+(?:approve|deny|reject)\s+(?:the\s+)?claim\b",
            "",
            text.lower(),
        )
        text = re.sub(r"\b(?:not|no)\s+proven\s+fraud\b", "", text)
        if re.search(unsafe, text):
            issues.append("Generated text crosses the handler decision boundary.")
    return {
        "passed": not issues,
        "issues": list(dict.fromkeys(issues)),
        "scope": "schema, citation membership and action boundaries; not a semantic truth guarantee",
    }


class InvestigationService:
    def __init__(self, settings, adapter, analytics):
        self.settings, self.adapter, self.analytics = settings, adapter, analytics
        self.store = Store(settings.claims_database_path)
        self.agents = Agents(settings, self.store.event)
        self.retriever = HistoricalRetriever(settings.claims_data_path)
        self.lock = threading.RLock()
        graph = StateGraph(InvestigationState)
        for name, action in (
            ("classify", self.classify),
            ("retrieve", self.retrieve),
            ("investigate", self.investigate),
            ("risk", self.risk),
            ("recommend", self.recommend),
            ("validate", self.validate),
            ("review", self.review),
        ):
            graph.add_node(name, action)
        graph.add_edge(START, "classify")
        graph.add_edge("classify", "retrieve")
        graph.add_edge("retrieve", "investigate")
        graph.add_edge("investigate", "risk")
        graph.add_edge("risk", "recommend")
        graph.add_edge("recommend", "validate")
        graph.add_edge("validate", "review")
        graph.add_edge("review", END)
        # LangGraph checkpoints run in a background executor; keep their
        # transactions separate from foreground audit transactions.
        self.checkpoint_connection = sqlite3.connect(
            settings.claims_database_path, check_same_thread=False, timeout=30
        )
        self.graph = graph.compile(checkpointer=SqliteSaver(self.checkpoint_connection))

    def trace(self, state, stage, detail):
        item = {"stage": stage, "status": "complete", "detail": detail}
        self.store.event(state["run_id"], "stage", item)
        return {"trace": state.get("trace", []) + [item]}

    def classify(self, state):
        result = self.agents.classify(ClaimInput.model_validate(state["claim"]), state["run_id"])
        claim = dict(state["claim"])
        claim["claim_type"] = result["claim_type"]
        return {"classification": result, "claim": claim} | self.trace(
            state, "classify", result["method"]
        )

    def retrieve_context(self, claim, filters):
        bundle = self.adapter.retrieve(claim)
        evidence = [e.model_dump(mode="json") for e in bundle.evidence]
        evidence.append(
            {
                "source_id": "claim:input",
                "title": "Submitted claim, not independently verified",
                "text": str(claim.model_dump(mode="json")),
                "provenance": "user_input",
                "provider_id": None,
            }
        )
        similar = self.retriever.search(
            claim,
            filters,
            self.settings.synapt_top_k,
            list(
                dict.fromkeys(
                    match
                    for e in evidence
                    if e["provenance"] == "synapt"
                    for match in re.findall(r"CLM-[A-Za-z0-9-]+", e["text"])
                )
            ),
        )
        for case in similar:
            evidence.append(
                {
                    "source_id": "history:" + case["claim_id"],
                    "title": "Synthetic historical case " + case["claim_id"],
                    "text": str(case),
                    "provenance": "published_synthetic"
                    if self.retriever.origin == "published_synthetic_dataset"
                    else "synthetic_fixture",
                    "provider_id": None,
                }
            )
        return {"evidence": evidence, "similar_cases": similar, "warnings": bundle.warnings}

    def retrieve(self, state):
        context = self.retrieve_context(
            ClaimInput.model_validate(state["claim"]),
            SearchFilters.model_validate(state["filters"]),
        )
        return {
            "evidence": context["evidence"],
            "similar_cases": context["similar_cases"],
            "findings": [
                {"kind": "limitation", "text": warning, "source_ids": []}
                for warning in context["warnings"]
            ],
        } | self.trace(
            state,
            "retrieve",
            f"{len(context['evidence'])} cited evidence entries; {len(context['similar_cases'])} historical cases. Local ranking is BM25 plus feature similarity; live Synapt case IDs add semantic ranking when available.",
        )

    def investigate(self, state):
        findings = self.agents.investigate(
            ClaimInput.model_validate(state["claim"]),
            state["evidence"],
            state["similar_cases"],
            state["run_id"],
        )
        return {"findings": state.get("findings", []) + findings} | self.trace(
            state, "investigate", "Compared evidence, gaps and supported contradictions"
        )

    def risk(self, state):
        claim = ClaimInput.model_validate(state["claim"])
        delay = (claim.claim_filed_date - claim.incident_date).days
        reasons = []
        if delay > 14:
            reasons.append(
                f"Submitted filing delay is {delay} days; investigate explanation, not proof of fraud."
            )
        if claim.previous_claims_count >= 3:
            reasons.append(
                "Three or more previous claims; inspect relevant history without assuming fraud."
            )
        if any(f["kind"] == "contradiction" for f in state["findings"]):
            reasons.append("Conflicting evidence requires focused handler clarification.")
        predictions = self.analytics.predict(claim)
        if predictions.get("available") and predictions.get("fraud", {}).get("review_signal"):
            reasons.append(
                "Synthetic fraud-flag model exceeds its review threshold; sample precision is weak, so independently investigate rather than infer fraud."
            )
        priority = {
            "service_urgency": "urgent" if claim.claim_amount >= 50000 else "normal",
            "investigation_priority": "elevated" if reasons else "normal",
            "reasons": reasons,
            "policy": "Explicit demo queue policy; thresholds are not insurer rules or legal deadlines.",
        }
        return {"priority": priority, "predictions": predictions} | self.trace(
            state, "risk", "Separated queue policy from statistical predictions"
        )

    def recommend(self, state):
        return {"recommendations": self.agents.recommend(state, state["run_id"])} | self.trace(
            state, "recommend", "Prepared handler actions; no adjudication"
        )

    def validate(self, state):
        validation = validate_brief(state)
        return {
            "validation": validation,
            "status": "awaiting_review" if validation["passed"] else "needs_manual_review",
        } | self.trace(
            state,
            "validate",
            "; ".join(validation["issues"]) or "Citation and boundary checks passed",
        )

    def review(self, state):
        # No side effect before interrupt: LangGraph replays this node on resume.
        decision = ReviewDecision.model_validate(
            interrupt(
                {
                    "run_id": state["run_id"],
                    "validation": state["validation"],
                    "scope": "Review the brief only; this does not approve or deny an insurance claim.",
                }
            )
        )
        return {
            "review": decision.model_dump(),
            "status": "reviewed" if decision.decision == "accept_brief" else "revision_requested",
        }

    def create(self, claim, filters):
        run_id = str(uuid4())
        state = {
            "run_id": run_id,
            "status": "running",
            "mode": self.settings.synapt_mode,
            "agent_mode": self.settings.agent_mode,
            "claim": claim.model_dump(mode="json"),
            "filters": filters.model_dump(mode="json"),
            "trace": [],
            "review": None,
        }
        with self.lock:
            self.store.save(run_id, state)
            try:
                result = self.graph.invoke(state, {"configurable": {"thread_id": run_id}})
                result.pop("__interrupt__", None)
            except Exception as exc:  # noqa: BLE001 - keep unknown adapter errors out of API responses
                result = dict(self.graph.get_state({"configurable": {"thread_id": run_id}}).values)
                result.update(
                    {
                        "status": "failed",
                        "error": "Investigation failed safely. Check integration configuration or validated model output; no fallback was used.",
                    }
                )
                self.store.event(
                    run_id,
                    "failure",
                    {
                        "reason": "adapter_model_or_workflow_failure",
                        "error_type": type(exc).__name__,
                    },
                )
            self.store.save(run_id, result)
            return result

    def submit_review(self, run_id, decision):
        with self.lock:
            current = self.store.get(run_id)
            if current is None:
                raise KeyError(run_id)
            if current["status"] not in ("awaiting_review", "needs_manual_review"):
                raise ValueError("This run is not awaiting review")
            if decision.decision == "accept_brief" and not current["validation"]["passed"]:
                raise ValueError(
                    "Brief validation failed. Request revision; acceptance is blocked."
                )
            result = self.graph.invoke(
                Command(resume=decision.model_dump()), {"configurable": {"thread_id": run_id}}
            )
            result.pop("__interrupt__", None)
            self.store.save(run_id, result)
            self.store.event(run_id, "handler_review", decision.model_dump())
            return result

    def close(self):
        self.checkpoint_connection.close()
        self.store.close()
