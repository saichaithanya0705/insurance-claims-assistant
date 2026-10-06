# Synapt integration contract and verification gate

This integration is implemented against the official Python MCP SDK 1.x Streamable HTTP
transport. Authentication, tool discovery, original chunk retrieval, statistics, schema and
explicit two-hop graph traversal were verified against `synapt_final_capstone` on 2026-10-06.
The provider contained six documents/chunks; seven live synthetic application scenarios passed
functional checks. See [LIVE_PROJECT_EVALUATION.md](LIVE_PROJECT_EVALUATION.md) for remaining
identity, graph provenance and semantic-quality limitations.

## What was implemented and why

`FixtureSynaptAdapter.retrieve(ClaimInput)` returns fixed synthetic handling procedures,
explicitly labeled `synthetic_fixture`. These are application test fixtures, not policies,
historical claim records, or statements about a submitted incident.

`LiveSynaptAdapter.retrieve(ClaimInput)` uses a synchronous bridge to
`retrieve_async(ClaimInput)`. Async callers must await `retrieve_async`; the sync method
rejects an already running event loop. `build_synapt_adapter(Settings)` selects one mode.
Live mode never falls back to synthetic fixtures, including when retrieval fails or is empty.

The adapter authenticates, initializes an MCP session, discovers tools with bounded
pagination, validates provider scope and schemas, and accepts evidence only with source
identifiers and text. Only transient read failures receive up to three attempts. Credentials,
tokens and raw server errors are excluded from public exception messages. HTTP redirects
are disabled for authentication and MCP transport. Temporary HTTP/MCP sessions close after
each operation. Application logging records event names, retry number and evidence counts;
do not enable raw MCP/HTTP debug logging with credentials or claim data.

This boundary avoids treating natural language as tool arguments, prevents mutation during
retrieval, and keeps retrieval failures visible. Silent fallback was rejected because it could
make a fixture demonstration appear to be a verified Synapt integration. A tenant-specific
schema adapter is a valid future pattern once real `tools/list` responses are available.

## Verified beta contract and remaining assumptions

1. The beta `SYNAPT_AUTH_BASE` accepts JSON `{email, password}`. Set
   `SYNAPT_AUTH_USERNAME_FIELD=email`; `SYNAPT_USERNAME` holds the login email.
   Other tenants may explicitly select `username` or form encoding; neither is automatically guessed.
   Authentication returns `access_token` and optionally `token_type` equal to `bearer`.
   No cookies, guessed alternate fields or automatic authentication fallback are used.
2. `SYNAPT_MCP_URL` accepts Streamable HTTP and an `Authorization: Bearer` header.
3. A retrieval tool named `trident_get_chunks`, `trident_search` or `trident_query`
   accepts explicit string `provider_id` and `query`. Optional integer fields `top_k`
   and `graph_hops` are sent only if its discovered schema declares them. Primary selection
   is in that order; a returned malformed primary response fails rather than silently trying
   another tool. After primary passages, supported `trident_get_procedures` and
   `trident_search` can enrich context. Procedures may advertise only provider scope;
   query is supplied when declared. Unknown required parameters make an optional tool
   unsupported and produce a visible warning. Query generation is only additionally called
   if no source evidence is available, preventing redundant generated answers.
4. The verified beta chunk response is `{result: "<JSON array>"}` with `chunk_id`, `text`,
   `source_file` and `doc_type`. Decode exactly one bounded wrapper layer, rejecting foreign
   outer or inner provider identifiers. A compatible retrieval response is also a list of chunk
   objects or `{chunks: [...]}`, either
   structured MCP content or one JSON text block. Each chunk has `source_id`, `document_id`
   or `chunk_id`, plus `text` or `content`; `title` is optional. An explicit foreign
   `provider_id` is rejected. Other node/answer/source shapes remain unsupported until verified.
   Source identifiers prove traceability within the response contract, not factual correctness.
   Procedure responses may use `{procedures: [...]}` with the same source identifier fields
   and direct text/content or ordered `steps` containing strings/text objects. Steps retain
   their document source; procedure IDs alone do not establish evidence provenance.
   Unsupported optional graph/procedure response shapes produce warnings and cannot become
   cited evidence. Identical source/text entries are deduplicated across retrieval tools.
5. The server enforces the requested provider scope. Chunks without a provider field inherit
   the requested provider identifier; this assumption must be checked with known documents.
6. Tool schemas do not require unknown parameters. Unknown fields and external JSON-schema
   references are rejected; arguments are validated against discovered schemas.

`await discover()` returns allowlisted tool names, compatible retrieval tool names,
redacted schemas, the configured provider ID and `retrieval_contract_verified: false`.
Discovery alone establishes neither successful retrieval nor provenance quality.

## Explicit tool interfaces

- `await call_read_tool(name: str, arguments: dict) -> dict`: only discovered tools from
  `trident_get_chunks`, `trident_get_procedures`, `trident_search`, `trident_traverse`,
  `trident_get_schema`, `trident_get_stats`, `trident_query`, `trident_episodes` are allowed.
  The caller must pass the configured `provider_id`. A structured response object is required.
  This lower-level method returns data for callers to validate, not approved evidence findings.
- `await ingest(content: str, filename: str, document_type: str = "text") -> dict`:
  explicitly invokes `trident_ingest` once. Discovered fields must include `provider_id` and
  `content`, and exactly one of `extraction_mode` or `extractionmode`, set to `"balanced"`.
  `filename`, `document_type="text"` and `connector_type="content"` are included only when
  the advertised schema declares them. Full schema validation rejects unknown required
  fields, incompatible enums or other unsupported contracts before submission.
  A valid `req_id` returns `status="submitted"` and `completion_verified=false`.
  If the tenant uses other field names, integration must be updated after discovery.
- `await feedback(query_id: str, rating: str, reason: str) -> dict`: explicit reviewed feedback
  only. The initial contract requires exact fields `provider_id`, `query_id`, `rating`, `reason`
  on `trident_feedback`. Ratings must conform to the discovered schema; no rating vocabulary
  is guessed. Caller must associate the actual server query identifier with a reviewed result.

Ingestion and feedback never run as part of retrieval and never automatically retry.
A timeout may occur after a remote write; inspect remote state before resubmitting.
Provider creation is outside this module. No permissions are bypassed. Configured credentials
were used server-side for the authorized live tests and remain excluded from reports.

The current beta `trident_query` takes `question`, rather than the generic `query` contract;
normal retrieval uses `trident_get_chunks` and does not consume generated query answers as evidence.
`trident_get_procedures` returns names/intents/steps without source IDs, and `trident_search`
returns node IDs without original source passages. These optional responses remain excluded
from cited evidence with visible warnings. Explicit `trident_traverse` at depth 2 returned
source-linked chunks and document relationships, but that probe is not automatically integrated
into the application retrieval path. `SYNAPT_GRAPH_HOPS` is sent only where advertised; chunks
has no hops argument. Runtime `live_verified` means the last retrieval in that process produced
validated source-bearing passages, resets on errors/empty results, and is not an accuracy score.

The beta feedback schema is `feedback_id`, `caller_type`, `verdict` (and optional metadata),
which differs from the explicit initial feedback adapter. It therefore fails closed; local
handler feedback works and no remote feedback writes were attempted. Ingestion submission
contract/completion through MCP remains untested; the corpus was uploaded through the console.

## Live acceptance checks after access is granted

1. Add credentials and the authorized provider ID to an ignored local `.env`.
2. Run discovery; compare authentication, exact argument schemas and transport with assumptions.
3. With explicit authorized onboarding, submit one labeled synthetic document. Preserve its
   `req_id`; poll the verified task/status interface if available, then confirm extraction in
   the console. Submission alone is not completion.
4. Retrieve an exact known passage and verify its source, provider and graph provenance.
5. Test denied provider access, expired authentication, empty results and malformed outputs.
   None may produce synthetic evidence or a successful live status.
6. Verify procedures, graph traversal and episodic retrieval independently. Do not label hybrid
   search, extraction quality or end-to-end live integration as passed until observed.

## Validation evidence

Targeted tests cover mocked authentication encodings, Bearer headers, no redirects, provider
boundaries, schema checks, error sanitization, read retry limits, explicit ingestion, no write
retries, malformed evidence, source requirements and no live-to-fixture fallback. They validate
application contracts, not Synapt permissions, authentication or service behavior.

Official SDK reference used:
https://github.com/modelcontextprotocol/python-sdk/blob/v1.20.0/src/mcp/client/streamable_http.py

## Console and corpus status — 2026-10-06

The console now displays CP Admin. A provider creation attempt returned
`Field required; Field required`; Knowledge Pack listing separately returned 403.
No provider or ingestion was independently verified in that browser attempt. The user subsequently
reported creating `synapt_final_capstone`, uploading two pilot documents and provided two query
outputs. Both match the source content, but the claim answer denies finding the direct claim ID,
both warn about incomplete/low-confidence graph data, and no source citations are shown in the pasted
answers. These are partial retrieval signals, not a passed identity/provenance/graph acceptance check.
The new provider ID is configured in `.env` and `.env.example`; the settings loader confirms it.
Synapt mode remains fixture and local login fields are empty, so application MCP access is unverified.

Subsequent [direct browser tests](SYNAPT_BROWSER_TESTS.md) submitted four fresh Query Agent chats
to synapt_final_capstone. SOP content/source passage and two missing-information checks passed
in those runs. Known-claim identity remained contradictory; the displayed assembled context masked
numeric identifiers as PHONE/US_SSN and provenance listed the historical document as unknown.
Visible Procedure/Step candidates establish some graph extraction, not a verified MCP procedure
contract. These browser observations do not establish the application's live transport/parsing.

After the additional four SOP uploads, [six more browser queries](SYNAPT_SOP_TESTS.md)
validated all four individual procedures and a targeted cross-procedure answer. A general
mixed query omitted a named review citation, and Doc ID metadata varied across queries for
the same chunks. Five answers retained the graph warning, one did not. Historical identifiers
remain masked in displayed chunks; live MCP authentication and parsing are still unverified.

The [upload guide](SYNAPT_UPLOAD_GUIDE.md) records screenshots, reproducible corpus commands,
pilot probes and expansion instructions. Local pilot: ten attributed historical cards plus
five synthetic procedures; complete eligible sample: 2,163 cards in 38 bounded batches.
QA expectations are kept outside upload folders. Local validation: nine corpus/pack tests
passed and Ruff passed; remote extraction, graph, procedure and retrieval checks remain open.
