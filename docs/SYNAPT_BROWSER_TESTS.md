# Direct Synapt browser tests — 2026-10-06

Later testing after the four additional SOP uploads is recorded in
[SYNAPT_SOP_TESTS.md](SYNAPT_SOP_TESTS.md): four individual content checks passed; a focused
mixed query recovered all three relevant SOPs, while general mixed citations and metadata remain partial.

## Verdict

**Partial pass; hold bulk expansion.** The selected provider was `synapt_final_capstone`
in the user's authenticated Synapt browser tab. Four new tests were submitted through
Query Agent, each in a fresh chat; the user's existing contradictory passage answer was
also inspected. Query completion was checked before capturing answers and Context Ledger.
The live test chats remain in Synapt History. No files, provider settings, security settings,
system prompts or application runtime configuration were changed during these browser tests.

| Test | Result | Observed evidence |
| --- | --- | --- |
| Known claim CLM-0000000012 | FAIL identity/consistency; PASS recorded numeric values | Answer says it could not find the claim specifically, then quotes that exact claim ID with amount 18302.01, deductible 1500.0 and policy POL-100297760 |
| SOP-AUTO-001 | PASS content and supporting source passage | Correct incident statement, repair estimate and conditional police report; names SOP-AUTO-001 and quotes the original procedure |
| Absent CLM-NOT-IN-PILOT-9999 | PASS refusal in this run | Says no answer is available for that claim; explicitly refuses to assign another record's values to it, although it unnecessarily lists that other record |
| Actual policy wording/exclusions for POL-100297760 | PASS missing-information handling in this run | Says no actual wording/exclusions were supplied; distinguishes synthetic history and illustrative SOP from actual policy terms |

These are four observed runs, not an accuracy benchmark. SOP source attribution is verified
against the displayed passage, but the dedicated MCP procedure response contract and our
application's end-to-end live connection remain unverified.

## Concrete findings in the retrieved evidence

The displayed Assembled Context contained both uploaded documents, confirming that their
content reached this provider's query workflow. Claim amounts and other tabular fields match
the original local record. However, the visible historical chunk replaces identifiers:

```text
Local uploaded source:
source_id: history:CLM-0000000012
claim_id: CLM-0000000012
policy_id: POL-100297760

Displayed assembled context:
source_id: history:CLM-[PHONE_4946642c31d5]
claim_id: CLM-[PHONE_4946642c31d5]
policy_id: POL-[US_SSN_931b8e5995b3]
```

The synthetic claim and policy numbers were treated as phone/SSN-shaped values in the displayed
context. Source attribution/URL text also contains ORGANIZATION placeholders. This is direct
evidence of redaction in the displayed ledger, not proof of where it occurs internally or of
every field actually passed to the model. The mismatch is a likely contributor to the failed
identity test, but the precise service stage requires Synapt inspection.

The answer nevertheless quotes unmasked IDs while denying that the requested ID was found.
That is internally inconsistent. The displayed masked passage alone does not verify the
answer's quote of the original identifiers; an unmasking or other evidence path was not inspected.

### Provenance displayed by the ledger

| Source | Chunk identifier | Document linkage |
| --- | --- | --- |
| Historical claim | `chunk_23e793cd-72bd-4c7e-8dc5-248b3f882c38` | **unknown document** |
| Auto SOP | `chunk_dda561b0-14fa-4608-a8a4-941ff9ff58e9` | `bcf0650e-9269-4825-9fb9-d1c5346ca0db` |

The historical passage header and known-claim answer contain filename
`02608e11-fa30-451a-b8a0-12279cb3118c_b98984b3-cde9-4da2-8446-ac1ee1ba258c.txt`.
That filename does not repair the ledger's missing Doc ID. Whether this is a backend graph
relationship problem or a UI mapping defect is not established.

The Critical Subset displayed Procedure and Step candidates for auto and theft documentation,
so procedure-like graph extraction is visible. All four answers retained the low-confidence /
incompletely-connected graph warning; the ledger also showed `temporal absent`. These labels
do not establish which exact graph relationships failed. Customer/Order selection or a missing
Claim type has not been proven to be the cause, and adding a Claim type alone would not resolve
the demonstrated identifier redaction or contradictory answer.

## Recommended remediation and retest

1. For synthetic test documents, use stable alphabetic lookup aliases such as
   `CLAIM-PILOT-AUTO-ALPHA` and `POLICY-PILOT-AUTO-ALPHA`, preserving the original record and
   a local alias-to-source mapping. Verify the aliases survive ingestion before expanding.
   A prefix-aware identifier classification repair by the Synapt team is the permanent service
   fix if these are confirmed false positives; do not disable general PII protections.
2. Ask the Synapt team to inspect the historical chunk's missing document linkage and the
   pipeline stage that produces the PHONE/US_SSN placeholders. This report is prepared locally;
   no message was sent to them.
3. Rerun known-ID/alias retrieval, exact source attribution and absent-ID checks after repair.
   An answer must not both deny finding a record and quote it as supporting evidence.
4. Verify application MCP access separately using authorized local credentials, discovered
   schemas and actual returned provider-bound evidence. The application remains in fixture mode.

No remediation document was uploaded in this test turn, and no bulk expansion was attempted.

## Saved browser evidence

Evidence lives under `artifacts/synapt/browser-tests-2026-10-06/`:

- `masked-identifiers.png`: the user's original contradictory answer and provenance panel.
- `known-claim.png` and `known-claim-ledger.txt`: direct fresh-chat reproduction.
- `procedure.png` and `procedure-ledger.txt`: correct SOP content, quote and source linkage.
- `absent-claim.png` and `absent-claim-ledger.txt`: missing-record refusal and retrieved candidates.
- `policy-wording.png` and `policy-wording-ledger.txt`: missing policy wording handled explicitly.

Text snapshots retain visible evidence and workflow metadata only; private model reasoning and
credentials were not inspected or saved. Screenshots and snapshots validate the observed UI,
not the MCP transport or application's live evidence parser.
