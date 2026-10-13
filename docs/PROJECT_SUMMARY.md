# AI-Powered Insurance Claims Assistant: project summary

Figures are as of **10 October 2026**. They come from the dated reports in this folder
([MODEL_CARD](MODEL_CARD.md), [EVAL_AUDIT](EVAL_AUDIT_2026-10-07.md), [VALIDATION](VALIDATION.md),
[SYNAPT_INTEGRATION](SYNAPT_INTEGRATION.md), [OBSERVABILITY_EXPLAINABILITY](OBSERVABILITY_EXPLAINABILITY.md))
and from the audit log in `data/runtime/claims.sqlite`, read from a copy. The data is **synthetic**
(CC BY-NC 4.0), so no figure here describes real-world claims.

The Synapt data split was corrected on **13 October 2026**: past claims moved from text "cards" in the document store
to Synapt's ticket store (section 2). Retrieval figures measured on the cards are kept below as history and labelled so.

---

## 0. Problem statement (Project 7 brief)

> Insurance companies process large volumes of claims involving auto, home, renters, property, and business
> insurance. Claims teams need to review historical claims, identify similar cases, assess claim
> characteristics, detect potentially fraudulent patterns, prioritize claims, and understand factors affecting
> claim outcomes and resolution time. Manually reviewing large numbers of historical claims can be
> time-consuming and inconsistent.

The brief poses three professional questions:

1. Has a similar claim been processed previously, and what was its outcome?
2. What claim characteristics are associated with higher claim amounts or longer resolution times?
3. Does a new claim show characteristics similar to previously flagged fraudulent claims?

> Build a semantic retrieval and AI-assisted claims analysis system that can help insurance professionals
> investigate, assess, and prioritize claims.

**Scope.** Requirement 1 (basic) covers hybrid RAG similarity search, a classification agent, metadata
filtering, basic assessment and recommendations, input guardrails, prioritization and API endpoints.
Requirement 2 (advanced) covers DeepEval, amount and resolution-time models, an LLM-as-judge, a multi-agent
workflow, fraud-risk prediction, explainability, a feedback loop and a front end. The dataset is *Free
Synthetic Insurance Claims 100M* (Parquet, 100,000,000 claims).

### The problem as the evals frame it

Each question in the brief maps to a measurement, so the result below is what the system actually delivers:

| Question in the brief | How it was measured | Result |
|---|---|---|
| **1. Similar claim and outcome** | Filter correctness on all five filter dimensions over 100M rows; search latency; Synapt semantic precision against chance | Filters always hold. A fused search takes **3 to 5 s** over 100M rows. Semantic retrieval over the claim-card corpus (removed 13 Oct) was **4.4x chance on claim type**, **5.3x** on state, **3.0x** on amount band and only **1.1x** on prior-claims band; the ticket-store lookup that replaced it has not been measured this way |
| **2. What drives amount and resolution time** | Held-out MAE against a global median and a stronger feature-aware comparator; interval coverage | Amount MAE **$15,105 vs $22,630** baseline (-33%), **identical to a claim-type median** ($15,105). Resolution MAE **6.31 vs 7.26 days** (-13%), driven by filing delay. Claim type is the only real amount signal in this data |
| **3. Resembles flagged fraud** | PR-AUC, precision, recall and Brier on a policy-disjoint, time-split holdout; always-negative baseline | PR-AUC **0.321 vs 0.077** prior (4.2x). Precision **51%**, recall **32%**, so **68% of flagged claims are missed**. Accuracy is 92.38% against **92.28% for predicting "never fraud"**. A weak screening aid, never a fraud decision |
| **Support handling decisions safely** | Golden cases, 8 deterministic validation rules, DeepEval, an independent judge | Golden cases **4/4**. DeepEval Faithfulness and safety mostly pass, but **Contextual Relevancy passes only 1 of 4 cases**. The judge is advisory and a person decides |

Stated plainly: the system delivers **evidence-led triage with enforced boundaries**: cited similar claims,
explained estimates, an audited priority and a human gate. It does **not** deliver accurate fraud detection or
settlement prediction, and the evals show where and why it falls short.

---

## 1. What it does

**User:** a claims handler (adjuster) who needs to investigate a new claim, plus an administrator who manages
accounts, promotes lessons and reads traces. **Problem:** finding comparable past claims, spotting gaps and
contradictions, and ranking work is slow and inconsistent when done by hand across millions of records.

The system **never approves, denies or pays a claim**, and never states coverage or proven fraud.

1. **Hybrid similar-claim search over 100M claims.** The Parquet file is queried in place with DuckDB. Exact
   filters (claim type, state, status, amount range, prior-claims range) run in SQL, then keyword, numeric
   similarity and Synapt semantic ranks are fused. Only claims that were settled *before* the new claim was
   filed count as precedent.
2. **Cited, guarded investigation brief.** An 8-stage LangGraph workflow classifies the claim (and abstains
   when the category is ambiguous), finds evidence gaps and contradictions, and proposes handler actions
   from a closed list of six. Every finding and recommendation must cite a supplied source. A validator blocks
   coverage, fraud and payment conclusions, and a person accepts or revises the brief.
3. **Predictions with explanations and an audited priority.** Amount, resolution days and the dataset fraud
   flag, each with an interval or threshold, the direction of each feature's effect, and a per-claim
   breakdown. A 0 to 100 priority score attributes every point to a stated factor.
4. **Closed feedback loop plus observability.** A handler rates a brief, an administrator promotes the
   lesson, and it is then cited as evidence in later investigations of the same claim type. Every query leaves a
   trace, and an Explainability page shows how the brief was generated, sourced and evaluated.

---

## 2. Architecture

![Architecture](architecture.svg)

**Principle:** Synapt cannot hold 100M claims (document ingestion managed about 100 claim records per call, 2 to 3
minutes each), so each store does the job it can do.

| Store / component | Role |
|---|---|
| **Parquet, 100M rows** (2.5 GB, SHA256-verified) via **DuckDB** | Authority for filters, every number shown, similar-claim candidates and model training |
| **Synapt** (MCP over Streamable HTTP), provider `synapt_capstone1` (kind `ticket_mining`) | Documents: 17 handling procedures (SOPs), from which Synapt extracts the knowledge graph (21 procedures, 93 ordered steps), plus promoted handler lessons. Ticket store: **2,000 settled past claims** (400 per claim type), used for 2 to 4 similar past claims per lookup. Episodic memory written by Synapt. **Required, with no fallback.** Until 13 October past claims were held as 10,000 text "cards" in the document store; see [SYNAPT_INTEGRATION](SYNAPT_INTEGRATION.md#how-the-data-is-split-across-synapt-corrected-13-october-2026) |
| **SQLite** | Runs, audit log, spans, accounts, feedback, LangGraph checkpoints |
| **FastAPI service** | Auth, CSRF, roles, strict input validation, the API, and the compiled UI |
| **LangGraph workflow** | `classify, retrieve, investigate, risk, recommend, validate, judge, review`, checkpointed with a human interrupt |
| **Retriever** | Reciprocal-rank fusion `1/(60+keyword) + 1/(60+numeric) + 0.5/(60+Synapt)`. Synapt-suggested IDs are re-checked against the same filters, so a semantic hit cannot bypass one |
| **Priority** | Additive 0 to 100 rubric (amount, filing delay, prior claims, contradiction, evidence gaps, fraud signal, similar flagged claims, uncertain category) |

**Models**

| Purpose | Model |
|---|---|
| Agents (classify, investigate, recommend) | `nvidia/nemotron-3-super-120b-a12b` through NVIDIA NIM, temperature 0, schema-constrained JSON, bounded retries |
| DeepEval judge | Same Nemotron model (reported as **not independent**) |
| Independent inline judge | `openai/gpt-oss-20b`, pass line 0.70, runs in the background |
| Amount | Claim-type median (selected over gradient boosting and a forest by selection-cohort MAE) |
| Resolution time | Histogram gradient boosting, absolute-error loss |
| Fraud flag | Random forest (80 trees), log-odds sigmoid calibration, PR-curve F1 threshold |
| Explanations | Permutation importance, partial dependence and per-claim feature replacement (associations, not causes) |

**Stack:** Python 3.11, FastAPI, LangGraph, DuckDB, scikit-learn (CatBoost for the rejected experiment),
DeepEval, the MCP client, SQLite, and React 19 + Vite + TypeScript. Dependencies are locked with `uv`.

---

## 3. Evals

### Datasets: size and who labeled them

| Eval | Size | Labels / ground truth from | Used for |
|---|---|---|---|
| **Golden cases** | **4** (auto, theft gap, home conflict, ambiguous), plus a 7-scenario live run and 2 adversarial cases | **The developer** wrote the cases and the expected outcomes in code (`core/demo_cases.py`, `evaluation/service.py`), with AI coding-assistant help. There are **no independent human annotators** | Regression: schema, citations, status, classification, gap/contradiction surfaced, handler gate |
| **Model holdout** | **120,158** test claims for amount and fraud, and **98,270** for resolved durations, from a **600,000-record** sample, split by filing date 60/20/20 with policies disjoint | **The dataset publisher** (ZiadataLabs synthetic ground truth). Nothing was relabeled or generated | Amount, resolution and fraud metrics |
| **Fresh fraud holdout** | **17,666** claims (1,361 flagged, 7.70%), policy-disjoint | Same synthetic labels | Confirm fraud results on unseen policies, and test a challenger model |
| **Retrieval precision** (card corpus, before 13 Oct) | **60** query claims x 20 returned cards | The cards' own attributes (type, state, bands), compared with a random pair of cards | Synapt semantic quality of the former card corpus |
| **DeepEval** | 4 cases x 3 metrics = **12 scores** per run, threshold 0.5 | An **LLM judge** (Nemotron, the same model as the author) | Faithfulness, contextual relevancy, safety/usefulness |
| **Independent judge** | One verdict per brief | An LLM (`gpt-oss-20b`) | Advisory grounding check |

No human-adjudicated set exists. The reviewed-claims importer is built and tested, but its template holds no
records. Two handler ratings (4 and 4) are in the audit log. **Four golden cases are a regression spine, not an
accuracy estimate.**

### Metric scores (held-out test)

| Target | Saved model | Baseline | Stronger comparator |
|---|---:|---:|---:|
| Amount MAE | **$15,105.13** | $22,629.80 (global median) | $15,105.18 (claim-type median), a tie |
| Resolution MAE | **6.309 days** | 7.261 (global median) | 6.478 (filing-delay regression), 2.6% better |
| Fraud PR-AUC | **0.3207** | 0.0772 (prior) | Previous model 0.3222 |
| Fraud Brier | **0.0605** | 0.0712 | |

- **Interval coverage (nominal 90%):** amount 89.92%, resolution 88.82%.
- **Error by type:** business amount MAE is about **$55.3k** against about **$2.2k** for renters, so one overall
  number hides large per-type error.
- **Fraud at the F1 threshold (0.287):** precision **50.98%**, recall **31.86%**, F1 0.392, balanced accuracy
  64.65%. It flagged 5,794 of 120,158 claims (2,954 true and 2,840 false positives) and missed 6,318.
- **Fresh 17,666-claim cohort:** accuracy 92.26%, precision 49.60%, recall 32.11%, against always-negative
  92.30% accuracy and 0% recall.
- **Experiments that did not ship:**
  - Class weighting and doubling the training pool gave no material gain.
  - Ratio features with CatBoost **failed the pre-registered promotion gate** (recall +0.44 points, precision -2.2 points).
  - A richer 1,000-claim Mendeley benchmark reached 72.54% accuracy against an 81.35% majority baseline, with
    55.6% recall and 35.1% precision. It was not promoted either.

### Retrieval: Synapt semantic precision against chance (card corpus, history)

These measurements are of the claim cards Synapt held before 13 October. The cards were removed then, and similar past
claims now come from Synapt's ticket store (2 to 4 per lookup), which has not been measured with this test. Trials of the
ticket store's own labels (`resolution`, `fraud_flag`) found no signal over the majority class, so the labels are ignored.

| Share of returned cards matching the query claim | 1,000 cards (random pair) | **10,000 profile cards (random pair)** | Times chance, 1,000 / 10,000 |
|---|---:|---:|---|
| Claim type | 33.5% (20.1%) | **84.0%** (19.3%) | 1.7x / **4.4x** |
| State | 6.8% (3.9%) | **20.7%** (3.9%) | 1.7x / **5.3x** |
| Amount band | 23.0% (15.7%) | **49.4%** (16.5%) | 1.5x / **3.0x** |
| Prior-claims band | 35.2% (34.9%) | **46.6%** (40.9%) | 1.0x / **1.1x** |

The 10,000-card column is the corrected count from 10 October (an earlier version, 59.9% / 14.2% / 35.0% / 45.5%,
counted the next card's header in each chunk as a match; see
[SYNAPT_INTEGRATION](SYNAPT_INTEGRATION.md#new-provider-9-october-2026)). The 1,000-card column was not re-run.
The corpus was redesigned after a coverage analysis. Among 72.2M settled claims there are only 110,093 distinct
descriptions. Ten thousand cards, chosen most-common-first within each claim type, give an exact-description
twin for **63.0%** of claims, against 41.4% for a random 10,000. This is one run of 60 queries, and the two
corpora differ in size, selection, duplicate rate and card wording, so the gain cannot be credited to one change.

### Brief quality

| Check | Result |
|---|---|
| Golden cases (live Synapt and live model) | **4/4** pass. A replay of saved briefs through the stricter independent checks passes **3/4**, because the stale auto brief fails the document-availability guard |
| Deterministic validation (8 rules, no AI) | **55 of 70** recorded runs pass. **13 of the 16** issues on the other runs are deliberate abstentions on ambiguous claims |
| DeepEval on saved briefs (12 scores) | **9/12** pass. Faithfulness 1.00, 0.67, 0.80, 1.00. Contextual relevance **0.35, 0.41, 0.53, 0.06**. Safety/usefulness 1.00, 0.90, 1.00, 0.90 |
| DeepEval across all recorded results | Faithfulness **16/20**, Contextual Relevancy **3/20**, safety/usefulness **20/20** |
| Independent judge (`gpt-oss-20b`) | **35 of 35** completed verdicts passed (0.80 to 0.95, median 0.90). Seven runs got no verdict. It also **passed a known-bad brief** before the deterministic pre-check was added, so it stays advisory |

Thresholds were never lowered to make a run pass. Contextual Relevancy is weak because the retrieval context
deliberately includes comparison claims and procedures, which the metric counts as off-topic.

### Baselines compared

Global median and training prior; claim-type median; filing-delay linear regression; an always-negative
fraud classifier; a random pair of cards for retrieval; the earlier 1,000-card corpus; and rejected challenger
models (balanced and weighted forests and boosting, ratio CatBoost).

**Test suites at the last full recorded run (7 Oct):** 349 backend tests and 35 frontend tests, with Ruff and
the TypeScript check clean. On 13 October, after the Synapt split was corrected: 905 backend and 171 frontend tests.

---

## 4. Observability and audit

**What is traced.** Each run is a tree of spans written to SQLite as they close, so a run that fails part-way
still leaves its partial trace:

- one root span per run and one span per workflow stage;
- one span per **model call** (purpose, model, every attempt with outcome, HTTP status and duration, prompt and
  answer size, finish reason, provider-reported token usage);
- **Synapt calls** (attempts and the queries sent);
- the **historical search** (candidate counts, per-method rank and points for every result);
- model estimates, priority scoring, validation (every rule with items inspected), and the background judge;
- a second root span for the handler's decision.

**What is logged.**

- An append-only **audit table**: prompts, validated outputs, stage events, model failures, judge verdicts,
  per-metric DeepEval results, evaluation reports, handler reviews, feedback and who submitted each run.
- An **API request log**: route template, status, latency and role. Run IDs never enter it, and the newest
  20,000 rows are kept.
- **Never recorded:** credentials, authorization headers, reasoning traces and provider error text (only the
  exception type is kept). Observing can never fail the work.
- Runs saved before tracing get a **labelled, reconstructed** trace built from their audit events.

**Views and access.** The administrator's Observability page shows volume, p50/p95 run time, model calls,
tokens per query, validation and review pass rates, an execution waterfall per query, JSON export and
prompt/answer inspection. The Explainability page (handlers and administrators) shows how a brief was
generated, the source behind each statement, how comparable claims were ranked, why the priority, what the
estimates rest on, and how the brief was evaluated. The API enforces roles: handlers get **403** on traces,
prompts and metrics.

**Recorded scale (audit log, 5 to 7 Oct 2026):**

| Measure | Value |
|---|---|
| Events / runs | **1,820** events across **70** runs, 12 event kinds |
| Model traffic | 608 prompts and 585 outputs, about **1.63M prompt + 0.17M completion tokens** as the provider reported |
| Model failures | **23** |
| Run outcomes | 47 awaiting review, 15 held for manual review, 7 reviewed, 1 revision requested |
| Live brief time | median **14.5 s**, p90 **19.3 s** (49 live runs, from stage timestamps) |

The runtime database predates per-query spans (it holds 0), so these figures come from the audit log. The
tracing and explainability code has 35 backend tests (19 observability, 16 explainability) and 19 frontend
tests, and a stubbed live-style run records 23 spans.

### Failure modes it surfaced

1. **A verdict that could not be trusted: a false pass on a document claim.** A saved auto brief said a
   repair estimate had been *received*, but the intake only *named* the document. Its stored validation said
   pass, and the inline judge scored it 0.95, 0.90, 0.90 and 0.90 on the four saved briefs. Replaying the saved
   briefs through independent checks, with an audit database of prompts and outputs, exposed it. The
   document-receipt guard was rewritten (15 positive and negative tests), the brief is now rejected **before any
   model call**, and the golden suite no longer trusts a stored `passed` flag.
2. **Judge and agent reliability, and latency.** The audit shows **14 judge transport failures** (10 on the
   first attempt, 4 on the second), 3 judge schema failures and **6 agent output-schema failures** (4 recommendation,
   2 investigation), so 7 judge runs ended with no verdict. The bounded retries recovered every agent failure, since
   no recorded run ended `failed`. Earlier, an inline judge timeout plus a retry made one brief **67 s slower**.
   The judge now runs in the background and the brief appears in about 15 s.
3. **Retrieval ranking error, then a weak semantic signal.** Inspecting per-method ranks showed a $3,393 New
   Jersey claim outranking exact $8,500 Texas matches, because IDF rewarded the rare terms of diverse outliers
   in a pool of near-identical claims. The fix was no IDF in the keyword leg, a 0.5 weight on Synapt, extras shown
   separately and a regression test. Measuring Synapt against chance then showed only 1.7x on claim type, which
   led to the 10,000-card profile corpus (4.4x).
4. **The wrong store for past claims.** Review feedback said the Synapt data split was wrong, and measurement
   agreed: the cards were 99.6% of the provider's chunks but had 55 graph links against 135 from the 17 procedure
   chunks, and they crowded the procedures out of passage search. On 13 October the cards were deleted and 2,000
   settled claims were loaded into Synapt's ticket store instead (provider now 18 documents, 39 chunks). A live
   check of three investigations (auto, home, no type) returned procedure passages, graph procedures and 2 to 3
   ticket-store claims for each; the judge passed the auto and home briefs (0.95, 0.92) and the typeless claim went
   to manual review as designed.

Also found: Synapt rewrites identifiers and place names (claim IDs became phone and SSN placeholders), fixed with
a letters-only alias and an opaque region token. Repeated logins caused HTTP 429, fixed with one cached token.
Contextual Relevancy remains an open weakness at 3 of 20.

---

## 5. My role

**Solo project.** Git history shows a single contributor: 9 commits under two git identities, which appear to
be the same person. All of these parts were built in this repository:

- the FastAPI service, authentication, roles and CSRF, and strict input validation;
- the LangGraph workflow, agents, validator and judge;
- the DuckDB retrieval and fusion over 100M rows;
- the Synapt MCP adapter, the corpus design and builder, and the store-verification tooling;
- the models and their explanations;
- the priority rubric, the feedback loop, the evaluation suite, the traces and observability, and the React UI;
- the setup and test tooling, and all of the documentation.

**Not built here:** the dataset (ZiadataLabs), the Synapt platform, the NVIDIA-hosted models, and the
open-source libraries.

**AI assistance:** the project was built with AI coding assistants. The repo's reports refer to Codex and a
"main agent".

---

*Where to look next:* [REQUIREMENTS.md](REQUIREMENTS.md) maps every requirement to code and evidence,
[MODEL_CARD.md](MODEL_CARD.md) holds the full model results, and [PRESENTATION.md](PRESENTATION.md) holds the
ten-minute panel script.
