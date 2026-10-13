"""One finished investigation read agent by agent: who did what, for how long, and with which tools.

Built from the spans the run recorded (``claims.agents.access`` stamps each agent's work), so it is a record of what happened, never a
description of what was meant to. Everyone who may see the run gets names, timings and counts; the tools by name, the models and
any refused call are for administrators only.
"""

from collections import Counter
from datetime import timedelta

from claims.agents import roster
from claims.observability import telemetry


def _interval(spans):
    starts = [telemetry.parse_time(s["started_at"]) for s in spans]
    ends = [start + timedelta(milliseconds=s["duration_ms"] or 0) for start, s in zip(starts, spans, strict=True)]
    return min(starts), max(ends)


def summary(spans: list[dict], admin: bool = False) -> dict:
    agents = []
    run_start = min((telemetry.parse_time(s["started_at"]) for s in spans), default=None)
    for spec in roster.investigation_agents():
        mine = [s for s in spans if s["kind"] == "agent" and (s.get("attributes") or {}).get("agent") == spec.id]
        row = {
            "id": spec.id,
            "name": spec.name,
            "method": spec.method,
            "stage": spec.stage,
            "purpose": spec.purpose,
            "ran": bool(mine),
        }
        if not mine:
            agents.append(row)
            continue
        first, last = _interval(mine)
        attributes = [s.get("attributes") or {} for s in mine]
        statuses = {s["status"] for s in mine}
        calls = Counter()
        denied: list[str] = []
        for a in attributes:
            calls.update(a.get("tool_calls") or {})
            denied += [d for d in a.get("tools_denied") or [] if d not in denied]
        model_calls = [s for s in spans if s["kind"] == "llm" and (s.get("attributes") or {}).get("agent") == spec.id]
        row |= {
            "status": "error" if "error" in statuses else "waiting" if "waiting" in statuses else "ok",
            "background": any(a.get("background") is True for a in attributes),
            "started_ms": round((first - run_start).total_seconds() * 1000, 1) if run_start else None,
            "duration_ms": round((last - first).total_seconds() * 1000, 1),
            "tool_calls": sum(calls.values()),
            "refused": len(denied),
            "model_calls": len(model_calls),
            "tokens": sum(int((s.get("attributes") or {}).get("total_tokens") or 0) for s in model_calls),
        }
        if admin:
            row |= {
                "tools_used": dict(sorted(calls.items())),
                "tools_refused": denied,
                "models": sorted({a["model"] for s in model_calls if (a := s.get("attributes") or {}).get("model")}),
            }
        agents.append(row)
    return {"agents": agents}
