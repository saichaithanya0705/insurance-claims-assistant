# Synapt pilot upload and verification

Prepared 2026-10-06. The user reports uploading `sop-auto-001.txt` and
`claim-CLM-0000000012.txt` into **`synapt_final_capstone`** and supplied two query outputs.
The local `.env` and credential-free `.env.example` now use that provider ID.
Upload completion/source attribution have not been independently verified through the console or MCP.
Generated manifests describe preparation-time status, not a live ingestion ledger.

After four additional user uploads, [direct SOP browser tests](SYNAPT_SOP_TESTS.md) confirm
all five SOPs are retrievable, and the provider graph displays six documents including the
historical record. The four new individual content checks passed; general mixed retrieval,
query-dependent document links and historical numeric-ID handling remain unresolved.

## Initial user-reported query results

Subsequent direct browser verification is recorded in [SYNAPT_BROWSER_TESTS.md](SYNAPT_BROWSER_TESTS.md).
Four fresh-chat tests confirm SOP retrieval and two missing-information checks, but known-claim
identity remains inconsistent. The displayed ledger masks numeric claim/policy IDs and lists the
historical chunk's document as unknown. Hold expansion until identity and source linkage pass.

| Probe | Source comparison | Remaining issue |
| --- | --- | --- |
| Claim CLM-0000000012 | Amount 18302.01, deductible 1500.0 and policy POL-100297760 exactly match the uploaded source | Answer says no direct record for the requested claim ID; no source citation is shown in the pasted answer |
| SOP-AUTO-001 | Incident statement, repair estimate and police report when applicable match the source | Pasted answer has no source citation; procedure-store extraction is unverified |

Both outputs warn that graph data is low-confidence or incompletely connected.
Verdict: **content matches; claim identity, source attribution and graph linkage are not passed**.
The current Policy-only scope does not constitute a Claim-to-Policy schema; this is a possible
limitation, not a verified cause of the warnings. No policy wording or coverage conclusion was tested.

Next ask: `Show the exact source passage containing claim_id: CLM-0000000012 and
policy_id: POL-100297760, with its source document identifier.` Require that both appear
in attributable evidence, rather than accepting matching values from an unidentified record.
Also ask about absent ID `CLM-NOT-IN-PILOT-9999`; the provider should report insufficient
evidence and must not assign CLM-0000000012's values to it. Verify actual extracted schema,
document chunks and links before expansion; add a persistent Claim type if the tenant supports it.

## Prepared files

| Package | Contents | Where |
| --- | --- | --- |
| Pilot | 10 historical claim cards, two per type; five synthetic handling procedures | `artifacts/synapt/pilot-v1/upload/` (15 individual TXT files) |
| Combined pilot alternative | Same 15 documents, 15,125 UTF-8 bytes | `artifacts/synapt/pilot-v1/pilot-combined.txt` |
| Expansion | All 2,163 eligible historical cards from the local sample, 38 TXT batches | `artifacts/synapt/expansion-v1/upload/` |
| Local verification | File hashes, provenance, IDs and factual probes | Each package's `manifest.json` and `QA_NOT_FOR_UPLOAD.json` |

Upload **either the 15 pilot files or the combined pilot**, never both. Individual files
give clearer document-level attribution. Never upload manifests or QA files: they contain
test expectations. Expansion batches contain at most 58 cards and 60,865 bytes with this source;
the generator enforces a maximum of 100 cards and 61,440 bytes per batch.

## Source and limits

The local source is a 3,000-row slice of ZiadataLabs' synthetic
FreeInsuranceClaims100M dataset, attributed under CC BY-NC 4.0 for educational use.
No new dataset download was necessary. Its recorded rows SHA256 was verified:
`942e2498947baa786a62b5a317708a02c7fffb65a51e2053ad241d6127886e5f`.

Only approved/denied historical records with a derived closure date strictly before
2026-01-01 are included. Closure follows the application's whole-day date semantics;
fractional resolution durations are preserved in the original fields. Excluded: 561 records
without a closed status and 276 closed on/after the cutoff. Original numerical facts remain
unchanged; fraud target labels and invented incident narratives are excluded.
The sample is not representative of an insurer or population. Authored procedures are clearly
synthetic training examples, not actual insurance policies or insurer requirements.

## Observed console blocker

The logged-in console displays **CP Admin**. One attempt to create
`Synapt Claims Investigator — Pilot v1` (slug `synapt-claims-pilot-v1`) returned
**`Field required; Field required`**. The error did not identify the missing field names.
The ingestion provider picker still listed the existing 15 providers and no claims pilot.
Separately, Knowledge Pack displayed **`fetchPkuPackets: 403`**.
The custom type editor explicitly stated that definitions are only held in the browser
session and are not saved to the server. No persistent type was created there.

These observations do not establish which missing fields caused the save failure, or whether
the 403 caused it. Ask the Synapt team for the two required backend fields and permission to
read/select the appropriate persistent Knowledge Pack. No guessed pack name, bypassed
permission or unrelated shared provider was used.

Screenshots: [provider validation](../artifacts/synapt/console-verification/provider-validation-error.png)
and [Knowledge Pack error](../artifacts/synapt/console-verification/knowledge-pack-403.png).

## Upload once the actual provider exists

1. In **Data Ingestion**, select the exact dedicated claims provider. Record its actual ID;
   the proposed slug is not a verified provider ID. Prefer Balanced extraction and the
   relevant knowledge, procedure and graph stores where supported by the actual provider.
2. Select **Data → File**. Keep the observed initial chunk settings: Recursive, size 512,
   overlap 64. The console does not state the unit; do not assume bytes or tokens.
3. Start with `artifacts/synapt/pilot-v1/upload/sop-auto-001.txt`. Click **Ingest** once and
   retain its request/task ID. If submission times out, inspect History before retrying.
4. In **History / Context Status**, confirm completion rather than just submission.
   Query the selected provider for the synthetic auto documentation/theft procedure;
   require an attributable source and the incident statement/repair estimate passage.
5. Upload the remaining 14 pilot TXT files after that first document is retrievable.
   Use separate uploads if the picker only accepts one file. Alternatively, for a fresh
   empty pilot provider, upload the combined pilot once instead of all individual files.
6. Use local `pilot-v1/QA_NOT_FOR_UPLOAD.json` to check exact claim facts and five procedure
   probes. For example, retrieve `CLM-0000000012`: recorded amount **18302.01**, deductible
   **1500.0**, type **auto**, source `history:CLM-0000000012`. Verify actual returned source
   attribution, provider scope and text; a generated answer alone is insufficient.
7. Check procedure extraction and graph/schema/traversal independently. A knowledge passage
   containing a procedure does not establish a populated Procedure Store or Claim graph.
   Record failed, empty or unavailable capabilities explicitly.

## Expansion without duplicate pilot records

The expansion contains the ten pilot historical records too. Do not append all 38 batches
to the same pilot provider unless Synapt's deduplication/upsert behavior has been verified.
For a complete corpus, use a fresh dedicated expansion provider, upload the 38 historical
batches and the five pilot SOP files, then repeat the provider-bound probes. This preserves
the pilot and avoids assuming unknown update semantics. For incremental expansion into the
pilot, first generate a separate remainder package that excludes its ten IDs.

Upload and verify the first expansion batch, then proceed in bounded groups while checking
errors and the tenant's ingestion limits. The full 100-million-row source is not prepared or
needed for initial testing. There is no automatic remote bulk uploader in this change.

## Application connection remains a separate gate

`SYNAPT_PROVIDER_ID=synapt_final_capstone` is now set in the ignored local `.env`
and credential-free `.env.example`. The local username/password fields are currently empty.
The settings loader confirms the new ID and two graph hops. Keep `SYNAPT_MODE=fixture`
until authorized credentials and the actual authentication/tool contracts are verified.
Never put credentials into `.env.example`, upload files, manifests or screenshots.

Provider creation defaults showed mTLS and auditing enabled. Preserve the actual provider's
security requirements; the current Python adapter has no mTLS certificate configuration.
If the tenant requires it, obtain the supported client certificate/authentication contract
and implement that before calling the provider. UI upload success alone does not prove
the application's MCP connection works.

## Reproduce and validate locally

From `D:\projects\synapt_capstone`:

```powershell
.venv/Scripts/python.exe scripts/prepare_synapt_corpus.py
.venv/Scripts/python.exe -m pytest tests/test_synapt_corpus.py tests/test_synapt_pack.py -q
.venv/Scripts/ruff.exe check scripts/prepare_synapt_corpus.py tests/test_synapt_corpus.py
```

Generation is deterministic and accepts identical existing outputs. Conflicting or unknown
files are rejected before writes; use new version directories for changed corpus contents.
Validation on 2026-10-06: **9 tests passed; Ruff passed**. File hash checks and target/date/type
tests validate the local package, not remote extraction or retrieval quality.
