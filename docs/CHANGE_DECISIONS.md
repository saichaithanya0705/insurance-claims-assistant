# Change transparency

## What I did
Built the API/workflow, Synapt boundary, statistical pipeline, evaluation harness, static frontend,
startup configuration and test/documentation suite in the initially empty workspace.
Included architecture/design and a timed panel presentation; tightened action schemas, added local
historical citations, made theft evidence requests relevant, and separated checkpoint transactions.

## Why this approach
Explicit execution state and typed boundaries allow development before Synapt permissions arrive.
The live adapter remains separate from fixtures; statistical predictions use the actual synthetic source.

## Why not the alternative
A second independently generated knowledge base would duplicate Synapt. Unbounded agent conversations
would make review, costs and reproduction harder. Full 100M-row ingestion is unnecessary for a pilot.

## What was the issue / root cause
The project had no implementation, Synapt write access was pending, and the required dataset lacked
incident narrative and policy documents. Outcome fields also create leakage if used as model inputs.
An intermittent persistence test additionally exposed concurrent checkpoint/audit use of one
connection, whose shared transaction state could interfere with foreground commits.

## Why this works best
The development path is executable without credentials while preserving a separately tested real
connector. Data provenance, held-out comparisons and handler gates make practical limits visible.
Separate connections with WAL address transaction ownership; repeated checkpoint/review tests
exercise that boundary. Precomputed BM25 document frequencies avoid repeated corpus scans.
Independent review also found negated-only loss statements incorrectly marked contradictory,
unconstrained recommendation reasons and evaluation checks that ignored recommendation citations.
Regression tests now cover those cases. The ingestion pack defaults to ten cards because the full
sample exceeded the adapter's bounded content size and the pilot should be measurable before expansion.
Queue priority includes supported contradictions and the model's qualified review signal, because
filing delay/history alone missed investigations that require evidence reconciliation. This remains
an explicit demonstration queue policy and does not change coverage or claim outcomes.

## Other valid patterns
CrewAI Flows or Microsoft Agent Framework could replace orchestration. PostgreSQL and a job queue
are suitable for a multi-user deployment; SQLite and synchronous bounded runs keep this local pilot
simple. A production deployment additionally requires real identity/authorization, retention controls,
provider permissions, measured capacity and real-world quality validation.

# NVIDIA integration and live validation

## What I did
Added NVIDIA-specific secret configuration, model/time/token settings and one shared validated
completion client for agents and DeepEval. Updated the ignored environment and credential-free example,
documented setup/results, added an explicit live testing script, and isolated unit-test configuration
and HTTP transport. Strengthened substantive finding citations and false-contradiction rejection.
Preserved full evaluator objectives, claim fields, source identities/provenance and partial metric status.
Disabled optional evaluator telemetry in the environment files. Formatting changes normalize imports
and layout without changing other feature behavior.

## Why this approach
Independent agent/Synapt switches support real model testing while Synapt permissions are pending.
The same completion boundary validates every agent/judge response, handles truncated/malformed JSON,
limits retries and records safe prompts, final outputs and numeric usage. Explicit live tests prevent
accidental provider calls during regressions. Source identities prevent current/history facts from
being merged by an evaluator that receives only anonymous passages.

## Why not the alternative
Separate duplicated HTTP clients drifted in error handling. Assuming catalog availability failed with
an account-specific 404. A generic credential alias could forward the NVIDIA key to another provider.
Silent fixture fallback would disguise live failures. Lowering judge thresholds would hide quality
limits rather than repair evaluation context.

## What was the issue / root cause
The prior generic provider configuration had no verified NVIDIA model/account contract. Live responses
exposed uncited substantive findings and an absence-of-conflict finding labeled as a contradiction.
The evaluator used an obsolete DeepEval metric property, lost evidence identities and omitted structured
claim inputs. Its status could call an empty metric list completed. DeepEval's pytest plugin also loaded
the live `.env` into process variables, unexpectedly overriding credential-free test settings. Review
found unsafe cross-host key selection, malformed optional usage handling and cumulative audit counting.

## Why this works best
NVIDIA keys are selected only for its hostname; other endpoints require their own explicit key.
Schema errors retry without retaining malformed content or private reasoning, persistent failures stay
visible, and final side effects remain handler gated. Regression isolation fixes the environment leak
at the boundary. Judge accounting now counts only the relevant role/run interval, and completed status
requires full metric coverage. Live evidence records four passing workflow cases and twelve completed
judge metrics with eight passing scores, rather than claiming a full quality pass.

## Other valid patterns
The OpenAI-compatible SDK could replace direct httpx; a second judge model could reduce correlated
evaluation errors. Native JSON-schema constrained generation is useful where the selected model/API
supports it, but output validation remains necessary. Background jobs and streaming can improve UI
responsiveness at deployment scale. Real Synapt retrieval, labeled relevance sets and independent
domain review remain necessary before a quality claim or large expansion.

# Professional light UI and interaction repair - 2026-10-06

## What I did
Converted the user's React layout to a warm off-white workspace: porcelain canvas, white cards,
stone navigation, charcoal text and forest-green actions. Removed aurora, gradients, glow,
spotlights, orbit/pulsing branding, animated counting and simulated stage completion. Reduced
repeated summary tiles from eight to four, made evidence readable with original passages disclosed,
and shortened presentation IDs while retaining full identifiers in copy/export and evidence.
Fixed pending-document submission, same-run feedback draft loss, native rating keyboard behavior,
field validation/focus, hidden-filter validation, demo failure/retry/key recovery, request-order guards,
late review updates, missing-validation wording, result positioning and view scroll/focus.
Added frontend rendering regressions and rebuilt the static application served by FastAPI.

## Why this approach
Preserved the user's application structure and API contracts. Shared semantic tokens provide consistent
light surfaces and states throughout forms, results, charts, connection readiness and command palette.
Atlassian recommends neutral surfaces and intentional elevation, while Carbon offers white/gray light
themes; these informed the choice, with warm neutrals as this project's own visual direction.
Sources: https://atlassian.design/foundations/color?afsrc=1,
https://atlassian.design/foundations/elevation/,
https://www.carbondesignsystem.com/building-blocks/foundations/themes/code.

## Why not the alternative
A dark palette was superseded by the user's off-white request. A beige CSS overlay would leave
inconsistent native controls, dark icons and semantic states. A replacement component library or
complete layout redesign would add migration risk without addressing the data/state defects.

## What was the issue / root cause
React queued document state changes before submission read the old form. Keys included mutable run
status and remounted draft state. Demo requests were not retried on credential changes and failure
looked like perpetual loading. Concurrent refreshes could apply stale responses. Missing validation
fell through to success-like wording. Fixed-size decoration exceeded narrow cards; long intake and
retained page scroll hid the user's next step. Animated counts exposed zero until scrolled into view.

## Why this works best
Submission passes one synchronous form snapshot; component identity follows stable run IDs.
Independent request generations and selected-run identity guard stale responses. Native constraints,
radio inputs, field errors and focus support accessible correction. Mobile completion collapses intake
and requests result focus once. Values render immediately and validation explicitly distinguishes
unavailable, failed and passed. Source identifiers and original passages remain traceable.
Measured token contrast is at least 5.18:1 for neutral text across neutral surfaces, 5.81:1 for semantic
pill text, 7.62:1 for primary-button text and 3.44:1 for strong control borders. These are palette
measurements, not a claim of full WCAG certification or demonstrated user preference.

## Other valid patterns
A cool neutral white/blue enterprise theme is equally valid; the chosen warm theme matches the user's
request. A branded sans-serif heading is another option; restrained Georgia headings plus Segoe UI
controls give this application a modest editorial finish without external font requests. A production
multi-user app could use abortable queries, per-run draft state, background jobs and a streamed trace.
The current bounded local workflow uses request generations and truthful in-progress messaging.

# Synapt pilot and expansion preparation — 2026-10-06

## What I did
Added a deterministic corpus generator and seven focused regression tests; prepared ten original
historical cards and five synthetic SOPs, a combined pilot alternative, and 2,163 eligible records
in 38 expansion batches. Added SHA/byte manifests, separate local QA probes and an upload guide;
linked the guide from README and updated the integration status. Recorded console screenshots.
Attempted provider creation once; it was rejected. No upload or environment change was made.

## Why this approach
Small documents support attributable first retrieval tests before bulk ingestion. Verified source
integrity and explicit field allowlists preserve original facts while excluding outcome target labels.
Temporal filtering matches the current application's historical eligibility. Both output plans are
checked for conflicts before writes, and identical regeneration is safe.

## Why not the alternative
Uploading the full dataset before validating provider scope/extraction would make failures expensive
to diagnose. Invented historical narratives would corrupt source facts. Ingesting local expected answers
would contaminate retrieval evaluation. An arbitrary existing shared provider or guessed Knowledge Pack
could mix unrelated data or conceal the actual console problem; neither was used.

## What was the issue / root cause
The prior small pack did not provide full five-type pilot coverage, a complete bounded expansion,
per-file hashes or separated retrieval probes. The remote provider save returned two unnamed required
field errors, while Knowledge Pack access independently returned 403. The backend's missing field names
and their relationship to that 403 remain unknown. CP Admin display alone does not prove all permissions.

## Why this works best
The pilot covers all five supported types and synthetic review procedures without current demo inputs.
Expansion excludes unresolved and post-cutoff records, preserves attribution and has bounded bytes/counts.
Local tests check integrity, original facts, exclusions, type coverage, reproducibility and conflict
handling. Nine corpus/pack tests and Ruff passed; no remote success is claimed. The user took over
provider creation, and the browser setup page remains available for that handoff.

## Other valid patterns
Individual pilot uploads offer clearer document provenance; one combined file is convenient when the
picker accepts only one file. Use one representation per provider. A fresh expansion provider avoids
duplicating pilot records; verified upsert semantics or an explicitly filtered remainder package are
valid alternatives. Real tenant schema adaptation and mTLS support depend on the verified service contract.

# Provider identifier and initial query assessment — 2026-10-06

## What I did
Set SYNAPT_PROVIDER_ID to synapt_final_capstone in .env and the credential-free .env.example.
Updated README, integration status and the upload guide with the user's two reported uploads,
source comparisons and remaining verification probes. Preserved all other environment settings.

## Why this approach
The actual user-supplied identifier supersedes the proposed slug. Comparing each returned statement
to the original files separates correct content from unresolved identity, attribution and graph checks.

## Why not the alternative
Hardcoding a provider in application code would break configurable tenant scope. Calling the whole
pilot passed because the numbers match would ignore the answer's missing claim ID and explicit warnings.
Enabling live mode without configured login and verified MCP contracts would create a misleading status.

## What was the issue / root cause
The environment did not reference the final provider. The claim response retrieved matching facts but
did not establish the requested claim identity; the pasted responses showed no source citations and
both flagged incomplete or low-confidence graph data. The cause is unverified. Policy-only exposure
is a possible schema limitation, not proof of why claim linkage failed.

## Why this works best
Byte-level replacement changed only the provider-setting line; fresh Settings loading confirms the ID,
fixture mode and two-hop limit without exposing credentials. The guide requires attributable claim ID
evidence and an absent-ID probe before expansion. No remote queries or uploads were performed here.

## Other valid patterns
Process environment or a secret/config manager can supply the provider in deployment. Verified
knowledge-chunk retrieval can support a pilot independently of a complete graph; a persistent Claim
schema and typed Claim-to-Policy relation can support the richer graph after tenant schema verification.

# Direct Synapt browser verification — 2026-10-06

## What I did
Ran four independent fresh-chat Query Agent tests on synapt_final_capstone: known claim, auto SOP,
absent claim and absent policy wording. Inspected visible assembled passages, retrieved candidates
and provenance, saved screenshots/text snapshots, and added SYNAPT_BROWSER_TESTS.md with linked
status updates in the upload guide, contract and README. Test chats were saved by Synapt itself.

## Why this approach
The user explicitly requested direct testing without waiting for manual relays. Fresh chats reduce
ordinary conversation carryover; source comparisons and negative probes separate answer correctness
from identity, source linkage and missing-information handling. Existing authenticated browser access
supports these checks without obtaining credentials or making unverified MCP calls.

## Why not the alternative
Checking only answer wording missed the masked identifiers and unknown document linkage. Asking the
user to repeat tests would delay authorized work. A global PII bypass or invented graph schema would
not be an appropriate response to a synthetic-ID false positive; no security settings were changed.

## What was the issue / root cause
The displayed ledger masks synthetic numeric claim/policy IDs as PHONE/US_SSN, while known-claim
answers deny finding the ID and then quote that ID. The historical chunk's Doc ID is unknown.
The redaction and missing linkage are observed; the service stage, exact confidence-warning trigger
and how original IDs reach the answer are unverified. A missing Claim type alone is not a proven cause.

## Why this works best
The report distinguishes three content-level passing checks from a failed identity/consistency check,
retains attributable SOP and chunk evidence, and avoids calling four runs an accuracy benchmark.
It proposes alphabetic lookup aliases with local provenance and a service classification/linkage
repair before expansion. Application live MCP integration stays a separate unpassed gate.

## Other valid patterns
Prefix-aware identifier classification or a verified scoped redaction exception can preserve
legitimate synthetic keys; consistent opaque aliases with a local mapping avoid numeric-pattern
collisions while preserving privacy controls. Typed Claim/Policy graph relations can improve traversal
after source linkage is verified. Further testing should follow remediation, not repeat unchanged runs.

# Four additional SOP uploads: direct browser validation — 2026-10-06

## What I did
Ran four individual SOP queries and two synthetic mixed renters queries in fresh Synapt chats;
saved graph counts, answers, retrieved passages and provenance screenshots/snapshots. Added
SYNAPT_SOP_TESTS.md and linked current results from README, contract, upload guide and the prior
browser report. No application code, data corpus or remote configuration was changed.

## Why this approach
The user authorized direct queries after uploading the four files. Individual questions isolate
documentation, conflict and review rules; the mixed case checks whether the provider combines
and cites the required procedures. A focused follow-up names sources after the general answer
omitted the review identifier, without supplying expected answers.

## Why not the alternative
Graph node/document counts do not prove correct answers or citations. Accepting source labels
alone would miss query-dependent Doc IDs and paraphrased quotations. Re-uploading historical data
or altering confidence/security settings would not address these demonstrated retrieval limits.

## What was the issue / root cause
The general mixed query omitted SOP-REVIEW-001 from displayed chunks and used an unnamed coverage
boundary. Naming the three relevant SOPs recovered that source in the follow-up. Doc IDs for the
same chunks varied by query; warnings persisted even when all retrieved Doc IDs resolved. These
observations suggest retrieval/metadata limitations but do not establish the internal service cause.
Historical numeric-ID masking remained visible in retrieved context.

## Why this works best
The report separates four passing individual content checks and a passing focused mixed answer
from partial general citations, variable provenance and unverified application MCP access.
It records the review quote caveat and six observed runs without claiming statistical quality.
Future application routing can retrieve relevant SOP categories explicitly and validate evidence.

## Other valid patterns
Category-based procedure selection, query decomposition and a reranker can improve required-source
coverage; compare their measured relevance, latency and usage. Larger top-k may help but can add
noise and does not repair source metadata. Exact quote validation can be deterministic against
retrieved passages; extracted procedure summaries should be identified as summaries rather than quotes.


## 2026-10-06: verified live tenant integration and evaluator checks

### What I did
Added configurable JSON/form login identity (`SYNAPT_AUTH_USERNAME_FIELD`), configured the local beta account with `email`, decoded the verified one-layer JSON `result` wrapper, and enabled local live Synapt mode. Added runtime retrieval verification to health/status, refreshed it after UI investigations, used readable SOP headings and shortened visible chunk citation labels while retaining full IDs. Added a resumable live evaluator with separate SQLite storage, seven synthetic claim scenarios, API/review/persistence checks and saved source evidence; tightened model instructions about document availability and procedure applicability. Updated the contract, README and evaluator report. Credentials were preserved in ignored `.env` and were not printed or copied into examples.

### Why this approach
Authentication was verified through a successful email/password response and MCP discovery, then the real source response shape was tested before enabling live mode. Verification is per process and follows successful source-bearing retrieval; source membership and human review remain separate from answer accuracy. Synthetic evaluation uses a separate database so existing investigations remain intact.

### Why not the alternative
Guessed authentication fallback, hardcoded green status, fixture fallback, fabricated graph citations and re-uploading all data would hide the real contract or create misleading success. Repeating completed test scenarios after a runner error would waste provider calls; a checkpoint permits explicit continuation.

### What was the issue / root cause
The beta endpoint expects `email`, while the initial adapter assumed `username`; tools return JSON strings inside `result`, while normalization expected direct chunk arrays. Health and UI labels were permanently unverified. Graph search nodes and extracted procedure responses lack source IDs in those interfaces. Probabilistic generation sometimes extended theft-only guidance to collision claims or described reported document names as inspected evidence; source-ID membership checks do not detect that semantic error. Synapt ingestion masks numeric claim/policy IDs as PII, breaking exact identity matching.

### Why this works best
The explicit tenant contract, bounded decoding, provider checks and malformed-payload regression tests restore actual live source retrieval without weakening scope or provenance. Verification resets before each retrieval and stays false on failure or empty evidence. Readable headings reduce filename clutter without altering chunk identities. The revised grounding objective improved the targeted retest, while reports preserve original defects and avoid claiming semantic perfection. No remote ingestion, feedback promotion, provider/security changes, claim adjudication or payments were performed.

### Other valid patterns
A tenant-specific versioned adapter or an advertised structured MCP result contract would simplify normalization. Graph-derived evidence can be added after validating links back to original chunks; the current app safely cites original passages instead. Typed evidence-applicability outputs plus independent semantic evaluation offer stronger acceptance gates than prompts alone. Alphabetic synthetic record keys or a platform-supported structured-ID exemption could restore identity matching; coordinate with the Synapt team before changing privacy processing.


---

# 2026-10-06: full dataset, Synapt-first retrieval, and the audit fixes

An audit of the project against the brief found five partial requirements and several missing
deliverables. This round fixed them against the real 100M-row dataset and the real Synapt provider.
Each entry gives the decision, the alternative rejected, and the evidence.

| Decision | Alternative rejected | Evidence |
|---|---|---|
| **Query the Parquet file in place with DuckDB** for filters, similar claims and training samples | Load it into memory (does not fit); ingest it all into Synapt (years, see below); keep the 3,000-row JSON slice (not random, hid the NaN trap, made the fraud model weak) | 100M rows scanned in 3 to 5 s; fraud precision rose from 28% to 56% on a proper sample |
| **Handle NaN durations in SQL** (`TRY_CAST`) | Trust the JSON API's null | The file stores pending durations as NaN; the API had converted them to null |
| **Synapt holds a 1,000-card sample, not the dataset** (superseded on 13 October 2026: past claims are now in Synapt's ticket store, see [that entry](#past-claims-moved-from-cards-to-synapts-ticket-store--2026-10-13)) | Upload everything | Ingestion is about 100 cards per call at 2 to 3 minutes per call |
| **Masking-safe identifiers** (lower-case letters-only alias, opaque region token) | Upload the original IDs and names | A probe against the real tenant showed digits, upper-case tokens and place names are rewritten before indexing |
| **One card per chunk** (`chunk_size=100` tokens) | Default chunking | The default packed about 14 cards per chunk |
| **Weighted fusion (Synapt 0.5), same candidate pool, extras shown separately** | Equal-weight fusion | A semantic outlier (a $3,393 NJ claim) ranked above exact $8,500 TX matches |
| **No IDF in the keyword leg** | Standard BM25 | The root cause of that outlier: IDF rewards rare terms in a pool of near-identical claims. A regression test reproduces it |
| **Independent judge, in the background** | Judge inline; judge with the author model | Inline cost one brief 67 s; the first candidate judge took over a minute; the author-model judge is not independent. `gpt-oss-20b` completed 4 of 5 verdicts in 12 to 23 s |
| **Cache the Synapt access token; honour `Retry-After`** | A login per call | The token endpoint rate-limited (HTTP 429) after a burst |
| **Promotion by an administrator closes the feedback loop** | Automatic learning; ingesting every rating | Lessons are human text. Nothing is promoted automatically, lessons carry no claim identifiers, and they never decide a claim |
| **Audited priority score** (every point attributed) | An opaque score; a single label | Handlers can see why a claim ranks where it does; `GET /api/queue` orders by it |
| **Direction-of-effect and per-claim explanations** | Importance only | The brief asks how characteristics affect outcomes, which importance alone cannot answer |
| **All four dataset statuses are filterable** | Only approved and denied | Pending and under-review claims are real, and are labelled as having no outcome |
| **Tell the agents to write "reports ... is available"** | Rely on the validator alone | The validator correctly held a brief saying a document "has been provided"; the wording cut that from one in four to zero in four |
| **Optional Synapt graph calls off by default** | Always call them | Their responses carry no source passages, so they are never citable; they only added calls and a standing warning |
| **Unit tests never touch the real dataset** | Let tests pick up the default path | Test time rose from 46 s to 6 minutes when they accidentally scanned 100M rows |
| **Remove the old corpus scripts and tests** | Keep both | They produced the masked-ID cards and referenced a 3,000-row file |
| **A pptx deck in `docs/`** | Only a script | The brief lists a 10-minute presentation as a deliverable |

## What was measured, not assumed

* Synapt's semantic precision on 60 claims: 1.7x chance on claim type, 1.5x on amount band, none on
  prior claims ([SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md)).
* DeepEval on live runs: 8 of 12 metrics pass; Contextual Relevancy is the weak one.
* The independent judge's latency and reliability across five models, of which only two answered.

## Not done

* Uploading the full dataset to Synapt (infeasible through the ingestion tool; a ticket-store
  provider via the console is the untested route).
* Docker packaging (the Docker daemon was not running to test it).
## Original-plan reference document and diagram archive

### What I did
Saved `PROJECT_PLAN.md` and a self-contained `PROJECT_PLAN.html` with the complete planning substance,
framework decision and both supplied flowcharts. Stored PNG/SVG diagram images, exact Mermaid sources
and a byte-for-byte copy of the pasted transcript under `docs/images/project-plan/`. The HTML embeds
both images and the original transcript; the README links to the plan. Local generation helpers are
kept in `artifacts/` for reproducibility.

### Why this approach
A structured Markdown plan is easy to revisit and maintain, while the offline HTML is a portable single
file with readable tables, navigation and images. Preserving the original transcript retains all wording
and historical details independently of the organized plan.

### Why not the alternative
A link back to chat would not create the requested reusable file. Mermaid code alone requires a renderer
and would not guarantee that the images appear offline. Replacing the original plan with the current
architecture would lose the historical recommendation and framework rationale.

### What was the issue / root cause
The original recommendation, framework comparison and diagrams were distributed across conversation
messages and a pasted transcript, without a dedicated reference document containing the image assets.

### Why this works best
The original design is labeled as a plan, with links to evolving implementation documents; it does not
turn historical capability assumptions into current verification claims. Both diagrams preserve the
supplied nodes and relationships, and editable sources remain available. No application behavior,
credentials, data or runtime settings were changed.

### Other valid patterns
A PDF would be useful for fixed-page printing; a Word document would support nontechnical editing.
The HTML supports browser printing, and the SVGs can be reused in presentations without losing resolution.

## 2026-10-07: end-to-end test against the brief, and four fixes

### What was found
The running system was tested from sign-in to the brief, against the brief's three example questions
and against ground truth computed independently from all 100,000,000 rows. Retrieval, models,
explanations, filters, ranking, roles, review and feedback all matched the data (amount model MAE
$15,105 against a best-possible $15,095; resolution MAE 6.3 d against 6.31 d; every cited historical
claim matched the Parquet exactly). Four defects were found and fixed.

### What was the issue / root cause
1. **No handling procedure for many claims.** The procedure query embedded the claim narrative. With about
   20,900 claim cards now in the provider, 8 or 9 of the 10 hits were cards, which are discarded by design,
   so the burst-pipe and ambiguous claims got no procedure and the brief said none was supplied.
2. **Weak input checks.** `ZZ` and `XX` passed as states; a description of ten spaces or only symbols passed.
3. **Personal data echoed.** An SSN, card number, email and phone in the description were stored, sent to the
   language model and repeated in the brief.
4. **Judge failures.** About a quarter of independent reviews failed: both 35 s attempts timed out on endpoint
   latency when briefs ran back to back.

### Why this works best
1. The procedure query now uses the procedures' own vocabulary and the claim type, not the narrative
   (`synapt/adapter.py`). Measured against the live provider, every test claim now gets four or five real
   procedures instead of zero to four. It also keeps free text out of that provider call.
2. `ClaimInput` and `SearchFilters` accept only the 50 states and DC, and a description must hold at least
   five letters after trimming (`core/schemas.py`).
3. `redact_personal_data` masks SSNs, Luhn-valid card numbers, emails and phone numbers when a claim is
   accepted, so the masked text is what is stored, sent and retrieved. Dates, amounts, claim and policy IDs
   are left alone (covered by tests).
4. The judge's per-attempt budget is 60 s (`JUDGE_TIMEOUT_SECONDS`, maximum 120). It runs in the
   background, so the longer budget cannot delay a brief.

### Not changed, and why
The brief lists individual similar claims but no outcome rate for the whole neighbourhood, so "varied
outcomes" can describe a group that is 93% approved. A neighbourhood summary would fix that; it is a
feature, not a bug fix, and is left for a decision.

# UI redesign: formal light workspace with verdict band — 2026-10-07

## What I did
Rebuilt `frontend/src/index.css` as one token-based system (type scale 12–36px, radii 6/10/16, tinted
shadows) and removed the trailing `!important` patch blocks that inverted caption and heading sizes.
Bundled Geist, Source Serif 4 and JetBrains Mono through `@fontsource-variable` (no runtime font requests).
Added a verdict band to the case brief (priority ring, open gaps, fraud-flag signal, next step), turned
Saved cases into a compact queue with filters behind a toggle, ordered findings so gaps and contradictions
come first, gave the login a brand panel, and added decorative 3D tilt tiles and a cursor-following card border.
Fixed: select chevrons drawn at the top-left, titles cut mid-word (frontend `shortTitle`, backend `_short_title`),
wrapping shortcut badges, out-of-order Alt shortcuts (now 1–5 in display order), duplicate nav icons,
Title Case enum labels (now sentence case), the full-width focus outline around results, and misaligned Quality bars.

## Why this approach
The user asked for a more professional, likeable UI and confirmed a formal light theme over a dark one.
Numbers stay factual from the first frame: motion only affects position, tilt and ring drawing, and
reduced-motion users get a static surface.

## Why not the alternative
A dark sidebar or dark theme was considered and rejected as less formal for a claims tool.
A component-library migration would add risk without fixing the identified defects.


# Synapt store verification moved to the graph, and into Git — 2026-10-07

## What I did
Added `claims.synapt.inventory`, `scripts/verify_synapt_store.py` and the committed
`data/synapt/expected_inventory.json`. The check reads each document's chunk count and character span from
Synapt's graph, identifies expansion documents by the marker in their header chunk (tolerating Synapt's
masking of a 9-digit run as `[US_SSN_…]`) and base documents by size, and compares both with the local
batch. `bootstrap.py check` and `ingest_expanded_cards.py --verify-only` now use it; the latter records
graph-verified batches in the local ledger. Live result: 10/10 base batches, 40/40 expansion batches
(19,887 cards), 5/5 procedures, 63 documents, 20,914 chunks.

## Why this approach
The old reconciliation asked for `chunks + 100` chunks in one query. The tenant returns at most 1,923 per
query and fails a `top_k` near 21,000, so the script crashed and the ledger kept saying "500 of 19,887
verified" although the data was complete. By the old check's own arithmetic (500 of 19,887 cards verified,
19,387 pending) it would have reported NOT READY on this machine; that was worked out from its code and the
ledger, not observed, because the ledger has since been updated. The ledger also lives in `artifacts/`, outside Git, so a second laptop could not see it. The graph
gives exact counts, and a committed inventory gives every machine the same expectation.

## Why not the alternative
Sampling cards by their own text was tried first and discarded: it hit only about a third of cards, base
cards that were already known to be present included, so a miss proved nothing. Uploading again to "make
sure" would have created permanent duplicates, because the tenant exposes no deletion tool.

## Known limit
The uploader's post-submit retrieval check (`verify_batch`) still cannot confirm a batch at this store
size. This provider is complete, so it is documented rather than rewritten; new corpora belong in a new
provider with their own inventory.

A second limit surfaced when a fresh clone rebuilt the base corpus: `bootstrap.py corpus` is deterministic
(three builds agree) but selects a different 1,000 claims from the ones uploaded (52 coincide), most likely because
the uploaded batches came from an earlier builder that Git does not retain (an inference). No runtime code reads the local corpus, so this is documented, not changed.


# Per-query traces, observability and explainability — 2026-10-07

## What I did
Added `observability/telemetry.py` (spans written to SQLite as they close), `observability/observatory.py` (per-run traces and system
metrics), `observability/explain.py` (how a saved brief was generated and evaluated), five API endpoints, two pages
(Observability for administrators, Explainability for everyone) and an **Explain** tab on every brief. The
workflow, model client, Synapt adapter and retriever record spans; `validate_brief` now also returns one
result per rule. Runs saved before this change get a reconstructed trace from their audit events.
Full description: [OBSERVABILITY_EXPLAINABILITY.md](OBSERVABILITY_EXPLAINABILITY.md).

## Why this approach
* **Spans in the existing SQLite, not a collector.** The service is one process and the audit log is already
  there. Stage spans are parented through a registry rather than ambient context because the workflow engine
  may run a node on another thread; the background review receives its context explicitly, and anything
  recorded inside background work inherits that flag so it is not counted as time a handler waited.
* **Reconstruct, do not backfill or leave blank.** Seventy saved runs (and the 55 shipped in the template)
  would otherwise show nothing. The reconstruction is computed on read, never stored, and says it is
  approximate on every page.
* **A structural explanation, not a model-written one.** A language model asked to explain its own brief
  would produce a plausible rationale that nothing guarantees is the real one. The explanation is built from
  what was stored: the cited sources, the recorded ranks, the point rule, the validation results.
* **Ranking detail kept apart.** `retriever.last_search` is pinned by tests and the case dictionaries are
  fed to the models as evidence text, so per-method ranks live in a separate `last_trace` and in the span.
* **Prompts are linked, not copied.** A model span stores the audit event ids of its prompt and answer; the
  administrator opens them on demand. Copying them would roughly double the stored prompt volume.
* **Colour was validated, not chosen.** The application's own teal, sky and violet fail a colour-blindness
  check as a three-series set, so the one three-series chart uses slots that pass it.

## Why not the alternative
OpenTelemetry or Langfuse would add a dependency and an external collector for a single-process demo
service. Backfilling spans for old runs would store guesses as if they were measurements.

## Found while checking it in a browser, and fixed
A handler's explanation repeated a line naming Synapt (the estimates note), and the review model's own call
was counted as time spent waiting for the brief. Both have regression tests.

## Known limit
Reconstructed traces have no retrieval or scoring detail. Tokens are the provider's own figures and no price
table exists, so no cost is shown. Spans are not pruned.

# Synapt is mandatory, with no fixture mode or fallback — 2026-10-09

## What I did
Removed `SYNAPT_MODE=fixture` and `FixtureSynaptAdapter`. `Settings` now refuses to load without the Synapt
username, password and provider ID and accepts only `SYNAPT_MODE=live`; `build_synapt_adapter` can only
return the live adapter; lesson promotion always ingests into Synapt. The stand-in adapter moved to
`tests/synapt_stub.py` as a unit-test double. Removed `scripts/test_live_nim.py` (it needed fixture Synapt),
the "switch to fixture mode if the network fails" step in the presentation script, and the per-script
`SYNAPT_MODE` guards that could no longer fail. New tests in `tests/test_synapt_required.py` pin the
requirement.

## Why this approach
The project is built on Synapt and is presented to the company that makes it. A mode that quietly runs on
canned procedures can be mistaken for the integration, and a demo that falls back to it proves nothing about
Synapt. The existing live adapter already failed closed (no brief, "no fallback was used"); this removes the
remaining way to run without it.

## Why not the alternative
Keeping the fixture mode as an explicit, labelled offline demo was rejected: it is still a path in which the
application works without Synapt. `AGENT_MODE=fixture` is unchanged; it replaces only the NVIDIA model-written
brief, and the evidence still comes from live Synapt.

## Known limit
Anything that builds `Settings()` now needs the Synapt login, including the data-download and training steps of
`bootstrap.py`. Runs saved before this change keep their original `mode` value (`fixture` for 10 of them); they
are history and are not rewritten. The local history fallback (a small JSON sample or built-in rows when the
100M-row Parquet file is absent) is about historical claims, not Synapt, and is unchanged.

# A better corpus in a new provider: profile cards — 2026-10-09

*Superseded on 13 October 2026: the cards were removed from Synapt and past claims moved to its ticket store; see
[that entry](#past-claims-moved-from-cards-to-synapts-ticket-store--2026-10-13). The provider `synapt_capstone1` is still the one in use.*

## What I did
Measured how the 100 million claims map onto claim cards, built a new corpus from that measurement, and
uploaded it to a new empty provider, `synapt_capstone1`, which the application now uses. A card only describes
a claim through bands, so there are 110,093 distinct descriptions among 72.2 million eligible claims. The new
corpus has one card per description, most common first within each claim type, 2,000 per type, each carrying
the size, approval share and median days of its whole group. It is built by `scripts/build_profile_corpus.py`
(`claims.corpus.profile_cards`), analysed by `scripts/analyze_card_coverage.py`, and verified from Synapt's graph
(20 of 20 batches, 5 of 5 procedures). `bootstrap.py` now builds and uploads it. The old provider is untouched.
I also added a `coverage_assertion` validation check so a brief can never say a claim is or is not covered.

## Why this approach
Random and equal-per-group sampling repeat descriptions (a third of a random 20,887-card sample) and waste cards;
volume-first covers 63% of claims with 10,000 cards where a random 10,000 would cover 41%. An equal 2,000 per
claim type costs 2.6 points overall against ranking everything together but lifts business from 43% to 63%.
Retrieval on the new provider is 3.2x chance on claim type against 1.7x before. The build is reproducible, which
the earlier first batch was not.

## Why not the alternative
Uploading the whole dataset is impossible (about a million uploads, years of extraction) and pointless (about 650
claims per description on average). Adding to the old provider is not possible: it cannot be cleaned and the
uploader refuses it.

## Known limit
Coverage means an exact description has a card; semantic search also finds near matches. The retrieval gain
mixes several changes and rests on one run of 60 queries. The profile statistics are stored in Synapt but the
application does not use them. The old provider keeps its leftover probe documents.

# Degraded-mode fallback, evaluation progress and a card audit — 2026-10-10

## What I did
**Fallback.** At the owner's request, so a demonstration survives a beta outage, a Synapt failure no longer ends the run
when a local copy exists: `claims.retrieval.fallback.LocalKnowledge` serves the five procedures and a local semantic index of the
10,000 cards, and the run is labelled `degraded` everywhere (`tests/test_fallback.py`, 9 tests). This reverses the earlier
"no fallback" decision of 9 October. Synapt is still required by `Settings`, still tried first, and no setting selects the
fallback. **Evaluation.** A run can start in the background and report progress (`EvaluationService.start`, the step list,
an activity log); the page polls it, shows an overall verdict that says whether the judge ran, and no longer re-renders
the whole page every second. **Stage count.** The Connection page said 7 stages and Explainability said eight; both now
read the one UI list, and a test ties the workflow, explanation, observability and UI lists together. **Model cards** state
the gain over the baseline and list the candidates compared.

## Why this approach
The fallback is a safety net with visible labels, not a second mode, so it cannot be mistaken for the Synapt integration.
Evaluation took minutes with no sign of life and showed the judge's result below a large rule-based "4/4 passed", which
read as if the judge had not run. A new `.verdict` CSS class collided with the brief page's tile grid and overlapped text;
the class is now `eval-verdict` and a test guards it.

## Found while checking
An audit of 6,733 of the 10,000 uploaded cards found 163 (2.4%) with the region token rewritten by Synapt's PII masking
(`regionkey_xx` became `regionkey_[LOCATION_…]`); the graph check cannot see this because Synapt records lengths before
masking. Each returned chunk also ends with the next card's header, so the application's semantic candidates and the
published retrieval figures counted unrelated neighbours; fixed in code and the figures corrected. The profile sentence
says "settled claims in the dataset" but counts the 88% settled before 2026. The console can delete a document, but not a card.

## Known limit
The fallback ranks the same cards but is not Synapt: its numbers are measured separately and it embeds only each card's
description. A degraded run takes about ten seconds longer because Synapt is retried before the fallback answers.

# Cohort statistics panel — 2026-10-10

## What I did
Added `claims.history.cohort`. For each investigation it computes exact figures for past claims with the same description as the
new claim, from the full Parquet dataset with DuckDB in one pass: the exact description cohort, the same type, amount and
prior-claims bands in any state, and the whole claim type. The run stores the result as `cohort`, the trace records it as
a `cohort.statistics` span, and the Comparisons tab shows "How claims like this were settled" above the similar cases.
Synapt contributes only an optional cross-check: how many of the card IDs retrieval already had describe a claim in the
same cohort. It makes no new request, and its label follows the bundle mode (Synapt, or the local fallback copy when the
run is degraded). The figures are display-only: never evidence, never cited, never given to a model.

## Why this approach
The cards in `synapt_capstone1` carry an approximate group profile (size, approval share, median days, taken from the
nearest cards and worded "settled in the dataset" although it counts claims settled before 2026), and a corrected
description-only corpus would leave it out altogether. Either way, exact cohort numbers are better computed from the
dataset at query time. Keeping them out of Synapt and out of the evidence keeps
the two roles honest: Synapt supplies cited procedures and a meaning-based lookup, DuckDB supplies counts about the
dataset, and a reader can tell which is which. Three cohorts from one scan show how far a single description is from the
broader groups without another query.

## Why not the alternative
Writing the counts into the cards or the evidence list would make Synapt the source of figures it does not compute and let
a language model cite them. Asking Synapt for counts would add a request per claim and still need DuckDB to check them.
Sampling would make the figures approximate, which a handler cannot check against the dataset.

## Known limit
* The cut-off is 1 January 2026, the same cut-off as the profile cards. Claims that closed later, and claims still pending
  or under review, are not counted, so the figures describe settled history only.
* The fraud figure is the dataset's synthetic flag: a synthetic label, not proof of fraud.
* Cost: on the 100-million-row file one cohort query took 5.9 s on the first (cold) call and 3.2 to 4.1 s after that. It runs
  on every investigation, so it adds about 3 to 6 seconds to each; evaluation runs pay it per claim. The interactive case
  search (`/api/search`) skips it (`retrieve_context(..., with_cohort=False)`), because it holds the service lock.
* A cohort under 30 claims is shown as too few claims for a stable figure, not hidden.
* Runs saved before this change have no `cohort` and show no panel.

# Claim-sentence intake with a model reading pass — 2026-10-10

## What I did
Replaced the three-step intake wizard with a paste-first page: a "What happened" box above one sentence whose blanks are
the claim fields, margin notes (reporting delay, net exposure, missing evidence), "Compare against" chips that map to
the existing search filters, and a "What gets sent" preview. A deterministic local reader (`lib/readNotes.ts`) fills the
blanks as the handler types; a model pass (`POST /api/intake/extract`) refines them, each value tied to a quote that the
server has checked against the notes. The old all-fields form is still available as "Use the full form".

## Why this approach
Most handlers start from an email or a call note, so reading the notes into the form removes retyping, while the sentence
keeps every value visible and one click from correction. Showing where a value came from (notes, model, handler) and the
quote behind it lets a handler glance instead of re-checking. The quote rule makes the model's reading checkable: a
value the notes do not contain word for word is dropped, so an invented figure cannot reach the form.

## Why not the alternative
Letting the model fill the form silently, or submit on its own, would hide where values came from and put an advisory
reading in front of the human gate. Relying on the model alone would leave the form empty whenever it is offline; the
local reader works without it. Keeping the wizard added steps without making errors easier to see.

## Known limit
* The local reader is pattern based: it handles ordinary phrasing ("no prior claims", "$1,000 deductible",
  "March 3", "8 months") but not every way of writing a claim. The model pass covers more, and anything either misses
  is a blank the handler fills.
* "No" within about 40 characters before a document name marks it as missing, so "No photos at first, but she later sent
  photos" reads as missing until the sentence is split.
* The outcome control labels the default as "Settled" (approved or denied), because that is what the search does when no
  outcome is chosen.
* The model pass is optional and silent on failure; in `AGENT_MODE=fixture` it returns a minimal deterministic reading.

# Judge model calls traced, and an Evaluation runs view in Observability — 2026-10-10

## What I did
The evaluation suite's LLM judge scored each case's brief after that investigation had ended, outside any trace, so its
model calls (and the evaluation run itself) never reached Observability: they were saved only as audit events and shown on
the Quality page. Now each judge metric is a `judge.metric` span, and its model calls are `llm.judge_metric` spans, recorded
under the case's own run (`telemetry.resume`, `Store.root_span_id`) and flagged as background, so a run's duration and stages
do not change. Observability has a third tab, **Evaluation runs** (`GET /api/observability/evaluations`, administrators
only): per run, the golden cases, the judge status and model, metrics scored and met, mean score, judge model calls (count,
tokens, model time), duration, and buttons that open each case's trace. Evaluation reports now also carry `started_at` and
`finished_at`.

## Why
A reviewer asked why judge reviews done during the day were missing from Observability. Part of the answer was that some
had been run on scratch copies of the app with their own databases; the real gap was that judge metric calls were not traced
at all. A quality check that cannot be seen in the page built to show it is a weak story.

## Known limit
* Evaluations saved before this change have no timing and no traced judge calls; the page says "Not traced" instead of
  showing zero.
* The judge's tokens now count towards the case run's token totals and appear as their own purpose ("Evaluation judge"),
  so tokens per evaluation query are higher than before; handler queries are unaffected.
* Metric scores are listed as saved. On the 10 October evaluation the Contextual Relevancy metric met its threshold on 0 of
  4 cases (mean 0.30), so that run is "Not passed" overall even though all 4 golden cases passed.

# Editable last look before an investigation starts — 2026-10-10

## What I did
The intake's final dialog ("What gets sent") showed the request as a block of JSON. It now shows every value as a labelled
box that can still be changed: claim type, state, amount, deductible, both dates, tenure, earlier claims, documents
(comma-separated), the description, and the comparison filters (type, state, outcome, amount range, earlier-claims range)
with the plain-English caption under them. Edits go through the same paths as the sentence behind it, so the sentence, the
"Same …" chips and the request stay in step; required boxes that are still blank say "Still needed", and values the notes
reader filled in carry "Read from your notes. Please check it." The exact JSON is one click away under "Show the exact
request as JSON", because the dialog's promise is that this is what is sent.

## Why
A handler reads boxes faster than JSON, and the last look is the moment to correct a value. Keeping the JSON behind a summary
keeps the promise checkable without making it the default view.

## Known limit
Editing the description in the last look does not re-run the notes reader (it would overwrite boxes just corrected); go
back to editing for that. The document box is free text split on commas, semicolons and line breaks.

# Comparison selection: two kinds of control, verified end to end — 2026-10-10

## What I did
Checked on the real 100-million-row file that every claim the search returns obeys every intake selection (type, state,
amount range, earlier-claims range, outcome), and added `tests/test_comparison_filters.py` (18 tests) for the whole contract:
each control, combinations, the "known before filing" rule, Synapt's matches obeying the selection, the Synapt request not
depending on it, and the cohort figures not following it. One inconsistency fixed: the sample-data search did not compare
the claim's own type when no type was chosen (the Parquet search always did); both now do. One wording fix: with no type
chosen the intake said "Any type" and "claims", but the search compares the claim's own type, so it now says "Same as the
claim" and "claims of the same type".

## Why
Two kinds of control (chips for what a compared claim looks like, the outcome for its status) read as one idea, and the
"Same type" chip changed nothing because that limit is always on. The honest answer needed to be written down and tested.

## Known limit
On the real file the chips rarely change the result for a common claim, because the closest 300 by score are already
same-state, near-same-amount claims; they matter when a limit excludes what the score would choose.

# Synapt knowledge graph used for every investigation — 2026-10-12

## What I did
The application only read Synapt as text passages (`trident_get_chunks`); the knowledge graph, the thing Synapt is built
around, was used only to verify the store. `claims.synapt.knowledge_graph` now reads it for each investigation: `trident_search`
finds procedure nodes by meaning, an explicit check on the claim type keeps the ones that apply, and `trident_traverse`
walks each to its ordered steps and the rules they reference. Each graph procedure is cited as evidence
(`graph:procedure:<id>`) and states the passages it was extracted from. The Evidence tab shows the procedures as numbered
steps with their links and source, and a "How these were found" list shows every search hit and why one was set aside. One
sentence was added to the investigation prompt so a requirement stated by a graph procedure is cited to it; before that a
live run cited only passages, after it three live runs (auto theft, auto collision, business) cited graph procedures and
all validated.

## Why
Using Synapt's main feature matters for a review of the Synapt integration, and the graph holds structure (ordered steps,
prerequisites, responsible roles, linked rules) that a passage search flattens. The calls are read-only.

## Alternatives not taken
* `trident_query` (answer plus graph traversal, and visible in Synapt's Explainability pages): writes episodes, so it needs
  the owner's agreement; it would also add a generated answer our validator would have to check. Offered, not built.
* Trusting the graph search alone: measured to rank the business-loss procedure above the auto one for an auto claim, so the
  applicability check on claim type is ours and is shown on the page.

## Known limits
The graph is small (9 procedures, 34 steps from 5 hand-written SOPs); the nodes extracted from claim cards (`claimref_...`,
`cohort_ee`, `regionkey_db`) are noise and are not used. It adds about 5 to 7 Synapt calls and 3 to 5 seconds per
investigation; the interactive case search skips it. A graph failure continues with passages only and says so. The step
sentences are Synapt's extraction of our own illustrative procedures, not insurer rules.

# Live view of an investigation in progress — 2026-10-12

## What I did
While an investigation runs, the page now shows what it is really doing: the eight stages, and under each the calls it makes
(passage search, graph search and walk, past-claim search, statistics, model calls), each with a running timer, a result such
as "3 procedures" and a waterfall bar. An administrator also sees the tool, the query sent, `top_k`, the model and its token
use; everyone else sees plain labels only. A run waiting for another says "queued" (investigations run one at a time).
Backed by an in-memory board that telemetry updates when a span opens (a stored trace is written only when a span closes),
a `/progress` endpoint with a cursor, and a run ID chosen by the page.

## Why
A reviewer of the Synapt integration should be able to see live retrieval happening, not a spinner and an elapsed counter
("actual stages appear after completion" was the old text). It also showed something true that nobody had seen: on a cold
start the retrieve stage took 17.6 s, mostly the DuckDB statistics and the first dataset scan.

## Alternatives not taken
Streaming over SSE or turning the investigation into a background job: both change how the request returns and need more
infrastructure; polling a cursor with a client-chosen ID keeps the request exactly as it was and survives a dropped poll.
Showing the same technical lines to everyone: the existing rule keeps vendor and model names for administrators.

## Known limits
The board is per process (a restart loses it; the page then says live steps are unavailable). A stage that never opens a
span of its own shows only its start and finish. Refreshing the page cannot resume following a run.

# Side chat: ask about the claim without changing it — 2026-10-12

## What I did
"Ask on the side" (button, or Alt+B) opens a panel beside the brief for questions about the case, like Claude's /btw: the
brief, its evidence and its checks are never touched. A router sends each question to the source that can answer it:
handling knowledge (documents to request, who does a step) to Synapt's query agent (`trident_query`); the claim's facts,
the brief, past-claim statistics, estimates and provenance to the saved run, exactly and with no model; a decision question
is declined. A mixed question gets one labelled part per source. Suggested questions are built from the run. Answers are
stored apart from the run, and an administrator sees Synapt's confidence, passages, procedures, graph and query ID while
everyone else sees the answer, a confidence word and where it came from.

## Why
Handlers have follow-up questions the brief does not answer, and most can be answered exactly from data we already hold, so
only the one kind that needs Synapt's knowledge goes there. That also makes the questions visible in Synapt's Explainability,
which the investigation itself never produces (it reads passages and the graph, not answers).

## Cost and safeguards
Synapt's documentation says it learns from the questions it answers (measured later the same day: a query alone created no
episode, feedback did). So only handling questions reach it; the question is masked and the only claim context is its type; a repeated question is answered from the saved answer; a case is
limited to 40 questions and a person to 6 a minute; a failed call is not saved, so it can be retried. Synapt's own answer is
shown as written, labelled as not checked by the brief's validation, and its low-confidence signal is shown as a note.

## Known limits
The router is rules, not a model: an unusual phrasing may reach the wrong source, so every answer names its sources, and a
question no pattern recognises but that reads like a question goes to Synapt, flagged as a fallback. Each side answer is
independent; there is no memory of the thread. Estimates and statistics describe synthetic past claims, not this claim.

# Every investigation asks Synapt's query agent once — 2026-10-12

## What I did
Each investigation now makes one real `trident_query` call (`claims.synapt.query_agent`) with a fixed question built from the claim
type alone ("For an auto claim involving theft, which documents should a claims handler request and in what order, who is
responsible for each step, and what must a human claims handler review before any decision?"), carrying the run's ID as the
`task_id`. The answer appears at the top of the Evidence tab: the exact question, what was and was not sent, the answer,
Synapt's confidence (administrators see the numbers, the query ID and the task ID; everyone else a confidence word), the
passages, procedures and graph it used, and where to find the call in Synapt's Explainability. Confidence words now follow
Synapt's own Retrieval Pass Card scale (70 and above High, 40 to 70 Medium, below 40 Low), and the three numbers are named
as the Pass Card names them (knowledge store, procedure store, context graph).

## Why
The owner asked for it: Synapt's reviewers will check their Explainability pages, which list the query agent's answers.
Before this an investigation read passages and the graph directly, so it never appeared there and the intake was never sent.

## Safeguards
Only the claim type (and a bare "involving theft") goes out, never the narrative, names, amounts or dates. The answer is
display only: never evidence, never cited by findings, never given to the brief's models, not covered by its validation. The
call runs beside the rest of retrieval (6.9 s inside an 18.9 s stage), a failure leaves one sentence and the brief intact, and
evaluation runs, the interactive search and degraded runs make none, in case Synapt records episodes from queries.

## Known limits
A query alone created no episode on 12 October, but a handler's feedback on it does, so rated answers accumulate as episodes in `synapt_capstone1`. The question is the same for every claim of a type, so
the answers differ little; it shows the integration rather than adding information the brief lacks. Synapt's answer can
include its own low-confidence note, which the page shows.

# Handlers rate the query agent's answer, and Synapt is told — 2026-10-12

## What I did
Under the query agent's answer (Evidence tab) and under a saved knowledge-base answer in the side chat, a handler can choose
Yes, it helped / Partly / No, with an optional note. The choice is sent to Synapt with `trident_feedback`
(`claims.synapt.query_feedback`), mapped to Synapt's verdicts `deflected`, `partial` and `not_deflected`. The query ID is looked up
from the saved run, never taken from the request; one verdict per answer; nothing is saved unless Synapt accepted it.

## Why
The owner approved using `trident_feedback`. It is the call Synapt's documentation ties to its learning loop, and measuring
showed it is the one that creates an episode (queries alone did not), so this is what makes the integration two-way: the
application reads from Synapt and tells it whether the answer helped.

## Safeguards
The tool has no provider field, so the arguments are validated against the schema the tenant advertises and the response must be
`accepted: true`; the note is masked; the send is attempted once, never retried automatically; the brief is untouched; the
page shows the plain choice and only an administrator sees Synapt's wording or the query ID.

## Known limits
Every accepted click is a permanent lived episode in `synapt_capstone1` (no way to delete one is known), so demonstrations
should rate a few answers, not many. Whether Synapt's Explainability page shows the feedback beside the query was not known
when this was written.

# Twelve more handling procedures, applied by the facts of the claim — 2026-10-12

## What I did
The owner asked for good procedures. `claims.corpus.procedures` authors 12 illustrative procedures as ordered steps (each with a
prerequisite and a responsible role, a stated applicability and a boundary), uploaded once each to `synapt_capstone1`: provider
documents 25 to 38 (the 38th is Synapt's own episodic document), procedures 9 to 21, steps 34 to 93. Four apply only when a
fact about the claim is true (filed more than 30 days late, $50,000 or more, three or more earlier claims, policy under a
year) and the water damage one only when the narrative mentions water. So `knowledge_graph` now works out the claim's **fact
cues**, searches once per cue, and keeps a conditional procedure only when its condition is met; the search is wider (15 hits)
because the procedures are worded alike.

## Why
The graph held 9 procedures from 5 paragraphs, too little for a Synapt reviewer to see a knowledge graph doing work, and a
generic procedure list for every claim would have been noise. Conditional procedures make the Evidence tab differ by claim.

## Safeguards
Every document is labelled hand-authored synthetic, says it is not an insurer rule or legal requirement, and leaves every
decision to a human claims handler. The thresholds are those the application already uses to point a claim out. Nothing is
cited unless the live graph returned it; the store check now expects 17 procedures.

## Known limits
The cue check is ours (Synapt's search ranks by wording), and a narrative that describes a theft or a leak in unusual words is
missed by the keyword cues. The procedures are illustrative, not an insurer's. One of the twelve, the fraud-flag review signal
procedure, is in the graph but no investigation retrieves it: the signal is computed after retrieval, so it is never a search
cue. Using it would need a second graph lookup after the models run.

# The Connection page shows what the knowledge base holds — 2026-10-12

## What I did
`claims.synapt.stats` reads `trident_get_stats` and `trident_episodes` (inspect, writes nothing) and the Connection page
shows documents, passages, graph nodes, connections, procedures, steps, entities, episodes and the graph's contents by kind.
Cached for 60 seconds; administrators only.

## Why
The owner thought it cheap and good to have: a reviewer sees the size of the knowledge base the application relies on without
opening the Synapt console.

## Known limits
An unreachable Synapt shows a sentence (and the last known figures, marked stale), not an error. The figures are Synapt's, not
ours, so they change when the provider changes.

# A 2,000-ticket workbook for the larger ticket-store test — 2026-10-12

## What I did
`scripts/make_ticketing_sample.py` gained `--natural` (do not over-sample the fraud flag) and `--name`, and wrote
`artifacts/synapt/ticketing-2000/claims_tickets_2000.xlsx`: 2,000 settled claims, 400 per type, the 16 columns the first trial's second
upload accepted. `scripts/ticket_label_trial.py` can now exclude a workbook of any size from its held-out set.

## Why
The owner will upload tickets through the console and asked me to build them. The first trial (300 tickets, 48 neighbours) returned
the majority label; a few-thousand-ticket store was the untested case. I used claims from the dataset rather than reviewed briefs:
only 2 of 75 saved investigations carry a handler's review, and a label from the application's own output would be circular.

## Safeguards
Policy IDs never appear; ticket IDs are the card aliases; the text Synapt embeds carries no outcome or label word (read back and
tested). The fraud flag is a synthetic dataset label, as in the first workbook, and can be left as store-only.

## Known limits
At natural rates the majority classes are 89 % (approved) and 95 % (not flagged), so a label that matches the baseline shows no signal.
The upload goes to a separate ticket provider; whether Synapt takes 2,000 rows promptly is unknown (300 rows worked).

## Result (added the same day)
The owner uploaded it as provider `ticket_mining` (2,000 tickets, 400 held out by Synapt, labels `fraud_flag` and `resolution`). Synapt's own
held-out accuracy (top-1 95.8 % and 89.5 %) is within a point or two of the majority rates (94.8 % and 89.1 %), and our 100-claim
trial matches the baseline exactly (0 of 21 denied and 0 of 20 flagged found, AUC 0.58). Decision unchanged: no Synapt-predicted outcome
or fraud card. The ticket store stays a tested integration, not a feature. *(Superseded on 13 October 2026: the same 2,000 rows
now form the ticket store of `synapt_capstone1` and supply similar past claims; the labels are still ignored. See
[that entry](#past-claims-moved-from-cards-to-synapts-ticket-store--2026-10-13).)*

# Side-chat routing and the water-damage cue, fixed after a test pack — 2026-10-12

## What I did
Running a pack of new test questions through the side chat's router offline found eight that went somewhere questionable. Fixed:
a coverage question ("does the wear-and-tear exclusion apply") and an offer question ("how much should we offer") are now
declined as decisions; "is the claimant telling the truth" is declined like the other fraud judgements; "how many days passed
between the incident and the filing", "any claims from this state in your records" and "how confident is the amount model" go to the
saved claim, the past-claim figures and the estimates instead of Synapt. A new kind, **outside**, answers weather and other
events in the world, and a person's phone, address or identity details, with "not something this tool holds" rather than the
claim's dates or a guess. A state question is answered from the closest comparison cases and says what that does not show; a
confidence question explains what the 90% interval means. In `knowledge_graph`, the water-damage cue no longer fires on "pipes" alone:
a plumbing word now needs a failure with it (burst, failed, cracked, froze), so "copper pipes stripped from a rental" is not water damage.

## Why
The owner asked for test claims and questions outside the dataset and then asked for the findings to be fixed. Of the questions
that reached Synapt, the legal-deadline and other-insurer ones were left routed there on purpose: asked live on 12 October, its query
agent answered "not available in the provided context" for both, which is the honest answer, so no local decline was needed.

## Safeguards
Each fixed question is a row in `tests/test_sidechat.py`, with near misses that must keep their old route; the cue has positive and
negative cases in `tests/test_knowledge_graph.py`. A decision, outside or unknown question never reaches Synapt.

## Known limits
The router is still rules, not a model: an unusual phrasing can reach the wrong source, and every answer names its source. The water
cue is still keywords.

## Found by the live questions (added the same day)
Asked on the live app, three more answers were wrong or noisy and are fixed: a claim below its deductible showed a negative net amount
(now "$0.00 (the claimed amount is $120.00 below the deductible)"); a question about claims "over $50,000" was answered with the
exact-description group and no word that the figures cannot be re-cut (now it says so); and the bare word "claimant" pulled the whole claim
record in beside a handling answer (it now counts only when nothing else is recognised). Also: the full-suite failure seen once in
`test_a_person_never_sees_synapts_name_...` was the question's microsecond timestamp containing "0.76" by chance; the test now ignores timestamps.
Not fixed, and reported: of 17 in-scope live investigations 10 were clean, 6 went to manual review (4 from the model citing "limitation" or
"findings" as a source ID) and 1 failed; a run takes 27 s at the median, 16 s of it retrieval that runs one step after another.

# Faster retrieval, citation repair and a deadline for stalled Synapt calls — 2026-10-12

## What I did
Three changes after 20 live runs showed a median of 27 s per investigation and only 10 of 17 in-scope runs clean.
1. **Retrieval overlaps.** The DuckDB cohort scan starts at once, the graph lookup and the query agent start when the passages are in,
   and the past-claim search runs beside them (`Service.retrieve_context`, `claims.history.cohort.cohort_statistics(late=...)`). Measured on live
   runs: retrieval median 12.3 s (9 to 17) instead of 16.1; the whole investigation median 25.4 s instead of 26.9, with a best case of 17 to
   20 s. Most of what is left is the two model calls, which varied from 2 to 20 s.
2. **Citation repair** (`claims.agents.stage_agents.repair_citations`). Four of the seven non-clean live runs had one cause: on the "verify applicable
   policy terms" recommendation the model wrote the word "limitation" or "findings" in `source_ids` instead of an evidence ID, so the
   brief failed the mechanical citation check and went to manual review. A kind-of-finding word now becomes what that kind of finding cites
   (a limitation cites nothing by design, so it becomes the submitted claim), and an ID that an evidence item's text names, such as a
   passage a graph procedure was extracted from, becomes that evidence item. Each repair is written to the audit log as `citation_repair`.
3. **A deadline for stalled Synapt calls, and not waiting out their clean-up.** In 314 recorded fast calls (passage search, graph search,
   graph walk) about 2% stalled for about 18 s and then succeeded at once on a retry, which made 4 of 10 runs take 40 to 60 s. A
   passage-search or graph-lookup attempt now has a 12 s deadline (`SYNAPT_FAST_ATTEMPT_SECONDS`) and, when it misses it, is **abandoned
   rather than awaited**: a first version with a per-call deadline still lost 19 s once, because cancelling a stalled call made its session
   wait for the transport to give up. The query agent, which takes 6 to 13 s, keeps the 20 s deadline.
4. **The brief does not wait more than 12 s for the query agent.** Its answer is display only. A slow Synapt took 30 to 48 s to answer
   on 12 October, and retrieval waited for it. Now the brief goes ahead, the panel says the answer is still being written, and the answer
   is attached to the saved run when it arrives and picked up by the page (`Store.set_query_agent`, the same pattern as the judge's verdict).
Also: a failed model call now records where its output failed validation (field paths and rule names, never the content), so a
repeated failure like the injury claim's can be diagnosed.

## Why
The owner will show a live investigation to a review panel and asked for the latency and the citation failures to be fixed.

## Safeguards
The repair is narrow: a source the model made up is **not** repaired and still fails the check. The overlap is tested with events rather than
clocks (`tests/test_parallel_retrieval.py`): the scan starts before the passage search ends, the graph call runs while it is busy, the evidence
order is fixed, a failed graph lookup is reported, and a failed retrieval does not leave the scan waiting. The deadline is tested with a stall
that clears on retry and one that never clears (`tests/test_knowledge_graph.py`).

## Known limits
Retrieval cannot go below the two DuckDB queries (about 9 s) or the query agent (about 7 s), because DuckDB runs one query at a time on a
connection. A stall that lasts longer than one retry still costs time. The document-wording check ("attached", "provided") that sent two runs
to manual review is not changed.

# Faster again: everything starts at once, exact figures from small tables, a page that shows parts as they land — 2026-10-12

## What I did
The owner asked for the speed-up plan to be built in the order proposed. A typical investigation went from 25.4 s to about 16 s (median 16.3 s,
12.7 to 23.4 in the last batch of ten live runs; retrieval 5.6 s, was 12.3).
1. **The query agent starts at t=0 and the brief never waits for it.** It needs only the claim type; the passages in the evidence are marked
   when its answer comes back. When the brief is ready it gets up to 12 s more (it has had the model stages to finish), then a background
   thread attaches the answer if it still has not come (`settle_query_answer`).
2. **The graph lookup starts at t=0** beside the passage search. A run that falls back to the local knowledge base ignores the graph and the
   answer that were asked for before the outage was known.
3. **The graph lookup's calls go out together** (3 searches, then up to 6 walks) instead of one after another.
4. **The models write less**: at most 8 findings of one sentence and 5 actions with short reasons; output fell from about 456 and 246 tokens to
   400 and 155, and the two model stages from 6.4 + 4.6 s to 4.4 + 2.6 s.
5. **The exact cohort figures come from three small tables** (`claims.history.cohort_summary`, `scripts/build_cohort_summary.py`): 4 ms instead of 4 to 10 s.
   Built in 28 s; 30 random descriptions compared with the full scan (0 differ); the application uses it only if it records this dataset's SHA-256,
   the cutoff and the band edges, otherwise it scans as before.
6. **The 300-closest-claims search starts at t=0** (`history.candidates`); the semantic matches are added when the passages are in.
7. **The page shows what has landed** while a run is going (`GET /api/investigations/{id}/preview`, `BriefPreview`): the first section after
   about 6 s, findings and priority at about 11 s, the finished brief at about 14 s, with a note that it is not yet the brief.

## Why
The owner will show a live investigation to a review panel and asked for the latency to come down in that order: the low-risk changes first,
then the DuckDB speed-up and the progressive display.

## Safeguards
Nothing changes an answer: the summary is compared with the scan at build time and in tests (every group of a test dataset, and the percentiles
against `quantile_cont`), and is refused for any other dataset; the candidate pool gives the same rows in the same order with or without
prefetching (tested); a degraded run ignores what was asked for early; the preview is built from the role-filtered run, so a person never
sees the vendor's name, and only the owner or an administrator can read it. The overlap is tested with events, not clocks.

## Known limits
Passage search is still about 3 s (mostly Synapt session setup) and the DuckDB search for the 300 closest claims 3 to 5 s. A copy of the dataset in
DuckDB's own format, sorted by type and state, did that search in 1.4 s (measured: 2.6 GB, a 5-minute build) and was not adopted. The model calls
vary with the provider's load. The figures are ten live runs on one afternoon.

# The sorted native copy of the dataset, adopted — 2026-10-12

## What I did
The owner approved the 2.6 GB and the 5-minute build I had measured and not adopted. `scripts/build_claims_copy.py` writes the dataset in DuckDB's own
format, sorted by type, state and amount, with each claim's closing date stored once (`ClaimsStore.build_copy`); the search for the 300 closest past
claims reads it when it belongs to this dataset (`attach_copy`: SHA-256, row count, layout version). It was built in 522 s (the machine was also
running tests) and verified against the Parquet file on 18 random searches: 0 rows or orders differ. The span `history.candidates` fell from a median of
2.7 s to 1.3 s (0.6 to 2.2 s). A lookup by claim ID stays on the Parquet file, whose row-group statistics find an ID without a scan; a background read
at start-up warms the copy (a cold first search took 4 s).

## Why
After the earlier changes the DuckDB search was the longest step of retrieval that the application itself controls.

## Safeguards
Same rows in the same order, checked at build time and in `tests/test_sorted_copy.py` across ten filter sets and a sweep of filing dates that
crosses the days claims close (the comparison is strict: "settled before the new claim was filed"); a copy for another dataset, layout or row count
is refused; with no copy the Parquet file is searched exactly as before. `data/derived/` is git-ignored.

## Known limits
In the last batch of ten live runs the whole investigation took a median of 19.5 s (14.6 to 24.6), not less than the 16.3 s of the batch before, because
Synapt and the model provider were slower that afternoon (passage search 4.1 s against 2.9, classification 1.6 s against 0.9, recommendation 6.1 s
against 2.9): the copy took DuckDB off the critical path, and what remains is what the providers do. All ten briefs were clean. The copy has to be rebuilt if the
dataset file changes (the app then ignores the old one).


# Named agents with role-based tool access, and the retrieve stage as a LangGraph graph of agents — 2026-10-12

## What I did
The owner pointed out that the project had become all about Synapt and that its agents, with roles, prompts and tool access that matches
each agent's job, were missing. Before the change the investigation was a LangGraph graph of eight stage nodes; the model-backed stages
were single structured calls and every Synapt call was made by one shared piece of code with no notion of who was asking. Now:

* `src/claims/agents/roster.py` defines ten agents (and three other actors that can reach Synapt: the operator, the ingestion job and the human
  reviewer) with a role, a purpose, a tool list and, for the model agents, a written role prompt.
* `src/claims/agents/access.py` checks every tool call against the acting agent's list, failing closed: a call with no acting agent, or for a
  tool outside the list, is refused, counted on the agent's span and recorded as an `access.denied` span. `AccessDenied` is not a
  `SynaptError`, so a policy refusal is never retried or answered with the degraded fallback. Only the three retrieval agents hold
  Synapt tools; no investigation agent holds a write tool (ingestion belongs to the ingestion job, feedback to the human reviewer).
* The retrieve stage is now a LangGraph graph of its own (`src/claims/retrieval/graph.py`): four agent nodes that run side by side and a
  join node. `retrieve_context` keeps its signature and result, so the speed work (everything starts at t=0) is unchanged.
* Each model agent's system message starts with its own role, then the rules every agent follows, then its task.
* The live page shows the agent team working; the Explainability page shows who did the work; a new Agents page draws the compiled
  graphs, the cards and (for an administrator) the access matrix. Agent spans carry the tool-call counts.

## Why
For an interview about deploying agents, "which agent may touch what, and how is that enforced and audited" is the question; the answer
should be in the code and the trace, not in a slide. The enforcement is where each tool is called, so it cannot be skipped by adding a
caller.

## Safeguards
`tests/test_agent_roster.py` (30 tests): every tool an actor holds exists, exactly the three retrieval agents hold Synapt tools and each
holds only its own, no agent holds a write tool, each model agent receives its own role, the check refuses at the adapter before any
call is sent, a denial is not an outage, and a whole run records the right agent on every model call and Synapt call. A live run on 12
October (Synapt and the model provider both live): the Policy Passage Retriever made 2 `trident_get_chunks` calls, the Procedure Graph
Navigator 2 `trident_search` and 5 `trident_traverse`, the Knowledge Q&A Agent 1 `trident_query`; nothing was refused.

## Did the role prompts change the quality of the briefs? An experiment, and what it can and cannot say
The first live pack after the change looked worse (validation 8 of 10, judge pass 4 of 8 completed, against 10 of 10 and 9 of 10 before),
and I first put that down to the new role prompts. That was a guess, so I ran the 20-claim live pack (live Synapt, live models, evidence
checked identical to before) with four configurations. Results, validation passed / judge passed of those completed:

| Configuration | Validation | Judge | Median investigation |
|---|---|---|---|
| no role prompt (first run) | 15 / 20 | 17 / 18 | 13.0 s |
| no role prompt (the same, repeated) | 16 / 20 | 11 / 15 | not recorded |
| a minimal role ("You are the Investigation Agent. You hold no tools.") | 15 / 20 | 10 / 15 | 12.7 s |
| the descriptive role used now | 14 / 20 | 12 / 17 | 14.8 s |

The repeat of the identical no-role configuration scored 11 of 15 against 17 of 18 the first time, so run-to-run variation (the judge
model and the providers) is as large as any difference between configurations. The honest reading is: no effect of the role prompts is
detectable at this sample size, and the earlier suspicion was wrong. The descriptive role is shipped. Any future prompt change should
be judged on more runs than 20, not on one pack. The one failed run (B9, an out-of-scope claim) was the recommendation model's output
failing validation twice, which this application reports as a failure by design (no fixture fallback).

## Known limits
Two behaviours changed. Passage retrieval no longer asks Synapt's query agent when the passage search comes back empty (the retriever does
not hold that tool, and the query agent writes answers, not evidence). A nested LangGraph graph inherits its parent's checkpointer
unless compiled with `checkpointer=False`; the retrieve graph is. The model agents still make single structured calls and choose no
tools. Per-agent identities at Synapt (the Agent Connector) are not built: the public docs do not describe it, the client IDs can be
configured and are reported as set or not, but every Synapt call is still made with the one configured login. See `docs/AGENTS.md`.


# A model inside the three agents that read Synapt — 2026-10-12

## What I did
The owner asked for the agents that talk to Synapt to be LLM agents, wired into the existing ones (so the identities to register in the
Agent Connector, the tool limits and the LangGraph nodes stay as they were). Each of the Policy Passage Retriever, the Procedure Graph
Navigator and the Knowledge Q&A Agent now runs its standard work first, exactly as before, and then a model holding only that agent's
tools may add to it (`src/claims/retrieval/agents.py`, `src/claims/agents/tools.py`, `CompletionClient.chat_with_tools`):

* the Passage Retriever's model may search once for passages the standard queries missed and keep up to four;
* the Graph Navigator's model may search once for a kind of procedure the standard searches missed and read up to three that fit;
* the Q&A Agent's model writes the one handling question, from the claim's type and conditions only.

The pattern is that a model proposes and the application disposes: searches are 2 to 14 plain words that cannot contain numbers,
symbols, personal data or any name or place from the claim; a procedure still has to pass the applicability rule; passages still pass
the provenance checks; a tool the agent does not hold is refused and recorded; after one look-around the model can only choose; the
whole step has a time budget (8 s); and if it fails the standard result stands. When the model searched and nothing that fits the claim
exists, the graph panel records it (a first version also put a limitation in the brief; see below).

## Why
So that the agents that connect to Synapt use a model to decide something, while the guarantees (what is sent to Synapt, what counts
as applicable, what is cited) stay in code. Wiring the model into the existing agents, not adding a new "evidence agent" with all three
tools, keeps least privilege and the three identities.

## Safeguards
`tests/test_agent_tools.py` (34 tests): the query and question guards, the loop (a forbidden tool is refused and recorded, a failing
tool does not stop the run, the round and time limits), the transport (tools offered, thinking off, malformed arguments retried then
refused), and each follow-up including that a model failure leaves the standard result untouched and that only the claim's type and
conditions reach the question writer. Stand-in adapters without the new reads, fixture mode and `AGENT_LLM_RETRIEVAL=false` never call
a model, so the existing 790 tests are unchanged.

## A mistake the live pack caught
The first version added a limitation to the brief when the model's graph search found nothing that fits ("the knowledge graph holds no
procedure that fits ..."). On the 20-claim pack on the new key it appeared in 7 briefs, and in most it was wrong: the standard search had
already read the relevant procedure (a water-damage claim got "no procedure fits 'water damage claim procedure'"), because the model's
search returned other documents. Only the pet-insurance claim was a true case. It was removed; the model's search is shown on the graph
panel only. In the same run the follow-ups added nothing in 20 of 20 runs for either agent, and were `unavailable` (the 8 s budget, or
invalid output) in about 38 percent.

## Known limits
Measured live on 12 October: on ordinary claims the model found nothing to add in 4 of 4 runs (the standard searches already cover
them); on out-of-scope claims (a pet, a boat, a premium refund) it searched sensibly and correctly found nothing. The step added about
3 to 6 s to a run, and one model call took 29 s before the time budget was added. No pack result yet shows a better brief; the value
today is the behaviour on odd claims and the demonstration of bounded, guarded model autonomy, not a measured quality gain. The History
Analyst, Risk Analyst and Validator stay deterministic on purpose.


# A shared model request budget, and why GLM 5.3 flash is not the model — 2026-10-12

## What I did
Two live runs of the 20-claim pack with the model follow-ups on failed almost entirely (18 and 19 of 20 runs) with HTTP 429 from NVIDIA
NIM on every model call, the brief's classification included. The follow-ups add 3 to 5 model calls to a run, and a failure of an
optional call must never cost the brief its own. `claims/llm/ratelimit.py` now keeps one sliding one-minute budget per provider endpoint
(`LLM_REQUESTS_PER_MINUTE`, default 36; 0 switches it off): the brief's calls wait for a slot, and an agent's optional follow-up calls are
skipped once only a reserve (`LLM_OPTIONAL_RESERVE`, default 10) is left. A 429 now waits as long as the provider's `Retry-After` asks
(at most 10 s) instead of half a second.

The owner also asked to use `z-ai/glm-5.3-flash` for every model call, the judge included. I measured it before switching: a 100-token
classification took 25 to 44 s (the writer model takes about 1 s), a 1,400-token answer 87 s (about 16 tokens a second, reasoning
included, and the reasoning cannot be switched off: four request variants tried), tool calls 33 to 37 s, and the investigation call
timed out at 120 s and then returned HTTP 504 from the provider's gateway. A full run on GLM for everything failed after 277 s. The
owner chose to keep the current models for now; GLM stays selectable by setting (the model, judge and intake timeouts now go up to
900 s). With the same model as writer and judge the judge would not be independent, and the application would say so.

## Safeguards
`tests/test_ratelimit.py` (8 tests, with a fake clock): optional calls yield first, essential calls get the reserve, a full window
makes essential calls wait or go ahead rather than start a 429, the window forgets old requests, `Retry-After` is honoured, and a refused
optional call sends nothing. The unit-test configuration switches the budget off so that bursts of mocked calls never wait for it.

## What the 429s turned out to be
I first suspected the follow-ups. A paired run (follow-ups on, then off) failed 18 of 20 in both, and a direct probe showed the key was
throttled hard regardless: with one tiny request a second, the 4th was already refused and about 11 of 40 succeeded (about 15 a minute,
against 25 to 30 a minute the application had made hours earlier without trouble). The owner then changed the key; the same probe on the new
key refused its first request only at the 32nd (about 30 to 40 a minute). So the failures were the provider's limit on the old key, not the
follow-ups. What the application can do about a limit it does not control: the brief's calls now wait out a 429 (3, 6, then up to 10 s,
three times) before failing, and the budget adapts, halving on a 429 down to 6 a minute and creeping back up after eight successes, so a
throttled key makes investigations slower instead of failing them.

## Known limits
The default budget (36 a minute) matches the new key's observed limit, which is not published and may change. The brief's calls wait at most
20 s for a slot and then go ahead, so a limit far below the application's needs still fails runs, only later.


# The Supervisor Agent: summary, and one repair of a brief that failed fixably — 2026-10-12

## What I did
The owner asked for LLM agents that coordinate and give the final result. A new `supervise` stage (between `validate` and `judge`) is a
LangGraph graph of its own (`src/claims/agents/supervisor.py`): a Supervisor model call (no tools) reviews the finished brief and writes a short
summary for the handler, and a brief that failed the validator for something rewording can fix is sent back once to the Investigation
Agent with the checks' own words, the sentences they object to and the Supervisor's instructions; the Risk Analyst, Recommendation Agent
and validator then redo their work, so the brief that goes on is a checked brief. The summary appears at the top of the brief.

## Why
So that agents coordinate (hand work to each other, loop, and finish) and there is a final, readable result, in the one place where that
is safe: after the validator, with the application deciding what is allowed.

## Safeguards
The repair is policy (exactly one, only for fixable failures), not the model's choice: in the first live test a model that was shown a
fixable failure answered "finalize", so the application no longer leaves it to the model. The summary passes the same text checks as the
brief plus a no-new-numbers check, and is asked for once more if refused. `tests/test_supervisor.py` (28 tests): what counts as
fixable, each summary check, the one-repair limit, a repair that fails or does not help, a model that cannot be reached, fixture mode,
a real revision (only the investigator's findings are rewritten and everything is re-checked), and two whole runs (a bad first draft is
fixed once and ends passing; a model that says "finalize" still gets the repair). The stage lists in the explanation page, the
observability page, the preview and the UI (nine stages now) are tied together by the existing consistency test.

## Known limits
Two bugs found by running it live and fixed: the number check treated a date written two ways (2026-09-01, "September 1, 2026") as
different numbers, and the model sometimes wrote "has provided" about documents (the app's own rule forbids it), which the check now
refuses and asks to rewrite. A repair can fail to help: on 12 October one brief was fixed (an unknown citation removed) and another
traded a wording problem for an unknown citation and stayed flagged. The Supervisor adds about 3 to 5 s to a run and a repair about 15
to 20 s more.


# The backend split into packages by the work each does — 2026-10-12

## What I did
`src/claims/` held 50 modules in one folder. It is now 13 packages (`core`, `api`, `investigation`, `agents`, `retrieval`, `synapt`, `corpus`, `history`, `ml`, `llm`, `evaluation`, `observability`, `storage`). [ARCHITECTURE.md](ARCHITECTURE.md#backend-layout) lists every module with its former name. Names that only made sense in a flat folder were made clearer (`models.py` is `core/schemas.py`, `retrieval.py` is `history/retriever.py`, `agents.py` is `agents/stage_agents.py`, `corpus.py` is `corpus/builder.py`, `feedback.py` is `corpus/lessons.py`). The code in each module is unchanged. What changed: the imports, the docs and comments that name a module, and the three places that found a file next to themselves (the compiled UI, the account schema, the table of state names, which three modules each loaded and one shared module now loads).

## Why
Finding the part of the system that does something meant reading 50 file names in a row. The packages follow how the system is described elsewhere: the HTTP service, running an investigation and its agents, the retrieve stage, Synapt, the documents uploaded to it, the past-claims data, the models, the shared model transport, evaluation, observability and storage.

## Safeguards
* **Trained model files record their classes by module path.** `artifacts/models/claims_models.joblib` holds a `claims.analytics.ClaimTypeMedianRegressor`, and the feature-candidate file holds two classes from `claims.fraud_features`. With no module at those paths `joblib.load` raises `ModuleNotFoundError`, which the loader does not catch, so the application would not start. The experiment reports record the files' SHA-256, so re-saving them was not an option. `analytics.py` and `fraud_features.py` therefore stay at the top of the package and only re-export the moved classes. Removing them from a copy reproduced the failure; `tests/test_legacy_module_paths.py` keeps both paths working. Models saved from now on record the new paths.
* `uvicorn claims.api:app` still works: `claims/api/__init__.py` resolves `app` and `create_app` on first use and nothing else, so importing `claims.api.auth` does not build the app and a stale `monkeypatch` target fails instead of patching the wrong module. The documented command is now `claims.api.main:app`.
* A guard test (`tests/test_synapt_required.py`) searched the package for a stand-in for Synapt with a top-level glob. After the split that would have searched nothing and passed. It is recursive now and asserts it found the sources.
* Stored runs, checkpoints and the audit log contain no module paths (scanned on a copy of the runtime database), so nothing saved needs migrating.
* Checked mechanically: for every file in `src/`, `tests/` and `scripts/`, the imports before and after are identical once old names are mapped to new ones (the one deliberate difference is `STATE_NAMES`, now defined once in `core/us_states.py`); the code of 129 of the 134 files is identical apart from imports, and the other five are the edits above; all 828 `claims` imports resolve to a real name; ruff is clean. 871 tests pass (the 864 from before, which also passed before the change, plus 7 new), run in a copy of the repository without `.env` and without the runtime data. The frontend type-checks and its 171 tests pass.

## Known limits
`tests/` and `scripts/` are still flat folders (scripts find the repository root from their own location, and the docs name them by path). `static/` stays where `frontend/vite.config.ts` builds the UI. Line numbers quoted in `AGENTS.md` and in the reviewer Q&A were moved to where the lines are now; several in the Q&A had already drifted from the code and now point at the named function.


# Past claims moved from cards to Synapt's ticket store — 2026-10-13

## What I did
Review feedback from the panel (Synapt's company) said the data split in Synapt was wrong. Provider `synapt_capstone1` held the 17
handling procedures and 10,000 claim records written as text cards (20 documents, 501 chunks each): 38 documents, about 10,040 chunks.
2,000 settled past claims (400 per claim type) were uploaded to the same provider's ticket store through the console (Data Ingestion,
Ticketing; ID `ticket_id`; embedded `title`, `description`, `category`, `region`; predicted `resolution`, `fraud_flag`), checked, and then
the 20 card documents were deleted in the console. The provider (now kind `ticket_mining`) holds 18 documents and 39 chunks: the 17
procedures and Synapt's own episodic document; the graph keeps 21 procedures, 93 ordered steps and 93 entities. The Policy Passage
Retriever now gets similar past claims with `trident_query` and `ticket_mode="only"` (no question, no graph walk, no model) under a new,
narrow permission `trident_ticket_neighbours`; the ticket is built by `claims.corpus.cards.claim_ticket`. The 2 to 4 neighbours Synapt
names are decoded to claim IDs, looked up in the Parquet file under the handler's filters, fused as a half-weight semantic rank and can
add up to 3 claims. Chunks of Synapt's episodic document are no longer treated as evidence. `scripts/verify_synapt_store.py` checks the
procedures, the ticket store and that no large non-procedure document is left. Full description:
[SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md#how-the-data-is-split-across-synapt-corrected-13-october-2026).

## Why
The review was right, and the graph shows it: the card documents were 99.6 % of the chunks but had 55 graph links, against 135 from the
17 procedure chunks. They added almost no knowledge and crowded the procedures out of passage search. A settled claim is a case with an
outcome, which is what a ticket store is for; procedures are knowledge, which is what documents and the graph are for.

## Safeguards
The ticket store supplies identifiers only: every claim it names is re-read from the Parquet file under the handler's filters, so it
cannot bypass a filter or supply a number. The ticket labels are ignored, because the 12 October trials showed no signal over the
majority class. The retriever's new permission cannot ask the query agent a question. Live check on 13 October, three investigations
(auto, home, no claim type): each got procedure passages, graph procedures, 2 to 3 ticket-store claims and a query-agent answer; the
judge passed the auto and home briefs (0.95, 0.92) and the typeless claim went to manual review as designed. The suites stand at 905
backend and 171 frontend tests.

## Known limits
A lookup now gives 2 to 4 past claims where the card search gave up to 20, and the ticket-store lookup has not been measured against
chance as the cards were. Episode mining has not happened: the store holds 22 lived episodes from query-agent sessions and no mined
ones, and mining cannot be started over MCP (it is a console step, the Episodic Mining Dashboard), so it is not verified. The
degraded-mode fallback still ranks a local card index, which exists only on this machine. The 100 million claims stay in Parquet and
DuckDB, the authority for every number. Earlier card-corpus decisions are kept above as history.
