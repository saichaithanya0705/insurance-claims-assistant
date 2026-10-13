import asyncio
import logging
import re
import sqlite3
import threading
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from copy import deepcopy
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from claims.agents import access
from claims.agents.stage_agents import Agents
from claims.agents.supervisor import Supervisor, stage_detail
from claims.core.schemas import ClaimInput, ReviewDecision, SearchFilters
from claims.corpus.lessons import lesson_document
from claims.evaluation.judge import LLMJudge
from claims.history.cohort import DEFAULT_CUTOFF, cohort_statistics, trace_attributes
from claims.history.cohort_summary import CohortSummary
from claims.history.retriever import HistoricalRetriever
from claims.investigation.priority import score_priority
from claims.observability import telemetry
from claims.observability.progress import ProgressBoard
from claims.retrieval.agents import RetrievalAgents
from claims.retrieval.graph import RetrievalGraph
from claims.storage.run_store import Store
from claims.synapt import knowledge_graph, query_agent
from claims.synapt.adapter import SynaptError

logger = logging.getLogger(__name__)

# How long retrieval waits for the query agent's display-only answer before the brief goes ahead without it.
QUERY_WAIT_SECONDS = 12
# And how long the finished brief waits for an answer that is still on its way, having had the whole model stage to arrive.
QUERY_GRACE_SECONDS = 12

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
    # Display-only cohort statistics from DuckDB (claims.history.cohort): never evidence, never given to a model.
    cohort: dict
    # Handling procedures from the Synapt knowledge graph (claims.synapt.knowledge_graph); each is also a cited evidence item.
    graph: dict
    # Synapt's query agent's answer to one fixed handling question (claims.synapt.query_agent): display only, never evidence.
    query_agent: dict
    validation: dict
    judge: dict
    review: dict | None
    # What the Investigation Agent wrote (the tail of ``findings``), so the Supervisor can send exactly that back (claims.agents.supervisor).
    investigator_findings: list
    # The Supervisor Agent's record: its summary of the brief, and whether it sent the findings back once.
    supervisor: dict
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
    "coverage_assertion": (
        "No coverage or eligibility conclusions",
        (
            "No finding or recommendation says a claim is or is not covered, valid, eligible or likely "
            "to be approved. The system holds no policy terms, so coverage is the handler's decision."
        ),
    ),
    "classification_confident": (
        "Claim category is confident",
        "The claim category did not need manual review.",
    ),
}


# Wording that states or implies a coverage conclusion. The system holds no policy terms, so a model
# that fills a gap with "this looks covered" (or "not covered") is guessing; the handler decides.
_COVERAGE_HEDGE = re.compile(
    r"\b(?:do|does|did|can|could|will|would|must|should|may|might)(?:\s+not|n't)\b(?:(?!\bbut\b|\band\b)[^.;,])*"
    r"|\b(?:cannot|can't|unable\s+to|never|nor)\b(?:(?!\bbut\b|\band\b)[^.;,])*"
    r"|\bwhether\b(?:(?!\bbut\b|\band\b)[^.;,])*"
    r"|\b(?:unverified|not\s+(?:been\s+)?(?:verified|assessed|determined|confirmed))\b(?:(?!\bbut\b|\band\b)[^.;,])*"
    r"|\b(?:verify|confirm|check|determine|assess|clarify)\b(?:(?!\bbut\b|\band\b)[^.;,])*"
)
_COVERAGE_ASSERTION = re.compile(
    r"\b(?:claim|loss|incident|damage|theft|event|peril|case)\b[^.;]{0,60}?"
    r"\b(?:is|are|was|were|appears?|seems?|looks?|remains?|should\s+be|would\s+be|will\s+be|"
    r"likely|probably)\s*(?:to\s+be\s+)?(?:clearly\s+|fully\s+|also\s+|likely\s+|probably\s+|not\s+)?"
    r"(?:covered|claimable|eligible|ineligible|payable|valid|invalid|legitimate|genuine|excluded|compensable)\b"
    r"|\b(?:likely|probably|expected)\s+to\s+be\s+(?:approved|paid|accepted|denied|rejected|covered)\b"
    r"|\b(?:should|will|would|must|ought\s+to)\s+be\s+(?:paid|approved|denied|rejected|honou?red)\b"
    r"|\b(?:qualif(?:y|ies|ied)|eligible|entitled)\s+(?:for|to)\s+"
    r"(?:coverage|payment|payout|reimbursement|compensation|benefits?)\b"
    r"|\b(?:valid|legitimate|genuine|invalid)\s+claim\b"
    r"|\b(?:isn't|is\s+not|not)\s+(?:covered|claimable|eligible)\b"
    r"|\boutside\s+(?:the\s+)?(?:policy|coverage)\b"
)


def asserts_coverage_conclusion(text: str) -> bool:
    """True when generated text states or implies that a claim is or is not covered or valid."""
    return bool(_COVERAGE_ASSERTION.search(_COVERAGE_HEDGE.sub(" ", text.lower())))


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
    coverage_texts = [f["text"] for f in state["findings"]]
    for r in state["recommendations"]:
        coverage_texts += [r["action"], r["reason"]]
    for text in coverage_texts:
        tally["coverage_assertion"]["inspected"] += 1
        if asserts_coverage_conclusion(text):
            fail(
                "coverage_assertion",
                "Generated text states or implies a coverage or eligibility conclusion; "
                "the system has no policy terms and the handler decides.",
            )
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
    def __init__(self, settings, adapter, analytics, fallback=None):
        self.settings, self.adapter, self.analytics = settings, adapter, analytics
        # Degraded-mode knowledge, used only after a live Synapt call fails (claims.retrieval.fallback).
        self.fallback = fallback
        self.last_retrieval: str | None = None
        self.store = Store(settings.claims_database_path)
        self.agents = Agents(settings, self.store.event)
        self.judge_agent = LLMJudge(settings, self.store.event)
        self.retriever = HistoricalRetriever(
            settings.claims_data_path,
            settings.claims_parquet_path,
            candidate_limit=settings.claims_candidate_limit,
            memory_limit=settings.claims_duckdb_memory,
            copy_path=settings.claims_sorted_copy_path,
        )
        self.lock = threading.RLock()
        self.judge_threads: list[threading.Thread] = []
        self.pending_queries: dict[str, Future] = {}
        self._summary, self._summary_for, self._summary_lock = None, None, threading.Lock()
        self.tracer = telemetry.Tracer(self.store)
        # The retrieve stage is a LangGraph graph of its own: four agents that run side by side (claims.retrieval.graph).
        self.retrieval_agents = RetrievalAgents(self)
        self.retrieval = RetrievalGraph(self)
        # The supervise stage is a LangGraph graph of its own: review the brief, write the summary, send it back once if it can be fixed.
        self.supervisor = Supervisor(self)
        # Spans of runs in progress, for the live view; telemetry reaches it through the store (the recorder).
        self.progress = ProgressBoard()
        self.store.progress = self.progress
        graph = StateGraph(InvestigationState)
        for name, action in (
            ("classify", self.classify),
            ("retrieve", self.retrieve),
            ("investigate", self.investigate),
            ("risk", self.risk),
            ("recommend", self.recommend),
            ("validate", self.validate),
            ("supervise", self.supervise),
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
        graph.add_edge("validate", "supervise")
        graph.add_edge("supervise", "judge")
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
                self._save_partial(state, result, name)
                return result

        run_stage.__name__ = f"traced_{name}"
        return run_stage

    PARTIAL_STAGES = ("retrieve", "investigate", "risk", "recommend")

    def _save_partial(self, state, result, name):
        """Save what has landed after a stage that produces something to read, so the page can show it while the rest is still
        running (`GET /api/investigations/{id}/preview`). The run is still "running"; the finished run replaces this save."""
        if name not in self.PARTIAL_STAGES:
            return
        try:
            self.store.save(state["run_id"], {**state, **result, "status": "running"})
        except Exception as error:  # noqa: BLE001 - a preview is a convenience and must never fail the investigation
            logger.warning("partial result could not be saved (%s)", type(error).__name__)

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
        if name == "supervise":
            record = out["supervisor"]
            return {
                "status": record.get("status"),
                "summary": bool(record.get("summary")),
                "revised": bool(record.get("revised")),
                "passed_after": (record.get("revision") or {}).get("passed_after"),
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
        with access.acting_as("triage"):
            result = self.agents.classify(ClaimInput.model_validate(state["claim"]), state["run_id"])
        claim = dict(state["claim"])
        claim["claim_type"] = result["claim_type"]
        return {"classification": result, "claim": claim} | self.trace(
            state, "classify", result["method"]
        )

    def _start_query_agent(self, claim, evidence_box, run_id):
        """Ask Synapt's query agent at once, beside the rest of retrieval. It needs only the claim type; the passages that are in
        the evidence are looked up when its answer comes back, through ``evidence_box``. The worker is handed the trace
        position, because a thread does not inherit it."""
        context = telemetry.current()
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="query-agent")

        def known():
            try:
                return evidence_box.result(timeout=60)
            except Exception:  # noqa: BLE001 - retrieval failed: the answer is still shown, with no passage marked as in evidence
                return set()

        def work():
            with telemetry.attach(context), access.acting_as("knowledge_qa"):
                question = self.retrieval_agents.write_question(claim, run_id)  # None keeps the fixed question
                return query_agent.run_query(self.adapter.ask, claim, known, run_id, question=question)

        future = pool.submit(work)
        pool.shutdown(wait=False)
        return future

    def _attach_query_answer_later(self, run_id, task):
        """Wait for a query-agent answer the brief did not wait for, then put it on the saved run. Daemon thread, like the judge's."""

        def work():
            try:
                answer = task.result(timeout=120)
            except Exception:  # noqa: BLE001 - never shown; the panel says the knowledge base did not answer
                answer = query_agent.unavailable(
                    "The Synapt query agent did not answer for this claim; the brief does not depend on it."
                )
            try:
                self.store.set_query_agent(run_id, answer)
            except Exception as error:  # noqa: BLE001 - e.g. the database closed during shutdown
                logger.warning("query agent answer could not be saved (%s)", type(error).__name__)

        thread = threading.Thread(target=work, name="query-late-" + run_id[:8], daemon=True)
        self.judge_threads = [t for t in self.judge_threads if t.is_alive()] + [thread]
        thread.start()

    def _cohort_summary(self):
        """The pre-aggregated cohort tables, if a summary built for this very dataset is on disk; otherwise None and the scan runs."""
        store = self.retriever.store
        with self._summary_lock:
            if store is None:
                return None
            if self._summary_for is not store:
                self._summary_for = store
                self._summary = CohortSummary.open(self.settings.claims_cohort_summary_path, store, DEFAULT_CUTOFF)
            return self._summary

    def _cohort_worker(self, context, claim, semantic_box):
        """The DuckDB scan for the cohort figures, started before retrieval has finished: it needs nothing from retrieval
        until the cross-check at the end, which waits for the semantic matches through ``semantic_box``."""
        with telemetry.attach(context), access.acting_as("history_analyst"), telemetry.span("cohort.statistics", kind="compute") as trace:
            access.authorize("cohort.statistics")
            cohort = cohort_statistics(
                self.retriever.store,
                claim,
                late=lambda: semantic_box.result(timeout=120),
                summary=self._cohort_summary(),
            )
            trace.set(**trace_attributes(cohort))
            return cohort

    def _pool_worker(self, context, claim, filters):
        """The DuckDB search for the 300 closest past claims by feature score. It needs only the claim and the filters, so it starts
        with retrieval; the semantic matches are added to it later, from the passages."""
        with telemetry.attach(context), access.acting_as("history_analyst"), telemetry.span("history.candidates", kind="retrieval") as trace:
            access.authorize("history.search")
            rows = self.retriever.prefetch(claim, filters)
            trace.set(candidates=len(rows or []))
            return rows

    def _graph_worker(self, context, claim, run_id=None):
        """The knowledge-graph lookup, run beside the past-claim search, then the model's follow-up for the procedures the standard
        searches missed. Returns the graph and whether the lookup failed."""
        with telemetry.attach(context), access.acting_as("graph_navigator"), telemetry.span("knowledge.graph", kind="tool") as trace:
            failed = False
            try:
                graph = self.adapter.retrieve_graph(claim)
            except SynaptError:
                failed = True
                graph = knowledge_graph.unavailable(
                    "The Synapt knowledge-graph lookup failed for this claim; handling guidance uses passages only."
                )
            if not failed:
                graph = self.retrieval_agents.graph_followup(claim, graph, run_id)
            trace.set(available=graph["available"], procedures=len(graph["procedures"]))
            return graph, failed

    def retrieve_context(self, claim, filters, *, with_cohort=True, with_graph=True, with_query=True, run_id=None, query_wait=None):
        """The retrieve stage: four agents (``claims.retrieval.graph``) work at the same moment, as nodes of a LangGraph graph.

        The cohort scan, the graph lookup and the query agent need only the claim, so they start with the passage search instead of
        after it, and the past-claim ranking (which needs the passages' semantic matches) follows as soon as those are in. The results
        are put back in the order they always had, so the evidence list does not depend on which part finished first.

        The query agent's answer is display only, so the brief does not wait for it: after ``query_wait`` seconds (default
        ``QUERY_WAIT_SECONDS``) the run carries a "pending" answer and the answer is attached when it arrives. A run that had to
        fall back to the local copy of the knowledge base ignores the graph and the answer, which were asked for before it was known."""
        return self.retrieval.run(
            claim,
            filters,
            with_cohort=with_cohort,
            with_graph=with_graph,
            with_query=with_query,
            run_id=run_id,
            query_wait=query_wait,
        )

    def settle_query_answer(self, run_id, result):
        """Called when the brief is ready: give the query agent's answer a last moment to arrive, because it has had the whole
        model stage (about 11 s) to finish. If it has, the run carries it; if it has not, the run stays pending and the answer is
        attached to the saved run when it comes. A failure is reported the way it always was, as a limitation."""
        task = self.pending_queries.pop(run_id, None)
        if task is None or not (result.get("query_agent") or {}).get("pending"):
            return result
        try:
            answer = task.result(timeout=QUERY_GRACE_SECONDS)
        except FutureTimeout:
            return result
        except Exception:  # noqa: BLE001 - never shown
            answer = query_agent.unavailable(
                "The Synapt query agent did not answer for this claim; the brief does not depend on it."
            )
            result = result | {
                "findings": [*(result.get("findings") or []), {"kind": "limitation", "text": answer["reason"], "source_ids": []}]
            }
        return result | {"query_agent": answer}

    def retrieve(self, state):
        context = self.retrieve_context(
            ClaimInput.model_validate(state["claim"]),
            SearchFilters.model_validate(state["filters"]),
            run_id=state["run_id"],
            query_wait=0,
        )
        source = "local fallback" if context["mode"] == "degraded" else "Synapt"
        return {
            "mode": context["mode"],
            "evidence": context["evidence"],
            "similar_cases": context["similar_cases"],
            "cohort": context["cohort"],
            "graph": context["graph"],
            "query_agent": context["query_agent"],
            "findings": [
                {"kind": "limitation", "text": warning, "source_ids": []}
                for warning in context["warnings"]
            ],
        } | self.trace(
            state,
            "retrieve",
            f"{len(context['evidence'])} cited evidence entries; {len(context['similar_cases'])} historical "
            f"cases ranked by BM25 + feature similarity + {source} semantic rank ({source} matched "
            f"{context['semantic']['semantic_candidates']} similar past claim(s); "
            f"{context['semantic']['semantic_eligible']} eligible under the filters; "
            f"{context['semantic']['semantic_in_results']} in the top results); "
            f"{len(context['lessons_used'])} reviewed handler lesson(s) applied"
            + (
                f"; {len(context['graph']['procedures'])} handling procedure(s) read from the knowledge graph"
                if context["graph"] and context["graph"]["available"]
                else ""
            )
            + (
                "; the Synapt query agent answered a handling question (display only)."
                if (context["query_agent"] or {}).get("available")
                else "; the Synapt query agent was asked beside retrieval and its answer is added when it arrives (display only)."
                if (context["query_agent"] or {}).get("pending")
                else "."
            ),
        )

    def investigate(self, state):
        with access.acting_as("investigator"):
            findings = self.agents.investigate(
                ClaimInput.model_validate(state["claim"]),
                state["evidence"],
                state["similar_cases"],
                state["run_id"],
            )
        return {"findings": state.get("findings", []) + findings, "investigator_findings": findings} | self.trace(
            state, "investigate", "Compared evidence, gaps and supported contradictions"
        )

    def risk(self, state):
        with access.acting_as("risk_analyst"):
            return self._risk(state)

    def _risk(self, state):
        priority, predictions = self._risk_values(state)
        return {"priority": priority, "predictions": predictions} | self.trace(
            state,
            "risk",
            f"Priority {priority['tier']} (score {priority['score']}/100) from stated factors; "
            "queue policy kept separate from statistical predictions",
        )

    def _risk_values(self, state):
        """The estimates and the priority for a brief's findings (the Risk Analyst's work), without recording a stage."""
        claim = ClaimInput.model_validate(state["claim"])
        with telemetry.span("models.predict", kind="compute") as trace:
            access.authorize("models.predict")
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
            access.authorize("priority.score")
            priority = score_priority(
                claim,
                state["findings"],
                predictions,
                state.get("similar_cases", []),
                state["classification"],
            )
            trace.set(score=priority["score"], tier=priority["tier"])
        return priority, predictions

    def recommend(self, state):
        with access.acting_as("recommender"):
            recommendations = self.agents.recommend(state, state["run_id"])
        return {"recommendations": recommendations} | self.trace(
            state, "recommend", "Prepared handler actions; no adjudication"
        )

    def validate(self, state):
        with access.acting_as("validator"):
            access.authorize("brief.validate")
            validation = validate_brief(state)
        return {
            "validation": validation,
            "status": "awaiting_review" if validation["passed"] else "needs_manual_review",
        } | self.trace(
            state,
            "validate",
            "; ".join(validation["issues"]) or "Citation and boundary checks passed",
        )

    def supervise(self, state):
        update = self.supervisor.supervise(state)
        return update | self.trace(state, "supervise", stage_detail(update["supervisor"]))

    def revise_brief(self, work, feedback):
        """The Supervisor's revision: the findings go back to the Investigation Agent with the reviewer's feedback, then the risk
        analyst, the Recommendation Agent and the validator work on the result in turn, so what comes back is a checked brief."""
        run_id = work["run_id"]
        claim = ClaimInput.model_validate(work["claim"])
        kept = work["findings"][: len(work["findings"]) - len(work.get("investigator_findings", []))]  # what retrieval reported
        with access.acting_as("investigator"):
            rewritten = self.agents.investigate(claim, work["evidence"], work["similar_cases"], run_id, revision=feedback)
        revised = work | {"findings": kept + rewritten, "investigator_findings": rewritten}
        with access.acting_as("risk_analyst"):
            priority, predictions = self._risk_values(revised)
        revised |= {"priority": priority, "predictions": predictions}
        with access.acting_as("recommender"):
            revised["recommendations"] = self.agents.recommend(revised, run_id)
        with access.acting_as("validator"):
            access.authorize("brief.validate")
            revised["validation"] = validate_brief(revised)
        return revised

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
            access.acting_as("judge", background=True),
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

    def create(self, claim, filters, run_id=None, owner=None):
        """Run one investigation. Investigations run one at a time, so a second caller waits for the lock;
        the live view (`self.progress`) shows that wait as "queued". ``run_id`` may be supplied by the caller
        (a UUID it has already told the page about) so the page can follow the run while it is in progress."""
        run_id = run_id or str(uuid4())
        self.progress.register(run_id, owner)
        status = "failed"
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
        try:
            with self.lock:
                self.progress.mark_running(run_id)
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
                status = result.get("status") or "failed"
                result = self.settle_query_answer(run_id, result)
                self.store.save(run_id, result)
                return result
        finally:
            self.progress.finish(run_id, status)

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
        """Make a reviewed handler lesson reusable: later investigations cite it, and it is also
        ingested (once, never retried) into the Synapt provider."""
        with self.lock:
            lesson = self.store.lesson(lesson_id)
            if lesson is None:
                raise KeyError(lesson_id)
            if not lesson["reviewed"]:
                raise ValueError("Only feedback on an accepted (reviewed) brief can be promoted")
            if lesson["promoted"]:
                raise ValueError("This lesson is already promoted")
            run = self.store.get(lesson["run_id"])
            with access.acting_as("ingestion"):
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
