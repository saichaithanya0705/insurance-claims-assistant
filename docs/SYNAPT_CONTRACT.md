# Synapt integration contract and verification gate

This integration is implemented against the official Python MCP SDK 1.x Streamable HTTP
transport. Authentication, tool discovery, original chunk retrieval, statistics, schema and
explicit two-hop graph traversal were verified against `synapt_final_capstone` on 2026-10-06.
The provider contained six documents/chunks; seven live synthetic application scenarios passed
functional checks. See [LIVE_PROJECT_EVALUATION.md](LIVE_PROJECT_EVALUATION.md) for remaining
identity, graph provenance and semantic-quality limitations.

## What was implemented and why

There is no fixture adapter. An early version had one (fixed procedures labelled `synthetic_fixture`);
it was removed because Synapt is required and no setting or fallback may stand in for it. The unit tests
use a test double that lives only under `tests/` and cannot be selected by configuration.

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
  `trident_get_schema`, `trident_get_stats`, `trident_get_node`, `trident_find_exact`, `trident_cypher`,
  `trident_query`, `trident_episodes` are allowed (`READ_ONLY_TOOLS` in `claims.synapt.adapter`).
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
- `await send_feedback_async(feedback_id, verdict, caller_type="user", post_action=None, reason=None) -> dict`: a handler's
  explicit verdict on an answer Synapt's query agent wrote. The tenant's `trident_feedback` schema (12 October 2026) is
  `feedback_id`, `caller_type` (`user`, `agent`, `mcp_tool`), `verdict` (`deflected`, `partial`, `not_deflected`), `post_action`
  (`proceeded`, `retried`, `fallback`, `escalated`, `failed`), `score` and `reason`, and has **no provider field**, so the
  provider-scoping check cannot apply: only a query ID that Synapt returned for this application's own query is sent, and
  every argument is validated against the discovered schema. Synapt answers `{"accepted": true, "status": "received"}`; any
  other answer is an error. Single attempt, never retried.

Ingestion and feedback never run as part of retrieval and never automatically retry.
A timeout may occur after a remote write; inspect remote state before resubmitting.
Provider creation is outside this module. No permissions are bypassed. Configured credentials
were used server-side for the authorized live tests and remain excluded from reports.

The current beta `trident_query` takes `question`, rather than the generic `query` contract;
normal retrieval uses `trident_get_chunks` and does not consume generated query answers as evidence.
Since 13 October 2026 similar past claims come from the provider's ticket store through `trident_query` with
`ticket_mode="only"` (see "Update, 2026-10-13" below); that call returns no generated answer.
`trident_get_procedures` returns names/intents/steps without source IDs, and `trident_search`
returns node IDs without original source passages. These optional responses remain excluded
from cited evidence with visible warnings. Explicit `trident_traverse` at depth 2 returned
source-linked chunks and document relationships, but that probe is not automatically integrated
into the application retrieval path. `SYNAPT_GRAPH_HOPS` is sent only where advertised; chunks
has no hops argument. Runtime `live_verified` means the last retrieval in that process produced
validated source-bearing passages, resets on errors/empty results, and is not an accuracy score.

The beta feedback schema is `feedback_id`, `caller_type`, `verdict` (and optional metadata),
which differs from the explicit initial feedback adapter. It therefore fails closed; local
handler feedback works and no remote feedback writes were attempted. (Superseded on 12 October 2026: the adapter now
sends that schema, see `send_feedback_async` above.) Ingestion submission
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

The earlier upload guide (removed; superseded by [SETUP.md](SETUP.md) and [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md)) recorded screenshots, corpus commands,
pilot probes and expansion instructions. Local pilot: ten attributed historical cards plus
five synthetic procedures; complete eligible sample: 2,163 cards in 38 bounded batches.
QA expectations are kept outside upload folders. Local validation: nine corpus/pack tests
passed and Ruff passed; remote extraction, graph, procedure and retrieval checks remain open.


## Update, 2026-10-06 (full-dataset work)

* **Ingestion response.** `trident_ingest` returns `accepted`, `connector_type` and `response`; there is
  no `req_id`. The adapter accepts a response without an `error` as "submitted" with `req_id: null`
  and the caller verifies completion from `trident_get_stats` (document count rising).
* **Chunking.** `chunk_size` and `chunk_overlap` are advertised and are measured in **tokens**; each is sent
  only if the tool schema declares it.
* **Authentication.** The access token is cached and reused (`expires_in` when stated, otherwise 4 minutes),
  re-obtained on a 401, and HTTP 429 waits for `Retry-After`. Writes use a 180-second budget.
* **Optional graph tools** (`trident_get_procedures`, `trident_search`) are off by default
  (`SYNAPT_GRAPH_ENRICHMENT`); they return no source passages and cannot be cited.
* **Masking.** Identifiers and place names are rewritten before indexing; see
  [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md) for the formats that survive.

## Update, 2026-10-13 (procedures as documents, past claims as tickets)

The provider `synapt_capstone1` now holds the 17 procedures as documents and 2,000 settled past claims in its ticket store
(kind `ticket_mining`, `has_ticket_store: true`); the claim-card documents were deleted. See
[SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md) ("How the data is split across Synapt").

* **Similar past claims.** One `trident_query` call per retrieval with `provider_id`, a fixed `question` ("Past claims like
  this one", not embedded in this mode), `ticket_mode="only"` and `tickets` holding one ticket: `title`, `description`,
  `category`, `region`, built by `claims.corpus.cards.claim_ticket` (masking-safe, no outcome). Arguments are validated
  against the discovered schema. In `only` mode Synapt embeds no question, walks no graph and calls no model.
* **Permission.** The call is authorised as `trident_ticket_neighbours`, a separate entry on the Policy Passage Retriever's
  tool list, so that agent can search tickets without being able to ask the query agent a question.
* **Response.** A `provider_id` other than the configured one is rejected. From the first `ticket_labels` item, every label
  value's `example` neighbour whose `ticket_id` is a claim alias (`claimref_...`) is kept, ordered by its `score`, decoded to
  a claim ID and de-duplicated; one example per label value gives 2 to 4 claims. Labels and confidences are ignored. An
  empty or skipped ticket store (`stores_skipped.ticket`) or a failed call leaves a warning and no semantic rank; the claims
  are always read from the Parquet file under the handler's filters.
* **Episodic chunks.** A passage with `doc_type: "episodic"` (Synapt's episode memory, `es_<provider>`) is dropped from
  evidence: it records an earlier query session, not policy.
* **Verification.** `scripts/verify_synapt_store.py` checks the 17 procedures by source ID, the ticket store from
  `trident_get_stats` (2,000 tickets, ID field `ticket_id`, label fields `fraud_flag` and `resolution`) and that no
  document of more than 100 chunks, other than Synapt's episodic document (`es_...`), is left.
