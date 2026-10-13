"""The retrieve stage as a LangGraph graph of agents.

The investigation graph (``workflow.py``) has one node per stage. Most stages are one agent. Gathering evidence is four agents
working at the same moment, so this stage is itself a small LangGraph graph: four agent nodes that run side by side (a fan-out),
then one node that joins what they found (a fan-in).

    START ─┬─> passage_retriever ──┐
           ├─> graph_navigator ────┤
           ├─> knowledge_qa ───────┼─> assemble_evidence ─> END
           └─> history_analyst ────┘

Each agent node runs as that agent (``claims.agents.access.acting_as``): it can call only the tools in its role, and what it does is
recorded under its name. The agents reach each other only through the shared working data (``Board``) and the graph's state.
Because LangGraph runs the nodes of one step in parallel threads, the speed work is kept: the cohort scan, the past-claim search,
the graph lookup and the query agent still all start at once, and the past-claim ranking still waits only for the passages'
semantic matches.

Nothing here is checkpointed: the stage is quick, and its result is saved by the stage that called it.
"""

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from claims.agents import access
from claims.core.schemas import ClaimInput, SearchFilters
from claims.corpus.cards import claim_ids_in_text
from claims.corpus.lessons import lesson_evidence
from claims.observability import telemetry
from claims.synapt import knowledge_graph, query_agent
from claims.synapt.adapter import SynaptError

logger = logging.getLogger(__name__)

AGENT_NODES = ("passage_retriever", "graph_navigator", "knowledge_qa", "history_analyst")
JOIN_NODE = "assemble_evidence"
# More than the nodes that run together, so no agent ever waits for a thread another agent holds.
MAX_CONCURRENCY = 8


@dataclass
class Board:
    """The working data of one retrieval, shared by the agents that run beside each other. The two boxes are how an agent that
    needs something from another waits for it: the past-claim ranking waits for the passages' semantic matches, and the query
    agent marks which of its passages are in the evidence."""

    claim: ClaimInput
    filters: SearchFilters
    run_id: str | None
    with_cohort: bool
    with_graph: bool
    with_query: bool
    query_wait: float | None
    context: Any = None
    semantic_box: Future = field(default_factory=Future)
    evidence_box: Future = field(default_factory=Future)
    query_task: Future | None = None


class RetrievalState(TypedDict, total=False):
    board: Board
    passages: dict
    graph_result: tuple
    graph_error: Exception
    history: dict
    result: dict


class RetrievalGraph:
    def __init__(self, service):
        self.service = service
        graph = StateGraph(RetrievalState)
        graph.add_node("passage_retriever", self.passage_retriever)
        graph.add_node("graph_navigator", self.graph_navigator)
        graph.add_node("knowledge_qa", self.knowledge_qa)
        graph.add_node("history_analyst", self.history_analyst)
        graph.add_node(JOIN_NODE, self.assemble_evidence)
        for name in AGENT_NODES:
            graph.add_edge(START, name)
        graph.add_edge(list(AGENT_NODES), JOIN_NODE)  # waits for all four
        graph.add_edge(JOIN_NODE, END)
        # checkpointer=False: called from inside a node of the investigation graph, this graph must not inherit its checkpointer.
        self.graph = graph.compile(checkpointer=False)

    def run(self, claim, filters, *, with_cohort=True, with_graph=True, with_query=True, run_id=None, query_wait=None) -> dict:
        board = Board(claim, filters, run_id, with_cohort, with_graph, with_query, query_wait, context=telemetry.current())
        try:
            state = self.graph.invoke({"board": board}, {"max_concurrency": MAX_CONCURRENCY})
        finally:
            # Anything still waiting on a box (an agent whose partner failed) is released rather than left to time out.
            for box in (board.semantic_box, board.evidence_box):
                if not box.done():
                    box.set_exception(RuntimeError("Retrieval did not finish."))
        return state["result"]

    # ---- the agents ---------------------------------------------------------------------------------------------------

    def passage_retriever(self, state: RetrievalState) -> dict:
        """Policy Passage Retriever: the passages and procedures that apply, and the past claims in the ticket store closest in meaning."""
        board, service = state["board"], self.service
        try:
            with access.acting_as("passage_retriever"):
                with telemetry.span("knowledge.retrieve", kind="tool", adapter="live") as trace:
                    try:
                        bundle = service.adapter.retrieve(board.claim)
                        service.last_retrieval = "synapt"
                    except SynaptError:
                        if service.fallback is None or not service.fallback.available():
                            raise
                        logger.warning("Synapt retrieval failed; serving degraded local knowledge")
                        trace.set(adapter="local_fallback", fell_back_from="synapt")
                        bundle = service.fallback.retrieve(board.claim)
                        service.last_retrieval = "local_fallback"
                    trace.set(evidence=len(bundle.evidence), semantic_cards=len(bundle.semantic_claim_ids), warnings=list(bundle.warnings))
                evidence = [e.model_dump(mode="json") for e in bundle.evidence]
                standard_ids = [e.source_id for e in bundle.evidence]
                # Semantic matches: the ticket store's own ranking of similar past claims first, then any claim identifiers that
                # appear in source-bearing evidence text.
                semantic_ids = list(
                    dict.fromkeys(
                        bundle.semantic_claim_ids
                        + [m for e in evidence if e["provenance"] == "synapt" for m in claim_ids_in_text(e["text"])]
                    )
                )
                board.semantic_box.set_result((semantic_ids, bundle.mode))
                # The standard search is done and the agents waiting for it have what they need. Now the model may add to it.
                if service.last_retrieval == "synapt":
                    evidence += service.retrieval_agents.passage_followup(board.claim, evidence, board.run_id)
            return {
                "passages": {
                    "bundle": bundle,
                    "live": service.last_retrieval == "synapt",
                    "warnings": list(bundle.warnings),
                    "evidence": evidence,
                    "standard_ids": standard_ids,
                    "semantic_ids": semantic_ids,
                }
            }
        finally:
            # The evidence box is filled when the evidence is assembled (after the passages are matched to the graph); if this
            # agent fails, run() releases it.
            if not board.semantic_box.done():
                board.semantic_box.set_exception(RuntimeError("Retrieval did not finish."))  # lets an agent waiting on it end

    def graph_navigator(self, state: RetrievalState) -> dict:
        """Procedure Graph Navigator: handling procedures read from the knowledge graph. A failure is reported, never silent."""
        board, service = state["board"], self.service
        if not (board.with_graph and hasattr(service.adapter, "retrieve_graph")):
            return {}
        try:
            return {"graph_result": service._graph_worker(board.context, board.claim, board.run_id)}
        except Exception as error:  # noqa: BLE001 - raised later, and only if the graph is used: a degraded run ignores it
            return {"graph_error": error}

    def knowledge_qa(self, state: RetrievalState) -> dict:
        """Knowledge Q&A Agent: asks the knowledge base's query agent beside everything else. Its answer is display only, so this
        node only starts the question; the answer is collected, or left pending, when the evidence is assembled."""
        board, service = state["board"], self.service
        if board.with_query and board.run_id and hasattr(service.adapter, "ask") and telemetry.current_origin() == "user":
            board.query_task = service._start_query_agent(board.claim, board.evidence_box, board.run_id)
        return {}

    def history_analyst(self, state: RetrievalState) -> dict:
        """Claims History Analyst: the cohort figures and the closest past claims, from this application's own data. The scan and
        the candidate search need only the claim, so they start at once; the ranking waits for the passages' semantic matches."""
        board, service = state["board"], self.service
        pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="history")
        try:
            cohort_task = pool.submit(service._cohort_worker, board.context, board.claim, board.semantic_box) if board.with_cohort else None
            numeric_task = pool.submit(service._pool_worker, board.context, board.claim, board.filters)
            try:
                semantic_ids, _ = board.semantic_box.result(timeout=120)
            except RuntimeError:
                return {}  # the passage search failed; its own error is the one that is reported
            with access.acting_as("history_analyst"), telemetry.span("history.search", kind="retrieval") as trace:
                access.authorize("history.search")
                similar = service.retriever.search(
                    board.claim, board.filters, service.settings.synapt_top_k, semantic_ids, pool=numeric_task.result()
                )
                trace.set(
                    semantic_ids_supplied=len(semantic_ids),
                    results=len(similar),
                    **service.retriever.last_search,
                    **service.retriever.last_trace,
                )
            return {"history": {"similar": similar, "cohort": cohort_task.result() if cohort_task is not None else None}}
        finally:
            pool.shutdown(wait=False)  # every result needed has been waited for; an unneeded one is not worth waiting for

    # ---- the join -----------------------------------------------------------------------------------------------------

    def assemble_evidence(self, state: RetrievalState) -> dict:
        """Not an agent: puts what the agents found together in the order the brief has always had (passages, graph procedures,
        the submitted claim, past cases, handler lessons), and collects or defers the query agent's answer."""
        from claims.investigation import (
            workflow,  # the waits are module settings that tests and operators adjust
        )

        board, service = state["board"], self.service
        passages = state["passages"]
        bundle, live, warnings, evidence = passages["bundle"], passages["live"], passages["warnings"], passages["evidence"]
        history = state.get("history") or {"similar": [], "cohort": None}
        similar, cohort = history["similar"], history["cohort"]
        # The knowledge graph (procedures found by meaning, walked step by step, with their source passages) was read in its own
        # call, so a failure there cannot break passage retrieval; it is reported, never silent. A run that had to fall back to the
        # local copy of the knowledge base ignores the graph and the answer, which were asked for before it was known.
        graph = None
        if live and state.get("graph_error") is not None:
            raise state["graph_error"]
        if state.get("graph_result") is not None and live:
            graph, graph_failed = state["graph_result"]
            if graph_failed:
                warnings.append(graph["reason"])
            elif graph["procedures"]:
                # Keep a standard passage only when it is the source of a procedure the graph chose for this claim; the rest are
                # other claim types' procedures. Passages the model's follow-up kept stay. With no graph, every passage stays.
                backed = knowledge_graph.backed_passages(graph["procedures"])
                standard = set(passages["standard_ids"])
                with telemetry.span("evidence.passages", kind="compute") as trace:
                    dropped = [e["source_id"] for e in evidence if e["source_id"] in standard - backed]
                    evidence = [e for e in evidence if e["source_id"] not in standard - backed]
                    trace.set(kept=len(evidence), dropped=dropped)
            provider = service.settings.synapt_provider_id or None
            evidence += [knowledge_graph.evidence_item(r, provider) for r in graph["procedures"]]
        board.evidence_box.set_result({e["source_id"] for e in evidence})
        evidence.append(
            {
                "source_id": "claim:input",
                "title": "Submitted claim, not independently verified",
                "text": str(board.claim.model_dump(mode="json")),
                "provenance": "user_input",
                "provider_id": None,
            }
        )
        for case in similar:
            evidence.append(
                {
                    "source_id": "history:" + case["claim_id"],
                    "title": "Synthetic historical case " + case["claim_id"],
                    "text": str(case),
                    "provenance": "published_synthetic"
                    if service.retriever.origin == "published_synthetic_dataset"
                    else "synthetic_fixture",
                    "provider_id": None,
                }
            )
        query_result = None
        if board.query_task is not None and live:
            wait = workflow.QUERY_WAIT_SECONDS if board.query_wait is None else board.query_wait
            try:
                query_result = board.query_task.result(timeout=wait)
            except FutureTimeout:
                # A healthy call takes 6 to 13 s; on 12 October a slow Synapt took 30 to 48 s. The answer is display only, so
                # the brief goes ahead and the answer is attached to the saved run when it arrives.
                query_result = query_agent.pending(query_agent.question_for(board.claim), board.run_id)
                service._attach_query_answer_later(board.run_id, board.query_task)
                service.pending_queries[board.run_id] = board.query_task
            except Exception:  # noqa: BLE001 - the brief does not depend on the answer; a provider error is never shown
                query_result = query_agent.unavailable(
                    "The Synapt query agent did not answer for this claim; the brief does not depend on it."
                )
                warnings.append(query_result["reason"])
        # Reviewed handler lessons an administrator promoted: the feedback loop's return path.
        with telemetry.span("feedback.lessons", kind="retrieval") as trace:
            lessons = service.store.promoted_lessons(board.claim.claim_type.value if board.claim.claim_type else None)
            trace.set(applied=len(lessons), lesson_ids=[lesson["id"] for lesson in lessons])
        for lesson in lessons:
            evidence.append(lesson_evidence(lesson).model_dump(mode="json"))
        return {
            "result": {
                "evidence": evidence,
                "similar_cases": similar,
                "cohort": cohort,
                "graph": graph,
                "query_agent": query_result,
                "warnings": warnings,
                "semantic": dict(service.retriever.last_search),
                "lessons_used": [lesson["id"] for lesson in lessons],
                "mode": "degraded" if bundle.mode == "degraded" else "live",
            }
        }


def structure(retrieval: "RetrievalGraph", investigation, supervision=None) -> dict:
    """The compiled graphs as nodes and edges, for the Agents page: what is drawn is the graph that runs. Each node carries the
    agents that work in it; the retrieve and supervise nodes are the stages the other two graphs expand."""
    from claims.agents import roster

    def read(compiled, agents_of):
        drawn = compiled.get_graph()
        return {
            "nodes": [{"id": n, "agents": agents_of(n)} for n in drawn.nodes if n not in ("__start__", "__end__")],
            "edges": [{"from": e.source, "to": e.target, "conditional": bool(getattr(e, "conditional", False))} for e in drawn.edges],
            "mermaid": drawn.draw_mermaid(),
        }

    team = roster.investigation_agents()
    stage_agents = lambda stage: [a.id for a in team if a.stage == stage]
    result = {
        "investigation": read(investigation, stage_agents),
        "retrieve": read(retrieval.graph, lambda node: [node] if node in roster.AGENTS else []),
    }
    if supervision is not None:
        # inside the stage the Supervisor reviews, and the agents it sends the brief back to work on the revision
        result["supervise"] = read(supervision, lambda node: ["supervisor"] if node == "review" else ["investigator", "risk_analyst", "recommender", "validator"])
    return result
