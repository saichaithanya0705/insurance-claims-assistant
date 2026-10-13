# Claim-card expansion and provider audit — 7 October 2026

> Note (13 October 2026): the application stopped using the provider described here on 9 October, and since 13 October it keeps no claim cards in Synapt at all; past claims are now in Synapt's ticket store. See [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md#how-the-data-is-split-across-synapt-corrected-13-october-2026).

## What I did

Read the supplied insurance-assistant PDF, `PROJECT_PLAN.md`, the completed architecture and panel
presentation. The approved design uses recorded claim facts and keeps missing narratives and policy
wording explicit. Inspected the configured `synapt_final_capstone` provider through its existing
StreamableHTTP MCP adapter; no new provider or credentials were created.

Built **19,887 new historical claim cards**, paired native ZSTD Parquet and 40 text batches, from the
existing full 100-million-row Parquet. The source has 13 recorded fields; the export adds deterministic
retrieval descriptors, source/license provenance and explicit missing-content flags. It does not
invent narratives, policy terms or fraud outcomes. Policy identifiers and the target fraud flag are
excluded from the retrieval export. Text uses opaque claim references that survive PII masking.

| Artifact | Measured result |
|---|---|
| `artifacts/synapt/corpus-2026-10-07/claim_cards.parquet` | 19,887 rows; 1,049,800 bytes |
| Distinct claim IDs and distinct opaque references | 19,887 each; zero internal duplicates |
| Overlap with the original 1,000-card manifest | Zero |
| Overlap with the initial 903 readable MCP claim IDs | Zero; this was a partial live inventory |
| Claim-type/state coverage | All five types × 40 states; 200 cells with 67–100 cards each |
| Types | Auto 4,000; business 3,894; home 4,000; property 3,998; renters 3,995 |
| Other coverage | Nine amount bands; four prior-claim bands; only 178 many-prior cases |
| Text batches | `cards/expanded-0001.txt` through `expanded-0040.txt`; 500 each, final 387 |

Parquet SHA256: `f62b211ddcf81791344953f69c764436a44c1ed98197a67906350501caf69377`.
DuckDB rereading verifies every exported ID/reference/card-text round trip against the manifest.
The user-uploaded first export is preserved unchanged.

## Provider observations and current state

Initially the provider had **22 documents / 1,025 chunks**, including ten original 100-card documents,
procedures and other evidence. The user's Parquet upload added **one structured schema chunk** with
21 columns: **23 documents / 1,026 chunks**. This did not make 19,887 individual records searchable.
The provider reports `provider_kind=knowledge` and `has_ticket_store=false`; ticket-mode queries
therefore cannot supply structured claim predictions.

The first text pilot added **500 actual claim-card chunks**. All 500 expected IDs and three sentinels
were independently retrieved through MCP, and document graph counts confirmed 500 linked chunks.
Extraction took about nine minutes. The provider then had **24 documents / 1,526 chunks**.

At 19:32 UTC (01:02 IST), MCP counts increased to **26 documents / 2,526 chunks**: 1,500 newly
indexed card chunks including the pilot. The authenticated browser history confirms card batches
are progressing through parse/chunk/knowledge/completed stages, with one job per new batch. Full
500-ID verification remains established for the pilot only; query-dependent partial inventories
must not be mistaken for complete verification of the later batches.

**All 40 batches, totaling 19,887 new cards, have now been submitted through MCP. Only the first 500
are verified searchable so far.** Batch 21 received an explicit provider rejection and was retried
once after preserving and classifying that acknowledgement; its retry was accepted. Other accepted
batches were not resubmitted. Asynchronous provider extraction remains unverified for the other
19,387 cards. See `upload-ledger.jsonl`, `final-provider-stats.json` and `reconciliation.json` for the
latest local evidence. Query-dependent retrieval is partial: absence from a returned list is not
proof that a card was never ingested. Do not upload the same text batches from the browser as well.

**Update, later on 2026-10-07: extraction is complete and verified.** Statements above about pending or
unverified extraction record the moment they were written and are superseded. Synapt's graph shows 40
documents of the expected sizes (38 × 500, 1 × 501 and 1 × 387 chunks for 19,887 cards), each identified
by its batch marker and matching its local batch's text length; the provider holds 63 documents and
20,914 chunks. Extraction was genuinely still running when this report was first written (2,526 chunks
then); it has since finished. The retrieval method could not have confirmed it either way: reads are
capped at about 1,900 chunks, so a retrieval inventory cannot confirm the later batches.
Details and the check are in [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md).

Uploads set `has_ttl=false` when supported, rather than silently using the server's 30-day expiry.
The ledger records provider, immutable file hash and write-start before side effects. Unknown or
interrupted responses are reconciled without automatic retry. Verification requires the actual
expected card IDs, rather than document-count growth alone.

## What was the issue / root cause

The source already contains ample tabular data, but only a small fraction was represented as
retrievable cards. CSV/Parquet file ingestion into this knowledge provider extracts schema rather
than automatically creating one semantic card per record. More synthetic prose cannot add missing
incident evidence, policy wording or genuine adjudication labels. Treating submission as successful
extraction would also overstate the corpus and risk duplicate browser uploads.

## Why this approach

Stratified selection covers claim types and states instead of adding mostly common auto claims.
Known IDs are excluded before export. Repeatable, bounded reservoir candidates avoid a large
100-million-row sort; the immutable manifest records the exact exported cohort. DuckDB writes native
Parquet without a new heavy dependency. Text batches directly match the proven MCP content contract.
Explicit response budgets and provider-scoped read guards support audits without relaxing normal
application limits or allowing graph mutations.

## Why not the alternative

Blindly uploading the same Parquet repeatedly would repeat schema ingestion. Copying raw CSV fields
into invented claim stories would introduce unsupported facts. Uploading all 100 million cards would
consume resources without first proving retrieval quality. Automatic retries after a transport
failure could duplicate an already accepted document.

## Why this works best

The paired artifacts retain a columnar dataset for analysis and factual text for Synapt retrieval.
Independent round-trip and ID checks establish uniqueness within the export and against known prior
cards; they do not establish uniqueness against inaccessible or still-processing external uploads.
The pilot proves the end-to-end text extraction path. Readiness now reports verified card counts
separately from submission and remains pending until extraction is confirmed.

## Other valid patterns and remaining limits

A structured database/ticket connector could expose records directly, but would require a different
provider contract and separate validation. Smaller targeted card cohorts can improve rare-case
coverage at lower ingestion cost. More independent procedures, policy documents and labeled incident
narratives would add information these 13 fields lack; authored examples must remain marked synthetic.
The current expansion improves broad coverage, but does not prove sufficient joint-cohort coverage,
retrieval quality, real-world accuracy or policy-grounded decisions. Card expansion and ML sampling
are separate: the [ML report](ML_RETRAINING_2026-10-07.md) uses 600,000 original source rows and honest
global/feature-aware comparisons. [Evaluation results](EVAL_AUDIT_2026-10-07.md) retain real quality
failures instead of changing thresholds to manufacture a pass.

## Inspect and continue safely

```powershell
uv run python scripts/verify_synapt_store.py
uv run python scripts/ingest_expanded_cards.py --verify-only
uv run python scripts/audit_synapt_data.py
uv run python scripts/inspect_synapt_graph.py
uv run python scripts/bootstrap.py check
```

All inspection commands make no provider writes. The two verification commands read Synapt's graph and are exact;
the ledger preserves prior successful verification. The normal uploader reconciles each tracked
batch using its marker and complete expected ID set before continuing, and never repeats an uncertain
write. Use a new empty output directory for any additional expansion so existing upload hashes remain
valid. The earlier presentation remains a dated snapshot of the 1,000-card / 200,000-row build; these
refresh reports record the newer measured state.

## Integration and validation

The bounded ML and evaluation agents returned their owned code, tests and dated reports. Main
reviewed calibration/holdout boundaries, model artifact loading, evaluator contracts and document
receipt guards, then integrated them. Both delegated tasks are closed and their temporary processes
exited. Main retains final integration and provider-verification responsibility.

The full backend suite passed **223 tests**; seven additional uploader safety checks passed, including
unknown-write resumption, read-only reconciliation, explicit rejected-write retry and cross-provider
ledger refusal. The final focused card/uploader run passed **17 tests**, Ruff passed, and Git's diff
whitespace check passed after normalizing the generated HTML line endings. Frontend tests passed
**16**, its TypeScript/Vite build succeeded, and frontend lint had zero errors with 14 existing warnings.
The rebuilt quality view distinguishes completed judge calls from actual quality passes. This is
build/test validation, not an authenticated browser walkthrough of the quality page.

The existing local API was restarted on port 8000 after validation to load the new backend and model
artifact; the root page returned HTTP 200. Independent loading confirms all three models are available
with a 600,000-row origin. The application service is intentionally left running, while temporary
audit/training/upload workers are closed. The provider's remaining asynchronous extraction is an
external pending step; readiness intentionally reports it instead of claiming a complete corpus.
