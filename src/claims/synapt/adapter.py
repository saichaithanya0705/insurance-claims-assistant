"""The Synapt MCP boundary: fail-closed, read-only retrieval. Synapt is required; there is no
fixture or fallback adapter."""

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from urllib.parse import urlsplit

import httpx
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from claims.agents import access
from claims.core.schemas import ClaimInput, Evidence, RetrievalBundle
from claims.core.settings import Settings
from claims.corpus.cards import (
    ALIAS,
    LESSON_MARKER,
    claim_id_from_alias,
    claim_ticket,
    is_card_chunk,
)
from claims.observability import telemetry
from claims.synapt import knowledge_graph

logger = logging.getLogger(__name__)
INGEST_TIMEOUT_SECONDS = 180.0
# Used when the token endpoint does not state a lifetime; short, so a stale token costs one retry.
DEFAULT_TOKEN_SECONDS = 240.0
MAX_TOKEN_SECONDS = 900.0
READ_ONLY_TOOLS = frozenset(
    {
        "trident_get_chunks",
        "trident_get_procedures",
        "trident_search",
        "trident_traverse",
        "trident_get_schema",
        "trident_get_stats",
        "trident_get_node",
        "trident_find_exact",
        "trident_cypher",
        "trident_query",
        "trident_episodes",
    }
)
# The roster's name for the ticket-only leg of `trident_query` (`ticket_mode="only"`: no question embedding, no graph walk, no
# model call). A separate permission, so the passage retriever can find similar past tickets without being able to ask the
# provider's query agent anything.
TICKET_NEIGHBOURS = "trident_ticket_neighbours"


def ticket_examples(item: dict) -> list[str]:
    """The ticket aliases one `ticket_labels` entry names, best score first, each once. Per label field and value the ticket
    leg returns the neighbour that best supports it; those examples are the closest past claims Synapt names."""
    examples = []
    for field in (item.get("fields") or {}).values():
        for label in (field or {}).get("labels") or []:
            example = (label or {}).get("example") or {}
            alias, score = example.get("ticket_id"), example.get("score")
            if isinstance(alias, str) and ALIAS.fullmatch(alias):
                examples.append((-(score if isinstance(score, int | float) else 0.0), alias))
    return list(dict.fromkeys(alias for _, alias in sorted(examples)))


def _http_client_factory(headers=None, timeout=None, auth=None):
    # Explicitly prevent forwarding bearer credentials to a redirect destination.
    return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth, follow_redirects=False)


class SynaptError(RuntimeError):
    """Only static, credential-free messages cross the integration boundary."""


def _transient(exc: Exception) -> bool:
    if isinstance(exc, ExceptionGroup):
        return bool(exc.exceptions) and all(_transient(e) for e in exc.exceptions)
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, TimeoutError)):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {
        429,
        502,
        503,
        504,
    }


def _statuses(exc: Exception):
    if isinstance(exc, ExceptionGroup):
        for inner in exc.exceptions:
            yield from _statuses(inner)
    elif isinstance(exc, httpx.HTTPStatusError):
        yield exc.response


def _unauthorized(exc: Exception) -> bool:
    return any(r.status_code == 401 for r in _statuses(exc))


def _access_denied(exc: BaseException):
    """The access denial inside ``exc``, if it is one or wraps one (the MCP transport wraps errors raised inside a session in groups)."""
    if isinstance(exc, access.AccessDenied):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            found = _access_denied(inner)
            if found is not None:
                return found
    return None


def _backoff(exc: Exception, attempt: int) -> float:
    """Seconds to wait before retrying; a rate-limited login waits as the server asks."""
    for response in _statuses(exc):
        if response.status_code == 429:
            try:
                return min(float(response.headers.get("Retry-After", "")), 30.0)
            except ValueError:
                return min(2.0 * 2**attempt, 15.0)
    return 0.2 * (attempt + 1)


async def _together(coroutines) -> list:
    """Await independent calls at once and return their results in order. If one fails the others are cancelled and awaited, so
    nothing is left running against a session that is closing, and the first error is raised as itself."""
    tasks = [asyncio.ensure_future(c) for c in coroutines]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


class LiveSynaptAdapter:
    """Explicit integration assumptions are recorded in docs/SYNAPT_CONTRACT.md.

    Retrieval never creates providers, ingests documents or submits feedback.
    Explicit ingestion/feedback methods are separate opt-in operations.
    Unsupported tenant contracts fail with an actionable static error.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.live_verified = False
        # Writes (ingestion embeds many chunks) get a longer budget than reads.
        self._timeout_override: float | None = None
        # One login serves many calls: the beta token endpoint rate-limits (HTTP 429) otherwise.
        self._token: tuple[str, float] | None = None
        self._token_lifetime: float | None = None
        provider = settings.synapt_provider_id
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", provider):
            raise SynaptError("A single explicit Synapt provider identifier is required.")
        if not settings.synapt_username or not settings.synapt_password.get_secret_value():
            raise SynaptError("Synapt login configuration is incomplete.")
        for url in (settings.synapt_mcp_url, settings.synapt_auth_base):
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise SynaptError("Synapt endpoints must be HTTPS without embedded credentials.")

    async def _authenticate(self) -> str:
        credentials = {
            self.settings.synapt_auth_username_field: self.settings.synapt_username,
            "password": self.settings.synapt_password.get_secret_value(),
        }
        body = {self.settings.synapt_auth_encoding: credentials}
        if self.settings.synapt_auth_encoding == "form":
            body = {"data": credentials}
        async with httpx.AsyncClient(
            timeout=self.settings.synapt_timeout_seconds,
            follow_redirects=False,
        ) as client:
            response = await client.post(self.settings.synapt_auth_base, **body)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise SynaptError("Synapt authentication response has an unsupported schema.")
        token = payload.get("access_token")
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 16384
            or any(c.isspace() for c in token)
        ):
            raise SynaptError("Synapt authentication did not return a valid access token.")
        token_type = payload.get("token_type", "bearer")
        if not isinstance(token_type, str) or token_type.lower() != "bearer":
            raise SynaptError("Synapt authentication requires a supported Bearer token.")
        lifetime = payload.get("expires_in")
        self._token_lifetime = (
            float(lifetime)
            if isinstance(lifetime, (int, float)) and not isinstance(lifetime, bool) and lifetime > 0
            else None
        )
        return token

    async def _bearer(self) -> str:
        """The cached access token, or a fresh login when absent or about to expire."""
        now = time.monotonic()
        if self._token is not None and self._token[1] > now:
            return self._token[0]
        with telemetry.span("synapt.login", kind="tool"):
            token = await self._authenticate()
        lifetime = (
            min(max(self._token_lifetime - 60.0, 0.0), MAX_TOKEN_SECONDS)
            if self._token_lifetime
            else DEFAULT_TOKEN_SECONDS
        )
        self._token = (token, now + lifetime)
        return token

    @asynccontextmanager
    async def _session(self):
        token = await self._bearer()
        timeout = self._timeout_override or self.settings.synapt_timeout_seconds
        async with (
            streamablehttp_client(
                self.settings.synapt_mcp_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout,
                sse_read_timeout=timeout,
                httpx_client_factory=_http_client_factory,
            ) as (read_stream, write_stream, _),
            ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=timeout),
            ) as session,
        ):
            with telemetry.span("synapt.initialize", kind="tool"):
                await session.initialize()
            yield session

    async def _tools(self, session) -> list:
        tools = []
        cursor = None
        for _ in range(5):
            with telemetry.span("synapt.list_tools", kind="tool") as trace:
                page = await session.list_tools(cursor=cursor)
                trace.set(tools=len(page.tools))
            tools.extend(page.tools)
            cursor = page.nextCursor
            if cursor is None:
                return tools
        raise SynaptError("Synapt tool discovery exceeded the supported page limit.")

    async def _retry(self, operation, *, attempts=3, deadline=None):
        """Run ``operation`` up to ``attempts`` times. With a ``deadline`` (a read that normally takes seconds) an attempt that has not
        finished by then is abandoned, not awaited: cancelling a stalled call makes its session wait for the transport to give up
        (19 s on 12 October), which is the very wait the deadline is there to avoid, so the next attempt starts at once and the old
        one is left to clean up on its own. Without a deadline an attempt is cancelled and awaited, as before."""
        for attempt in range(attempts):
            try:
                if deadline is None:
                    async with asyncio.timeout(
                        self._timeout_override or self.settings.synapt_timeout_seconds
                    ):
                        return await operation()
                task = asyncio.ensure_future(operation())
                try:
                    done, _ = await asyncio.wait({task}, timeout=deadline)
                except asyncio.CancelledError:
                    task.cancel()
                    raise
                if not done:
                    task.add_done_callback(lambda t: t.cancelled() or t.exception())  # nobody awaits it: keep the loop quiet
                    task.cancel()
                    raise TimeoutError(f"no result within {deadline:g} s")
                return task.result()
            except Exception as exc:  # noqa: BLE001 - integration errors must never expose secrets
                denied = _access_denied(exc)
                if denied is not None:
                    raise denied from None  # a role's limit, not an outage: never retried, never answered with the fallback
                if _unauthorized(exc):
                    self._token = None  # stale token: the next attempt logs in again
                if (_transient(exc) or _unauthorized(exc)) and attempt < attempts - 1:
                    logger.info("synapt_transient_retry attempt=%s", attempt + 1)
                    await asyncio.sleep(_backoff(exc, attempt))
                    continue
                if isinstance(exc, SynaptError):
                    raise SynaptError(str(exc)) from None
                raise SynaptError(
                    "Synapt request failed; check access, connectivity and integration contract."
                ) from None

    async def discover(self) -> dict:
        async def operation():
            async with self._session() as session:
                tools = await self._tools(session)
                supported = [tool.name for tool in tools if tool.name in READ_ONLY_TOOLS]
                compatible = []
                for tool in tools:
                    if self._arguments(tool, "contract compatibility check") is not None:
                        compatible.append(tool.name)
                return {
                    "mode": "live",
                    "read_only_tools": supported,
                    "compatible_retrieval_tools": compatible,
                    "provider_id": self.settings.synapt_provider_id,
                    "tool_schemas": self._redact(
                        {
                            tool.name: tool.inputSchema
                            for tool in tools
                            if tool.name in READ_ONLY_TOOLS | {"trident_ingest", "trident_feedback"}
                        }
                    ),
                    "retrieval_contract_verified": False,
                }

        return await self._retry(operation)

    def _redact(self, value):
        if isinstance(value, dict):
            return {
                key: "[redacted]"
                if any(
                    s in key.lower()
                    for s in (
                        "password",
                        "access_token",
                        "authorization",
                        "secret",
                        "credential",
                    )
                )
                else self._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, str):
            for secret in (
                self.settings.synapt_password.get_secret_value(),
                self.settings.synapt_username,
                self._token[0] if self._token else "",
            ):
                if secret:
                    value = value.replace(secret, "[redacted]")
        return value

    def _validate_arguments(self, tool, arguments, *, scoped=True):
        """Check arguments against the tool's discovered schema. ``scoped`` is False only for a tool whose schema has no
        provider field (`trident_feedback`); the caller then vouches that the identifier is one Synapt gave us."""
        if not isinstance(arguments, dict):
            raise SynaptError("Synapt tool arguments must be an object.")
        if tool.name == "trident_cypher":
            query = arguments.get("query", "")
            if (
                not isinstance(query, str)
                or not query.lstrip().upper().startswith("MATCH ")
                or "{provider_id: $provider_id}" not in query
                or ";" in query
                or re.search(r"\b(CREATE|DELETE|DETACH|MERGE|SET|REMOVE|DROP|LOAD|CALL|FOREACH)\b",
                             query, re.IGNORECASE)
            ):
                raise SynaptError("Cypher reads require a bounded provider-scoped MATCH query.")
        schema = tool.inputSchema

        def has_external_ref(value):
            if isinstance(value, dict):
                return ("$ref" in value and not str(value["$ref"]).startswith("#/")) or any(
                    has_external_ref(v) for v in value.values()
                )
            if isinstance(value, list):
                return any(has_external_ref(v) for v in value)
            return False

        if has_external_ref(schema):
            raise SynaptError("Synapt tool schema contains an unsupported external reference.")
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        if scoped and (
            not isinstance(props, dict)
            or "provider_id" not in props
            or arguments.get("provider_id") != self.settings.synapt_provider_id
        ):
            raise SynaptError("Synapt tool must be scoped to the configured provider.")
        if not isinstance(props, dict):
            raise SynaptError("Synapt tool schema has no properties.")
        if not arguments.keys() <= props.keys():
            raise SynaptError("Synapt tool arguments include unsupported parameters.")
        try:
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(arguments)
        except (SchemaError, ValidationError):
            raise SynaptError("Synapt tool arguments do not match the discovered schema.") from None

    def _structured_payload(self, result, max_response_chars=1_000_000) -> dict:
        if result.isError:
            raise SynaptError("Synapt tool reported an error.")
        payload = result.structuredContent
        if payload is not None and len(json.dumps(payload)) > max_response_chars:
            raise SynaptError("Synapt tool response exceeds the bounded response budget.")
        if payload is None:
            blocks = [b.text for b in result.content if b.type == "text"]
            if len(blocks) != 1 or len(blocks[0]) > max_response_chars:
                raise SynaptError("Synapt tool response has an unsupported schema.")
            try:
                payload = json.loads(blocks[0])
            except (ValueError, TypeError):
                raise SynaptError("Synapt tool response must be a structured object.") from None
        if not isinstance(payload, dict):
            raise SynaptError("Synapt tool response must be a structured object.")
        return self._redact(payload)

    async def _explicit_tool(self, name: str, arguments, *, mutation=False,
                             max_response_chars=1_000_000) -> dict:
        access.authorize(name)
        allowed = {"trident_ingest", "trident_feedback"} if mutation else READ_ONLY_TOOLS
        if name not in allowed:
            raise SynaptError("Synapt tool is not permitted for this operation.")

        async def operation():
            async with self._session() as session:
                matches = [t for t in await self._tools(session) if t.name == name]
                if len(matches) != 1:
                    raise SynaptError("Requested Synapt tool is not uniquely available.")
                resolved = arguments(matches[0]) if callable(arguments) else arguments
                self._validate_arguments(matches[0], resolved)
                response = await session.call_tool(name, arguments=resolved)
                return self._structured_payload(response, max_response_chars)

        if not mutation:
            return await self._retry(operation)
        self._timeout_override = INGEST_TIMEOUT_SECONDS
        try:
            return await self._retry(operation, attempts=1)
        finally:
            self._timeout_override = None

    async def call_read_tool(self, name: str, arguments: dict, *,
                             max_response_chars: int = 1_000_000) -> dict:
        """Call only a discovered, allowlisted, explicitly provider-scoped read tool."""
        if (type(max_response_chars) is not int
                or not 1_000 <= max_response_chars <= 20_000_000):
            raise SynaptError("Read response budget must be bounded to 1,000..20,000,000 characters.")
        return await self._explicit_tool(name, arguments, max_response_chars=max_response_chars)

    async def ingest(
        self,
        content: str,
        filename: str,
        document_type: str = "text",
        *,
        chunking: dict | None = None,
        persistent: bool = True,
    ) -> dict:
        """Submit once; a returned request ID does not prove extraction completion.

        ``chunking`` may set chunking_type, chunk_size and chunk_overlap; each is sent only if the
        discovered tool schema advertises it."""
        chunking = {
            k: v
            for k, v in (chunking or {}).items()
            if k in ("chunking_type", "chunk_size", "chunk_overlap")
        }
        if (
            not isinstance(content, str)
            or not content.strip()
            or len(content) > 1_000_000
            or not isinstance(filename, str)
            or not filename.strip()
            or len(filename) > 250
            or document_type != "text"
        ):
            raise SynaptError("Ingestion requires bounded text and a valid filename.")

        def ingestion_arguments(tool):
            props = tool.inputSchema.get("properties", {})
            extraction_fields = {"extraction_mode", "extractionmode"} & props.keys()
            if len(extraction_fields) != 1:
                raise SynaptError("Synapt ingestion requires an advertised extraction-mode field.")
            if not {"provider_id", "content"} <= props.keys():
                raise SynaptError("Synapt ingestion has an unsupported content contract.")
            values = {
                "provider_id": self.settings.synapt_provider_id,
                "content": content,
                "filename": filename,
                "document_type": document_type,
                "connector_type": "content",
                "has_ttl": not persistent,
                next(iter(extraction_fields)): "balanced",
                **chunking,
            }
            return {key: value for key, value in values.items() if key in props}

        response = await self._explicit_tool(
            "trident_ingest",
            ingestion_arguments,
            mutation=True,
        )
        # The beta tenant sometimes wraps the body as {"result": "<json>"}; decode one layer.
        body = response
        if isinstance(response.get("result"), str):
            try:
                decoded = json.loads(response["result"])
                body = decoded if isinstance(decoded, dict) else response
            except ValueError:
                body = response
        if (
            body.get("accepted") is False
            or body.get("error") or body.get("errors")
            or str(body.get("status", "")).lower() == "error"
        ):
            # Private diagnostics for the explicitly authorized uploader; never public API errors.
            self.last_ingest_rejection = {
                "accepted": body.get("accepted"),
                "summary": self._redact(str(body.get("error") or body.get("errors")
                                             or body.get("response") or body.get("status")))[:500],
            }
            raise SynaptError("Synapt ingestion was rejected by the provider.")
        req_id = next(
            (
                body[key]
                for key in ("req_id", "request_id", "task_id", "job_id", "id")
                if isinstance(body.get(key), str) and body[key].strip() and len(body[key]) <= 500
            ),
            None,
        )
        # A write that returned no identifier may still have been accepted; completion is checked
        # by the caller from provider statistics, never assumed from this response.
        return {
            "status": "submitted",
            "req_id": req_id,
            "response_keys": sorted(str(k) for k in body)[:12],
            "extractionmode": "balanced",
            "completion_verified": False,
        }

    async def send_feedback_async(
        self, feedback_id: str, verdict: str, *, caller_type: str = "user", post_action: str | None = None, reason: str | None = None
    ) -> dict:
        """Record a handler's verdict on an answer Synapt's query agent wrote (`trident_feedback`).

        The tenant's schema is `feedback_id`, `caller_type` (user, agent, mcp_tool), `verdict` (deflected, partial,
        not_deflected), `post_action`, `score` and `reason`, with no provider field, so the usual provider-scoping check
        cannot apply. Instead the caller passes only a query ID this application received from Synapt for its own query, and
        every argument is validated against the discovered schema. Explicit and single-attempt, like ingestion: a timeout may
        follow a write that landed, so it is never retried. Never invoked by retrieval.
        """
        if not isinstance(feedback_id, str) or not feedback_id.strip() or len(feedback_id) > 200:
            raise SynaptError("Synapt feedback needs the query identifier Synapt returned.")
        access.authorize("trident_feedback")
        arguments = {"feedback_id": feedback_id.strip(), "caller_type": caller_type, "verdict": verdict}
        if post_action:
            arguments["post_action"] = post_action
        if reason and reason.strip():
            arguments["reason"] = reason.strip()[:500]

        async def operation():
            async with self._session() as session:
                tools = [t for t in await self._tools(session) if t.name == "trident_feedback"]
                if len(tools) != 1:
                    raise SynaptError("Synapt does not expose the feedback tool.")
                self._validate_arguments(tools[0], arguments, scoped=False)
                result = await session.call_tool("trident_feedback", arguments=arguments)
                payload = self._structured_payload(result)
                if payload.get("accepted") is not True:
                    raise SynaptError("Synapt did not accept the feedback.")
                return payload

        return await self._retry(operation, attempts=1)

    def send_feedback(self, feedback_id: str, verdict: str, **kwargs) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.send_feedback_async(feedback_id, verdict, **kwargs))
        raise SynaptError("Use await send_feedback_async inside an asynchronous event loop.")

    def _arguments(self, tool, query: str, top_k: int | None = None) -> dict | None:
        if tool.name not in {
            "trident_get_chunks",
            "trident_search",
            "trident_query",
            "trident_get_procedures",
        }:
            return None
        schema = tool.inputSchema
        if not isinstance(schema, dict) or schema.get("type") != "object":
            return None
        props = schema.get("properties", {})
        mandatory = {"provider_id"}
        if tool.name != "trident_get_procedures":
            mandatory.add("query")
        if not isinstance(props, dict) or not mandatory <= props.keys():
            return None
        values = {
            "provider_id": self.settings.synapt_provider_id,
            "query": query,
            "top_k": top_k or self.settings.synapt_top_k,
            "graph_hops": self.settings.synapt_graph_hops,
        }
        required = schema.get("required", [])
        if not isinstance(required, list) or not set(required) <= values.keys():
            return None
        arguments = {key: value for key, value in values.items() if key in props}
        for key, value in arguments.items():
            spec = props[key]
            expected = "integer" if isinstance(value, int) else "string"
            if not isinstance(spec, dict) or spec.get("type") != expected:
                return None
            if "enum" in spec and value not in spec["enum"]:
                return None
            if "const" in spec and value != spec["const"]:
                return None
            if isinstance(value, int):
                if value < spec.get("minimum", value) or value > spec.get("maximum", value):
                    return None
            else:
                if len(value) < spec.get("minLength", 0) or len(value) > spec.get(
                    "maxLength", 100000
                ):
                    return None
                if "pattern" in spec and re.search(spec["pattern"], value) is None:
                    return None
        try:
            self._validate_arguments(tool, arguments)
        except SynaptError:
            return None
        return arguments

    def _normalize(
        self, result, *, procedures=False, limit=None
    ) -> list[Evidence]:
        if result.isError:
            raise SynaptError("Synapt retrieval tool reported an error.")
        payload = result.structuredContent
        if payload is None:
            blocks = [block.text for block in result.content if block.type == "text"]
            if len(blocks) != 1 or len(blocks[0]) > 1_000_000:
                raise SynaptError("Synapt retrieval response has an unsupported schema.")
            try:
                payload = json.loads(blocks[0])
            except (ValueError, TypeError):
                raise SynaptError(
                    "Synapt retrieval response must contain structured evidence."
                ) from None
        # The verified beta tenant wraps a JSON-encoded list in `result`.
        # Decode one bounded layer only; retain the outer provider boundary.
        if isinstance(payload, dict) and "result" in payload:
            if (
                payload.get("provider_id", self.settings.synapt_provider_id)
                != self.settings.synapt_provider_id
            ):
                raise SynaptError("Synapt returned evidence outside the configured provider.")
            wrapped = payload["result"]
            if not isinstance(wrapped, str) or len(wrapped) > 1_000_000:
                raise SynaptError("Synapt retrieval response has an unsupported result wrapper.")
            try:
                payload = json.loads(wrapped)
            except (ValueError, TypeError):
                raise SynaptError(
                    "Synapt retrieval result must contain structured evidence."
                ) from None
        if isinstance(payload, dict):
            if (
                payload.get("provider_id", self.settings.synapt_provider_id)
                != self.settings.synapt_provider_id
            ):
                raise SynaptError("Synapt returned evidence outside the configured provider.")
            chunks = payload.get("procedures" if procedures else "chunks")
        else:
            chunks = payload
        if not isinstance(chunks, list) or len(chunks) > 100:
            raise SynaptError("Synapt retrieval response must contain a bounded chunk list.")
        evidence = []
        seen = set()
        for item in chunks:
            if not isinstance(item, dict):
                raise SynaptError("Synapt returned malformed evidence.")
            if (
                item.get("provider_id", self.settings.synapt_provider_id)
                != self.settings.synapt_provider_id
            ):
                raise SynaptError("Synapt returned evidence outside the configured provider.")
            if item.get("doc_type") == "episodic":
                # Synapt's own memory of earlier query sessions (its `es_<provider>` document) comes back from passage
                # search like any chunk. It records what an agent once asked and answered, not policy, so it is not evidence.
                continue
            source = item.get("source_id") or item.get("document_id") or item.get("chunk_id")
            text = item.get("text") or item.get("content")
            if procedures and text is None:
                steps = item.get("steps")
                if isinstance(steps, list) and 0 < len(steps) <= 100:
                    texts = [
                        step
                        if isinstance(step, str)
                        else step.get("text") or step.get("content")
                        if isinstance(step, dict)
                        else None
                        for step in steps
                    ]
                    if all(isinstance(step, str) and step.strip() for step in texts):
                        text = "\n".join(texts)
            heading = None
            if item.get("doc_type") == "sop" and isinstance(text, str) and text.strip():
                candidate = text.strip().splitlines()[0].strip().lstrip("# ")
                if 0 < len(candidate) <= 250:
                    heading = candidate
            title = (
                item.get("title") or heading or item.get("source_file") or "Synapt source passage"
            )
            if (
                not isinstance(source, str)
                or not source.strip()
                or len(source) > 500
                or not isinstance(text, str)
                or not text.strip()
                or len(text) > 30000
                or not isinstance(title, str)
                or not title.strip()
                or len(title) > 500
            ):
                raise SynaptError(
                    "Synapt returned evidence without valid source identifiers or text."
                )
            identity = (source, text)
            if identity not in seen:
                seen.add(identity)
                evidence.append(
                    Evidence(
                        source_id=source,
                        title=title,
                        text=text,
                        provenance="synapt",
                        provider_id=self.settings.synapt_provider_id,
                    )
                )
        # Claim cards (if any remain in a provider) and promoted lessons are never cited as sources.
        evidence = [e for e in evidence if not is_card_chunk(e.text) and LESSON_MARKER not in e.text]
        return evidence[: limit or self.settings.synapt_top_k]

    def _ticket_neighbours(self, result) -> tuple[list[str], str | None]:
        """Claim IDs of the past claims the ticket store matched, closest first, and why there are none if so.

        The ticket leg returns, per label field and value, the neighbour that best supports it. Those examples are the
        closest past claims Synapt names; their ticket IDs are claim aliases, decoded here. Labels and confidences are
        deliberately ignored: on this data they never beat the majority class (docs/SYNAPT_INTEGRATION.md)."""
        try:
            payload = knowledge_graph.decode(result, self._redact)
        except knowledge_graph.GraphError as exc:
            raise SynaptError(str(exc)) from None
        if not isinstance(payload, dict):
            raise SynaptError("Synapt's ticket search returned an unsupported shape.")
        if payload.get("provider_id", self.settings.synapt_provider_id) != self.settings.synapt_provider_id:
            raise SynaptError("Synapt returned tickets outside the configured provider.")
        skipped = (payload.get("stores_skipped") or {}).get("ticket")
        labels = payload.get("ticket_labels")
        if not isinstance(labels, list) or not labels:
            return [], f"The provider has no usable ticket store ({skipped})." if skipped else (
                "Synapt's ticket search returned no tickets."
            )
        item = labels[0]
        if not isinstance(item, dict) or item.get("error"):
            return [], "Synapt could not match this claim against its ticket store."
        ids = [claim_id_from_alias(alias) for alias in ticket_examples(item)]
        return ids[: self.settings.synapt_case_top_k], None

    async def retrieve_async(self, claim: ClaimInput) -> RetrievalBundle:
        """The passage search belongs to the Policy Passage Retriever: it runs as that agent unless the caller named another."""
        with access.acting_unless_already("passage_retriever"):
            access.require("trident_get_chunks", "trident_search", any_of=True)
            return await self._retrieve_async(claim)

    async def _retrieve_async(self, claim: ClaimInput) -> RetrievalBundle:
        self.live_verified = False
        attempts_made = 0

        async def operation():
            nonlocal attempts_made
            attempts_made += 1
            async with self._session() as session:

                async def call(name, arguments, purpose, permission=None, shown=None, count=None):
                    access.authorize(permission or name)
                    # The queries are the deterministic, masking-safe ones built below; recording
                    # them lets a reader see exactly what the knowledge store was asked.
                    with telemetry.span(
                        "synapt.call_tool",
                        kind="tool",
                        tool=name,
                        purpose=purpose,
                        top_k=(arguments or {}).get("top_k"),
                        query=shown or (arguments or {}).get("query"),
                    ) as trace:
                        result = await session.call_tool(name, arguments=arguments)
                        trace.set(reported_error=bool(getattr(result, "isError", False)))
                        try:  # how many items came back, for the live view; never fails the call
                            trace.set(items=count(result) if count else knowledge_graph.item_count(knowledge_graph.decode(result)))
                        except (knowledge_graph.GraphError, SynaptError):
                            pass
                        return result

                tools = await self._tools(session)
                tools.sort(
                    key=lambda tool: {
                        "trident_get_chunks": 0,
                        "trident_search": 1,
                        "trident_query": 2,
                    }.get(tool.name, 99)
                )
                # Procedures are generic per claim type. Querying in the procedures' own vocabulary
                # retrieves them reliably (when the provider also held claim cards, a narrative query
                # returned 8-9 cards in its top 10), and keeps free text, which may hold personal
                # data, out of this provider call.
                subject = f" {claim.claim_type}" if claim.claim_type else ""
                query = (
                    f"Synthetic{subject} claim documentation procedure: "
                    "required evidence and handling steps"
                )
                evidence = []
                warnings = []
                used = set()
                primary_found = False
                for tool in tools:
                    if tool.name not in {"trident_get_chunks", "trident_search", "trident_query"} or not access.permits(tool.name):
                        continue
                    arguments = self._arguments(tool, query, self.settings.synapt_top_k + 5)
                    if arguments is not None:
                        result = await call(tool.name, arguments, "procedures")
                        evidence = self._normalize(result)
                        used.add(tool.name)
                        primary_found = True
                        break
                if not primary_found:
                    raise SynaptError(
                        "Synapt exposes no compatible provider-scoped retrieval schema; "
                        "verify tools/list and update the documented integration contract."
                    )
                # Enrich passages with procedures and source-bearing graph context. Bare nodes,
                # unsourced steps or generated answers must never acquire invented citations.
                # Off by default: these tools return names/steps and node IDs that carry no source
                # passage, so they can never be cited and would only add calls and a standing warning.
                optional_names = (
                    ["trident_get_procedures", "trident_search"]
                    if self.settings.synapt_graph_enrichment
                    else []
                )
                for name in optional_names:
                    matches = [t for t in tools if t.name == name and t.name not in used]
                    if len(matches) != 1:
                        warnings.append(f"Optional Synapt {name} context is unavailable.")
                        continue
                    tool = matches[0]
                    arguments = self._arguments(tool, query)
                    if arguments is None:
                        warnings.append(f"Optional Synapt {name} schema is unsupported.")
                        continue
                    try:
                        result = await call(name, arguments, "graph_enrichment")
                        evidence.extend(
                            self._normalize(result, procedures=name == "trident_get_procedures")
                        )
                        used.add(name)
                    except SynaptError:
                        warnings.append(
                            f"Optional Synapt {name} response lacks supported provenance."
                        )
                if not evidence and "trident_query" not in used and access.permits("trident_query"):
                    matches = [t for t in tools if t.name == "trident_query"]
                    if len(matches) == 1:
                        arguments = self._arguments(matches[0], query)
                        if arguments is not None:
                            result = await call("trident_query", arguments, "procedures_fallback")
                            evidence.extend(self._normalize(result))
                unique = {(e.source_id, e.text): e for e in evidence}
                evidence = list(unique.values())
                if not evidence:
                    warnings.append("Synapt returned no supporting evidence.")
                # Similar past claims come from the provider's ticket store (settled claims uploaded through the
                # console's Ticketing source), not from the documents: the documents are the procedures.
                semantic_ids = []
                query_tools = [t for t in tools if t.name == "trident_query"]
                if access.permits(TICKET_NEIGHBOURS) and len(query_tools) != 1:
                    warnings.append("Synapt's ticket store cannot be searched: the query tool is unavailable.")
                elif access.permits(TICKET_NEIGHBOURS):
                    ticket = claim_ticket(claim.model_dump(mode="json"))
                    ticket_arguments = {
                        "provider_id": self.settings.synapt_provider_id,
                        "question": "Past claims like this one",
                        "ticket_mode": "only",
                        "tickets": [ticket],
                    }
                    try:
                        self._validate_arguments(query_tools[0], ticket_arguments)
                        result = await call(
                            "trident_query", ticket_arguments, "similar_claims",
                            permission=TICKET_NEIGHBOURS, shown=ticket["description"],
                            count=lambda reply: len(self._ticket_neighbours(reply)[0]),
                        )
                        semantic_ids, reason = self._ticket_neighbours(result)
                        if reason:
                            warnings.append(reason)
                    except (SynaptError, TypeError):
                        warnings.append("Synapt's ticket store was unavailable for this claim.")
                if not semantic_ids:
                    warnings.append(
                        "No similar past claims came back from the ticket store; semantic ranking was not applied."
                    )
                logger.info(
                    "synapt_retrieval_complete evidence_count=%s semantic_cards=%s",
                    len(evidence),
                    len(semantic_ids),
                )
                return RetrievalBundle(
                    mode="live",
                    evidence=evidence,
                    warnings=warnings,
                    semantic_claim_ids=semantic_ids,
                )

        with telemetry.span("synapt.retrieve", kind="tool", provider="synapt") as trace:
            try:
                bundle = await self._retry(operation, deadline=self.settings.synapt_fast_attempt_seconds)
            finally:
                trace.set(attempts=attempts_made)
            trace.set(
                evidence=len(bundle.evidence),
                semantic_cards=len(bundle.semantic_claim_ids),
                warnings=len(bundle.warnings),
            )
        self.live_verified = bool(bundle.evidence)
        return bundle

    def retrieve(self, claim: ClaimInput) -> RetrievalBundle:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.retrieve_async(claim))
        raise SynaptError("Use await retrieve_async inside an asynchronous event loop.")

    async def ask_async(self, question: str, *, top_k: int = 5, task_id: str | None = None) -> dict:
        """Ask Synapt's query agent (`trident_query`): a written answer with the passages, procedures and graph behind it.

        Unlike every other read this one has a side effect inside Synapt: the provider records the question as a "lived
        episode" it learns from. The caller (the side chat) therefore sends only a masked question and the claim's type,
        answers a repeated question from its own saved answer, and limits how many it asks. Nothing is written to our data.
        """
        provider = self.settings.synapt_provider_id
        arguments = {"provider_id": provider, "question": question, "ticket_mode": "off", "top_k": top_k}
        if task_id:
            arguments["task_id"] = task_id  # our run ID, so the entry in Synapt's Explainability can be matched to the run
        with access.acting_unless_already("knowledge_qa"):
            return await self.call_read_tool("trident_query", arguments, max_response_chars=2_000_000)

    def ask(self, question: str, *, top_k: int = 5, task_id: str | None = None) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.ask_async(question, top_k=top_k, task_id=task_id))
        raise SynaptError("Use await ask_async inside an asynchronous event loop.")

    async def retrieve_graph_async(self, claim: ClaimInput) -> dict:
        """The graph lookup belongs to the Procedure Graph Navigator: it runs as that agent unless the caller named another."""
        with access.acting_unless_already("graph_navigator"):
            access.require("trident_search", "trident_traverse")
            return await self._retrieve_graph_async(claim)

    async def _retrieve_graph_async(self, claim: ClaimInput) -> dict:
        """Handling procedures from the Synapt knowledge graph: search by meaning, check the claim type, walk, cite.

        Read-only (`trident_search`, `trident_traverse`); nothing is written to the provider. The search text is fixed
        vocabulary plus the claim type, never the claimant's narrative. See `claims.synapt.knowledge_graph`.
        """
        provider = self.settings.synapt_provider_id

        async def operation():
            calls = 0
            try:
                async with self._session() as session:
                    tools = {tool.name: tool for tool in await self._tools(session)}
                    if not {"trident_search", "trident_traverse"} <= tools.keys():
                        raise SynaptError("Synapt does not expose the knowledge-graph tools this lookup needs.")

                    async def call(name, arguments, purpose):
                        nonlocal calls
                        access.authorize(name)
                        arguments = {"provider_id": provider, **arguments}
                        self._validate_arguments(tools[name], arguments)
                        with telemetry.span(
                            "synapt.call_tool",
                            kind="tool",
                            tool=name,
                            purpose=purpose,
                            top_k=arguments.get("top_k"),
                            query=arguments.get("query"),
                            depth=arguments.get("depth"),
                            edge_types=arguments.get("edge_types"),
                        ) as trace:
                            result = await session.call_tool(name, arguments=arguments)
                            trace.set(reported_error=bool(getattr(result, "isError", False)))
                            calls += 1
                            decoded = knowledge_graph.decode(result, self._redact)
                            trace.set(items=knowledge_graph.item_count(decoded))
                            return decoded

                    # The searches do not depend on each other, nor do the walks, so each set goes out together: a dozen calls
                    # of 0.3 s one after another took 4 to 6 s with the session setup, together they take about one call.
                    plan = knowledge_graph.search_plan(claim)
                    payloads = await _together(
                        call(
                            "trident_search",
                            {"query": step["query"], "node_type": "Procedure", "top_k": knowledge_graph.SEARCH_TOP_K},
                            "graph_search",
                        )
                        for step in plan
                    )
                    found = [
                        (step["scope"], step["query"], knowledge_graph.parse_search(payload))
                        for step, payload in zip(plan, payloads, strict=True)
                    ]
                    chosen = knowledge_graph.select([(scope, hits) for scope, _, hits in found], claim)
                    walks = await _together(
                        call(
                            "trident_traverse",
                            {"node_id": hit["node_id"], "edge_types": knowledge_graph.EDGE_TYPES, "depth": 2},
                            "graph_walk",
                        )
                        for hit, _ in chosen
                    )
                    records = []
                    for (hit, reason), payload in zip(chosen, walks, strict=True):
                        record = knowledge_graph.procedure_record(hit, knowledge_graph.parse_walk(payload), reason)
                        if record:
                            records.append(record)
                    ids = {hit["node_id"] for hit, _ in chosen}
                    searches = [
                        knowledge_graph.search_summary(scope, query, hits, ids, claim) for scope, query, hits in found
                    ]
                    return knowledge_graph.context(records, searches, calls, provider, knowledge_graph.cue_summary(claim))
            except knowledge_graph.GraphError as exc:
                raise SynaptError(str(exc)) from None

        with telemetry.span("synapt.graph", kind="tool", provider="synapt") as trace:
            graph = await self._retry(operation, deadline=self.settings.synapt_fast_attempt_seconds)
            trace.set(procedures=len(graph["procedures"]), calls=graph["calls"])
        return graph

    def retrieve_graph(self, claim: ClaimInput) -> dict:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.retrieve_graph_async(claim))
        raise SynaptError("Use await retrieve_graph_async inside an asynchronous event loop.")


    # ---- reads an agent's model asks for after the standard lookups (each opens its own session: they are rare and small) -------

    async def _graph_call(self, name: str, arguments: dict, purpose: str, parse):
        """One provider-scoped knowledge-graph read made for a follow-up. The acting agent must hold the tool."""
        access.authorize(name)
        provider = self.settings.synapt_provider_id

        async def operation():
            try:
                async with self._session() as session:
                    tools = {tool.name: tool for tool in await self._tools(session)}
                    if name not in tools:
                        raise SynaptError("Synapt does not expose the knowledge-graph tool this follow-up needs.")
                    scoped = {"provider_id": provider, **arguments}
                    self._validate_arguments(tools[name], scoped)
                    with telemetry.span(
                        "synapt.call_tool",
                        kind="tool",
                        tool=name,
                        purpose=purpose,
                        top_k=scoped.get("top_k"),
                        query=scoped.get("query"),
                        depth=scoped.get("depth"),
                    ) as trace:
                        result = await session.call_tool(name, arguments=scoped)
                        trace.set(reported_error=bool(getattr(result, "isError", False)))
                        decoded = knowledge_graph.decode(result, self._redact)
                        trace.set(items=knowledge_graph.item_count(decoded))
                        return parse(decoded)
            except knowledge_graph.GraphError as exc:
                raise SynaptError(str(exc)) from None

        return await self._retry(operation, deadline=self.settings.synapt_fast_attempt_seconds)

    async def passage_search_async(self, query: str, top_k: int = 5) -> list[Evidence]:
        """Passages for one search (``trident_get_chunks``, or ``trident_search`` when that is all the agent holds), normalised and
        cited like every other passage. Provider-scoped and read-only."""

        async def operation():
            async with self._session() as session:
                tools = [t for t in await self._tools(session) if t.name in ("trident_get_chunks", "trident_search") and access.permits(t.name)]
                tools.sort(key=lambda t: 0 if t.name == "trident_get_chunks" else 1)
                for tool in tools:
                    arguments = self._arguments(tool, query, top_k)
                    if arguments is None:
                        continue
                    access.authorize(tool.name)
                    with telemetry.span(
                        "synapt.call_tool", kind="tool", tool=tool.name, purpose="passage_followup", top_k=top_k, query=query
                    ) as trace:
                        result = await session.call_tool(tool.name, arguments=arguments)
                        trace.set(reported_error=bool(getattr(result, "isError", False)))
                        evidence = self._normalize(result, limit=top_k)
                        trace.set(items=len(evidence))
                        return evidence
                raise SynaptError("Synapt exposes no compatible passage search for this agent.")

        return await self._retry(operation, deadline=self.settings.synapt_fast_attempt_seconds)

    @staticmethod
    def _run_sync(coroutine):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)
        coroutine.close()
        raise SynaptError("Use the asynchronous form inside an asynchronous event loop.")

    def graph_search(self, query: str, top_k: int = 8) -> list[dict]:
        """Procedures by meaning (``trident_search``): the hits, each with its node ID, name, intent and score."""
        return self._run_sync(
            self._graph_call("trident_search", {"query": query, "node_type": "Procedure", "top_k": top_k}, "graph_followup", knowledge_graph.parse_search)
        )

    def graph_walk(self, node_id: str) -> dict:
        """One procedure walked to its steps and source passages (``trident_traverse``)."""
        return self._run_sync(
            self._graph_call(
                "trident_traverse",
                {"node_id": node_id, "edge_types": knowledge_graph.EDGE_TYPES, "depth": 2},
                "graph_followup_walk",
                knowledge_graph.parse_walk,
            )
        )

    def passage_search(self, query: str, top_k: int = 5) -> list[Evidence]:
        return self._run_sync(self.passage_search_async(query, top_k))


def build_synapt_adapter(settings: Settings) -> LiveSynaptAdapter:
    """Always the live Synapt adapter: the application has no mode that runs without Synapt."""
    return LiveSynaptAdapter(settings)
