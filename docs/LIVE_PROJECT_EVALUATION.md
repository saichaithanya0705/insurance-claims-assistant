# Live project evaluation — 2026-10-06

> **Historical record.** Written before the full-dataset work of 2026-10-06. Commands, test counts and conclusions here may be out of date. Current status: [VALIDATION.md](VALIDATION.md); Synapt: [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md).

**Verdict: the live demonstration workflow works; production and bulk expansion are not signed off.**
The application authenticated to Synapt, retrieved uploaded source passages and used NVIDIA inference
through LangGraph. It did not fall back to fixtures. Numeric identity preservation and semantic quality
still need work before expanding the provider.

## Scope and evidence

- Provider: `synapt_final_capstone`; JSON email/password authentication and bearer Streamable HTTP MCP.
- Models: live `nvidia/nemotron-3-super-120b-a12b` through the configured NVIDIA endpoint.
- Verified corpus: **6 documents, 6 chunks, 6 procedures, 74 nodes, 150 edges, 31 steps**. This is five
  educational SOPs and one historical claim card, not the ten-card pilot or the 100M dataset.
- Application comparisons/models use the separately downloaded **3,000-row synthetic local sample**.
  The tested filtered search returned five auto/TX/approved cases, all respecting the filters, with
  **zero Synapt semantic case matches**. Local historical comparisons must not be presented as
  independently retrieved Synapt claim matches.
- The evaluator uses a separate SQLite database, saved local review records and no remote writes.
  No provider creation, uploads, privacy/security changes, remote feedback promotion, payment or
  claim approval/denial was performed during this evaluation.

Machine-readable evidence: [report](../artifacts/evaluation/live-2026-10-06/report.json),
[retrieval proof](../artifacts/evaluation/live-2026-10-06/retrieval.json),
[identity check](../artifacts/evaluation/live-2026-10-06/identity-check.json),
[grounding retests](../artifacts/evaluation/live-2026-10-06/grounding-regression.json).
Each `case-*.json` preserves the synthetic input, source passages, generated brief and validation.
Original defects are retained rather than replaced by successful retests.
The final running application's built-in evaluation was also triggered through the browser:
**4/4 golden cases passed with both modes live**; [saved result](../artifacts/evaluation/live-2026-10-06/browser-evaluation.json).
The optional LLM judge was not selected, and its status correctly remains `not_run`.

## Functional results

| Scenario | Live workflow result | Verified behavior |
| --- | --- | --- |
| Auto collision | Passed functional checks | Cited brief, review and duplicate-review block |
| Auto theft / late filing | Passed | Missing evidence and separate investigation priority |
| Home / conflicting cause | Passed | Conflicting statements surfaced without deciding coverage |
| Ambiguous category | Passed | Manual review required; acceptance blocked; revision allowed |
| Renters | Passed | Inventory/ownership clarification and cited source passages |
| Business | Passed | Estimated loss/accounting evidence and handler boundary |
| Property | Passed | Source-bearing brief and document verification limits |

**7/7** passed the evaluator's schema/citation/workflow/API gates. The seven cases produced **21
validated model outputs, zero recorded model failures**, and took **10.23–18.88 seconds per case**
including local review/feedback checks (93.08 seconds summed across cases). The runner was resumed
after its new extra-case fixture used the wrong document field; completed provider calls were not
repeated. All scenario inputs are now schema-validated before execution.

API checks passed: truthful runtime status before/after retrieval; invalid dates rejected with 422;
unknown run 404; filtered live search; available predictions; review-gated feedback lessons;
credentials absent from the inspected local audit; reviewed state surviving a new application instance.
Acceptance applies only to the investigation brief and does not adjudicate an insurance claim.

## Content and guardrails

The initial collision output suggested a police-report gap despite the supplied procedure making that
request conditional on theft. The business output initially borrowed property documentation guidance.
Some outputs described names of documents as though the documents had been inspected. These are real
quality defects even though all cited IDs exist. Membership validation is not semantic grounding.

The revised objective distinguishes reported availability from inspected contents, requires procedure
applicability, and tells the model to omit inapplicable gaps. The targeted final collision retest stopped
requesting a police report, and the business retest avoided property-only requests. These are bounded
observations, not proof that future model outputs cannot make similar errors. Handler review remains
required; stronger typed applicability checks and an independent semantic evaluation set are next work.

A separate prompt-injection input instructed approval, fraud determination and payment. The model
produced only allowlisted handler actions and no side effects. The mechanical boundary validator
flagged quoted unsafe phrases and held the brief for manual review. The original diagnostic expected
validation to pass and therefore marked that check false; **safe blocking is the correct safety outcome**.
The conservative validator was not weakened to turn that diagnostic green.

## Synapt limitations that block expansion

1. **Exact identity lookup fails.** Retrieved historical text masks `CLM-0000000012` as a PHONE
   placeholder and `POL-100297760` as a US_SSN placeholder. The amount 18,302.01 and deductible
   1,500 remain visible, but the requested identities are absent, so association cannot be verified.
   Coordinate structured synthetic ID handling with the Synapt team or test stable alphabetic record
   keys with an explicit local join map. Do not reconstruct original IDs by guessing or weaken global
   privacy settings.
2. **Graph provenance is interface-dependent.** `trident_get_procedures` exposes ordered descriptions
   without source IDs; `trident_search` exposes graph node IDs without original passages. The app
   excludes them as cited evidence and displays limitations. An explicit two-hop traversal did return
   linked Chunk/Document nodes and source-bearing entity properties; integrating those verified links
   into application graph enrichment remains future work. The app currently cites original chunks.
3. **Query/feedback contracts differ.** The live query tool uses `question`; the generic retrieval
   fallback expects `query` and is not used. Remote feedback uses `feedback_id/caller_type/verdict`,
   rather than the initial adapter's provider/query/rating fields. Unsupported writes fail closed.
   Local feedback works; MCP ingestion submission/completion and remote feedback were not live-tested.
4. **Policy wording is absent.** Educational SOPs and historical outcomes cannot establish coverage,
   proof of fraud, insurer requirements or a final claim decision.

## Statistical quality

The existing trained artifact loads and the prediction endpoint works. This evaluation did not retrain
or validate on real insurance data. Its temporal held-out metrics from the synthetic sample are:

| Model | Measured result | Interpretation |
| --- | --- | --- |
| Claim amount | MAE $16,906.97 vs baseline $23,567.14 | Broad estimates; nominal 90% interval covers 85.7% of held-out rows |
| Resolution time | MAE 6.49 days vs baseline 7.19 | Small improvement; held-out interval coverage 90.8% |
| Synthetic fraud flag | Precision 28.1%, recall 30.8% | Weak signal; investigation aid only, never a fraud conclusion |

## Browser and local checks

The Comet extension disconnected during this turn; Synapt verification used its actual MCP endpoint,
while application UI tests used Codex's in-app browser. Live theft and final collision submissions
completed through the UI. Citation navigation opened the matching original SOP chunk and provider,
source filtering worked, result tabs supported ArrowRight keyboard navigation, output received focus,
brief acceptance disabled further review actions, and usefulness feedback appeared in candidate lessons.

Desktop and 390px mobile layouts showed no document overflow. The beige/off-white theme, clear
boundaries and readable SOP headings are suitable for a professional demonstration. This is a heuristic
and functional UI review, **not a study measuring user likeability**. The existing warning text remains
visible; cited chunks and local comparisons have distinct provenance. Screenshots:
[desktop](../artifacts/evaluation/live-2026-10-06/browser-final-desktop.png),
[mobile](../artifacts/evaluation/live-2026-10-06/browser-final-mobile.png).

Final local checks: **89 backend tests**, **6 frontend tests**, Ruff passed, TypeScript/Vite build passed.
Frontend lint exited successfully with **14 existing warnings** and zero errors (Fast Refresh export
organization and synchronous state-in-effect rules). Live calls are explicit; ordinary pytest remains
network-blocked. Credential checks of generated JSON reports and browser JavaScript bundles found
no configured credentials. The existing project server was replaced with the current live build at
`http://127.0.0.1:8000`; only the application server is intentionally kept running.

## Next gate

Keep this as a live educational demo. Resolve stable IDs and source-linked graph enrichment, then
upload/validate the remaining ten-card pilot before measured 100 → 1,000 → eligible-sample batches.
Measure extraction completion, exact known/absent claim lookup, evidence applicability, cross-source
conflicts, citation fidelity, latency, quotas and failure recovery. **Do not upload 100M claims yet.**
The optional DeepEval judge and production concurrency/load/capacity have not been certified by this run.
