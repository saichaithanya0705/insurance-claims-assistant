"""Shared, validated model transport for agents and evaluators.

Two providers sit behind one ``complete()``: an OpenAI-compatible chat-completions endpoint (NVIDIA NIM today) and Anthropic's
Messages API. Both return the same thing, a validated object (or text), and are logged and traced the same way. For Anthropic a
structured answer is asked for through one forced tool call whose input schema is the Pydantic schema, so the model returns
arguments instead of free text that has to be parsed; the result is then validated by the same Pydantic class as before.
"""

import json
import time

import httpx
from pydantic import ValidationError

from claims.agents import access
from claims.llm import ratelimit
from claims.observability import telemetry


class CompletionError(RuntimeError):
    """Contains only a static, safe error description."""


ANTHROPIC_TOOL = "submit_answer"
RETRYABLE_STATUS = (429, 500, 502, 503, 504, 529)  # 529 is Anthropic's "overloaded"


def _merged_turns(messages):
    """The non-system messages with consecutive turns of one role joined, which is the shape the Messages API wants."""
    turns = []
    for message in messages:
        if message["role"] == "system":
            continue
        if turns and turns[-1]["role"] == message["role"]:
            turns[-1]["content"] += "\n\n" + str(message["content"])
        else:
            turns.append({"role": message["role"], "content": str(message["content"])})
    return turns


class CompletionClient:
    def __init__(self, settings, log, provider=None):
        self.settings, self.log = settings, log
        self.provider = provider or settings.llm_provider

    def complete(
        self,
        messages,
        schema=None,
        *,
        model=None,
        run_id="evaluation",
        role="judge",
        timeout=None,
        attempts=2,
        purpose=None,
        optional=False,
    ):
        """``timeout`` and ``attempts`` let optional, advisory callers (the judge) fail fast. ``optional`` marks a call the brief
        does not depend on: it is made only while the shared request budget has more than its reserve free (``claims.llm.ratelimit``),
        else it raises ``CompletionError`` at once, and it never waits for a slot.
        ``purpose`` names what the call was for in a trace when the output schema does not say.

        Inside an active trace the call is recorded as one span: its attempts, token usage,
        finish reason and the audit events that hold the full prompt and answer.
        """
        purpose = purpose or telemetry.purpose_for_schema(schema)
        model = model or self.settings.model_for(purpose, self.provider)
        if optional and self.provider != "anthropic":
            gate = ratelimit.gate_for(self.settings)
            if gate is not None and not gate.acquire(optional=True):
                raise CompletionError("Model request budget is kept for the brief.")
        with telemetry.span(
            f"llm.{purpose}",
            kind="llm",
            purpose=purpose,
            provider=self.provider,
            model=model,
            structured=schema is not None,
            max_attempts=attempts,
            temperature=0,
            max_tokens=self.settings.llm_max_tokens,
        ) as trace:
            return self._complete(messages, schema, model, run_id, role, timeout, attempts, trace, optional)

    def chat_with_tools(
        self,
        messages,
        tools,
        *,
        model=None,
        run_id="evaluation",
        role="agent",
        purpose="retrieval",
        timeout=None,
        attempts=2,
    ):
        """One model turn in which the model may call the tools it is offered (native tool calling on the OpenAI-compatible
        provider). Returns ``{"content", "tool_calls": [{"id", "name", "arguments"}], "message"}``, where ``message`` is the
        assistant turn to send back with the tool results. The caller decides whether to run a tool: nothing here executes one."""
        if self.provider == "anthropic":
            raise CompletionError("Tool calling is configured for the OpenAI-compatible provider only.")
        gate = ratelimit.gate_for(self.settings)
        if gate is not None and not gate.acquire(optional=True):
            # Optional work yields: the slots that are left are kept for the brief's own calls.
            raise CompletionError("Model request budget is kept for the brief.")
        model = model or self.settings.model_for(purpose, self.provider)
        with telemetry.span(
            f"llm.{purpose}",
            kind="llm",
            purpose=purpose,
            provider=self.provider,
            model=model,
            structured=False,
            tools=len(tools),
            max_attempts=attempts,
            temperature=0,
            max_tokens=self.settings.llm_max_tokens,
        ) as trace:
            attempt_log: list[dict] = []
            trace.set(attempt_log=attempt_log, attempts=0, prompt_messages=len(messages))
            for attempt in range(attempts):
                started = time.perf_counter()
                trace.set(attempts=attempt + 1)
                if attempt and gate is not None and not gate.acquire(optional=True):
                    raise CompletionError("Model request budget is kept for the brief.")
                self.log(run_id, "model_prompt", {"role": role, "agent": access.current(), "model": model, "messages": messages, "attempt": attempt + 1})
                request = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0,
                    "max_tokens": self.settings.llm_max_tokens,
                    "stream": False,
                    "tools": tools,
                    "tool_choice": "auto",
                }
                prefixes = tuple(p.strip() for p in self.settings.llm_thinking_switch_prefixes.split(",") if p.strip())
                if prefixes and model.startswith(prefixes):
                    request["chat_template_kwargs"] = {"enable_thinking": self.settings.llm_enable_thinking}
                try:
                    with httpx.Client(timeout=timeout or self.settings.llm_timeout_seconds, follow_redirects=False) as client:
                        response = client.post(
                            self.settings.llm_base_url.rstrip("/") + "/chat/completions",
                            headers={"Authorization": "Bearer " + self.settings.llm_api_key.get_secret_value()},
                            json=request,
                        )
                    if gate is not None and response.status_code == 429:
                        gate.throttled()
                    elif gate is not None and response.status_code < 500:
                        gate.succeeded()
                    response.raise_for_status()
                    payload = response.json()
                    turn = self._read_turn(payload)
                    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
                    counted = {
                        key: usage[key]
                        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                        if type(usage.get(key)) is int and 0 <= usage[key] <= 100_000_000
                    }
                    elapsed = time.perf_counter() - started
                    self.log(
                        run_id,
                        "model_output",
                        {
                            "role": role,
                            "agent": access.current(),
                            "model": model,
                            "output": {"content": turn["content"], "tool_calls": [{"name": c["name"], "arguments": c["arguments"]} for c in turn["tool_calls"]]},
                            "attempt": attempt + 1,
                            "elapsed_seconds": round(elapsed, 3),
                            "usage": counted,
                        },
                    )
                    attempt_log.append({"attempt": attempt + 1, "outcome": "ok", "elapsed_ms": round(elapsed * 1000, 1)})
                    trace.set(tool_calls_requested=len(turn["tool_calls"]), **counted)
                    return turn
                except httpx.HTTPStatusError as error:
                    status = error.response.status_code
                    self.log(run_id, "model_failure", {"role": role, "attempt": attempt + 1, "reason": "http_failure", "status_code": status})
                    attempt_log.append({"attempt": attempt + 1, "outcome": "http_failure", "status_code": status})
                    if status not in RETRYABLE_STATUS or attempt == attempts - 1:
                        raise CompletionError(f"Model provider rejected request (HTTP {status}).") from None
                    time.sleep(self._retry_delay(error.response))
                except (httpx.RequestError, ValueError, KeyError, IndexError, TypeError) as error:
                    reason = "transport_failure" if isinstance(error, httpx.RequestError) else "output_validation_failure"
                    self.log(run_id, "model_failure", {"role": role, "attempt": attempt + 1, "reason": reason, "error_type": type(error).__name__})
                    attempt_log.append({"attempt": attempt + 1, "outcome": reason})
                    if attempt == attempts - 1:
                        raise CompletionError("Model output or connection failed validation.") from None
            raise CompletionError("Model output or connection failed validation.")

    @staticmethod
    def _retry_delay(response) -> float:
        """How long to wait before trying again: what a rate-limited provider asks for (at most 10 s), else half a second."""
        if response.status_code == 429:
            try:
                return min(float(response.headers.get("Retry-After", "")), 10.0)
            except ValueError:
                return 3.0
        return 0.5

    @staticmethod
    def _read_turn(payload):
        """The model's turn from a chat-completions response: its text, and the tool calls it asked for with their arguments
        parsed. Raises ValueError for anything malformed (an unfinished turn, arguments that are not a JSON object)."""
        choice = payload["choices"][0]
        if choice.get("finish_reason") in ("length", "content_filter"):
            raise ValueError("Incomplete model response")
        message = choice["message"]
        content = message.get("content")
        content = content if isinstance(content, str) and content.strip() else None
        calls = []
        for index, call in enumerate(message.get("tool_calls") or []):
            function = call["function"]
            arguments = json.loads(function.get("arguments") or "{}")
            if not isinstance(arguments, dict) or not isinstance(function.get("name"), str):
                raise TypeError("Malformed tool call")
            calls.append({"id": call.get("id") or f"call_{index}", "name": function["name"], "arguments": arguments})
        echo = {"role": "assistant", "content": content}
        if calls:
            echo["tool_calls"] = [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}} for c in calls
            ]
        return {"content": content, "tool_calls": calls, "message": echo}

    def _post_patiently(self, client, messages, schema, model):
        """Send the request, waiting out a rate limit. A 429 is not the brief's fault: the call waits as long as the provider asks
        (3, 6, then 10 s at least) and tries again, three times at most, before it counts as a failure. Each 429 also tells the shared
        request budget to slow down, and each answer that is not one tells it things are fine."""
        gate = ratelimit.gate_for(self.settings) if self.provider != "anthropic" else None
        for attempt in range(4):
            response = self._post(client, messages, schema, model)
            if response.status_code != 429:
                if gate is not None and response.status_code < 500:
                    gate.succeeded()
                return response
            if gate is not None:
                gate.throttled()
            if attempt == 3:
                return response
            time.sleep(min(max(self._retry_delay(response), (3.0, 6.0, 10.0)[attempt]), 10.0))
            if gate is not None:
                gate.acquire()
        return response

    def _post(self, client, messages, schema, model):
        """Send one request in the shape the provider expects."""
        if self.provider == "anthropic":
            body = {
                "model": model,
                "max_tokens": self.settings.llm_max_tokens,
                "temperature": 0,
                "system": "\n\n".join(str(m["content"]) for m in messages if m["role"] == "system"),
                "messages": _merged_turns(messages),
            }
            if schema:
                body["tools"] = [{
                    "name": ANTHROPIC_TOOL,
                    "description": "Return the answer in exactly this structure.",
                    "input_schema": schema.model_json_schema(),
                }]
                body["tool_choice"] = {"type": "tool", "name": ANTHROPIC_TOOL}
            return client.post(
                self.settings.anthropic_base_url.rstrip("/") + "/v1/messages",
                headers={
                    "x-api-key": self.settings.anthropic_api_key.get_secret_value(),
                    "anthropic-version": self.settings.anthropic_version,
                    "content-type": "application/json",
                },
                json=body,
            )
        request = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.settings.llm_max_tokens,
            "stream": False,
        }
        if schema:
            request["response_format"] = {"type": "json_object"}
        prefixes = tuple(p.strip() for p in self.settings.llm_thinking_switch_prefixes.split(",") if p.strip())
        if prefixes and model.startswith(prefixes):
            request["chat_template_kwargs"] = {"enable_thinking": self.settings.llm_enable_thinking}
        return client.post(
            self.settings.llm_base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + self.settings.llm_api_key.get_secret_value()},
            json=request,
        )

    def _read(self, payload, schema):
        """The validated answer from a response: (parsed, raw text or JSON, finish reason, usage). Raises ValueError (or a Pydantic
        error, which is one) when the answer is incomplete, empty or does not fit the schema, so the caller retries."""
        if self.provider == "anthropic":
            reason = payload.get("stop_reason")
            if reason in ("max_tokens", "refusal"):
                raise ValueError("Incomplete model response")
            blocks = payload.get("content") or []
            if schema:
                call = next((b for b in blocks if b.get("type") == "tool_use" and b.get("name") == ANTHROPIC_TOOL), None)
                if call is None or not isinstance(call.get("input"), dict) or not call["input"]:
                    raise ValueError("Empty model response")
                parsed = schema.model_validate(call["input"])
                raw = json.dumps(call["input"])
            else:
                raw = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
                if not raw.strip():
                    raise ValueError("Empty model response")
                parsed = raw
            usage = payload.get("usage") or {}
            usage = usage if isinstance(usage, dict) else {}
            counted = {"prompt_tokens": usage.get("input_tokens"), "completion_tokens": usage.get("output_tokens")}
            if type(counted["prompt_tokens"]) is int and type(counted["completion_tokens"]) is int:
                counted["total_tokens"] = counted["prompt_tokens"] + counted["completion_tokens"]
            return parsed, raw, reason, counted
        choice = payload["choices"][0]
        if choice.get("finish_reason") in ("length", "content_filter"):
            raise ValueError("Incomplete model response")
        raw = choice["message"]["content"]
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("Empty model response")
        parsed = schema.model_validate_json(raw) if schema else raw
        usage = payload.get("usage") or {}
        return parsed, raw, choice.get("finish_reason"), usage if isinstance(usage, dict) else {}

    def _error_kind(self, response):
        """Anthropic names the kind of an error ("not_found_error" for a wrong model name); the text of the message is never kept."""
        if self.provider != "anthropic":
            return {}
        try:
            kind = response.json()["error"]["type"]
        except (ValueError, KeyError, TypeError):
            return {}
        return {"error_kind": kind} if isinstance(kind, str) and kind.replace("_", "").isalnum() else {}

    def _complete(self, messages, schema, model, run_id, role, timeout, attempts, trace, optional=False):
        messages = list(messages)
        attempt_log: list[dict] = []
        prompt_events: list[int] = []
        trace.set(attempt_log=attempt_log, prompt_events=prompt_events, attempts=0)
        gate = ratelimit.gate_for(self.settings) if self.provider != "anthropic" else None
        for attempt in range(attempts):
            started = time.perf_counter()
            if gate is not None and not optional:
                gate.acquire(optional=False)  # the brief's own calls wait for a slot rather than start a 429
            prompt_event = self.log(
                run_id,
                "model_prompt",
                {"role": role, "agent": access.current(), "model": model, "messages": messages, "attempt": attempt + 1},
            )
            if isinstance(prompt_event, int):
                prompt_events.append(prompt_event)
            trace.set(
                attempts=attempt + 1,
                prompt_messages=len(messages),
                prompt_chars=sum(len(str(m.get("content", ""))) for m in messages),
            )
            try:
                with httpx.Client(
                    timeout=timeout or self.settings.llm_timeout_seconds, follow_redirects=False
                ) as client:
                    response = self._post_patiently(client, messages, schema, model)
                response.raise_for_status()
                parsed, raw, finish, usage = self._read(response.json(), schema)
                trace.set(finish_reason=finish)
                counted = {
                    key: usage[key]
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if type(usage.get(key)) is int and 0 <= usage[key] <= 100_000_000
                }
                elapsed = time.perf_counter() - started
                # Log final content and numerical usage only, never auth headers or reasoning traces.
                output_event = self.log(
                    run_id,
                    "model_output",
                    {
                        "role": role,
                        "agent": access.current(),
                        "model": model,
                        "output": parsed.model_dump(mode="json") if schema else parsed,
                        "attempt": attempt + 1,
                        "elapsed_seconds": round(elapsed, 3),
                        "usage": counted,
                    },
                )
                attempt_log.append(
                    {"attempt": attempt + 1, "outcome": "ok", "elapsed_ms": round(elapsed * 1000, 1)}
                )
                trace.set(
                    output_chars=len(raw),
                    output_event=output_event if isinstance(output_event, int) else None,
                    **counted,
                )
                return parsed
            except httpx.HTTPStatusError as error:
                status = error.response.status_code
                self.log(
                    run_id,
                    "model_failure",
                    {
                        "role": role,
                        "attempt": attempt + 1,
                        "reason": "http_failure",
                        "status_code": status,
                        **self._error_kind(error.response),
                    },
                )
                attempt_log.append(
                    {
                        "attempt": attempt + 1,
                        "outcome": "http_failure",
                        "status_code": status,
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                )
                if status not in RETRYABLE_STATUS or attempt == attempts - 1:
                    raise CompletionError(
                        f"Model provider rejected request (HTTP {status}); no fixture fallback."
                    ) from None
                time.sleep(self._retry_delay(error.response))
            except (httpx.RequestError, ValueError, KeyError, IndexError, TypeError) as error:
                reason = (
                    "transport_failure"
                    if isinstance(error, httpx.RequestError)
                    else "output_validation_failure"
                )
                # Where the output failed, never what it said: field paths and rule names only, so a repeated failure can be diagnosed.
                where = (
                    [{"loc": list(e["loc"]), "type": e["type"]} for e in error.errors()][:10]
                    if isinstance(error, ValidationError)
                    else []
                )
                self.log(
                    run_id,
                    "model_failure",
                    {"role": role, "attempt": attempt + 1, "reason": reason, "error_type": type(error).__name__, "validation": where},
                )
                attempt_log.append(
                    {
                        "attempt": attempt + 1,
                        "outcome": reason,
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    }
                )
                if attempt == attempts - 1:
                    raise CompletionError(
                        "Model output or connection failed validation; no fixture fallback."
                    ) from None
                if not isinstance(error, httpx.RequestError):
                    details = (
                        [{"loc": list(e["loc"]), "type": e["type"]} for e in error.errors()]
                        if isinstance(error, ValidationError)
                        else []
                    )
                    messages = messages + [
                        {
                            "role": "user",
                            "content": "The previous response did not validate. Return a complete JSON object matching the supplied schema. Validation locations: "
                            + json.dumps(details),
                        }
                    ]
        raise CompletionError("Model request failed; no fixture fallback.")
