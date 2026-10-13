"""Per-query tracing: nested spans with timing, outcome and bounded attributes.

A trace is the ordered record of what one investigation did: which stages ran, how long each took,
which model and retrieval calls happened inside them, what they returned (counts and identifiers,
never credentials) and how the run ended. Spans are written to SQLite as they close, so a run that
fails part-way still leaves the trace of everything it did before failing.

Instrumented code calls :func:`span`; it records only while a trace is active for the current
context and is otherwise a no-op, so retrieval, model and adapter code stays usable on its own
(tests, scripts, the stand-alone search endpoint).

Runs saved before span tracing existed have no spans. :func:`reconstruct_spans` rebuilds an
approximate trace for them from the audit events they already have (stage completions, model
prompts, outputs and failures), and marks every reconstructed span so a reader is never told that
approximate timings were measured.
"""

import json
import logging
import math
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import ClassVar

logger = logging.getLogger(__name__)

MAX_VALUE_BYTES = 8_000
MAX_ATTRIBUTE_BYTES = 24_000
# The few attributes that aggregate views read without parsing a span's full attribute blob.
LIGHT_ATTRIBUTES = (
    "purpose",
    "model",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "attempts",
    "outcome",
    "origin",
    "error_type",
    "tool",
    "agent",
    "background",
    "mode",
    "agent_mode",
)
# Output schema class -> what the model call was for. The schema is the one stable label: the
# agents pass a long instruction sentence as their "role".
LLM_PURPOSES = {
    "Classification": "classification",
    "Investigation": "investigation",
    "Recommendations": "recommendation",
    "JudgeVerdict": "judge",
}
_ROLE_PREFIXES = (
    ("Classify", "classification"),
    ("Identify useful", "investigation"),
    ("Write focused", "recommendation"),
    ("judge", "judge"),
)


def purpose_for_schema(schema) -> str:
    return LLM_PURPOSES.get(getattr(schema, "__name__", ""), "completion")


def purpose_for_role(role) -> str:
    text = str(role or "")
    return next((purpose for prefix, purpose in _ROLE_PREFIXES if text.startswith(prefix)), "other")


def _sanitize(value, depth=0):
    """JSON-safe copy: finite numbers only, string keys, unknown objects as text."""
    if depth > 8:
        return str(value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _sanitize(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_sanitize(v, depth + 1) for v in value]
    return str(value)


def clean_attributes(attributes: dict) -> dict:
    """Bounded, JSON-safe attributes. An oversized value is replaced by a marker, never cut in half."""
    cleaned = {}
    for key, value in attributes.items():
        value = _sanitize(value)
        size = len(json.dumps(value))
        cleaned[str(key)] = {"truncated": True, "bytes": size} if size > MAX_VALUE_BYTES else value
    if len(json.dumps(cleaned)) > MAX_ATTRIBUTE_BYTES:
        cleaned = {
            k: v for k, v in cleaned.items() if not isinstance(v, (dict, list))
        } | {"truncated_attributes": True}
    return cleaned


class SpanHandle:
    """What instrumented code holds while a span is open."""

    __slots__ = ("attributes", "parent_id", "span_id", "status")

    def __init__(self, span_id, parent_id, attributes):
        self.span_id, self.parent_id = span_id, parent_id
        self.attributes = dict(attributes)
        self.status = "ok"

    def set(self, **attributes):
        self.attributes.update(attributes)
        return self

    def fail(self, error):
        # The exception type only: messages from providers are never copied into a trace.
        self.status = "error"
        self.attributes["error_type"] = type(error).__name__

    def waiting(self):
        self.status = "waiting"


class _NoSpan:
    """Stand-in used when no trace is active, so callers never branch."""

    span_id = None
    parent_id = None
    status = "ok"
    attributes: ClassVar[dict] = {}

    def set(self, **attributes):
        return self

    def fail(self, error):
        return None

    def waiting(self):
        return None


_NO_SPAN = _NoSpan()


@dataclass(frozen=True)
class TraceContext:
    recorder: object
    run_id: str
    span_id: str | None
    # Work recorded inside background work (the independent review) is background too: a reader
    # must not count it as time a handler waited for the brief.
    background: bool = False


_active: ContextVar[TraceContext | None] = ContextVar("claims_trace", default=None)


def current() -> TraceContext | None:
    """The active trace position; hand it to a worker thread with :func:`attach`."""
    return _active.get()


@contextmanager
def attach(context):
    """Continue a trace inside another thread (threads do not inherit the caller's context)."""
    if context is None:
        yield
        return
    token = _active.set(context)
    try:
        yield
    finally:
        _active.reset(token)


def resume(recorder, run_id, parent_id, *, background=True) -> TraceContext | None:
    """A trace position inside a run that has already finished, for work done on it afterwards.

    Evaluation judging scores each case's brief after its investigation ended. Recording that work
    under the same run lets it show in the run's trace, flagged as background so it is never counted
    as time a handler waited. ``None`` when the run has no native root span (saved before tracing)."""
    if not parent_id:
        return None
    return TraceContext(recorder, run_id, parent_id, background)


_origin: ContextVar[str] = ContextVar("claims_trace_origin", default="user")


@contextmanager
def origin(name):
    """Label runs started inside this block (for example ``evaluation`` for the golden suite)."""
    token = _origin.set(name)
    try:
        yield
    finally:
        _origin.reset(token)


def current_origin() -> str:
    return _origin.get()


_agent: ContextVar[str | None] = ContextVar("claims_trace_agent", default=None)


@contextmanager
def as_agent(agent_id):
    """Mark every span opened inside this block as the work of one agent (``claims.agents.access`` uses it)."""
    token = _agent.set(agent_id)
    try:
        yield
    finally:
        _agent.reset(token)


def current_agent() -> str | None:
    return _agent.get()


def _is_interrupt(error) -> bool:
    # LangGraph raises GraphInterrupt to pause at the handler gate; that is waiting, not failing.
    return any(cls.__name__ == "GraphInterrupt" for cls in type(error).__mro__)


@contextmanager
def _open(recorder, run_id, parent_id, name, kind, attributes, inherited_background=False):
    handle = SpanHandle(uuid.uuid4().hex[:16], parent_id, attributes)
    if _agent.get() and "agent" not in handle.attributes:
        handle.attributes["agent"] = _agent.get()
    background = inherited_background or handle.attributes.get("background") is True
    if background:
        handle.attributes["background"] = True
    token = _active.set(TraceContext(recorder, run_id, handle.span_id, background))
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    # The live view (claims.observability.progress) hears of a span when it opens, not only when it closes and is saved.
    live = getattr(recorder, "progress", None)
    if live is not None:
        try:
            live.span_start(run_id, handle.span_id, parent_id, name, kind, handle.attributes, background)
        except Exception as error:  # noqa: BLE001 - observability must never break the work it observes
            logger.warning("span %r could not be shown live (%s)", name, type(error).__name__)
    try:
        yield handle
    except Exception as error:
        if _is_interrupt(error):
            handle.waiting()
        else:
            handle.fail(error)
        raise
    finally:
        _active.reset(token)
        duration_ms = (time.perf_counter() - started) * 1000
        if live is not None:
            try:
                live.span_end(run_id, handle.span_id, handle.status, round(duration_ms, 3), handle.attributes)
            except Exception as error:  # noqa: BLE001 - observability must never break the work it observes
                logger.warning("span %r could not be closed live (%s)", name, type(error).__name__)
        try:
            recorder.add_span(
                run_id=run_id,
                span_id=handle.span_id,
                parent_id=parent_id,
                name=name,
                kind=kind,
                started_at=started_at.isoformat(),
                duration_ms=round(duration_ms, 3),
                status=handle.status,
                attributes=clean_attributes(handle.attributes),
            )
        except Exception as error:  # noqa: BLE001 - observability must never break the work it observes
            logger.warning("span %r could not be recorded (%s)", name, type(error).__name__)


@contextmanager
def span(name, kind="step", **attributes):
    """A child span of the active trace position; a no-op when nothing is being traced."""
    context = _active.get()
    if context is None:
        yield _NO_SPAN
        return
    with _open(
        context.recorder,
        context.run_id,
        context.span_id,
        name,
        kind,
        attributes,
        context.background,
    ) as handle:
        yield handle


class Tracer:
    """Opens the root and stage spans of a run.

    Stage spans are parented explicitly through the root registered here rather than through the
    ambient context: the workflow engine may execute a node on a thread that did not inherit it.
    """

    def __init__(self, recorder):
        self.recorder = recorder
        self._roots: dict[str, str] = {}
        self._lock = threading.Lock()

    @contextmanager
    def run(self, run_id, name, **attributes):
        with _open(self.recorder, run_id, None, name, "run", attributes) as handle:
            with self._lock:
                self._roots[run_id] = handle.span_id
            try:
                yield handle
            finally:
                with self._lock:
                    self._roots.pop(run_id, None)

    @contextmanager
    def stage(self, run_id, name, **attributes):
        with self._lock:
            parent = self._roots.get(run_id)
        with _open(self.recorder, run_id, parent, name, "stage", attributes) as handle:
            yield handle


# ---------------------------------------------------------------------------------------------
# Reading traces back
# ---------------------------------------------------------------------------------------------


def parse_time(value) -> datetime:
    return datetime.fromisoformat(value)


def percentile(values, q):
    """Linear-interpolated percentile (q in 0..100); None for an empty list."""
    data = sorted(v for v in values if v is not None)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    position = (len(data) - 1) * q / 100
    low = math.floor(position)
    high = min(low + 1, len(data) - 1)
    return data[low] + (data[high] - data[low]) * (position - low)


def describe(values) -> dict:
    data = [v for v in values if v is not None]
    return {
        "count": len(data),
        "p50": percentile(data, 50),
        "p95": percentile(data, 95),
        "max": max(data) if data else None,
        "mean": sum(data) / len(data) if data else None,
    }


def reconstruct_spans(run_id, events, run=None):
    """Approximate spans for a run that predates span tracing, from its audit events.

    ``events`` are dicts with ``id``, ``time``, ``kind`` and the small fields the audit body
    carries (``stage``, ``role``, ``model``, ``attempt``, ``elapsed_seconds``, token counts...).
    A stage's duration is the time since the previous stage finished, a model call's duration is
    the interval between its prompt and its answer. Both are approximations, and every returned
    span says so.
    """
    events = sorted(events, key=lambda e: e["id"])
    stages = [e for e in events if e["kind"] == "stage"]
    if not stages:
        return []
    run = run or {}
    first = parse_time(events[0]["time"])
    windows, previous_end = [], first
    for event in stages:
        end = parse_time(event["time"])
        windows.append((event, min(previous_end, end), end))
        previous_end = end
    root_id = f"audit-root-{run_id[:8]}"
    origin = "user" if any(e["kind"] == "submitted_by" for e in events) else "evaluation"
    marker = {"reconstructed": True}
    spans = [
        {
            "run_id": run_id,
            "span_id": root_id,
            "parent_id": None,
            "name": "investigation",
            "kind": "run",
            "started_at": first.isoformat(),
            "duration_ms": (previous_end - first).total_seconds() * 1000,
            "status": "error" if run.get("status") == "failed" else "ok",
            "attributes": marker
            | {
                "origin": origin,
                "mode": run.get("mode"),
                "agent_mode": run.get("agent_mode"),
                "outcome": run.get("status"),
            },
        }
    ]
    stage_ids = {}
    for event, start, end in windows:
        name = event.get("stage") or "stage"
        stage_ids[name] = f"audit-stage-{event['id']}"
        spans.append(
            {
                "run_id": run_id,
                "span_id": stage_ids[name],
                "parent_id": root_id,
                "name": name,
                "kind": "stage",
                "started_at": start.isoformat(),
                "duration_ms": (end - start).total_seconds() * 1000,
                "status": "ok",
                "attributes": marker,
            }
        )

    calls: list[dict] = []
    for event in events:
        if event["kind"] == "model_prompt":
            if event.get("attempt") in (None, 1) or not calls or calls[-1]["closed"]:
                calls.append({"attempts": [], "closed": False})
            calls[-1]["attempts"].append({"prompt": event, "end": None})
        elif event["kind"] in ("model_output", "model_failure") and calls and calls[-1]["attempts"]:
            calls[-1]["attempts"][-1]["end"] = event
            calls[-1]["closed"] = calls[-1]["closed"] or event["kind"] == "model_output"
    for call in calls:
        first_prompt = call["attempts"][0]["prompt"]
        last = call["attempts"][-1]
        start = parse_time(first_prompt["time"])
        end = parse_time(last["end"]["time"]) if last["end"] else start
        purpose = purpose_for_role(first_prompt.get("role"))
        if purpose == "judge" and "judge" in stage_ids:
            parent = stage_ids["judge"]
        else:
            parent = next(
                (
                    stage_ids[(e.get("stage") or "stage")]
                    for e, s, f in windows
                    if s <= start < f
                ),
                next(
                    (
                        stage_ids[(e.get("stage") or "stage")]
                        for e, s, f in windows
                        if s <= start <= f
                    ),
                    root_id,
                ),
            )
        output = last["end"] if last["end"] and last["end"]["kind"] == "model_output" else None
        spans.append(
            {
                "run_id": run_id,
                "span_id": f"audit-llm-{first_prompt['id']}",
                "parent_id": parent,
                "name": f"llm.{purpose}",
                "kind": "llm",
                "started_at": start.isoformat(),
                "duration_ms": (end - start).total_seconds() * 1000,
                "status": "ok" if output else "error",
                "attributes": marker
                | {
                    "purpose": purpose,
                    "model": first_prompt.get("model"),
                    "attempts": len(call["attempts"]),
                    "background": purpose == "judge",
                    "prompt_tokens": output.get("prompt_tokens") if output else None,
                    "completion_tokens": output.get("completion_tokens") if output else None,
                    "total_tokens": output.get("total_tokens") if output else None,
                    "prompt_events": [a["prompt"]["id"] for a in call["attempts"]],
                    "output_event": output["id"] if output else None,
                    "error_type": None if output else "CompletionError",
                },
            }
        )
    for event in events:
        if event["kind"] == "handler_review":
            spans.append(
                {
                    "run_id": run_id,
                    "span_id": f"audit-review-{event['id']}",
                    "parent_id": None,
                    "name": "handler_review",
                    "kind": "run",
                    "started_at": parse_time(event["time"]).isoformat(),
                    "duration_ms": 0.0,
                    "status": "ok",
                    "attributes": marker | {"outcome": event.get("decision")},
                }
            )
    return spans


def build_trace(spans, source):
    """Order spans depth-first and place each on a shared millisecond axis."""
    if not spans:
        return {"source": source, "started_at": None, "total_ms": 0, "spans": []}
    ordered = sorted(spans, key=lambda s: (parse_time(s["started_at"]), s.get("seq", 0)))
    t0 = parse_time(ordered[0]["started_at"])
    ids = {s["span_id"] for s in ordered}
    children: dict = {}
    for item in ordered:
        parent = item["parent_id"] if item["parent_id"] in ids else None
        children.setdefault(parent, []).append(item)
    flat = []

    def walk(parent, depth):
        for item in children.get(parent, []):
            offset = (parse_time(item["started_at"]) - t0).total_seconds() * 1000
            flat.append(
                {
                    "span_id": item["span_id"],
                    "parent_id": item["parent_id"] if item["parent_id"] in ids else None,
                    "name": item["name"],
                    "kind": item["kind"],
                    "status": item["status"],
                    "started_at": item["started_at"],
                    "offset_ms": round(max(offset, 0.0), 3),
                    "duration_ms": round(item["duration_ms"], 3),
                    "depth": depth,
                    "attributes": item.get("attributes") or {},
                }
            )
            walk(item["span_id"], depth + 1)

    walk(None, 0)
    total = max((s["offset_ms"] + s["duration_ms"] for s in flat), default=0.0)
    return {
        "source": source,
        "started_at": ordered[0]["started_at"],
        "total_ms": round(total, 3),
        "spans": flat,
    }


def summarize_spans(spans) -> dict | None:
    """The figures a list or dashboard shows for one run, from native or reconstructed spans."""
    if not spans:
        return None
    root = next(
        (s for s in spans if s["parent_id"] is None and s["name"] == "investigation"), None
    )
    starts = [parse_time(s["started_at"]) for s in spans]
    ends = [
        parse_time(s["started_at"]).timestamp() * 1000 + s["duration_ms"]
        for s in spans
        if not (s.get("attributes") or {}).get("background")
    ]
    started = min(starts)
    duration_ms = (
        root["duration_ms"]
        if root
        else max(ends, default=started.timestamp() * 1000) - started.timestamp() * 1000
    )
    stages = {}
    for item in sorted(
        (s for s in spans if s["kind"] == "stage"), key=lambda s: parse_time(s["started_at"])
    ):
        stages[item["name"]] = {
            "stage": item["name"],
            "duration_ms": item["duration_ms"],
            "status": item["status"],
        }
    llm = [s for s in spans if s["kind"] == "llm"]
    tokens = {"prompt": 0, "completion": 0, "total": 0}
    by_purpose: dict = {}
    for item in llm:
        a = item.get("attributes") or {}
        prompt, completion, total = (
            a.get("prompt_tokens") or 0,
            a.get("completion_tokens") or 0,
            a.get("total_tokens") or 0,
        )
        tokens["prompt"] += prompt
        tokens["completion"] += completion
        tokens["total"] += total or (prompt + completion)
        bucket = by_purpose.setdefault(
            a.get("purpose") or "completion",
            {"calls": 0, "ms": 0.0, "tokens": 0, "model": a.get("model")},
        )
        bucket["calls"] += 1
        bucket["ms"] += item["duration_ms"]
        bucket["tokens"] += total or (prompt + completion)
    errors = [
        {"span": s["name"], "error_type": (s.get("attributes") or {}).get("error_type")}
        for s in spans
        if s["status"] == "error"
    ]
    root_attributes = (root or {}).get("attributes") or {}
    return {
        "started_at": started.isoformat(),
        "duration_ms": round(duration_ms, 3),
        "stages": list(stages.values()),
        "llm": {
            "calls": len(llm),
            "total_ms": round(sum(s["duration_ms"] for s in llm), 3),
            "retries": sum(max((s.get("attributes") or {}).get("attempts") or 1, 1) - 1 for s in llm),
            "failures": sum(s["status"] == "error" for s in llm),
            "tokens": tokens,
            "by_purpose": by_purpose,
        },
        "errors": errors,
        "origin": root_attributes.get("origin"),
        "outcome": root_attributes.get("outcome"),
    }
