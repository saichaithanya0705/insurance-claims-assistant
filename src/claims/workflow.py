import asyncio
import logging
import re
import sqlite3
import threading
from collections import Counter
from copy import deepcopy
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from claims import telemetry
from claims.agents import Agents
from claims.cards import claim_ids_in_text
from claims.feedback import lesson_document, lesson_evidence
from claims.judge import LLMJudge
from claims.models import ClaimInput, ReviewDecision, SearchFilters
from claims.priority import score_priority
from claims.retrieval import HistoricalRetriever
from claims.store import Store

logger = logging.getLogger(__name__)

DOCUMENT_NAMES = r"(?:documents?|repair estimates?|incident statements?|photos?|photographs?|police reports?)"
DOCUMENT_RECEIPT_VERBS = r"(?:provided|submitted|uploaded|attached|received|reviewed|verified)"


def asserts_document_receipt(text):
    """Detect unqualified document receipt in either word order, one clause at a time."""
    clauses = re.split(r"[.!?;,\n]|\b(?:but|however|and|yet|while|although)\b", text.lower())
    for clause in clauses:
        matches = list(re.finditer(
            rf"\b{DOCUMENT_RECEIPT_VERBS}\b.{{0,100}}?\b{DOCUMENT_NAMES}\b"
            rf"|\b{DOCUMENT_NAMES}\b.{{0,100}}?\b{DOCUMENT_RECEIPT_VERBS}\b",
            clause,
        ))
        if not matches:
            continue
        if re.search(r"\b(?:reported|reports|names only|unverified|availability)\b", clause):
            continue
        for match in matches:
            span = match.group()
            verb_position = match.start() + re.search(rf"\b{DOCUMENT_RECEIPT_VERBS}\b", span).start()
            negated_verb = re.search(
                r"\b(?:not|never|cannot|hasn't|haven't|wasn't|weren't|isn't|aren't|didn't|doesn't)\b"
                r"\s+(?:(?:been|yet|ever|actually|independently|previously|already)\s+)*$",
                clause[:verb_position],
            )
            if negated_verb:
                continue
            # 'No police report was received' / 'received no documents' describe absence.
            document_position = match.start() + re.search(rf"\b{DOCUMENT_NAMES}\b", span).start()
            before_document = clause[:document_position]
            if re.search(r"\b(?:no|neither|without)\s*$", before_document):
                continue
            return True
    return False


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
    judge: dict
    review: dict | None
    trace: list
    error: str


VALIDATION_CHECKS = {
    "evidence_retrieved": (
        "External evidence retrieved",
        "At least one source beyond the submitted claim itself was retrieved.",
    ),
    "findings_cited": (
        "Findings cite a source",
        "Every finding that is not a stated limitation names at least one supporting source.",
    ),
    "citations_resolve": (
        "Finding citations resolve",
        "Every source a finding cites exists in the evidence supplied for this brief.",
    ),
    "document_claims": (
        "No unverified document-receipt claims",
        "Facts never say a document was provided, received or reviewed; only names are reported.",
    ),
    "recommendations_cited": (
        "Recommendations are cited",
        "Every recommendation cites at least one source, and every cited source exists.",
    ),
    "action_boundary": (
        "Actions stay inside the handler boundary",
        "No recommended action approves, denies, rejects or pays a claim, or alleges proven fraud.",
    ),
    "text_boundary": (
        "Generated text stays inside the decision boundary",
        "No finding or recommendation text decides a claim or alleges proven fraud.",
    ),
    "classification_confident": (
        "Claim category is confident",
        "The claim category did not need manual review.",
    ),
}


def validate_brief(state):
    ids = {e["source_id"] for e in state["evidence"]}
    issues = []
    # Per-check tallies describe the same decisions the issue list records, one row per rule.
    tally = {key: {"inspected": 0, "failed": 0} for key in VALIDATION_CHECKS}

    def fail(check, message):
        issues.append(message)
        tally[check]["failed"] += 1

    tally["evidence_retrieved"]["inspected"] += 1
    if ids <= {"claim:input"}:
        fail("evidence_retrieved", "No external evidence was retrieved; manual investigation required.")
    for finding in state["findings"]:
        if finding["kind"] != "limitation":
            tally["findings_cited"]["inspected"] += 1
            if not finding["source_ids"]:
                fail("findings_cited", "A substantive finding has no citation.")
        if finding["source_ids"]:
            tally["citations_resolve"]["inspected"] += 1
        if any(source not in ids for source in finding["source_ids"]):
            fail("citations_resolve", "A finding cites an unknown source.")
        # Intake contains document names, never uploaded document content. Catch
        # explicit received-content claims deterministically rather than relying
        # only on the model's availability instruction.
        if finding["kind"] == "fact":
            tally["document_claims"]["inspected"] += 1
            if asserts_document_receipt(finding["text"]):
                fail(
                    "document_claims",
                    "Document names describe reported availability only; document content was not received or reviewed.",
                )
    for recommendation in state["recommendations"]:
        tally["recommendations_cited"]["inspected"] += 1
        tally["action_boundary"]["inspected"] += 1
        if not recommendation["source_ids"] or any(
            source not in ids for source in recommendation["source_ids"]
        ):
            fail("recommendations_cited", "A recommendation has missing or unknown citations.")
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
            fail("action_boundary", "A recommendation crosses the handler decision boundary.")
    tally["classification_confident"]["inspected"] += 1
    if state["classification"]["needs_review"]:
        fail("classification_confident", "Claim classification needs manual review.")
    # Mechanical checks catch explicit boundary crossings in every generated field;
    # they do not establish semantic truth or replace handler review.
    generated_texts = [f["text"] for f in state["findings"]] + [
        r["action"] + " " + r["reason"] for r in state["recommendations"]
    ]
    unsafe = r"\b(?:approve|deny|reject)\s+(?:the\s+)?claim\b|\bsend\s+(?:the\s+)?payment\b|\bproven\s+fraud\b"
    for text in generated_texts:
        tally["text_boundary"]["inspected"] += 1
        # Common explicit prohibitions are valid discussion of the boundary.
        text = re.sub(
            r"\b(?:do not|never|cannot|must not|does not)\s+(?:approve|deny|reject)\s+(?:the\s+)?claim\b",
            "",
            text.lower(),
        )
        text = re.sub(r"\b(?:not|no)\s+proven\s+fraud\b", "", text)
        if re.search(unsafe, text):
            fail("text_boundary", "Generated text crosses the handler decision boundary.")
    return {
        "passed": not issues,
        "issues": list(dict.fromkeys(issues)),
        "scope": "schema, citation membership and action boundaries; not a semantic truth guarantee",
        "checks": [
            {
                "id": key,
                "label": VALIDATION_CHECKS[key][0],
                "description": VALIDATION_CHECKS[key][1],
                "passed": counts["failed"] == 0,
                "inspected": counts["inspected"],
                "failed": counts["failed"],
            }
            for key, counts in tally.items()
        ],
    }


class InvestigationService:
    def __init__(self, settings, adapter, analytics):
        self.settings, self.adapter, self.analytics = settings, adapter, analytics
        self.store = Store(settings.claims_database_path)
        self.agents = Agents(settings, self.store.event)
        self.judge_agent = LLMJudge(settings, self.store.event)
        self.retriever = HistoricalRetriever(
            settings.claims_data_path,
            settings.claims_parquet_path,
            candidate_limit=settings.claims_candidate_limit,
            memory_limit=settings.claims_duckdb_memory,
        )
        self.lock = threading.RLock()
        self.judge_threads: list[threading.Thread] = []
        self.tracer = telemetry.Tracer(self.store)
        graph = StateGraph(InvestigationState)
        for name, action in (
            ("classify", self.classify),
            ("retrieve", self.retrieve),
            ("investigate", self.investigate),
            ("risk", self.risk),
            ("recommend", self.recommend),
            ("validate", self.validate),
            ("judge", self.judge),
            ("review", self.review),
        ):
            graph.add_node(name, self._traced(name, action))
        graph.add_edge(START, "classify")
        graph.add_edge("classify", "retrieve")
        graph.add_edge("retrieve", "investigate")
        graph.add_edge("investigate", "risk")
        graph.add_edge("risk", "recommend")
        graph.add_edge("recommend", "validate")
        graph.add_edge("validate", "judge")
        graph.add_edge("judge", "review")
        graph.add_edge("review", END)
        # LangGraph checkpoints run in a background executor; keep their
        # transactions separate from foreground audit transactions.
        self.checkpoint_connection = sqlite3.connect(
            settings.claims_database_path, check_same_thread=False, timeout=30
        )
        self.graph = graph.compile(checkpointer=SqliteSaver(self.checkpoint_connection))

    def _traced(self, name, action):
        """Run a workflow node inside a stage span that records how it went and what it produced."""

        def run_stage(state):
            with self.tracer.stage(state["run_id"], name) as span:
                result = action(state)
                try:
                    span.set(**self._stage_attributes(name, state, result))
                except (KeyError, TypeError, AttributeError):  # attributes are descriptive only
                    pass
                return result

        run_stage.__name__ = f"traced_{name}"
        return run_stage

    def _stage_attributes(self, name, state, out):
        method = "model" if self.settings.agent_mode == "live" else "rules"

        def count(items, key):
            return dict(Counter(item.get(key) for item in items))

        if name == "classify":
            result = out["classification"]
            return {
                "method": result.get("method"),
                "claim_type": result.get("claim_type"),
                "needs_review": result.get("needs_review"),
            }
        if name == "retrieve":
            return {
                "evidence": len(out["evidence"]),
                "evidence_by_provenance": count(out["evidence"], "provenance"),
                "similar_cases": len(out["similar_cases"]),
                "semantic": dict(self.retriever.last_search),
                "filters": state.get("filters"),
            }
        if name == "investigate":
            new = out["findings"][len(state.get("findings", [])) :]
            return {"method": method, "findings": len(new), "by_kind": count(new, "kind")}
        if name == "risk":
            priority, predictions = out["priority"], out["predictions"]
            return {
                "priority_score": priority["score"],
                "priority_tier": priority["tier"],
                "factors": len(priority["components"]),
                "predictions_available": bool(predictions.get("available")),
                "fraud_review_signal": (predictions.get("fraud") or {}).get("review_signal"),
            }
        if name == "recommend":
            return {
                "method": method,
                "recommendations": len(out["recommendations"]),
                "actions": [r["action"] for r in out["recommendations"]],
            }
        if name == "validate":
            validation = out["validation"]
            return {
                "passed": validation["passed"],
                "issues": validation["issues"],
                "checks": validation.get("checks", []),
            }
        if name == "judge":
            verdict = out["judge"]
            return {
                "status": verdict.get("status"),
                "model": verdict.get("model"),
                "independent": verdict.get("independent"),
            }
        if name == "review" and out.get("review"):
            return {"decision": out["review"]["decision"]}
        return {}

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
        with telemetry.span(
            "knowledge.retrieve",
            kind="tool",
            adapter="live" if self.settings.synapt_mode == "live" else "fixture",
        ) as trace:
            bundle = self.adapter.retrieve(claim)
            trace.set(
                evidence=len(bundle.evidence),
                semantic_cards=len(bundle.semantic_claim_ids),
                warnings=list(bundle.warnings),
            )
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
        # Semantic matches: Synapt's own ranking of ingested claim cards first, then any claim
        # identifiers that appear in source-bearing evidence text.
        semantic_ids = list(
            dict.fromkeys(
                bundle.semantic_claim_ids
                + [
                    match
                    for e in evidence
                    if e["provenance"] == "synapt"
                    for match in claim_ids_in_text(e["text"])
                ]
            )
        )
        with telemetry.span("history.search", kind="retrieval") as trace:
            similar = self.retriever.search(
                claim, filters, self.settings.synapt_top_k, semantic_ids
            )
            trace.set(
                semantic_ids_supplied=len(semantic_ids),
                results=len(similar),
                **self.retriever.last_search,
                **self.retriever.last_trace,
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
        # Reviewed handler lessons an administrator promoted: the feedback loop's return path.
        with telemetry.span("feedback.lessons", kind="retrieval") as trace:
            lessons = self.store.promoted_lessons(
                claim.claim_type.value if claim.claim_type else None
            )
            trace.set(applied=len(lessons), lesson_ids=[lesson["id"] for lesson in lessons])
        for lesson in lessons:
            evidence.append(lesson_evidence(lesson).model_dump(mode="json"))
        return {
            "evidence": evidence,
            "similar_cases": similar,
            "warnings": bundle.warnings,
            "semantic": dict(self.retriever.last_search),
            "lessons_used": [lesson["id"] for lesson in lessons],
        }

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
            f"{len(context['evidence'])} cited evidence entries; {len(context['similar_cases'])} historical "
            f"cases ranked by BM25 + feature similarity + Synapt semantic rank (Synapt matched "
            f"{context['semantic']['semantic_candidates']} claim card(s); "
            f"{context['semantic']['semantic_eligible']} eligible under the filters; "
            f"{context['semantic']['semantic_in_results']} in the top results); "
            f"{len(context['lessons_used'])} reviewed handler lesson(s) applied.",
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
        with telemetry.span("models.predict", kind="compute") as trace:
            predictions = self.analytics.predict(claim)
            trace.set(
                available=bool(predictions.get("available")),
                tasks=[
                    task
                    for task in ("amount", "resolution", "fraud")
                    if (predictions.get(task) or {}).get("available")
                ],
            )
        with telemetry.span("priority.score", kind="compute") as trace:
            priority = score_priority(
                claim,
                state["findings"],
                predictions,
                state.get("similar_cases", []),
                state["classification"],
            )
            trace.set(score=priority["score"], tier=priority["tier"])
        return {"priority": priority, "predictions": predictions} | self.trace(
            state,
            "risk",
            f"Priority {priority['tier']} (score {priority['score']}/100) from stated factors; "
            "queue policy kept separate from statistical predictions",
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

    def judge(self, state):
        """Advisory second opinion, kept off the handler's critical path: the brief is saved and
        shown at once with the verdict "pending"; a background thread merges the result later."""
        verdict = self.judge_agent.skipped()
        if verdict is None:
            verdict = self.judge_agent.pending()
            snapshot = {
                key: deepcopy(state[key])
                for key in ("claim", "evidence", "findings", "recommendations")
            }
            thread = threading.Thread(
                target=self._judge_in_background,
                args=(state["run_id"], snapshot, telemetry.current()),
                name="judge-" + state["run_id"][:8],
                daemon=True,
            )
            self.judge_threads = [t for t in self.judge_threads if t.is_alive()] + [thread]
            thread.start()
        detail = {
            "pending": f"{verdict.get('model')}: review running in the background",
            "skipped": verdict.get("reason", "skipped"),
        }[verdict["status"]]
        return {"judge": verdict} | self.trace(state, "judge", detail)

    def _judge_in_background(self, run_id, snapshot, trace_context=None):
        # Threads start with an empty context, so the stage span is handed over explicitly.
        with (
            telemetry.attach(trace_context),
            telemetry.span("judge.review", kind="evaluation", background=True) as trace,
        ):
            try:
                verdict = self.judge_agent.evaluate(snapshot, run_id)
            except Exception as error:  # noqa: BLE001 - the judge is advisory and must never raise into a thread
                trace.fail(error)
                verdict = self.judge_agent.pending() | {
                    "status": "failed",
                    "reason": "Judge request failed; brief not judged.",
                }
            trace.set(
                status=verdict.get("status"),
                passed=verdict.get("passed"),
                score=verdict.get("score"),
                model=verdict.get("model"),
                independent=verdict.get("independent"),
            )
        try:
            self.store.event(
                run_id,
                "judge_verdict",
                {k: verdict.get(k) for k in ("status", "passed", "score", "model", "independent")},
            )
            self.store.set_judge(run_id, verdict)
        except Exception as error:  # noqa: BLE001 - e.g. the database closed during shutdown
            logger.warning("judge verdict could not be saved (%s)", type(error).__name__)

    def wait_for_judges(self, timeout=60.0):
        """Block until background judge threads finish (used by tests and graceful shutdown)."""
        for thread in list(self.judge_threads):
            thread.join(timeout)

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
            with self.tracer.run(
                run_id,
                "investigation",
                origin=telemetry.current_origin(),
                mode=state["mode"],
                agent_mode=state["agent_mode"],
                judge_mode=self.settings.judge_mode,
                claim_type=claim.claim_type.value if claim.claim_type else None,
            ) as root:
                try:
                    result = self.graph.invoke(state, {"configurable": {"thread_id": run_id}})
                    result.pop("__interrupt__", None)
                except Exception as exc:  # noqa: BLE001 - keep unknown adapter errors out of API responses
                    root.fail(exc)
                    result = dict(
                        self.graph.get_state({"configurable": {"thread_id": run_id}}).values
                    )
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
                root.set(outcome=result.get("status"))
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
            with self.tracer.run(run_id, "handler_review", decision=decision.decision) as root:
                result = self.graph.invoke(
                    Command(resume=decision.model_dump()), {"configurable": {"thread_id": run_id}}
                )
                root.set(outcome=result.get("status"))
            result.pop("__interrupt__", None)
            self.store.save(run_id, result)
            self.store.event(run_id, "handler_review", decision.model_dump())
            return result

    def promote_lesson(self, lesson_id, actor_id):
        """Make a reviewed handler lesson reusable: later investigations cite it, and in live mode
        it is also ingested (once, never retried) into the Synapt provider."""
        with self.lock:
            lesson = self.store.lesson(lesson_id)
            if lesson is None:
                raise KeyError(lesson_id)
            if not lesson["reviewed"]:
                raise ValueError("Only feedback on an accepted (reviewed) brief can be promoted")
            if lesson["promoted"]:
                raise ValueError("This lesson is already promoted")
            reference = "local"
            if self.settings.synapt_mode == "live":
                run = self.store.get(lesson["run_id"])
                result = asyncio.run(
                    self.adapter.ingest(
                        lesson_document(lesson, run), f"handler-lesson-{lesson_id}.txt"
                    )
                )
                reference = result["req_id"]
            self.store.mark_promoted(lesson_id, reference, actor_id)
            self.store.event(
                lesson["run_id"], "lesson_promoted", {"lesson_id": lesson_id, "reference": reference}
            )
            return {"id": lesson_id, "promoted": True, "reference": reference}

    def close(self):
        self.checkpoint_connection.close()
        self.store.close()
