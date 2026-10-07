import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from mcp.types import CallToolResult, TextContent, Tool

from claims.adapters import (
    FixtureSynaptAdapter,
    LiveSynaptAdapter,
    SynaptError,
    build_synapt_adapter,
)
from claims.models import ClaimInput
from claims.settings import Settings


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        synapt_mode="live",
        synapt_username="test-user",
        synapt_password="very-secret-password",
        synapt_provider_id="provider-1",
    )


@pytest.fixture
def claim():
    return ClaimInput(
        description="Vehicle damage after an incident.",
        claim_type="auto",
        state="CA",
        incident_date="2026-01-01",
        claim_filed_date="2026-01-02",
        claim_amount=5000,
        deductible=500,
        previous_claims_count=0,
        policyholder_tenure_years=3,
    )


def tool(name="trident_get_chunks", **extra):
    properties = {
        "query": {"type": "string"},
        "provider_id": {"type": "string"},
        "top_k": {"type": "integer"},
        "graph_hops": {"type": "integer"},
    }
    properties.update(extra)
    return Tool(
        name=name,
        inputSchema={
            "type": "object",
            "properties": properties,
            "required": ["query", "provider_id"],
        },
    )


def result(chunks):
    return CallToolResult(content=[], structuredContent={"chunks": chunks})


def stub_session(monkeypatch, adapter, tools, response):
    calls = []

    class Session:
        async def list_tools(self, cursor=None):
            return SimpleNamespace(tools=tools, nextCursor=None)

        async def call_tool(self, name, arguments):
            calls.append((name, arguments))
            return response[name] if isinstance(response, dict) else response

    @asynccontextmanager
    async def session():
        yield Session()

    monkeypatch.setattr(adapter, "_session", session)
    return calls


def test_fixture_is_explicit_and_does_not_invent_claim_facts(claim):
    bundle = FixtureSynaptAdapter().retrieve(claim)
    assert bundle.mode == "fixture"
    assert all(e.provenance == "synthetic_fixture" for e in bundle.evidence)
    assert "request an incident statement and repair estimate" in bundle.evidence[0].text
    assert claim.description not in " ".join(e.text for e in bundle.evidence)
    assert all(
        key in bundle.evidence[1].text
        for key in (
            "damage assessment",
            "inventory list",
            "loss assessment",
        )
    )


def test_live_retrieval_is_provider_scoped(monkeypatch, settings, claim):
    adapter = LiveSynaptAdapter(settings)
    calls = stub_session(
        monkeypatch,
        adapter,
        [tool(), tool("trident_ingest")],
        result(
            [
                {"document_id": "doc-1", "text": "Request repair estimate", "title": "Procedure"},
            ]
        ),
    )
    bundle = adapter.retrieve(claim)
    assert bundle.mode == "live"
    assert bundle.evidence[0].source_id == "doc-1"
    assert bundle.evidence[0].provider_id == "provider-1"
    assert calls[0][0] == "trident_get_chunks"
    assert calls[0][1]["provider_id"] == "provider-1"
    # One procedure query, then one claim-card query for semantic matching of similar cases.
    assert len(calls) == 2
    assert calls[1][1]["top_k"] == settings.synapt_case_top_k
    assert calls[1][1]["query"].startswith("Historical claim card.")
    assert bundle.semantic_claim_ids == []


@pytest.mark.parametrize("claim_type", ["home", None])
def test_procedure_query_uses_procedure_vocabulary_not_the_claim_narrative(
    monkeypatch, settings, claim, claim_type
):
    """A narrative-bearing query embeds nearer to the ~20k claim cards than to any procedure, so the
    top hits were cards (discarded) and some claims got no procedure. Measured against the live
    provider: 8-9 of 10 hits were cards. The query must stay generic and free of the description."""
    adapter = LiveSynaptAdapter(settings)
    private = ClaimInput.model_validate(
        claim.model_dump(mode="json")
        | {"description": "Basement flooded after the storm; neighbour Dana Smith saw it.",
           "claim_type": claim_type}
    )
    calls = stub_session(
        monkeypatch, adapter, [tool()],
        result([{"document_id": "doc-1", "text": "Request photos", "title": "Procedure"}]),
    )
    adapter.retrieve(private)
    procedure_query = calls[0][1]["query"]
    assert "procedure" in procedure_query.lower()
    assert "flooded" not in procedure_query and "Dana" not in procedure_query
    assert ("home" in procedure_query) == (claim_type == "home")
    assert calls[1][1]["query"].startswith("Historical claim card.")


@pytest.mark.parametrize(
    "chunks",
    [
        [{"text": "No provenance"}],
        [{"source_id": "d", "text": ""}],
        [{"source_id": "d", "text": "x", "provider_id": "wrong-provider"}],
        ["malformed"],
        {"wrong": "shape"},
    ],
)
def test_rejects_malformed_or_foreign_evidence(monkeypatch, settings, claim, chunks):
    adapter = LiveSynaptAdapter(settings)
    stub_session(monkeypatch, adapter, [tool()], result(chunks))
    with pytest.raises(SynaptError):
        adapter.retrieve(claim)


def test_rejects_unscoped_or_mutation_tools(monkeypatch, settings, claim):
    adapter = LiveSynaptAdapter(settings)
    unscoped = tool("trident_search")
    del unscoped.inputSchema["properties"]["provider_id"]
    calls = stub_session(monkeypatch, adapter, [unscoped, tool("trident_ingest")], result([]))
    with pytest.raises(SynaptError, match="no compatible provider-scoped"):
        adapter.retrieve(claim)
    assert not calls


def test_discovers_only_allowlisted_tools(monkeypatch, settings):
    adapter = LiveSynaptAdapter(settings)
    stub_session(monkeypatch, adapter, [tool(), tool("trident_ingest")], result([]))
    discovered = asyncio.run(adapter.discover())
    assert discovered["read_only_tools"] == ["trident_get_chunks"]
    assert discovered["retrieval_contract_verified"] is False


@pytest.mark.parametrize("encoding", ["json", "form"])
@pytest.mark.parametrize("identity_field", ["username", "email"])
def test_authentication_encoding_and_redirects(monkeypatch, settings, encoding, identity_field):
    settings.synapt_auth_encoding = encoding
    settings.synapt_auth_username_field = identity_field
    observed = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            observed.append(kwargs)
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={"access_token": "opaque-token", "token_type": "Bearer"},
            )

    monkeypatch.setattr("claims.adapters.httpx.AsyncClient", Client)
    assert asyncio.run(LiveSynaptAdapter(settings)._authenticate()) == "opaque-token"
    body = observed[0]["data" if encoding == "form" else "json"]
    assert body == {identity_field: "test-user", "password": "very-secret-password"}


def test_sdk_authorization_header(monkeypatch, settings):
    observed = {}
    adapter = LiveSynaptAdapter(settings)

    async def auth():
        return "test-token"

    @asynccontextmanager
    async def transport(url, **kwargs):
        observed.update(kwargs)
        yield "read", "write", None

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            pass

    async def run():
        async with adapter._session():
            pass

    monkeypatch.setattr(adapter, "_authenticate", auth)
    monkeypatch.setattr("claims.adapters.streamablehttp_client", transport)
    monkeypatch.setattr("claims.adapters.ClientSession", Session)
    asyncio.run(run())
    assert observed["headers"] == {"Authorization": "Bearer test-token"}
    client = observed["httpx_client_factory"]()
    assert not client.follow_redirects
    asyncio.run(client.aclose())


def test_errors_scrub_server_content_no_fallback(monkeypatch, settings, claim):
    adapter = build_synapt_adapter(settings)
    count = 0

    @asynccontextmanager
    async def session():
        nonlocal count
        count += 1
        raise ValueError("very-secret-password Bearer private-token raw-server-message")
        yield

    monkeypatch.setattr(adapter, "_session", session)
    with pytest.raises(SynaptError) as error:
        adapter.retrieve(claim)
    assert count == 1
    assert "secret" not in str(error.value)
    assert "private-token" not in str(error.value)
    assert error.value.__suppress_context__


def test_only_transient_errors_are_retried(monkeypatch, settings):
    adapter = LiveSynaptAdapter(settings)
    attempts = 0

    async def operation():
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("secret error detail")

    with pytest.raises(SynaptError):
        asyncio.run(adapter._retry(operation))
    assert attempts == 3


@pytest.mark.parametrize("provider", ["*", "", "all,other", "provider/../../", " white "])
def test_provider_is_explicit(settings, provider):
    settings.synapt_provider_id = provider
    with pytest.raises(SynaptError):
        LiveSynaptAdapter(settings)


def test_text_json_is_supported_but_prose_is_rejected(settings):
    adapter = LiveSynaptAdapter(settings)
    valid = CallToolResult(
        content=[TextContent(type="text", text='[{"chunk_id":"c-1","content":"Evidence passage"}]')]
    )
    assert adapter._normalize(valid)[0].source_id == "c-1"
    with pytest.raises(SynaptError):
        adapter._normalize(CallToolResult(content=[TextContent(type="text", text="trust me")]))


def test_async_callers_must_use_async_interface(settings, claim):
    async def run():
        with pytest.raises(SynaptError, match="retrieve_async"):
            LiveSynaptAdapter(settings).retrieve(claim)

    asyncio.run(run())


def test_explicit_read_rejects_unknown_args_and_mutations(monkeypatch, settings):
    adapter = LiveSynaptAdapter(settings)
    calls = stub_session(monkeypatch, adapter, [tool()], result([]))
    with pytest.raises(SynaptError, match="not permitted"):
        asyncio.run(adapter.call_read_tool("trident_ingest", {}))
    with pytest.raises(SynaptError, match="unsupported parameters"):
        asyncio.run(
            adapter.call_read_tool(
                "trident_get_chunks",
                {
                    "provider_id": "provider-1",
                    "query": "evidence",
                    "unknown": "unsafe",
                },
            )
        )
    with pytest.raises(SynaptError, match="configured provider"):
        asyncio.run(
            adapter.call_read_tool(
                "trident_get_chunks",
                {
                    "provider_id": "different",
                    "query": "evidence",
                },
            )
        )
    assert not calls


def test_ingest_is_explicit_and_submission_is_not_completion(monkeypatch, settings):
    adapter = LiveSynaptAdapter(settings)
    ingest = tool(
        "trident_ingest",
        content={"type": "string"},
        filename={"type": "string"},
        document_type={"type": "string", "enum": ["text"]},
        extractionmode={"type": "string", "enum": ["balanced"]},
    )
    ingest.inputSchema["required"] = [
        "provider_id",
        "content",
        "filename",
        "document_type",
        "extractionmode",
    ]
    calls = stub_session(
        monkeypatch,
        adapter,
        [ingest],
        CallToolResult(content=[], structuredContent={"req_id": "request-1"}),
    )
    response = asyncio.run(adapter.ingest("Document text", "policy.txt"))
    assert response == {
        "status": "submitted",
        "req_id": "request-1",
        "response_keys": ["req_id"],
        "extractionmode": "balanced",
        "completion_verified": False,
    }
    assert calls[0][1]["extractionmode"] == "balanced"
    assert len(calls) == 1


def test_ingest_accepts_unrecognised_success_shape_but_rejects_errors(monkeypatch, settings):
    ingest = Tool(
        name="trident_ingest",
        inputSchema={
            "type": "object",
            "properties": {
                "provider_id": {"type": "string"},
                "content": {"type": "string"},
                "extraction_mode": {"type": "string"},
            },
            "required": ["provider_id"],
        },
    )
    adapter = LiveSynaptAdapter(settings)
    stub_session(
        monkeypatch,
        adapter,
        [ingest],
        CallToolResult(content=[], structuredContent={"accepted": True, "response": "queued"}),
    )
    accepted = asyncio.run(adapter.ingest("Document text", "cards.txt"))
    assert accepted["req_id"] is None and accepted["response_keys"] == ["accepted", "response"]
    assert accepted["completion_verified"] is False
    failing = LiveSynaptAdapter(settings)
    stub_session(
        monkeypatch,
        failing,
        [ingest],
        CallToolResult(content=[], structuredContent={"error": "quota exceeded"}),
    )
    with pytest.raises(SynaptError, match="rejected"):
        asyncio.run(failing.ingest("Document text", "cards.txt"))


def test_ingest_does_not_retry_ambiguous_failures(monkeypatch, settings):
    adapter = LiveSynaptAdapter(settings)
    count = 0

    @asynccontextmanager
    async def session():
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("could have submitted already")
        yield

    monkeypatch.setattr(adapter, "_session", session)
    with pytest.raises(SynaptError):
        asyncio.run(adapter.ingest("Document text", "policy.txt"))
    assert count == 1


def test_schema_external_references_are_rejected(settings):
    adapter = LiveSynaptAdapter(settings)
    external = tool()
    external.inputSchema["properties"]["query"] = {"$ref": "https://untrusted/schema"}
    with pytest.raises(SynaptError, match="external reference"):
        adapter._validate_arguments(external, {"provider_id": "provider-1", "query": "evidence"})


def test_empty_live_retrieval_does_not_switch_to_fixtures(monkeypatch, settings, claim):
    adapter = LiveSynaptAdapter(settings)
    stub_session(monkeypatch, adapter, [tool()], result([]))
    bundle = adapter.retrieve(claim)
    assert bundle.mode == "live" and bundle.evidence == []
    assert bundle.warnings


def test_tool_error_does_not_expose_secret_server_text(monkeypatch, settings, claim):
    adapter = LiveSynaptAdapter(settings)
    stub_session(
        monkeypatch,
        adapter,
        [tool()],
        CallToolResult(
            isError=True,
            content=[TextContent(type="text", text="very-secret-password private-token")],
        ),
    )
    with pytest.raises(SynaptError) as exc:
        adapter.retrieve(claim)
    assert "secret" not in str(exc.value) and "private-token" not in str(exc.value)


def test_enrichment_is_off_by_default_so_no_uncitable_calls_or_standing_warning(
    monkeypatch, settings, claim
):
    adapter = LiveSynaptAdapter(settings)
    calls = stub_session(
        monkeypatch,
        adapter,
        [tool(), tool("trident_get_procedures"), tool("trident_search")],
        {"trident_get_chunks": result([{"source_id": "doc", "text": "Policy excerpt"}])},
    )
    bundle = adapter.retrieve(claim)
    assert {name for name, _ in calls} == {"trident_get_chunks"}
    assert not any("Optional Synapt" in warning for warning in bundle.warnings)


def test_retrieval_enriches_chunks_with_procedures_and_graph(monkeypatch, settings, claim):
    adapter = LiveSynaptAdapter(settings.model_copy(update={"synapt_graph_enrichment": True}))
    calls = stub_session(
        monkeypatch,
        adapter,
        [tool(), tool("trident_get_procedures"), tool("trident_search"), tool("trident_query")],
        {
            "trident_get_chunks": result([{"source_id": "doc", "text": "Policy excerpt"}]),
            "trident_get_procedures": CallToolResult(
                content=[],
                structuredContent={
                    "procedures": [
                        {
                            "document_id": "procedure-document",
                            "steps": [
                                "Request incident statement",
                                {"text": "Request repair estimate"},
                            ],
                            "title": "Handling procedure",
                        },
                    ]
                },
            ),
            "trident_search": result([{"source_id": "graph-doc", "text": "Related endorsement"}]),
        },
    )
    bundle = adapter.retrieve(claim)
    assert {e.source_id for e in bundle.evidence} == {"doc", "procedure-document", "graph-doc"}
    assert "Request repair estimate" in bundle.evidence[1].text
    assert {name for name, _ in calls} == {
        "trident_get_chunks",
        "trident_get_procedures",
        "trident_search",
    }
    assert bundle.warnings == [
        "No ingested historical claim cards matched; semantic ranking was not applied."
    ]


def test_optional_unsourced_graph_cannot_become_evidence(monkeypatch, settings, claim):
    adapter = LiveSynaptAdapter(settings.model_copy(update={"synapt_graph_enrichment": True}))
    stub_session(
        monkeypatch,
        adapter,
        [tool(), tool("trident_search")],
        {
            "trident_get_chunks": result([{"source_id": "doc", "text": "Policy excerpt"}]),
            "trident_search": CallToolResult(
                content=[],
                structuredContent={
                    "nodes": [
                        {
                            "id": "node",
                            "description": "Generated graph fact without document provenance",
                        },
                    ]
                },
            ),
        },
    )
    bundle = adapter.retrieve(claim)
    assert [e.source_id for e in bundle.evidence] == ["doc"]
    assert any("response lacks supported provenance" in w for w in bundle.warnings)


def test_ingestion_uses_advertised_snake_case_and_connector(monkeypatch, settings):
    adapter = LiveSynaptAdapter(settings)
    ingest = tool(
        "trident_ingest",
        content={"type": "string"},
        filename={"type": "string"},
        extraction_mode={"type": "string", "enum": ["balanced"]},
        connector_type={"type": "string", "enum": ["content"]},
    )
    del ingest.inputSchema["properties"]["query"]
    ingest.inputSchema["required"] = [
        "provider_id",
        "content",
        "filename",
        "extraction_mode",
        "connector_type",
    ]
    calls = stub_session(
        monkeypatch,
        adapter,
        [ingest],
        CallToolResult(content=[], structuredContent={"req_id": "request-1"}),
    )
    response = asyncio.run(adapter.ingest("Document content", "claims.txt"))
    assert response["completion_verified"] is False
    assert calls[0][1]["extraction_mode"] == "balanced"
    assert calls[0][1]["connector_type"] == "content"
    assert "extractionmode" not in calls[0][1]
    assert "document_type" not in calls[0][1]


def test_query_only_runs_when_no_source_evidence_available(monkeypatch, settings, claim):
    adapter = LiveSynaptAdapter(settings)
    calls = stub_session(
        monkeypatch,
        adapter,
        [tool(), tool("trident_query")],
        {
            "trident_get_chunks": result([]),
            "trident_query": result([{"source_id": "query-doc", "text": "Sourced passage"}]),
        },
    )
    bundle = adapter.retrieve(claim)
    assert bundle.evidence[0].source_id == "query-doc"
    assert [name for name, _ in calls] == [
        "trident_get_chunks",
        "trident_query",
        "trident_get_chunks",  # claim-card query for semantic matching
    ]


def test_claim_cards_rank_similar_cases_but_are_never_cited_evidence(monkeypatch, settings, claim):
    adapter = LiveSynaptAdapter(settings)
    card = "claim_ref: claimref_aaaaaaaabc\nauto claim in region regionkey_ac. Amount band 5,000-10,000"
    other = "claim_ref: claimref_aaaaaaaade\nauto claim in region regionkey_ag."
    lesson = "handler_lesson_ref: LESSON-1\nhandler_note: ask for the police report"
    sop = "For an auto claim request an incident statement and repair estimate."
    stub_session(
        monkeypatch,
        adapter,
        [tool()],
        result(
            [
                {"chunk_id": "chunk-card", "text": card + "\n" + other},
                {"chunk_id": "chunk-lesson", "text": lesson},
                {"chunk_id": "chunk-sop", "text": sop},
            ]
        ),
    )
    bundle = adapter.retrieve(claim)
    # Cards -> semantic ranking in order of appearance (aliases decode to dataset claim IDs).
    assert bundle.semantic_claim_ids == ["CLM-0000000012", "CLM-0000000034"]
    # Cards and lessons are not cited as sources; the procedure passage is.
    assert [e.source_id for e in bundle.evidence] == ["chunk-sop"]
    assert not any("claim_ref" in w for w in bundle.warnings)


def test_beta_result_wrapper_preserves_chunk_identity(settings):
    import json

    adapter = LiveSynaptAdapter(settings)
    evidence = adapter._normalize(
        CallToolResult(
            content=[],
            structuredContent={
                "result": json.dumps(
                    [
                        {
                            "chunk_id": "chunk-real",
                            "source_file": "uploaded-sop.txt",
                            "text": "Source passage",
                        }
                    ]
                )
            },
        )
    )
    assert evidence[0].source_id == "chunk-real"
    assert evidence[0].title == "uploaded-sop.txt"
    assert evidence[0].provider_id == "provider-1"
    assert evidence[0].provenance == "synapt"


@pytest.mark.parametrize(
    "payload",
    [
        {"result": "not JSON"},
        {"result": [{"chunk_id": "chunk", "text": "passage"}]},
        {"provider_id": "foreign", "result": "[]"},
        {"result": '[{"name":"Extracted procedure","steps":[{"description":"Request evidence"}]}]'},
    ],
)
def test_beta_wrapper_never_invents_sources(settings, payload):
    with pytest.raises(SynaptError):
        LiveSynaptAdapter(settings)._normalize(
            CallToolResult(content=[], structuredContent=payload)
        )


def test_runtime_verification_requires_evidence_and_resets(monkeypatch, settings, claim):
    adapter = LiveSynaptAdapter(settings)
    assert not adapter.live_verified
    stub_session(monkeypatch, adapter, [tool()], result([{"chunk_id": "chunk", "text": "Passage"}]))
    adapter.retrieve(claim)
    assert adapter.live_verified
    stub_session(monkeypatch, adapter, [tool()], result([]))
    adapter.retrieve(claim)
    assert not adapter.live_verified
    stub_session(monkeypatch, adapter, [tool()], CallToolResult(content=[], isError=True))
    with pytest.raises(SynaptError):
        adapter.retrieve(claim)
    assert not adapter.live_verified


def status_error(code, **headers):
    request = httpx.Request("POST", "https://beta.example/auth")
    response = httpx.Response(code, headers=headers, request=request)
    return httpx.HTTPStatusError("rejected", request=request, response=response)


def test_one_login_serves_many_calls_until_the_token_expires(monkeypatch, settings):
    adapter = LiveSynaptAdapter(settings)
    logins = []

    async def auth():
        logins.append(1)
        adapter._token_lifetime = 3600
        return f"token-{len(logins)}"

    monkeypatch.setattr(adapter, "_authenticate", auth)

    async def run():
        return [await adapter._bearer() for _ in range(5)]

    assert asyncio.run(run()) == ["token-1"] * 5 and len(logins) == 1
    adapter._token = ("token-1", 0.0)  # expired long ago
    assert asyncio.run(adapter._bearer()) == "token-2" and len(logins) == 2


def test_token_lifetime_uses_the_servers_value_with_a_safety_margin(monkeypatch, settings):
    import time

    adapter = LiveSynaptAdapter(settings)

    async def auth():
        adapter._token_lifetime = 100
        return "token"

    monkeypatch.setattr(adapter, "_authenticate", auth)
    asyncio.run(adapter._bearer())
    assert 38 < adapter._token[1] - time.monotonic() <= 40  # 100 s minus a 60 s margin

    async def unstated():
        adapter._token_lifetime = None
        return "token"

    adapter._token = None
    monkeypatch.setattr(adapter, "_authenticate", unstated)
    asyncio.run(adapter._bearer())
    assert 200 < adapter._token[1] - time.monotonic() <= 240  # short default when unstated


def test_authentication_records_the_servers_stated_lifetime(settings):
    adapter = LiveSynaptAdapter(settings)

    def handler(request):
        return httpx.Response(
            200, json={"access_token": "opaque", "token_type": "Bearer", "expires_in": 1800}
        )

    real = httpx.AsyncClient
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "claims.adapters.httpx.AsyncClient",
            lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
        )
        assert asyncio.run(adapter._authenticate()) == "opaque"
    assert adapter._token_lifetime == 1800


def test_a_rejected_token_is_dropped_and_retried_once(settings):
    adapter = LiveSynaptAdapter(settings)
    adapter._token = ("stale", 10**12)
    calls = []

    async def operation():
        calls.append(adapter._token)
        if len(calls) == 1:
            raise status_error(401)
        return "ok"

    assert asyncio.run(adapter._retry(operation)) == "ok"
    assert calls[0] is not None and calls[1] is None  # cache cleared before the retry


def test_rate_limited_logins_wait_as_the_server_asks(monkeypatch, settings):
    adapter = LiveSynaptAdapter(settings)
    delays, outcomes = [], iter([status_error(429, **{"Retry-After": "7"}), status_error(429), None])

    async def fake_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr("claims.adapters.asyncio.sleep", fake_sleep)

    async def operation():
        failure = next(outcomes)
        if failure:
            raise failure
        return "ok"

    assert asyncio.run(adapter._retry(operation, attempts=3)) == "ok"
    assert delays == [7.0, 4.0]  # honours Retry-After, then backs off exponentially


@pytest.mark.parametrize("code", [400, 403, 404])
def test_other_client_errors_are_not_retried(settings, code):
    adapter = LiveSynaptAdapter(settings)
    attempts = []

    async def operation():
        attempts.append(1)
        raise status_error(code)

    with pytest.raises(SynaptError):
        asyncio.run(adapter._retry(operation))
    assert len(attempts) == 1
