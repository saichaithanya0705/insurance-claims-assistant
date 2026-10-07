"""Fixture retrieval and a fail-closed, read-only Synapt MCP boundary."""

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

from claims.cards import LESSON_MARKER, claim_card_text, claim_ids_in_text, is_card_chunk
from claims.models import ClaimInput, Evidence, RetrievalBundle
from claims.settings import Settings

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


def _http_client_factory(headers=None, timeout=None, auth=None):
    # Explicitly prevent forwarding bearer credentials to a redirect destination.
    return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth, follow_redirects=False)


class SynaptError(RuntimeError):
    """Only static, credential-free messages cross the integration boundary."""


class FixtureSynaptAdapter:
    def retrieve(self, claim: ClaimInput) -> RetrievalBundle:
        docs = [
            (
                "fixture-procedure-auto",
                "Synthetic auto handling procedure",
                (
                    "For an auto claim, request an incident statement and repair estimate; "
                    "for theft, request a police report when applicable."
                ),
            ),
            (
                "fixture-procedure-property",
                "Synthetic property handling procedure",
                (
                    "For home, renters or property claims, request an incident statement, "
                    "damage photographs and a damage assessment (an itemized repair estimate). "
                    "For renters claims, request an inventory list of damaged or lost items. "
                    "For business claims, request an incident statement and a loss assessment "
                    "supported by loss documentation."
                ),
            ),
            (
                "fixture-review-boundary",
                "Synthetic review and coverage boundary",
                (
                    "Policy wording and applicable endorsements must be checked before a coverage "
                    "decision. Similar cases do not establish coverage or prove fraud. "
                    "A human claims handler reviews recommendations before any final decision."
                ),
            ),
        ]
        return RetrievalBundle(
            mode="fixture",
            evidence=[
                Evidence(source_id=key, title=title, text=text, provenance="synthetic_fixture")
                for key, title, text in docs
            ],
            warnings=["Synthetic procedure fixtures; live Synapt retrieval has not been verified."],
        )


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


def _backoff(exc: Exception, attempt: int) -> float:
    """Seconds to wait before retrying; a rate-limited login waits as the server asks."""
    for response in _statuses(exc):
        if response.status_code == 429:
            try:
                return min(float(response.headers.get("Retry-After", "")), 30.0)
            except ValueError:
                return min(2.0 * 2**attempt, 15.0)
    return 0.2 * (attempt + 1)


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
            await session.initialize()
            yield session

    async def _tools(self, session) -> list:
        tools = []
        cursor = None
        for _ in range(5):
            page = await session.list_tools(cursor=cursor)
            tools.extend(page.tools)
            cursor = page.nextCursor
            if cursor is None:
                return tools
        raise SynaptError("Synapt tool discovery exceeded the supported page limit.")

    async def _retry(self, operation, *, attempts=3):
        for attempt in range(attempts):
            try:
                async with asyncio.timeout(
                    self._timeout_override or self.settings.synapt_timeout_seconds
                ):
                    return await operation()
            except Exception as exc:  # noqa: BLE001 - integration errors must never expose secrets
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

    def _validate_arguments(self, tool, arguments):
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
        if (
            not isinstance(props, dict)
            or "provider_id" not in props
            or arguments.get("provider_id") != self.settings.synapt_provider_id
        ):
            raise SynaptError("Synapt tool must be scoped to the configured provider.")
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

    async def feedback(self, query_id: str, rating: str, reason: str) -> dict:
        """Optional explicit reviewed feedback; never invoked by retrieval."""
        if (
            not all(isinstance(x, str) and x.strip() for x in (query_id, rating, reason))
            or len(query_id) > 500
            or len(rating) > 50
            or len(reason) > 2000
        ):
            raise SynaptError("Synapt feedback requires bounded reviewed fields.")
        return await self._explicit_tool(
            "trident_feedback",
            {
                "provider_id": self.settings.synapt_provider_id,
                "query_id": query_id,
                "rating": rating,
                "reason": reason,
            },
            mutation=True,
        )

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
        self, result, *, procedures=False, keep_cards=False, limit=None
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
        if not keep_cards:
            # Claim cards and promoted lessons rank/inform locally; they are never cited as sources.
            evidence = [
                e for e in evidence if not is_card_chunk(e.text) and LESSON_MARKER not in e.text
            ]
        return evidence[: limit or self.settings.synapt_top_k]

    async def retrieve_async(self, claim: ClaimInput) -> RetrievalBundle:
        self.live_verified = False

        async def operation():
            async with self._session() as session:
                tools = await self._tools(session)
                tools.sort(
                    key=lambda tool: {
                        "trident_get_chunks": 0,
                        "trident_search": 1,
                        "trident_query": 2,
                    }.get(tool.name, 99)
                )
                # Procedures are generic per claim type, and the provider also holds ~20k claim
                # cards. A query that embeds the claim narrative sits closer to those cards than to
                # any procedure, so 8-9 of the top 10 hits were cards (discarded below) and some
                # claims got no procedure at all. Querying in the procedures' own vocabulary
                # retrieves them reliably, and keeps free text (which may hold personal data) out
                # of this provider call.
                subject = f" {claim.claim_type}" if claim.claim_type else ""
                query = (
                    f"Synthetic{subject} claim documentation procedure: "
                    "required evidence and handling steps"
                )
                evidence = []
                warnings = []
                used = set()
                primary_found = False
                primary_tool = None
                for tool in tools:
                    if tool.name not in {"trident_get_chunks", "trident_search", "trident_query"}:
                        continue
                    arguments = self._arguments(tool, query, self.settings.synapt_top_k + 5)
                    if arguments is not None:
                        result = await session.call_tool(tool.name, arguments=arguments)
                        evidence = self._normalize(result)
                        used.add(tool.name)
                        primary_tool = tool
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
                        result = await session.call_tool(name, arguments=arguments)
                        evidence.extend(
                            self._normalize(result, procedures=name == "trident_get_procedures")
                        )
                        used.add(name)
                    except SynaptError:
                        warnings.append(
                            f"Optional Synapt {name} response lacks supported provenance."
                        )
                if not evidence and "trident_query" not in used:
                    matches = [t for t in tools if t.name == "trident_query"]
                    if len(matches) == 1:
                        arguments = self._arguments(matches[0], query)
                        if arguments is not None:
                            result = await session.call_tool("trident_query", arguments=arguments)
                            evidence.extend(self._normalize(result))
                unique = {(e.source_id, e.text): e for e in evidence}
                evidence = list(unique.values())
                if not evidence:
                    warnings.append("Synapt returned no supporting evidence.")
                semantic_ids = []
                case_query = "Historical claim card. " + claim_card_text(
                    claim.model_dump(mode="json"), include_outcome=False, masking_safe=True
                )
                case_arguments = self._arguments(
                    primary_tool, case_query, self.settings.synapt_case_top_k
                )
                try:
                    result = await session.call_tool(primary_tool.name, arguments=case_arguments)
                    for chunk in self._normalize(
                        result, keep_cards=True, limit=self.settings.synapt_case_top_k
                    ):
                        if is_card_chunk(chunk.text):
                            semantic_ids += claim_ids_in_text(chunk.text)
                except (SynaptError, TypeError):
                    warnings.append("Synapt claim-card retrieval was unavailable for this claim.")
                semantic_ids = list(dict.fromkeys(semantic_ids))
                if not semantic_ids:
                    warnings.append(
                        "No ingested historical claim cards matched; semantic ranking was not applied."
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

        bundle = await self._retry(operation)
        self.live_verified = bool(bundle.evidence)
        return bundle

    def retrieve(self, claim: ClaimInput) -> RetrievalBundle:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.retrieve_async(claim))
        raise SynaptError("Use await retrieve_async inside an asynchronous event loop.")


def build_synapt_adapter(settings: Settings) -> FixtureSynaptAdapter | LiveSynaptAdapter:
    if settings.synapt_mode == "fixture":
        return FixtureSynaptAdapter()
    return LiveSynaptAdapter(settings)
