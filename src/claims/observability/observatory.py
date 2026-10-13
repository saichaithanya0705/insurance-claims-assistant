"""Reading traces back, and system-wide metrics derived from them.

Three sources feed this module and are never blended silently:

* **recorded** spans, written while a run executed (precise timings, rich attributes);
* **reconstructed** spans, rebuilt from the audit events of runs saved before span tracing existed
  (approximate timings, no retrieval or model internals) and marked as such;
* the **request log**, one row per API call (route, status, latency).
"""

from datetime import UTC, datetime, timedelta

from claims.observability import telemetry

WINDOWS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "all": None,
}
ORIGINS = ("all", "user", "evaluation")
# Spans that are structure rather than work: the root and the stage wrappers.
STRUCTURE_KINDS = {"run", "stage", "agent"}


def _ms(value):
    return None if value is None else round(value, 1)


def _stats(values):
    stats = telemetry.describe(values)
    return {k: (v if k == "count" else _ms(v)) for k, v in stats.items()}


class Observatory:
    def __init__(self, store):
        self.store = store

    # ----- one run -----

    def light(self, run_ids):
        """run_id -> (source, spans) carrying only the attributes list and dashboard views read."""
        run_ids = list(run_ids)
        recorded = self.store.light_spans(run_ids)
        found = {run_id: ("recorded", spans) for run_id, spans in recorded.items()}
        missing = [run_id for run_id in run_ids if run_id not in recorded]
        if missing:
            facts = self.store.run_facts(missing)
            events = self.store.audit_light(missing)
            for run_id in missing:
                spans = telemetry.reconstruct_spans(run_id, events.get(run_id, []), facts.get(run_id))
                if spans:
                    found[run_id] = ("reconstructed", spans)
        return found

    def overview(self, run_ids):
        """run_id -> {source, summary} for list views; runs with no trace at all are omitted."""
        return {
            run_id: {"source": source, "summary": telemetry.summarize_spans(spans)}
            for run_id, (source, spans) in self.light(run_ids).items()
        }

    def trace(self, run_id):
        """The full trace of one run: ordered spans on a shared time axis plus a summary."""
        spans = self.store.spans(run_id)
        source = "recorded"
        if not spans:
            source = "reconstructed"
            facts = self.store.run_facts([run_id]).get(run_id)
            events = self.store.audit_light([run_id]).get(run_id, [])
            spans = telemetry.reconstruct_spans(run_id, events, facts)
        if not spans:
            return None
        trace = telemetry.build_trace(spans, source)
        trace["run_id"] = run_id
        trace["summary"] = telemetry.summarize_spans(spans)
        if source == "reconstructed":
            trace["note"] = (
                "This run was saved before span tracing existed. Its timeline is rebuilt from the "
                "audit log: stage durations are the gaps between recorded stage completions and "
                "model-call timings come from their prompt and answer events. Retrieval and "
                "scoring internals were not recorded."
            )
        return trace

    # ----- all runs -----

    def summary(self, window="7d", origin="all", now=None):
        now = now or datetime.now(UTC)
        delta = WINDOWS[window]
        since = (now - delta).isoformat() if delta else None
        traced = self.store.traced_runs(since)
        run_ids = [run_id for run_id, _, _ in traced]
        spans_by_run = self.light(run_ids)
        facts = self.store.run_facts(run_ids)

        runs = []
        for run_id, started_at, source in traced:
            found = spans_by_run.get(run_id)
            if not found or run_id not in facts:
                continue
            spans = found[1]
            digest = telemetry.summarize_spans(spans)
            run_origin = digest.get("origin") or "user"
            if origin != "all" and run_origin != origin:
                continue
            runs.append(
                {
                    "run_id": run_id,
                    "started_at": digest["started_at"],
                    "source": found[0],
                    "origin": run_origin,
                    "digest": digest,
                    "spans": spans,
                    "facts": facts[run_id],
                }
            )

        durations = [r["digest"]["duration_ms"] for r in runs]
        status_counts: dict = {}
        for run in runs:
            status = run["facts"]["status"] or "unknown"
            status_counts[status] = status_counts.get(status, 0) + 1
        failed = status_counts.get("failed", 0)

        stages: dict = {}
        operations: dict = {}
        llm_groups: dict = {}
        tokens = {"prompt": 0, "completion": 0, "total": 0}
        errors = []
        for run in runs:
            for stage in run["digest"]["stages"]:
                bucket = stages.setdefault(stage["stage"], {"durations": [], "errors": 0})
                bucket["durations"].append(stage["duration_ms"])
                bucket["errors"] += stage["status"] == "error"
            for item in run["spans"]:
                attributes = item.get("attributes") or {}
                if item["kind"] not in STRUCTURE_KINDS:
                    op = operations.setdefault(
                        item["name"], {"kind": item["kind"], "durations": [], "errors": 0}
                    )
                    op["durations"].append(item["duration_ms"])
                    op["errors"] += item["status"] == "error"
                if item["kind"] == "llm":
                    key = (attributes.get("purpose") or "completion", attributes.get("model"))
                    group = llm_groups.setdefault(
                        key,
                        {
                            "calls": 0,
                            "durations": [],
                            "tokens": 0,
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "failures": 0,
                            "retries": 0,
                        },
                    )
                    prompt = attributes.get("prompt_tokens") or 0
                    completion = attributes.get("completion_tokens") or 0
                    total = attributes.get("total_tokens") or (prompt + completion)
                    group["calls"] += 1
                    group["durations"].append(item["duration_ms"])
                    group["tokens"] += total
                    group["prompt_tokens"] += prompt
                    group["completion_tokens"] += completion
                    group["failures"] += item["status"] == "error"
                    group["retries"] += max(attributes.get("attempts") or 1, 1) - 1
                    tokens["prompt"] += prompt
                    tokens["completion"] += completion
                    tokens["total"] += total
                if item["status"] == "error":
                    errors.append(
                        {
                            "run_id": run["run_id"],
                            "time": item["started_at"],
                            "span": item["name"],
                            "kind": item["kind"],
                            "error_type": attributes.get("error_type"),
                        }
                    )
        errors.sort(key=lambda e: e["time"], reverse=True)

        judge = {"completed": 0, "passed": 0, "failed": 0, "pending": 0, "skipped": 0}
        scores = []
        validated = validation_passed = 0
        for run in runs:
            f = run["facts"]
            if f["validation_passed"] is not None:
                validated += 1
                validation_passed += bool(f["validation_passed"])
            state = f["judge_status"]
            if state in judge:
                judge[state] += 1
                if state == "completed":
                    judge["passed"] += bool(f["judge_passed"])
                    if isinstance(f["judge_score"], (int, float)):
                        scores.append(f["judge_score"])

        recorded = sum(r["source"] == "recorded" for r in runs)
        return {
            "window": window,
            "origin": origin,
            "generated_at": now.isoformat(),
            "since": since,
            "queries": {
                "total": len(runs),
                "by_status": status_counts,
                "failed": failed,
                "success_rate": None if not runs else (len(runs) - failed) / len(runs),
                "by_origin": {
                    name: sum(r["origin"] == name for r in runs) for name in ("user", "evaluation")
                },
                "by_mode": {
                    name: sum((r["facts"]["agent_mode"] or "unknown") == name for r in runs)
                    for name in ("live", "fixture")
                },
            },
            "latency_ms": _stats(durations),
            "stages": [
                {"stage": name} | _stats(data["durations"]) | {"errors": data["errors"]}
                for name, data in sorted(stages.items(), key=lambda kv: STAGE_ORDER.get(kv[0], 99))
            ],
            "operations": sorted(
                [
                    {"name": name, "kind": data["kind"]}
                    | _stats(data["durations"])
                    | {"errors": data["errors"]}
                    for name, data in operations.items()
                ],
                key=lambda row: -row["count"],
            ),
            "llm": {
                "calls": sum(g["calls"] for g in llm_groups.values()),
                "failures": sum(g["failures"] for g in llm_groups.values()),
                "retries": sum(g["retries"] for g in llm_groups.values()),
                "tokens": tokens,
                "tokens_per_query": None if not runs else tokens["total"] / len(runs),
                "by_purpose": sorted(
                    [
                        {"purpose": purpose, "model": model}
                        | {
                            k: g[k]
                            for k in (
                                "calls",
                                "tokens",
                                "prompt_tokens",
                                "completion_tokens",
                                "failures",
                                "retries",
                            )
                        }
                        | {"latency_ms": _stats(g["durations"])}
                        for (purpose, model), g in llm_groups.items()
                    ],
                    key=lambda row: (PURPOSE_ORDER.get(row["purpose"], 99), row["model"] or ""),
                ),
            },
            "quality": {
                "validated": validated,
                "validation_passed": validation_passed,
                "validation_pass_rate": None if not validated else validation_passed / validated,
                "judge": judge
                | {
                    "pass_rate": None
                    if not judge["completed"]
                    else judge["passed"] / judge["completed"],
                    "mean_score": None if not scores else sum(scores) / len(scores),
                },
                "handler": {
                    "accepted": status_counts.get("reviewed", 0),
                    "revision_requested": status_counts.get("revision_requested", 0),
                    "awaiting": status_counts.get("awaiting_review", 0)
                    + status_counts.get("needs_manual_review", 0),
                },
            },
            "errors": errors[:12],
            "series": self._series(runs, window, now),
            "api": self._api(since),
            "coverage": {
                "recorded": recorded,
                "reconstructed": len(runs) - recorded,
                "note": "Reconstructed runs were saved before span tracing existed; their stage "
                "and model-call timings are approximate and they carry no retrieval or scoring "
                "internals.",
            },
        }

    def evaluations(self, limit=20, now=None):
        """Recent evaluation-suite runs: what each checked, how the judge scored it and what it cost.

        An evaluation is not an investigation, so it has no trace of its own. Its report is an audit
        event, its cases are ordinary traced runs, and (since judge metrics are traced) the model
        calls that scored them hang under those runs. Older reports carry no judge call figures."""
        reports = self.store.evaluation_reports(limit)
        run_ids = [
            case["run_id"]
            for report in reports
            for case in report["body"].get("cases") or []
            if case.get("run_id")
        ]
        spans = self.store.light_spans(run_ids) if run_ids else {}
        items = []
        for report in reports:
            body = report["body"]
            cases = body.get("cases") or []
            results = body.get("judge_results") or []
            scores = [
                r["score"]
                for r in results
                if r.get("status") == "completed" and isinstance(r.get("score"), (int, float))
            ]
            by_metric: dict = {}
            for result in results:
                row = by_metric.setdefault(
                    result.get("metric") or "unknown",
                    {"completed": 0, "passed": 0, "failed": 0, "skipped": 0, "scores": []},
                )
                state = result.get("status")
                if state == "completed":
                    row["completed"] += 1
                    row["passed"] += result.get("passed") is True
                    if isinstance(result.get("score"), (int, float)):
                        row["scores"].append(result["score"])
                elif state in ("failed", "skipped"):
                    row[state] += 1
            calls, tokens, milliseconds = 0, 0, 0.0
            for case in cases:
                for item in spans.get(case.get("run_id"), []):
                    attributes = item.get("attributes") or {}
                    if item["kind"] == "llm" and attributes.get("purpose") == "judge_metric":
                        calls += 1
                        milliseconds += item["duration_ms"]
                        tokens += attributes.get("total_tokens") or (
                            (attributes.get("prompt_tokens") or 0)
                            + (attributes.get("completion_tokens") or 0)
                        )
            started, finished = body.get("started_at"), body.get("finished_at")
            try:
                duration = (
                    (telemetry.parse_time(finished) - telemetry.parse_time(started)).total_seconds()
                    if started and finished
                    else None
                )
            except ValueError:
                duration = None
            items.append(
                {
                    "id": report["id"],
                    "time": report["time"],
                    "started_at": started,
                    "finished_at": finished,
                    "duration_seconds": None if duration is None else round(duration, 1),
                    "mode": body.get("mode"),
                    "agent_mode": body.get("agent_mode"),
                    "overall_passed": body.get("overall_passed"),
                    "cases": {
                        "passed": body.get("passed"),
                        "total": body.get("total"),
                        "items": [
                            {"case": c.get("case"), "passed": c.get("passed"), "run_id": c.get("run_id")}
                            for c in cases
                        ],
                    },
                    "judge": {
                        "requested": bool(body.get("judge_requested")),
                        "status": body.get("judge_status"),
                        "model": body.get("judge_model"),
                        "independent": body.get("judge_independent"),
                        "threshold": body.get("judge_threshold"),
                        "expected_metrics": body.get("judge_expected_metrics"),
                        "completed_metrics": body.get("judge_completed_metrics"),
                        "passed_metrics": body.get("judge_passed_metrics"),
                        "mean_score": None if not scores else sum(scores) / len(scores),
                        "metrics": [
                            {
                                "metric": name,
                                "completed": row["completed"],
                                "passed": row["passed"],
                                "failed": row["failed"],
                                "skipped": row["skipped"],
                                "mean_score": None
                                if not row["scores"]
                                else sum(row["scores"]) / len(row["scores"]),
                            }
                            for name, row in by_metric.items()
                        ],
                        "model_calls": {
                            "traced": calls > 0,
                            "calls": calls,
                            "tokens": tokens,
                            "total_ms": round(milliseconds, 1),
                        },
                    },
                }
            )
        return {"generated_at": (now or datetime.now(UTC)).isoformat(), "items": items}

    @staticmethod
    def _series(runs, window, now):
        """Query counts per hour (24 h window) or per day, with empty buckets kept."""
        hourly = window == "24h"
        step = timedelta(hours=1) if hourly else timedelta(days=1)

        def floor(moment):
            moment = moment.astimezone(UTC)
            return moment.replace(minute=0, second=0, microsecond=0) if hourly else moment.replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        parsed = [(telemetry.parse_time(r["started_at"]), r) for r in runs]
        if window == "all":
            start = min((t for t, _ in parsed), default=now) if parsed else now
            start = max(floor(start), floor(now) - timedelta(days=89))
        else:
            span = WINDOWS[window]
            start = floor(now - span) + step
        buckets, cursor = {}, start
        while cursor <= floor(now):
            buckets[cursor] = {"queries": 0, "failed": 0, "durations": []}
            cursor += step
        for moment, run in parsed:
            bucket = buckets.get(floor(moment))
            if bucket is None:
                continue
            bucket["queries"] += 1
            bucket["failed"] += run["facts"]["status"] == "failed"
            bucket["durations"].append(run["digest"]["duration_ms"])
        return [
            {
                "bucket": moment.isoformat(),
                "queries": data["queries"],
                "failed": data["failed"],
                "p50_ms": _ms(telemetry.percentile(data["durations"], 50)),
            }
            for moment, data in buckets.items()
        ]

    def _api(self, since):
        rows = self.store.requests_since(since)
        routes: dict = {}
        for row in rows:
            key = (row["method"], row["route"])
            bucket = routes.setdefault(key, {"durations": [], "client_errors": 0, "server_errors": 0})
            bucket["durations"].append(row["duration_ms"])
            status = row["status"] or 0
            bucket["client_errors"] += 400 <= status < 500
            bucket["server_errors"] += status >= 500
        server_errors = sum(b["server_errors"] for b in routes.values())
        return {
            "requests": len(rows),
            "server_errors": server_errors,
            "client_errors": sum(b["client_errors"] for b in routes.values()),
            "latency_ms": _stats([r["duration_ms"] for r in rows]),
            "routes": sorted(
                [
                    {"method": method, "route": route}
                    | _stats(data["durations"])
                    | {
                        "client_errors": data["client_errors"],
                        "server_errors": data["server_errors"],
                    }
                    for (method, route), data in routes.items()
                ],
                key=lambda row: -row["count"],
            )[:15],
        }


STAGE_ORDER = {
    name: index
    for index, name in enumerate(
        ("classify", "retrieve", "investigate", "risk", "recommend", "validate", "supervise", "judge", "review")
    )
}
PURPOSE_ORDER = {
    name: index
    for index, name in enumerate(
        ("classification", "investigation", "recommendation", "judge", "judge_metric")
    )
}
