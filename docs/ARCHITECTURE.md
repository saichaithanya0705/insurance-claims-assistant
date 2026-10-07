# Architecture and design

![Architecture](architecture.svg)

The diagram source is [architecture.svg](architecture.svg) (a PNG render is in
[architecture.png](architecture.png)). This document explains the design behind it.

## Components

| Component | Responsibility | Code |
|---|---|---|
| FastAPI service | Authentication, CSRF, roles, strict input validation, the HTTP API, and serving the compiled UI | `api.py`, `auth.py`, `models.py` |
| LangGraph workflow | The ordered, checkpointed investigation with a human review gate | `workflow.py` |
| Agents | Classification, investigation and recommendation (live: NVIDIA Nemotron; fixture: deterministic rules) | `agents.py`, `llm.py` |
| Historical data | The 100M-row Parquet file queried in place by DuckDB | `dataset.py` |
| Retriever | Exact filters, candidate generation, fusion of keyword, numeric and Synapt semantic ranks | `retrieval.py`, `cards.py` |
| Synapt adapter | MCP client: login, tool discovery, retrieval, ingestion; fail-closed and read-only by default | `adapters.py` |
| Models | Amount, resolution time and fraud-flag models with explanations | `analytics.py` |
| Priority | Transparent 0 to 100 score and tier | `priority.py` |
| Judge | An independent model's verdict on each live brief | `judge.py` |
| Evaluation | Golden cases and DeepEval | `evaluation.py` |
| Feedback | Reviewed lessons, promotion, reuse as evidence | `feedback.py`, `store.py` |
| Store | SQLite: runs, audit log, feedback; separate connection for LangGraph checkpoints | `store.py` |

## Where each kind of knowledge lives

Synapt cannot hold 100 million claims. Its ingestion tool accepts text, about 100 cards per call,
and every call takes two to three minutes to embed; 100 million cards would take years. The design
therefore gives each store the job it can do:

* **Parquet file (authoritative, 100M rows)**: filters, historical availability, similar-claim
  candidates, every number shown to the handler, and the sample the models learn from.
* **Synapt**: handling procedures (cited as evidence), a stratified sample of 1,000 claim cards
  used for semantic ranking, and reviewed handler lessons.
* **SQLite**: runs, audit trail, accounts, feedback, workflow checkpoints.

## Historical data

* The file is never loaded into memory. DuckDB reads the columns a query needs, with filters
  evaluated in the scan.
* **Historical availability.** A comparable claim must have been settled (`approved` or `denied`)
  and closed *before* the new claim was filed: filing date plus the whole-day part of
  `days_to_resolution`. Claims in `pending` or `under_review` can be requested explicitly; they
  were already on file but have no outcome.
* **The NaN trap.** In Parquet a pending claim's duration is NaN, not NULL (the Hugging Face JSON
  API hides this by converting it to null). The SQL uses `TRY_CAST` so such rows are excluded
  rather than raising or comparing as "largest".
* **Comparable pool.** When the claim's type is known, candidates are the same type, unless the
  handler filters explicitly. Comparing an auto claim with a renters claim is not informative.

## Retrieval and fusion

1. SQL returns the 300 candidates with the highest numeric similarity under the handler's filters:
   same type (+2), same state (+1), closeness of log-amount, closeness of prior-claims count.
2. Synapt is asked for the claim cards most similar to a card-shaped description of the new claim.
   Their identifiers are decoded and looked up in the Parquet file under **the same filters, pool
   and availability rules**, so a semantic match can never bypass a filter.
3. Three ranked lists are fused by reciprocal rank (`1 / (60 + rank)`):
   keyword match over claim descriptors (weight 1), numeric similarity (weight 1) and Synapt
   semantic rank (weight 0.5).
4. The five best are returned as the closest claims. Up to three more that Synapt ranks related in
   meaning, but the numeric search would not have chosen, follow, each labelled with its Synapt
   rank. The trace records how many cards Synapt matched, how many were eligible, and how many
   reached the results.

Three decisions came from measuring the live system, not from theory:

* **No IDF in the keyword leg.** The pool is about 300 near-identical claims plus a few diverse
  semantic outliers. IDF rewards rare terms, so it ranked the outliers (a $3,393 New Jersey claim
  for an $8,500 Texas claim) above the true near-exact matches. A regression test reproduces this.
* **Semantic weight 0.5, and extras shown separately.** With 1,000 of 100 million claims in Synapt,
  its nearest cards are rarely numerically close. It may lift or break ties but not displace.
* **Opaque identifiers.** Synapt masks personal-looking text before indexing; see
  [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md).

## Workflow

`classify`, `retrieve`, `investigate`, `risk`, `recommend`, `validate`, `judge`, `review`.

* **Classification** returns a claim type or abstains (`needs_review`) when the category is
  ambiguous; an abstention blocks acceptance of the brief.
* **Investigation and recommendation** are model-written in live mode, constrained to a schema,
  bounded retries and a closed list of action types. All input is treated as untrusted data.
* **Risk** attaches the three model estimates and computes the audited priority score.
* **Validation** is mechanical: schema, every citation resolves to a supplied source, no decision
  language (approve, deny, pay, proven fraud), and no claim that a document's contents were seen.
* **Judge** is advisory and runs **in the background**: the brief is saved and shown at once with
  the verdict "in progress", and a second, different model's verdict is merged in when ready
  (typically 15 to 60 seconds). A later save can never erase a finished verdict.
* **Review** is a LangGraph interrupt. The handler accepts the brief or requests a revision; neither
  approves a claim. Acceptance is blocked when validation failed.

## Priority

Every point of the score is attributable: claimed amount (up to 30), filing delay (10 to 15), prior
claims (10 to 15), a supported contradiction (15), evidence gaps (up to 10), the fraud-model review
signal (15), similar historical claims carrying the dataset fraud flag (10, needs two or more),
and an uncertain category (5). Tiers: critical from 60, high from 40, medium from 20. The rule is a
demonstration policy, not an insurer's. `GET /api/queue` lists open investigations by score.

## Models and explanations

Three scikit-learn models are trained on a repeatable 200,000-row sample drawn from the Parquet
file, split by filing date into 60/20/20 with repeated policies removed from earlier partitions.
See [MODEL_CARD.md](MODEL_CARD.md). Each model reports global permutation importance, the
**direction** of each feature's effect (partial dependence on a calibration subsample) in plain
language, and, for every prediction, how replacing each feature with a typical value would change
that estimate. All of it describes associations in the model, not causes.

## Feedback loop

1. A handler accepts a brief and rates it.
2. An administrator promotes the lesson (a deliberate act; nothing is promoted automatically).
3. The lesson is stored as `handler_lesson` evidence. It contains no claim identifiers or claim
   text. In live mode it is also ingested into the Synapt provider.
4. Later investigations of the same claim type retrieve it as cited evidence, and the agents can
   cite it. It never decides a claim.

## Persistence and security

SQLite in WAL mode with separate connections for checkpoints and audit writes. Sessions are
HttpOnly, revocable, expire after 12 hours and require a CSRF token for writes. Users see only their
own runs; administrators see technical detail, accounts and model tools. Credentials stay
server-side and never appear in responses, logs or the audit trail. Live mode never falls back to
fixtures when a provider fails; the run fails visibly instead.

## Scale and limits

A search scans the file: three to five seconds. Training samples 200,000 rows (80 seconds); the
sample size is a setting. Synapt holds a 1,000-card sample, so its semantic ranking is a mild signal
(measured in [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md)). The service is single-process;
multi-worker hosting would need a production persistence and identity design.
