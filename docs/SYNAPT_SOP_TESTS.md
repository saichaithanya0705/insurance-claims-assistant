# Newly uploaded SOP browser tests — 2026-10-06

> **Historical record.** Written before the full-dataset work of 2026-10-06. Commands, test counts and conclusions here may be out of date. Current status: [VALIDATION.md](VALIDATION.md); Synapt: [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md).

## Result

Six fresh Query Agent chats were submitted directly to **synapt_final_capstone** using the
user's authenticated browser. **All four individual SOPs passed content checks**. A general
mixed renters question returned correct guidance with incomplete citation; a focused version
naming the three relevant SOPs returned correct guidance and all three source identifiers.
This is a bounded functional check, not an accuracy benchmark or full provenance certification.

The provider's graph view displayed **74 nodes, 150 edges, six documents, six chunks and six
procedures**. Retrieved passages across the tests confirm the four newly uploaded SOPs are
available alongside the original auto SOP and synthetic historical record.

| Test | Content | Citation / document evidence | Graph warning |
| --- | --- | --- | --- |
| Property/renters | PASS: incident statement, photographs and itemized damage assessment for home/property; incident statement and inventory for renters | SOP-PROPERTY-001 and correct supporting passage; all five retrieved Doc IDs shown as unknown in this run | Present |
| Business | PASS: incident statement, documented loss assessment, estimates separated from documented amounts; no inferred business-interruption coverage | Correct SOP-BUSINESS-001 passages and primary Doc ID; two other retrieved documents unknown | Present |
| Conflict | PASS: preserve both dates/sources, check same event or correction, seek clarification; missing amount is not itself a contradiction | SOP-CONFLICT-001 and supporting passages; primary Doc ID resolved, historical Doc ID unknown | Present |
| Review | PASS: historical approval and risk scores do not establish coverage/fraud; missing policy terms require review; final decisions require human authorization | SOP-REVIEW-001 and five resolved retrieved Doc IDs; see quotation caveat below | Absent |
| General mixed renters case | PASS content; PARTIAL citations | Property/conflict named, but coverage procedure unnamed; SOP-REVIEW-001 absent from displayed chunks; historical Doc ID unknown | Present |
| Focused mixed renters case | PASS content and three requested SOP citations | Explicit SOP-PROPERTY-001, SOP-CONFLICT-001 and SOP-REVIEW-001; all five retrieved Doc IDs resolved | Present |

## What the mixed tests establish

Both mixed questions used the same fictional intake: different incident dates in two
statements, missing renters inventory and no actual policy wording. No real claimant data
or eligibility decision was involved.

The general question retrieved property, auto, business, conflict and historical passages.
It recommended the correct inventory request, preservation/clarification of both dates and
human review, but cited an unnamed coverage boundary instead of SOP-REVIEW-001.

The follow-up was a new chat naming the three relevant procedure IDs, without supplying the
expected answers. It retrieved the review document alongside property/conflict and returned:

- Inventory list and incident statement — SOP-PROPERTY-001.
- Preserve both dates and clarify the same-event/correction question — SOP-CONFLICT-001.
- State that missing policy wording prevents assessment from the available materials alone;
  route to a human handler — SOP-REVIEW-001.

This demonstrates that source targeting improved this observed run. It does not prove that
users should need to type SOP IDs, or that a prompt change alone repairs general retrieval.
The application should select the applicable procedure categories explicitly, retrieve their
evidence, and validate source IDs before presenting recommendations. These browser tests did
not verify that application routing or its live integration.

## Provenance is query-dependent

The same property and auto chunks displayed unknown Doc IDs in the property query but resolved
Doc IDs in later queries. The conflict and review links also varied according to the retrieved
context. Consequently, the ledger's unknown-document display is not evidence that every missing
link is permanently absent from storage; retrieval response metadata or UI mapping may contribute.
The exact service cause remains unverified.

| SOP | Observed chunk ID | Resolved document ID in later tests |
| --- | --- | --- |
| Property | chunk_f738f3e9-e651-471c-8fb1-c7c83a9bf27f | 11e0139f-2fb1-4bd8-ba23-edd18c5aea86 |
| Business | chunk_a4c5f552-533b-48b1-a32e-fbf92b01eec2 | fa3e05b7-03c6-42f7-96fc-8ff65ed61c51 |
| Conflict | chunk_b415e49c-bafb-44d3-b407-537659c08914 | a13a12fe-cc9e-4d33-9bbe-9c6229e8af32 |
| Review | chunk_7f74e0b5-3364-4561-85ab-c90dc939ac71 | 0adf659f-dc07-45bd-83b5-1502f7818812 |

Five of six answers carried the graph confidence/connectivity warning, including the focused
mixed response with all Doc IDs resolved. That warning cannot be attributed solely to unknown
document IDs. The review answer lacked the warning; absence of a warning is not an independent
measurement of high confidence or graph completeness.

### Quotation caveat

The review answer includes a quoted human-review sentence adding “before any decision is made,”
which is not a verbatim sentence in the local uploaded TXT. It labels this as coming from procedure
context, which may contain extracted/rephrased steps; that exact structured step was not inspected.
The meaning agrees with the human-review boundary, but do not treat every quoted sentence as
verified word-for-word document text. Source-text quotation validation remains necessary.

## Remaining gates

- Historical claim passages still display PHONE/US_SSN placeholders for numeric claim/policy IDs
  and an unknown historical document link when retrieved; claim identity is not repaired.
- General mixed-question retrieval needs reliable inclusion and citation of all applicable SOPs.
- Verify metadata consistency, graph-confidence causes and quotation accuracy separately.
- Application authentication, MCP schemas, procedure parsing and end-to-end live evidence remain
  unverified; the application stays in fixture mode.
- Hold the remaining historical files and bulk expansion until identity and provenance checks pass.

## Saved evidence and actions

`artifacts/synapt/sop-tests-2026-10-06/` contains `graph-overview.png` / `.txt` and screenshot
plus `-ledger.txt` pairs for `property`, `business`, `conflict`, `review`, `mixed` and
`mixed-targeted`. The six test chats remain in Synapt History; the final mixed result was left open.
No provider settings, system prompts, security controls, runtime code, credentials or remote
documents were changed. Browser queries were the only remote writes, apart from Synapt's own
automatic chat/history/audit recording. Private model reasoning was not inspected or retained.
