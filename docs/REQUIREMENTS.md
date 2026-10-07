# Requirements traceability

Every requirement of the project brief ("AI-Powered Insurance Claims Assistant with Synapt"),
mapped to the code that implements it and the evidence that it works. "Live" means run against the
real 100M-row dataset, the real Synapt provider and the real NVIDIA models. Results are in
[VALIDATION.md](VALIDATION.md); where something is only partly achieved, this document says so.

## Requirement 1: Basic

| Requirement | Implementation | Evidence |
|---|---|---|
| Basic RAG for historical claim similarity | Similar claims from the 100M-row Parquet (`dataset.py`, `retrieval.py`); procedures and claim cards from Synapt (`adapters.py`); findings cite supplied sources | Live: closest claims match type, state, amount (within ~$10) and history; findings cite a Synapt SOP passage |
| Hybrid keyword and semantic search | Keyword match over claim descriptors, numeric similarity and Synapt semantic rank, fused by weighted reciprocal rank (`retrieval.py`) | Fusion, filter and regression tests (`test_dataset.py`); live trace reports Synapt candidates, eligible and in-results. Synapt's signal is **mild**: 1.7x chance on claim type (see [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md)) |
| Claim classification agent | Typed classification stage that returns a claim type or abstains (`agents.py`, live Nemotron; deterministic in fixture mode) | Ambiguous claim abstains, is held for manual review and cannot be accepted (tests and live) |
| Metadata filtering: type, state, status, amount, policyholder claim history | `SearchFilters` and SQL clauses (`models.py`, `dataset.py`); all four statuses including `pending` and `under_review` | Every dimension verified against 100M rows; UI has all controls (`test_dataset.py`) |
| Basic claim assessment and recommendations | Findings (fact, gap, contradiction, limitation, risk indicator) and bounded action types, each cited (`agents.py`, `workflow.py`) | Live briefs on four cases; a theft claim yields a cited police-report gap |
| Input validation guardrails | Strict Pydantic models, date and range rules; output validation of citations, wording and decision boundaries (`models.py`, `workflow.py`) | 7 of 7 invalid inputs refused; a model brief saying a document "was provided" was held for review |
| Claim prioritization from characteristics and risk indicators | Audited 0 to 100 score and tier; `GET /api/queue` (`priority.py`, `store.py`) | Live: theft claim High 55/100 with five attributed factors; queue and sort in the UI |
| API endpoints for the core functionality | FastAPI routes: investigations, search, predictions, queue, review, feedback, lessons, models, evaluations (`api.py`) | `/docs`; 25 routes exercised by the test suite |

## Requirement 2: Advanced

| Requirement | Implementation | Evidence |
|---|---|---|
| DeepEval for analysis and recommendation quality | Faithfulness, Contextual Relevancy and a custom safety metric via DeepEval (`evaluation.py`) | Live run: 12 of 12 metrics completed, **8 pass**. Contextual Relevancy is weak (1 of 4 pass), see VALIDATION.md |
| Claim amount and resolution-time models | Random forests against median baselines, temporal split, empirical intervals (`analytics.py`) | 200,000-row sample of the full file: MAE 28% and 9% below baseline; interval coverage 90.1% and 89.8% ([MODEL_CARD.md](MODEL_CARD.md)) |
| LLM-as-Judge for analysis and recommendations | An independent model (`openai/gpt-oss-20b`, a different vendor from the Nemotron author) gives a structured verdict on every live brief, in the background (`judge.py`) | Live verdicts on four cases; unit tests for pass, flag, failure and the save race. It is advisory and probabilistic |
| Multi-agent workflow: investigation, risk, recommendation | LangGraph: classify, retrieve, investigate, risk, recommend, validate, judge, human review (`workflow.py`) | Checkpoint, resume and replay tests; live runs. The risk stage is rules plus statistical models rather than a language-model agent |
| Fraudulent-claim risk prediction | Calibrated random forest on the dataset's fraud flag; the flag rate among the closest historical claims; both feed the priority score | Precision 55.6%, recall 31.1%, PR-AUC 0.322 against 0.078. A screening signal, never a verdict |
| Explainable analysis of characteristics and their effect on outcomes | Global permutation importance, direction of effect (partial dependence) in plain language, and a per-claim breakdown (`analytics.py`) | Tests; UI "Why this estimate"; summaries such as filing delay 1 to 13 days moves resolution 13 to 25 days |
| Feedback loop for continuous improvement | Rate an accepted brief, administrator promotes it, it is cited as evidence in later investigations of the same claim type and ingested into Synapt (`feedback.py`, `workflow.py`) | Live: promoted lesson cited in the next brief's findings; Synapt grew 21 to 22 documents; double promotion refused |
| Simple front-end | React and TypeScript bundle served by the same service (`frontend/`) | 35 UI tests; type-check clean; driven live in a browser |

## Added after the brief: observability, traces and explainability

| Need | Implementation | Evidence |
|---|---|---|
| A trace for every query | Spans for each stage, model call, retrieval and scoring step with timings, tokens and outcomes (`telemetry.py`, `workflow.py`, `llm.py`, `adapters.py`); a labelled reconstruction for runs saved before tracing | `tests/test_observability.py`; every run in the shipped template database reconstructs and its token total matches the audit log |
| An observability page | Volume, latency by stage, model usage, validation and review pass rates, errors and API traffic, over a chosen window (`observability.py`, `ObservabilityView.tsx`) | Aggregation and window tests; checked live on 76 runs |
| How the answer is generated | Stage walkthrough, the sources behind every statement, how comparable claims were ranked, why the priority, what the estimates rest on (`explain.py`, `ExplanationView.tsx`) | `tests/test_explain.py`; the Explain tab and the Explainability page |
| How it is evaluated | Eight validation rules with per-rule results, citation grounding counts, the independent review with its pass criteria, the handler decision, and (administrators) the evaluation suite | Rule-level tests; a decision phrase fails exactly the rules that cover it |
| Handlers see no technical detail | Model and provider names, prompts, tokens, queries and raw traces are administrator-only, enforced by the API | RBAC tests for every new endpoint; checked in a browser as a handler |

## Deliverables

| Deliverable | Where |
|---|---|
| Architecture diagram | [architecture.svg](architecture.svg) and [architecture.png](architecture.png); also on slide 3 of the deck |
| Design | [ARCHITECTURE.md](ARCHITECTURE.md), [MODEL_CARD.md](MODEL_CARD.md), [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md), [CHANGE_DECISIONS.md](CHANGE_DECISIONS.md) |
| Full executable code (microservice) | This repository: FastAPI service, `uv.lock`, one-command setup ([SETUP.md](SETUP.md)); runs from a clean clone |
| Panel presentation, 10 minutes | [Claims_Assistant_Panel_Deck.pptx](Claims_Assistant_Panel_Deck.pptx) (9 slides, timed speaker notes) and [PRESENTATION.md](PRESENTATION.md) |

## Dataset

The brief names "Free Synthetic Insurance Claims 100M" (Parquet). The full 2.52 GB file is downloaded,
verified against the hash Hugging Face publishes, and used directly: all 13 key fields are present
and the file holds exactly 100,000,000 rows. Retrieval queries all of it; models train on a
repeatable 200,000-row sample.

## The brief's requirement to use Synapt

Synapt is used for what it can hold and do: procedures, a sample of claim cards for semantic
ranking, and shared lessons, all over MCP and exercised live. It cannot hold 100 million claims through
its text-ingestion tool ([why](SYNAPT_INTEGRATION.md#why-not-upload-all-100-million-claims)), so the
Parquet file remains the authority for filters, numbers and models. If the instructors expect the full
dataset inside Synapt, the route to investigate is a ticket-store provider uploaded through the
console, which could not be tested here.

## Known gaps

* Synapt's semantic signal is mild (1.7x chance on claim type; none on prior claims).
* DeepEval Contextual Relevancy passes on 1 of 4 live cases: the retrieval context deliberately
  includes several comparison claims and procedures that the metric counts as off-topic.
* The fraud model finds under a third of flagged claims (recall 31%).
* All results are on synthetic data. No claim of real-world accuracy is made.
