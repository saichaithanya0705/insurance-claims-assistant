"""Live view of an investigation in progress: the spans it opens and closes, as they happen.

Spans are saved to SQLite only when they close, so a stored trace cannot show a call that is still running. The
``ProgressBoard`` keeps an in-memory copy of each run's spans, updated when a span opens and again when it closes
(`telemetry` calls it), and the API serves everything that changed since a cursor. Nothing here is simulated: every
row is a span that really opened, with the time it really took.

What a reader may see depends on the role. An administrator gets the technical line (tool name, the query sent,
`top_k`, the model and its token use). Anyone else gets a plain-language label and a result such as "3 passages", and
never a vendor tool name, a query, a model or an identifier. Raw span attributes are never sent: only the strings built
here, so a new attribute cannot leak by accident.

The board is bounded (runs kept, spans per run, how long a finished run stays) and thread-safe: spans open on the
request thread, on the thread an asynchronous Synapt call runs on, and on the background thread of the independent
review.
"""

import threading
import time

from claims.agents import roster

MAX_RUNS = 40
MAX_SPANS = 600
KEEP_FINISHED_SECONDS = 1800

STAGE_LABELS = {
    "classify": "Classify the claim",
    "retrieve": "Gather evidence and compare past claims",
    "investigate": "Compare evidence, gaps and contradictions",
    "risk": "Score priority and estimates",
    "recommend": "Prepare cited handler actions",
    "validate": "Check citations and decision boundaries",
    "supervise": "Review the brief and write the summary",
    "judge": "Start the independent review",
    "review": "Wait for a handler",
}
# synapt.call_tool, by what the call was for. (plain label, administrator wording)
CALL_PURPOSES = {
    "procedures": ("Look up handling procedures", "Passage search for handling procedures"),
    "similar_claims": ("Find similar past claims", "Ticket-store search for similar past claims (trident_query, ticket_mode=only)"),
    "graph_search": ("Search the knowledge graph for procedures", "Graph search for procedure nodes"),
    "graph_walk": ("Walk a procedure's steps in the graph", "Graph walk from a procedure node"),
    "graph_enrichment": ("Read extra graph context", "Optional graph enrichment"),
    "procedures_fallback": ("Ask the knowledge store directly", "Fallback query"),
    "graph_followup": ("Search the knowledge graph for another kind of procedure", "Follow-up graph search (chosen by the model)"),
    "graph_followup_walk": ("Read another procedure's steps", "Follow-up graph walk (chosen by the model)"),
    "passage_followup": ("Search for more passages", "Follow-up passage search (chosen by the model)"),
    "query_agent": ("Ask the knowledge base how to handle this kind of claim", "Query agent (trident_query) writes a handling answer"),
}
LLM_PURPOSES = {
    "classification": "Model classifies the claim",
    "investigation": "Model drafts the findings",
    "recommendation": "Model drafts the recommended actions",
    "judge": "Independent model reviews the brief",
    "retrieval": "Model decides on follow-up searches",
    "supervision": "Supervisor reviews the brief and writes the summary",
}
# (plain label, administrator label) for every other span name
NAMED = {
    "knowledge.retrieve": ("Search the knowledge store", "Retrieve from Synapt (or the local fallback)"),
    "synapt.retrieve": ("Retrieve passages and similar past claims", "Synapt passage and ticket retrieval"),
    "synapt.login": ("Sign in to the knowledge store", "Synapt login"),
    "synapt.initialize": ("Open a session", "MCP session initialize"),
    "synapt.list_tools": ("Discover the available tools", "MCP tools/list"),
    "knowledge.graph": ("Read handling procedures from the knowledge graph", "Synapt knowledge-graph lookup"),
    "synapt.graph": ("Search and walk the knowledge graph", "Synapt graph search and traversal"),
    "history.search": ("Compare against past claims in the dataset", "DuckDB search over past claims"),
    "history.candidates": ("Find the closest past claims in the dataset", "DuckDB candidate pool (300 closest by feature score)"),
    "cohort.statistics": ("Compute exact statistics for similar past claims", "DuckDB cohort statistics"),
    "feedback.lessons": ("Check reviewed handler lessons", "Promoted handler lessons"),
    "models.predict": ("Estimate amount, resolution time and fraud-flag signal", "Trained model predictions"),
    "priority.score": ("Score the handling priority", "Priority score"),
    "judge.review": ("Independent review in the background", "Independent judge (background)"),
    "investigation": ("Investigation", "Investigation"),
    "handler_review": ("Handler review", "Handler review"),
}


# The only span attributes the board keeps, and only when they are plain scalars. Everything a span records for the
# stored trace (attempt logs, ranked lists, prompts) stays out of memory here and off the wire.
KEEP = frozenset({
    "purpose", "tool", "query", "top_k", "depth", "edge_types", "items", "tools", "evidence", "semantic_cards",
    "procedures", "calls", "available", "results", "pool_size", "exact_claims", "applied", "score", "tier",
    "total_tokens", "attempts", "model", "error_type", "adapter", "claim_type", "similar_cases", "findings",
    "priority_tier", "recommendations", "passed", "status", "confidence_label", "agent", "method", "tool_total", "refused", "summary", "revised",
})


def _keep(attributes: dict) -> dict:
    kept = {}
    for key, value in attributes.items():
        if key in KEEP and (value is None or isinstance(value, str | int | float | bool)):
            kept[key] = value[:300] if isinstance(value, str) else value
    return kept


def _number(value):
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def _plural(n, one, many=None):
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def label(name: str, kind: str, attributes: dict, admin: bool) -> str:
    if kind == "stage":
        return STAGE_LABELS.get(name, name.replace("_", " ").capitalize())
    if kind == "agent":
        spec = roster.AGENTS.get(attributes.get("agent"))
        return spec.name if spec else name.replace(".", " ").replace("_", " ").capitalize()
    purpose = attributes.get("purpose")
    if name == "synapt.call_tool" and purpose in CALL_PURPOSES:
        return CALL_PURPOSES[purpose][1 if admin else 0]
    if kind == "llm":
        return LLM_PURPOSES.get(purpose, "Model call")
    if name in NAMED:
        return NAMED[name][1 if admin else 0]
    return name.replace(".", " ").replace("_", " ").capitalize()


def detail(name: str, attributes: dict) -> str | None:
    """The technical line, for administrators only."""
    parts = []
    if name == "synapt.call_tool":
        if attributes.get("tool"):
            parts.append(str(attributes["tool"]))
        if attributes.get("query"):
            parts.append(f"“{str(attributes['query'])[:140]}”")
        if _number(attributes.get("top_k")) is not None:
            parts.append(f"top {int(attributes['top_k'])}")
        if _number(attributes.get("depth")) is not None:
            parts.append(f"depth {int(attributes['depth'])}")
        if attributes.get("edge_types"):
            parts.append("edges " + str(attributes["edge_types"]).replace(",", ", "))
    elif attributes.get("kind") == "llm" or name.startswith("llm."):
        if attributes.get("model"):
            parts.append(str(attributes["model"]))
    elif name == "knowledge.retrieve" and attributes.get("adapter"):
        parts.append(f"adapter {attributes['adapter']}")
    return " · ".join(parts) or None


def result(name: str, kind: str, status: str, attributes: dict, admin: bool) -> str | None:
    """What a finished span produced, in words. None while it runs or when there is nothing useful to say."""
    a = attributes
    if status == "error":
        return "Failed" + (f" ({a['error_type']})" if admin and a.get("error_type") else "")
    if name == "synapt.call_tool":
        items = _number(a.get("items"))
        if items is None:
            return None
        if a.get("purpose") == "query_agent":
            return f"Answer · {a.get('confidence_label', 'unrated')} confidence · {_plural(int(items), 'passage')}"
        noun = {"procedures": ("passage", "passages"), "similar_claims": ("past claim", "past claims"),
                "graph_search": ("procedure", "procedures"), "graph_walk": ("node", "nodes"),
                "graph_followup": ("procedure", "procedures"), "graph_followup_walk": ("node", "nodes"),
                "passage_followup": ("passage", "passages")}.get(a.get("purpose"), ("item", "items"))
        return _plural(int(items), *noun)
    if name == "synapt.list_tools" and _number(a.get("tools")) is not None:
        return _plural(int(a["tools"]), "tool")
    if name == "synapt.retrieve":
        parts = []
        if _number(a.get("evidence")) is not None:
            parts.append(_plural(int(a["evidence"]), "passage"))
        if _number(a.get("semantic_cards")) is not None:
            parts.append(_plural(int(a["semantic_cards"]), "similar past claim"))
        return ", ".join(parts) or None
    if name == "synapt.graph" and _number(a.get("procedures")) is not None:
        return f"{_plural(int(a['procedures']), 'procedure')} from {_plural(int(a.get('calls') or 0), 'call')}"
    if name == "knowledge.graph":
        return _plural(int(a.get("procedures") or 0), "procedure") if a.get("available") else "Not available"
    if name == "knowledge.retrieve":
        return _plural(int(a["evidence"]), "passage") if _number(a.get("evidence")) is not None else None
    if name == "history.search" and _number(a.get("results")) is not None:
        pool = _number(a.get("pool_size"))
        return f"{_plural(int(a['results']), 'similar claim')} ranked" + (f" from {int(pool):,} candidates" if pool else "")
    if name == "cohort.statistics":
        if a.get("available") is False:
            return "Not available"
        return f"{int(a['exact_claims']):,} claims with the same description" if _number(a.get("exact_claims")) is not None else None
    if name == "feedback.lessons" and _number(a.get("applied")) is not None:
        return _plural(int(a["applied"]), "lesson") + " applied"
    if name == "models.predict":
        return "Estimates ready" if a.get("available") else "Estimates unavailable"
    if name == "priority.score" and _number(a.get("score")) is not None:
        return f"Priority {int(a['score'])}/100 ({a.get('tier')})" if a.get("tier") else f"Priority {int(a['score'])}/100"
    if kind == "llm":
        tokens = _number(a.get("total_tokens"))
        attempts = _number(a.get("attempts"))
        parts = []
        if tokens:
            parts.append(f"{int(tokens):,} tokens")
        if admin and attempts and attempts > 1:
            parts.append(f"{int(attempts)} attempts")
        return " · ".join(parts) or None
    if kind == "stage":
        return stage_result(name, a)
    if kind == "agent":
        made, refused = _number(a.get("tool_total")) or 0, _number(a.get("refused")) or 0
        text = _plural(int(made), "tool call") if made else "Done"
        return text + (f" · {_plural(int(refused), 'call')} refused" if refused else "")
    return None


def stage_result(name: str, a: dict) -> str | None:
    if name == "classify" and a.get("claim_type"):
        return f"{str(a['claim_type']).capitalize()} claim"
    if name == "retrieve" and _number(a.get("evidence")) is not None:
        return f"{_plural(int(a['evidence']), 'evidence item')}, {_plural(int(a.get('similar_cases') or 0), 'comparison case')}"
    if name == "investigate" and _number(a.get("findings")) is not None:
        return _plural(int(a["findings"]), "finding")
    if name == "risk" and a.get("priority_tier"):
        return f"Priority {a['priority_tier']}"
    if name == "recommend" and _number(a.get("recommendations")) is not None:
        return _plural(int(a["recommendations"]), "recommended action")
    if name == "supervise" and a.get("status"):
        return {"skipped": "Not run", "unavailable": "Not available"}.get(
            str(a["status"]), "Summary written, and fixed once" if a.get("revised") else ("Summary written" if a.get("summary") else "No summary")
        )
    if name == "validate" and "passed" in a:
        return "Checks passed" if a["passed"] else "Checks need attention"
    if name == "judge" and a.get("status"):
        return "Review running in the background" if a["status"] == "pending" else str(a["status"]).capitalize()
    return None


class _Span:
    __slots__ = ("attributes", "background", "duration_ms", "kind", "name", "parent_id", "seq", "span_id", "started_ms", "status")

    def __init__(self, span_id, parent_id, name, kind, attributes, background, started_ms, seq):
        self.span_id, self.parent_id, self.name, self.kind = span_id, parent_id, name, kind
        self.attributes, self.background = dict(attributes), background
        self.started_ms, self.duration_ms, self.status, self.seq = started_ms, None, "running", seq


class _Run:
    def __init__(self, owner):
        self.owner = owner
        self.t0 = time.perf_counter()
        self.state = "queued"
        self.outcome = None
        self.running_ms = None
        self.finished_at = None
        self.spans: dict[str, _Span] = {}
        self.seq = 0
        self.truncated = False

    def now_ms(self):
        return (time.perf_counter() - self.t0) * 1000

    def bump(self):
        self.seq += 1
        return self.seq


class ProgressBoard:
    def __init__(self, max_runs=MAX_RUNS, max_spans=MAX_SPANS, keep_finished_seconds=KEEP_FINISHED_SECONDS):
        self._runs: dict[str, _Run] = {}
        self._lock = threading.Lock()
        self.max_runs, self.max_spans, self.keep_finished_seconds = max_runs, max_spans, keep_finished_seconds

    # ---- written by the workflow and by telemetry ------------------------------------------------

    def register(self, run_id, owner=None):
        """The run exists and is waiting for its turn (investigations run one at a time)."""
        with self._lock:
            self._prune()
            self._runs[run_id] = _Run(owner)

    def known(self, run_id) -> bool:
        with self._lock:
            return run_id in self._runs

    def mark_running(self, run_id):
        with self._lock:
            run = self._runs.get(run_id)
            if run and run.state == "queued":
                run.state, run.running_ms = "running", run.now_ms()
                run.bump()

    def finish(self, run_id, status):
        with self._lock:
            run = self._runs.get(run_id)
            if run:
                run.state = "failed" if status == "failed" else "done"
                run.outcome, run.finished_at = status, time.time()
                run.bump()

    def span_start(self, run_id, span_id, parent_id, name, kind, attributes, background=False):
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:  # a run that did not register (a handler review, a script): admin-only
                self._prune()
                run = self._runs[run_id] = _Run(None)
                run.state = "running"
            if len(run.spans) >= self.max_spans:
                run.truncated = True
                return
            run.spans[span_id] = _Span(
                span_id, parent_id, name, kind, _keep(attributes), background, run.now_ms(), run.bump()
            )

    def span_end(self, run_id, span_id, status, duration_ms, attributes):
        with self._lock:
            run = self._runs.get(run_id)
            span = run.spans.get(span_id) if run else None
            if span is None:
                return
            span.status, span.duration_ms = status, duration_ms
            span.attributes.update(_keep(attributes))
            span.seq = run.bump()

    def _prune(self):
        now = time.time()
        for run_id in [r for r, v in self._runs.items() if v.finished_at and now - v.finished_at > self.keep_finished_seconds]:
            del self._runs[run_id]
        while len(self._runs) >= self.max_runs:
            finished = [r for r, v in self._runs.items() if v.finished_at]
            del self._runs[min(finished or self._runs, key=lambda r: self._runs[r].t0)]

    # ---- read by the API -------------------------------------------------------------------------

    def can_read(self, run_id, viewer_id, admin) -> bool:
        with self._lock:
            run = self._runs.get(run_id)
            return run is not None and (admin or (run.owner is not None and run.owner == viewer_id))

    def read(self, run_id, after=0, *, viewer_id=None, admin=False):
        """Everything that changed after `after`, for this viewer; None when the run is unknown or not theirs."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None or not (admin or (run.owner is not None and run.owner == viewer_id)):
                return None
            changed = [s for s in run.spans.values() if s.seq > after]
            rows = [self._row(run, s, admin) for s in sorted(changed, key=lambda s: s.started_ms)]
            calls = [s for s in run.spans.values() if s.name == "synapt.call_tool"]
            models = [s for s in run.spans.values() if s.kind == "llm"]
            return {
                "run_id": run_id,
                "state": run.state,
                "outcome": run.outcome,
                "now_ms": round(run.now_ms(), 1),
                "running_ms": None if run.running_ms is None else round(run.running_ms, 1),
                "next": run.seq,
                "truncated": run.truncated,
                "spans": rows,
                "counts": {
                    "knowledge_calls": len(calls),
                    "model_calls": len(models),
                    "open": sum(s.status == "running" and not s.background for s in run.spans.values()),
                },
            }

    @staticmethod
    def _parent(run: _Run, span: _Span):
        """The span this one hangs under as a reader sees it: an agent is the one who did the work, not a step in it, so work
        reaches past its agent to the stage (the agents are listed in their own right, with the ``agent`` field)."""
        parent = span.parent_id
        while parent is not None:
            above = run.spans.get(parent)
            if above is None or above.kind != "agent":
                return parent
            parent = above.parent_id
        return None

    def _row(self, run: _Run, span: _Span, admin: bool) -> dict:
        a = span.attributes
        done = span.status != "running"
        return {
            "id": span.span_id,
            "parent": span.parent_id if span.kind == "agent" else self._parent(run, span),
            "agent": a.get("agent"),
            "kind": span.kind,
            "name": span.name if span.kind == "stage" else None,
            "label": label(span.name, span.kind, a, admin),
            "detail": detail(span.name, a | {"kind": span.kind}) if admin else None,
            "result": result(span.name, span.kind, span.status, a, admin) if done else None,
            "status": span.status,
            "started_ms": round(span.started_ms, 1),
            "duration_ms": None if span.duration_ms is None else round(span.duration_ms, 1),
            "background": bool(span.background),
            "seq": span.seq,
        }
