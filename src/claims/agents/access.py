"""Role-based tool access: every tool call is made by a named agent, and only a tool in that agent's list goes through.

Work is done inside ``acting_as(agent_id)``. The Synapt adapter and the other tools call :func:`authorize` before they act; a call
with no acting agent, or for a tool outside the agent's list, raises :class:`AccessDenied` and leaves a mark in the trace. The
check fails closed: there is no default that lets an unnamed caller through. ``roster`` holds the lists.

Everything recorded while an agent acts (model calls, tool calls, timings) carries its ID, so a run can be read agent by agent.
"""

import asyncio
import logging
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from claims.agents import roster
from claims.observability import telemetry

logger = logging.getLogger(__name__)
MAX_DENIALS_KEPT = 20


class AccessDenied(RuntimeError):
    """A tool call that the acting agent's role does not allow. Deliberately not a ``SynaptError``: a policy failure must never be
    treated as an outage and answered with the degraded fallback."""


@dataclass
class Scope:
    agent: str
    tools: frozenset[str]
    calls: Counter = field(default_factory=Counter)
    denied: list[str] = field(default_factory=list)


_scope: ContextVar[Scope | None] = ContextVar("claims_agent_scope", default=None)


def current() -> str | None:
    """The agent acting now, if any."""
    scope = _scope.get()
    return scope.agent if scope else None


@contextmanager
def acting_as(agent_id: str, **attributes):
    """Everything inside is done by this agent: its tool list applies, and what it records carries its ID. Extra ``attributes`` go
    on the agent's span (the independent review passes ``background=True``: nobody waits for it)."""
    spec = roster.agent(agent_id)
    scope = Scope(spec.id, spec.tools)
    token = _scope.set(scope)
    with telemetry.as_agent(spec.id), telemetry.span(
        f"agent.{spec.id}", kind="agent", agent=spec.id, role=spec.name, method=spec.method, tools_allowed=sorted(spec.tools),
        **attributes,
    ) as span:
        try:
            yield scope
        finally:
            _scope.reset(token)
            span.set(
                tool_calls=dict(scope.calls),
                tools_denied=list(scope.denied),
                tool_total=sum(scope.calls.values()),
                refused=len(scope.denied),
            )


@contextmanager
def acting_unless_already(agent_id: str):
    """For a capability that belongs to one agent (the passage search is the Policy Passage Retriever's): act as that agent when
    the caller has not named one, and leave an agent the caller did name in place, so its own list is what is checked."""
    if _scope.get() is not None:
        yield _scope.get()
        return
    with acting_as(agent_id) as scope:
        yield scope


def run_as(agent_id: str, coroutine):
    """Run a script's async ``main`` as one named actor (the scripts under ``scripts/`` read or write the knowledge base)."""
    with acting_as(agent_id):
        return asyncio.run(coroutine)


def permits(tool: str) -> bool:
    """Whether the acting agent holds this tool. Never raises; for choosing among tools without trying them."""
    scope = _scope.get()
    return bool(scope and tool in scope.tools)


def authorize(tool: str) -> str:
    """Let a call through if the acting agent holds the tool, else raise. Returns the agent's ID."""
    scope = _scope.get()
    if scope is None:
        _record_denial(None, tool)
        raise AccessDenied(f"{tool}: no agent is acting. Every tool call is made by a named agent.")
    if tool in scope.tools:
        scope.calls[tool] += 1
        return scope.agent
    if tool not in scope.denied and len(scope.denied) < MAX_DENIALS_KEPT:
        scope.denied.append(tool)
    _record_denial(scope.agent, tool)
    raise AccessDenied(f"The {scope.agent} agent is not permitted to call {tool}.")


def require(*tools: str, any_of: bool = False) -> None:
    """Check, before a capability starts, that the acting agent holds the tools it needs: all of them, or with ``any_of`` at least
    one. Nothing is counted and nothing is sent, so a capability the agent may not use does none of its work first."""
    scope = _scope.get()
    held = [tool for tool in tools if scope is not None and tool in scope.tools]
    if (held if any_of else len(held) == len(tools)):
        return
    missing = [tool for tool in tools if tool not in held] if not any_of else list(tools)
    for tool in missing:
        if scope is not None and tool not in scope.denied and len(scope.denied) < MAX_DENIALS_KEPT:
            scope.denied.append(tool)
        _record_denial(scope.agent if scope else None, tool)
    who = f"The {scope.agent} agent" if scope else "No agent"
    raise AccessDenied(f"{who} is not permitted to use this: it needs {' and '.join(tools) if not any_of else ' or '.join(tools)}.")


def refuse(tool: str) -> None:
    """Record that the acting agent (or a model acting for it) asked for a tool it does not hold, without raising: the caller
    answers the model and carries on. The refusal is counted on the agent's span and leaves an ``access.denied`` span."""
    scope = _scope.get()
    if scope is not None and tool not in scope.denied and len(scope.denied) < MAX_DENIALS_KEPT:
        scope.denied.append(tool)
    _record_denial(scope.agent if scope else None, tool)


def _record_denial(agent: str | None, tool: str) -> None:
    logger.warning("tool_denied agent=%s tool=%s", agent or "none", tool)
    with telemetry.span("access.denied", kind="tool", tool=tool, agent=agent or "none", outcome="denied") as span:
        span.fail(AccessDenied())
