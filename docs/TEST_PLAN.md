# Test plan and release gates

Scope: every Basic and Advanced requirement of the brief. Code correctness is separated from live
provider and model quality: fixture-mode tests are never reported as live Synapt verification.
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
| G8 Synapt adapter | Authentication, token reuse, 401 and 429 handling, schemas, ingestion responses, card ranking, no cited cards | Fail closed; no credential in any message |
| G9 corpus | Stratified, deterministic selection; masking-safe cards; batch limits; no labels or identifiers | Rebuilds are idempotent; conflicting content is refused |
| G10 feedback loop | Promotion rules, administrator-only, live ingestion, reuse as evidence, same claim type only | One-shot, explicit, never automatic |
| G11 UI | Rendering of priority, explanations, judge states, flags, filters, accessibility | Type-check, lint and tests pass |
| G12 live | The real dataset, real Synapt provider and real models | Recorded in VALIDATION.md with the commands used |

## Commands

```powershell
uv run pytest -q                                   # backend, offline (no network, no real dataset)
uv run ruff check src tests scripts
Set-Location frontend; npm run test; npx tsc -p tsconfig.app.json --noEmit; Set-Location ..
uv run python scripts/bootstrap.py check           # live readiness
uv run python scripts/synapt_ingest.py verify      # Synapt semantic precision
```

Unit tests clear provider settings, point the dataset path at a missing file, and reject external
HTTP, so a live `.env` cannot turn a regression test into a billed call.

## Quality measurements

Retrieval: Synapt precision against chance (claim type, state, amount band, history band). Generation:
faithfulness, contextual relevance and a safety metric (DeepEval), plus the independent judge.
Risk: precision, recall, PR-AUC and Brier score against baselines. Regression: MAE against a median
baseline and empirical interval coverage. No fairness claim is made from synthetic aggregate metrics.
