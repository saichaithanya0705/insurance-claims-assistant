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
| **Synapt holds a 1,000-card sample, not the dataset** | Upload everything | Ingestion is about 100 cards per call at 2 to 3 minutes per call |
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
   (`adapters.py`). Measured against the live provider, every test claim now gets four or five real
   procedures instead of zero to four. It also keeps free text out of that provider call.
2. `ClaimInput` and `SearchFilters` accept only the 50 states and DC, and a description must hold at least
   five letters after trimming (`models.py`).
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
