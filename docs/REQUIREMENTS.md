# Requirements traceability

Every requirement of the project brief ("AI-Powered Insurance Claims Assistant with Synapt"),
mapped to the code that implements it and the evidence that it works. "Live" means run against the
real 100M-row dataset, the real Synapt provider and the real NVIDIA models. Results are in
[VALIDATION.md](VALIDATION.md); where something is only partly achieved, this document says so.

## Requirement 1: Basic

| Requirement | Implementation | Evidence |
|---|---|---|
| Basic RAG for historical claim similarity | Similar claims from the 100M-row Parquet (`history/dataset.py`, `history/retriever.py`); procedure passages and graph procedures from Synapt's documents, and 2 to 4 similar settled claims from Synapt's ticket store (`synapt/adapter.py`); findings cite supplied sources | Live: closest claims match type, state, amount (within ~$10) and history; findings cite a Synapt SOP passage. Live check on 13 Oct 2026: three investigations each got passages, graph procedures and 2 to 3 ticket-store claims |
| Hybrid keyword and semantic search | Keyword match over claim descriptors, numeric similarity and Synapt semantic rank (ticket-store neighbours, half weight, at most 3 added claims), fused by weighted reciprocal rank (`history/retriever.py`) | Fusion, filter and regression tests (`test_dataset.py`); live trace reports Synapt candidates, eligible and in-results. Synapt's signal is **mild**: the former card corpus measured 4.4x chance on claim type and 1.1x on prior claims; the ticket-store lookup has not been measured this way (see [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md)) |
| Claim classification agent | Typed classification stage that returns a claim type or abstains (`agents/stage_agents.py`, live Nemotron; deterministic in fixture mode) | Ambiguous claim abstains, is held for manual review and cannot be accepted (tests and live) |
| Metadata filtering: type, state, status, amount, policyholder claim history | `SearchFilters` and SQL clauses (`core/schemas.py`, `history/dataset.py`); all four statuses including `pending` and `under_review` | Every dimension verified against 100M rows; UI has all controls (`test_dataset.py`) |
| Basic claim assessment and recommendations | Findings (fact, gap, contradiction, limitation, risk indicator) and bounded action types, each cited (`agents/stage_agents.py`, `investigation/workflow.py`) | Live briefs on four cases; a theft claim yields a cited police-report gap |
| Input validation guardrails | Strict Pydantic models, date and range rules; output validation of citations, wording and decision boundaries (`core/schemas.py`, `investigation/workflow.py`) | 7 of 7 invalid inputs refused; a model brief saying a document "was provided" was held for review |
| Claim prioritization from characteristics and risk indicators | Audited 0 to 100 score and tier; `GET /api/queue` (`investigation/priority.py`, `storage/run_store.py`) | Live: theft claim High 55/100 with five attributed factors; queue and sort in the UI |
| API endpoints for the core functionality | FastAPI routes: investigations, search, predictions, queue, review, feedback, lessons, models, evaluations (`api/main.py`) | `/docs`; 25 routes exercised by the test suite |

## Requirement 2: Advanced

| Requirement | Implementation | Evidence |
|---|---|---|
| DeepEval for analysis and recommendation quality | Faithfulness, Contextual Relevancy and a custom safety metric via DeepEval (`evaluation/service.py`) | Live run: 12 of 12 metrics completed, **8 pass**. Contextual Relevancy is weak (1 of 4 pass), see VALIDATION.md |
| Claim amount and resolution-time models | Random forests against median baselines, temporal split, empirical intervals (`ml/analytics.py`) | 200,000-row sample of the full file: MAE 28% and 9% below baseline; interval coverage 90.1% and 89.8% ([MODEL_CARD.md](MODEL_CARD.md)) |
| LLM-as-Judge for analysis and recommendations | An independent model (`openai/gpt-oss-20b`, a different vendor from the Nemotron author) gives a structured verdict on every live brief, in the background (`evaluation/judge.py`) | Live verdicts on four cases; unit tests for pass, flag, failure and the save race. It is advisory and probabilistic |
| Multi-agent workflow: investigation, risk, recommendation | LangGraph: classify, retrieve, investigate, risk, recommend, validate, judge, human review (`investigation/workflow.py`) | Checkpoint, resume and replay tests; live runs. The risk stage is rules plus statistical models rather than a language-model agent |
| Fraudulent-claim risk prediction | Calibrated random forest on the dataset's fraud flag; the flag rate among the closest historical claims; both feed the priority score | Precision 55.6%, recall 31.1%, PR-AUC 0.322 against 0.078. A screening signal, never a verdict |
| Explainable analysis of characteristics and their effect on outcomes | Global permutation importance, direction of effect (partial dependence) in plain language, and a per-claim breakdown (`ml/analytics.py`) | Tests; UI "Why this estimate"; summaries such as filing delay 1 to 13 days moves resolution 13 to 25 days |
| Feedback loop for continuous improvement | Rate an accepted brief, administrator promotes it, it is cited as evidence in later investigations of the same claim type and ingested into Synapt (`corpus/lessons.py`, `investigation/workflow.py`) | Live: promoted lesson cited in the next brief's findings; Synapt grew 21 to 22 documents; double promotion refused |
| Simple front-end | React and TypeScript bundle served by the same service (`frontend/`) | 35 UI tests; type-check clean; driven live in a browser |

## Added after the brief: observability, traces and explainability

| Need | Implementation | Evidence |
|---|---|---|
| A trace for every query | Spans for each stage, model call, retrieval and scoring step with timings, tokens and outcomes (`observability/telemetry.py`, `investigation/workflow.py`, `llm/client.py`, `synapt/adapter.py`); a labelled reconstruction for runs saved before tracing | `tests/test_observability.py`; every run in the shipped template database reconstructs and its token total matches the audit log |
| An observability page | Volume, latency by stage, model usage, validation and review pass rates, errors and API traffic, over a chosen window (`observability/observatory.py`, `ObservabilityView.tsx`) | Aggregation and window tests; checked live on 76 runs |
| How the answer is generated | Stage walkthrough, the sources behind every statement, how comparable claims were ranked, why the priority, what the estimates rest on (`observability/explain.py`, `ExplanationView.tsx`) | `tests/test_explain.py`; the Explain tab and the Explainability page |
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

Synapt is used for what each of its stores is for, all over MCP and exercised live: the 17 handling
procedures and shared lessons as documents (Synapt extracts the knowledge graph from them: 21 procedures,
93 ordered steps), 2,000 settled past claims in its ticket store for similar-claim lookups, and its
episodic memory for the query agent. Until 13 October 2026 past claims were held as 10,000 text "cards" in
the document store; review feedback said that split was wrong, and it was corrected
([details](SYNAPT_INTEGRATION.md#how-the-data-is-split-across-synapt-corrected-13-october-2026)). Synapt
does not hold 100 million claims ([why](SYNAPT_INTEGRATION.md#why-not-upload-all-100-million-claims)),
so the Parquet file remains the authority for filters, numbers and models.

## Known gaps

* Synapt's semantic signal is modest: the ticket-store lookup gives 2 to 4 past claims and has not been
  measured against chance (the former card corpus was 4.4x chance on claim type and 1.1x on prior claims),
  and the ticket store's outcome and fraud labels showed no signal over the majority class, so they are ignored.
* Synapt has 22 lived episodes and no mined ones yet; mining is a console step and is not verified.
* DeepEval Contextual Relevancy passes on 1 of 4 live cases: the retrieval context deliberately
  includes several comparison claims and procedures that the metric counts as off-topic.
* The fraud model finds under a third of flagged claims (recall 31%).
* All results are on synthetic data. No claim of real-world accuracy is made.
