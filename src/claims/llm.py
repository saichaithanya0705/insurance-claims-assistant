"""Shared, validated chat-completions transport for agents and evaluators."""

import json
import time

import httpx
from pydantic import ValidationError

from claims import telemetry


class CompletionError(RuntimeError):
    """Contains only a static, safe error description."""


class CompletionClient:
    def __init__(self, settings, log):
        self.settings, self.log = settings, log

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
    ):
        """``timeout`` and ``attempts`` let optional, advisory callers (the judge) fail fast.

        Inside an active trace the call is recorded as one span: its attempts, token usage,
        finish reason and the audit events that hold the full prompt and answer.
        """
        model = model or self.settings.llm_model
        purpose = telemetry.purpose_for_schema(schema)
        with telemetry.span(
            f"llm.{purpose}",
            kind="llm",
            purpose=purpose,
            model=model,
            structured=schema is not None,
            max_attempts=attempts,
            temperature=0,
            max_tokens=self.settings.llm_max_tokens,
        ) as trace:
            return self._complete(messages, schema, model, run_id, role, timeout, attempts, trace)

    def _complete(self, messages, schema, model, run_id, role, timeout, attempts, trace):
        messages = list(messages)
        attempt_log: list[dict] = []
        prompt_events: list[int] = []
        trace.set(attempt_log=attempt_log, prompt_events=prompt_events, attempts=0)
        for attempt in range(attempts):
            started = time.perf_counter()
            prompt_event = self.log(
                run_id,
                "model_prompt",
                {"role": role, "model": model, "messages": messages, "attempt": attempt + 1},
            )
            if isinstance(prompt_event, int):
                prompt_events.append(prompt_event)
            trace.set(
                attempts=attempt + 1,
                prompt_messages=len(messages),
                prompt_chars=sum(len(str(m.get("content", ""))) for m in messages),
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
            if model.startswith(("nvidia/nemotron-3", "nvidia/nemotron-nano-3")):
                request["chat_template_kwargs"] = {
                    "enable_thinking": self.settings.llm_enable_thinking
                }
            try:
                with httpx.Client(
                    timeout=timeout or self.settings.llm_timeout_seconds, follow_redirects=False
                ) as client:
                    response = client.post(
                        self.settings.llm_base_url.rstrip("/") + "/chat/completions",
                        headers={
                            "Authorization": "Bearer "
                            + self.settings.llm_api_key.get_secret_value()
                        },
                        json=request,
                    )
                response.raise_for_status()
                payload = response.json()
                choice = payload["choices"][0]
                trace.set(finish_reason=choice.get("finish_reason"))
                if choice.get("finish_reason") in ("length", "content_filter"):
                    raise ValueError("Incomplete model response")
                raw = choice["message"]["content"]
                if not isinstance(raw, str) or not raw.strip():
                    raise ValueError("Empty model response")
                parsed = schema.model_validate_json(raw) if schema else raw
                usage = payload.get("usage") or {}
                if not isinstance(usage, dict):
                    usage = {}
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
                if status not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                    raise CompletionError(
                        f"Model provider rejected request (HTTP {status}); no fixture fallback."
                    ) from None
                time.sleep(0.5)
            except (httpx.RequestError, ValueError, KeyError, IndexError, TypeError) as error:
                reason = (
                    "transport_failure"
                    if isinstance(error, httpx.RequestError)
                    else "output_validation_failure"
                )
                self.log(
                    run_id,
                    "model_failure",
                    {"role": role, "attempt": attempt + 1, "reason": reason},
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
