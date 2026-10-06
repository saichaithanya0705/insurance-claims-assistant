# Test plan and release gates

Scope: all approved Synapt Claims Investigator features, Basic and Advanced requirements.
This plan separates code correctness from live provider and model quality. Never label fixture
regressions as live Synapt verification. Never hide unavailable predictions behind successful cards.

## Gates

| Gate | Tests and evidence | Release criterion |
|---|---|---|
| G1 contracts | Dates, amounts, category/state/history filters, malformed fields, nonfinite values | Reject invalid requests; no unsafe fallback |
| G2 retrieval | BM25 rankings, exact filters, closed-before-query temporal check, no matches, semantic case-ID fusion | Filters hold and provenance resolves; fixture semantics explicitly simulated/unavailable |
| G3 workflow | Classifier ambiguity, missing evidence, contradictions, valid citations, source failures, review/replay | No fabricated success; approval blocked when validation fails |
| G4 persistence | Restart with saved interrupt; accept/revise; duplicate review; feedback candidates | State resumes exactly; no duplicate external writes |
| G5 models | Excluded targets/IDs, disjoint policy/time split, SHA provenance, baseline comparison, out-of-distribution notices | Metrics reported honestly; no minimum accuracy claim without domain review |
| G6 agents | Malformed JSON, unknown IDs, malicious evidence instructions, denied side effects, bounded retries | Schema-valid, source-bounded output or explicit failure; no autonomous adjudication |
| G7 evaluation | Deterministic goldens + DeepEval faithfulness/relevance/custom recommendation judge | Local regressions pass; judge status and configuration recorded separately |
| G8 UI | Desktop/mobile, keyboard, labels, validation, errors, evidence navigation, review/feedback | No overflow, fake progress/counts, or unlabeled synthetic content |
| G9 live Synapt | Authentication, tools/list, schemas, correct provider isolation, known source retrieval | Independently verified after credentials/access; no credential leakage |
| G10 live ingestion | Dedicated provider permission, 10 then 100 cards, request ID vs extraction completion, chunk/graph/SOP identity | Confirm usable extraction in console; do not equate submission with completion |
| G11 scale | 1k then 5k provider cards; record ingest cost, failures, P50/P95 query latency, citation/filter regression | Stay within tenant quotas and a agreed budget; no 100M graph ingestion by default |

## Golden cases

Four hand-authored cases cover an ordinary auto claim, theft with missing evidence, a conflicting
home narrative, and an ambiguous loss. Add failures for empty context, provider errors, forged
citations, input prompt injection, missing policy wording, and invalid human responses.
Historical records have no narrative; no generated story may be presented as a dataset fact.

## Quality measurements

Retrieval: independently label relevant case IDs and passages, then Recall@5 and precision@5;
judge scores do not replace these labels. Generation: faithfulness, contextual relevance,
recommendation usefulness, correct abstention and citation validity. Risk: PR-AUC, precision,
recall, calibration/Brier score and review threshold. Regression: MAE, median baseline and
empirical interval coverage. Show per-type/state slices only when samples are sufficient;
report counts and never claim fairness from synthetic aggregate metrics.

## Commands

`uv run pytest -q` and `uv run ruff check src tests scripts` are the local gate.
`uv run python scripts/fetch_dataset.py --count 3000` fetches original synthetic data.
`POST /api/models/train` evaluates/saves local models. `POST /api/evaluations/run` runs local
goldens; body `{"judge":true}` also requests optional DeepEval with configured judge credentials.
Run the live checks using `scripts/synapt_setup.py` only after access is ready.

## Current status

See `VALIDATION.md` and `LIVE_NIM_VALIDATION.md` for actual results. NVIDIA agents and judge
inference have been tested on synthetic fixtures. Synapt authentication, live ingestion/retrieval,
model quality on that corpus and real-world insurance accuracy are pending. Fixture coverage is a development
tool and does not waive those gates.
