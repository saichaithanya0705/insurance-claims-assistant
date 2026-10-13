"""The tool-using step of an agent: a model offered a short list of tools, a bounded loop, and the guards between the model and
the knowledge base.

The pattern throughout is that a model proposes and the application disposes. The agent's standard work has already run; here the
model may ask for more, with three limits that do not depend on the model behaving:

* it can only name the tools it was offered, and a request for any other tool is refused and recorded (``access.refuse``);
* every argument passes a guard before anything is sent. A search is a few plain words: no digits, symbols, personal data, or
  anything that repeats a name or place from the claim, so claimant details do not leave in a query;
* the loop is bounded in rounds, and each tool bounds what it returns and what it adds.

Nothing here executes on its own account: each tool is a function the caller passes in, and those functions call the Synapt adapter,
which checks the acting agent's tool list again on every call.
"""

import contextvars
import json
import logging
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any

from claims.agents import access
from claims.core.schemas import ClaimInput, redact_personal_data

logger = logging.getLogger(__name__)

MAX_RESULT_CHARS = 6_000
MAX_PARALLEL_CALLS = 3
_PLAIN_QUERY = re.compile(r"^[A-Za-z][A-Za-z ,'\-]{2,98}$")


class ToolArgumentError(ValueError):
    """A tool argument the application will not send. The message goes back to the model, so it says what is allowed."""


@dataclass
class AgentTool:
    name: str
    description: str
    parameters: dict
    run: Callable[[dict], Any]
    guard: Callable[[dict], dict] | None = None
    # A tool that ends the agent's turn: once it has run, the loop stops without asking the model again.
    final: bool = False

    def spec(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class LoopOutcome:
    rounds: int = 0
    calls: list[dict] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    stopped: str = "finished"  # "finished", "final_tool", "limit" or "budget" (the time allowed ran out)


# ----- guards ------------------------------------------------------------------------------------------------------------


def _proper_nouns(text: str) -> set[str]:
    """Words of the narrative that look like names or places: capitalised, and not just the first word of a sentence."""
    found: set[str] = set()
    for sentence in re.split(r"[.!?\n]+", text or ""):
        words = re.findall(r"[A-Za-z][A-Za-z'\-]*", sentence)
        for word in words[1:]:
            if len(word) >= 3 and word[0].isupper():
                found.add(word.lower())
        found.update(w.lower() for w in words if len(w) >= 2 and w.isupper())  # TX, USA
    return found


def _claim_words(claim: ClaimInput) -> set[str]:
    words = _proper_nouns(claim.description or "")
    if claim.state:
        words.add(str(claim.state).lower())
    return words


def safe_query(text, claim: ClaimInput) -> str:
    """A search a model wrote, or ToolArgumentError. Plain words only, and nothing that repeats the claimant's own details."""
    text = " ".join(str(text or "").split())
    count = len(text.split())
    if not _PLAIN_QUERY.match(text) or not 2 <= count <= 14:
        raise ToolArgumentError("A search is 2 to 14 plain words: letters only, with no numbers, symbols or sentences about the claimant.")
    if redact_personal_data(text) != text:
        raise ToolArgumentError("A search must not contain personal data.")
    used = {w.strip(",'-").lower() for w in text.split()} & _claim_words(claim)
    if used:
        raise ToolArgumentError("A search must not repeat names or places from the claim; describe the kind of procedure instead.")
    return text


def safe_question(text, claim: ClaimInput) -> str:
    """A handling question a model wrote for the knowledge base's query agent, or ToolArgumentError."""
    text = " ".join(str(text or "").split())
    if not 20 <= len(text) <= 300 or not text.endswith("?"):
        raise ToolArgumentError("A question is one sentence of 20 to 300 characters ending in a question mark.")
    if re.search(r"[\d$@#]", text) or redact_personal_data(text) != text:
        raise ToolArgumentError("A question must not contain numbers, amounts or personal data.")
    used = {w.strip(",'-?").lower() for w in text.split()} & _claim_words(claim)
    if used:
        raise ToolArgumentError("A question must not repeat names or places from the claim.")
    return text


# ----- the loop ----------------------------------------------------------------------------------------------------------


def _text(result) -> str:
    text = json.dumps(result, default=str)
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + '..."}'


def _execute(tools: dict[str, AgentTool], call: dict, outcome: LoopOutcome, closed: frozenset[str] = frozenset()) -> Any:
    tool = tools.get(call["name"])
    if tool is None and call["name"] in closed:
        # One of the agent's own tools, asked for after the looking-around is over: the model is told to choose. Not a policy refusal.
        outcome.calls.append({"tool": call["name"], "ok": False, "error": "closed"})
        return {"error": "Searching is over; choose now with the tools you are offered, or reply that nothing is needed."}
    if tool is None:
        # The model asked for something that is not one of its tools. It is refused and recorded; nothing runs.
        access.refuse(call["name"])
        outcome.refused.append(call["name"])
        outcome.calls.append({"tool": call["name"], "ok": False, "error": "not offered"})
        return {"error": f"{call['name']} is not one of your tools."}
    try:
        arguments = tool.guard(call["arguments"]) if tool.guard else call["arguments"]
    except ToolArgumentError as error:
        outcome.calls.append({"tool": tool.name, "ok": False, "error": "argument refused"})
        return {"error": str(error)}
    try:
        result = tool.run(arguments)
    except access.AccessDenied:
        raise
    except Exception as error:  # noqa: BLE001 - a failing tool is reported to the model by type only; the run does not stop
        logger.info("agent tool %s failed (%s)", tool.name, type(error).__name__)
        outcome.calls.append({"tool": tool.name, "ok": False, "error": type(error).__name__})
        return {"error": "The tool could not be used just now."}
    outcome.calls.append({"tool": tool.name, "ok": True})
    return result


def run_tool_loop(
    client,
    *,
    system: str,
    user: dict,
    tools: dict[str, AgentTool],
    run_id: str,
    role: str,
    purpose: str = "retrieval",
    max_rounds: int = 2,
    exploratory_rounds: int = 1,
    model: str | None = None,
    budget_seconds: float | None = None,
) -> LoopOutcome:
    """Offer the model ``tools`` and run what it asks for, round by round, until it stops asking, uses a final tool, or reaches
    ``max_rounds`` model calls. After ``exploratory_rounds`` the model is offered only the final tools: it may look around once
    (all its searches in one round, run together) and must then choose, so it cannot keep searching. Raises ``CompletionError``
    when the model cannot be reached; the caller keeps its standard result."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user)}]
    outcome = LoopOutcome()
    deadline = None if budget_seconds is None else time.monotonic() + budget_seconds
    for round_number in range(1, max_rounds + 1):
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining < 0.5:
            outcome.stopped = "budget"
            return outcome
        available = {name: tool for name, tool in tools.items() if round_number <= exploratory_rounds or tool.final}
        # With a budget, one attempt that gives up when the time is gone: a slow model call must not hold the agent up.
        extra = {} if remaining is None else {"timeout": remaining, "attempts": 1}
        turn = client.chat_with_tools(messages, [tool.spec() for tool in available.values()], run_id=run_id, role=role, purpose=purpose, model=model, **extra)
        outcome.rounds = round_number
        if not turn["tool_calls"]:
            outcome.stopped = "finished"
            return outcome
        messages.append(turn["message"])
        context = contextvars.copy_context()  # each call runs as the agent that asked, inside its trace
        closed = frozenset(tools) - frozenset(available)
        pool = ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS, thread_name_prefix="agent-tool")
        futures = [pool.submit(context.copy().run, _execute, available, call, outcome, closed) for call in turn["tool_calls"]]
        try:
            wait = None if deadline is None else max(deadline - time.monotonic(), 0.5)
            results = [future.result(timeout=wait) for future in futures]
        except FutureTimeout:
            pool.shutdown(wait=False, cancel_futures=True)  # a call that is still out is abandoned, not awaited
            outcome.stopped = "budget"
            return outcome
        pool.shutdown(wait=False)
        for call, result in zip(turn["tool_calls"], results, strict=True):
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": _text(result)})
        if any(available[c["name"]].final for c in turn["tool_calls"] if c["name"] in available):
            outcome.stopped = "final_tool"
            return outcome
    outcome.stopped = "limit"
    return outcome
