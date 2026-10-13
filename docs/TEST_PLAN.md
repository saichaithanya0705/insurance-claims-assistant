# Test plan and release gates

Scope: every Basic and Advanced requirement of the brief. Code correctness is separated from live
provider and model quality: unit tests use a Synapt test double that exists only under `tests/`, and they
are never reported as live Synapt verification.
Results are recorded in [VALIDATION.md](VALIDATION.md).

## Gates

| Gate | What is checked | Release criterion |
|---|---|---|
| G1 contracts | Dates, amounts, state, type and range filters; unexpected fields; non-finite numbers | Invalid requests refused with 422, and nothing is saved |
| G2 retrieval | Filters, historical availability, NaN durations, open statuses, candidate pool, fusion weights, the IDF regression, semantic IDs bound by the same filters | Filters always hold; a semantic match never bypasses them |
| G3 workflow | Abstention, gaps, contradictions, citations, provider failure, review, replay, background judge | No fabricated success; acceptance blocked when validation fails |
| G4 persistence | Restart with a saved interrupt; duplicate review; a late save cannot erase a judge verdict | State resumes exactly |
| G5 models | Leakage controls, temporal split with disjoint policies, provenance hash, baselines, explanations, per-claim effects | Metrics reported honestly against baselines |
| G6 agents and judge | Malformed output, unknown sources, injected instructions, bounded retries, advisory judge | Schema-valid, source-bounded output or an explicit failure |
| G7 evaluation | Golden cases and DeepEval metrics | Local goldens pass; judge status recorded separately |
| G8 Synapt adapter | Authentication, token reuse, 401 and 429 handling, schemas, ingestion responses, ticket-store neighbours closest first (a missing or foreign ticket store gives none and says why), episodic chunks never evidence, no cited cards | Fail closed; no credential in any message |
| G9 corpus | Stratified, deterministic selection; masking-safe cards (local fallback file); batch limits; no labels or identifiers; store verification: procedures, ticket count and label fields, no leftover card documents | Rebuilds are idempotent; conflicting content is refused |
| G10 feedback loop | Promotion rules, administrator-only, live ingestion, reuse as evidence, same claim type only | One-shot, explicit, never automatic |
| G11 UI | Rendering of priority, explanations, judge states, flags, filters, accessibility | Type-check, lint and tests pass |
| G12 live | The real dataset, real Synapt provider and real models | Recorded in VALIDATION.md with the commands used |

## Commands

```powershell
uv run pytest -q                                   # backend, offline (no network, no real dataset)
uv run ruff check src tests scripts
Set-Location frontend; npm run test; npx tsc -p tsconfig.app.json --noEmit; Set-Location ..
uv run python scripts/bootstrap.py check           # live readiness
uv run python scripts/verify_synapt_store.py       # Synapt store: 17 procedures, 2,000 tickets, no leftover cards
uv run python scripts/evaluate_retrieval.py --output artifacts/evaluation/retrieval-<date>.json  # live retrieval metrics, read-only
```

`synapt_ingest.py verify` (card-search precision against chance) measured the card documents, which were removed from
the provider on 13 October 2026; it has nothing to measure on `synapt_capstone1` now.

Unit tests clear provider settings, point the dataset path at a missing file, and reject external
HTTP, so a live `.env` cannot turn a regression test into a billed call.

## Quality measurements

Retrieval: precision@5, recall@5, hit@5, MRR and nDCG@5 for the procedure passages and the knowledge-graph procedures
against 15 hand-labelled claims; same-type precision and attribute-graded nDCG for similar past claims; known-item hit@1
and MRR for the ticket store. See [RETRIEVAL_METRICS_2026-10-13.md](RETRIEVAL_METRICS_2026-10-13.md). The ticket store's
label accuracy was measured separately (no better than the majority class, so labels are ignored); see
[SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md). Generation:
faithfulness, contextual relevance and a safety metric (DeepEval), plus the independent judge.
Risk: precision, recall, PR-AUC and Brier score against baselines. Regression: MAE against a median
baseline and empirical interval coverage. No fairness claim is made from synthetic aggregate metrics.
