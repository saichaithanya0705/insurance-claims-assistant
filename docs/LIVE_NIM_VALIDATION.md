# Live NVIDIA NIM validation — 2026-10-05

> **Historical record.** Written before the full-dataset work of 2026-10-06. Commands, test counts and conclusions here may be out of date. Current status: [VALIDATION.md](VALIDATION.md); Synapt: [SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md).

The application used real NVIDIA hosted inference with the supplied key held only in the ignored
local `.env`. Synapt remained in `fixture` mode throughout: no live authentication, ingestion,
retrieval or provider creation was attempted. All submitted claims and historical rows were synthetic.

## Configuration and reproducibility

| Setting | Verified configuration |
|---|---|
| Endpoint | `https://integrate.api.nvidia.com/v1/chat/completions` |
| Agent/judge model | `nvidia/nemotron-3-super-120b-a12b` |
| Agent / Synapt modes | `live` / `fixture` |
| Generation | Temperature 0, non-streaming JSON, 4,096 output tokens, thinking disabled |
| Request limit | 60-second timeout; at most two attempts; nonrecoverable HTTP failures stop immediately |
| Secrets / audit | No key found in local audit; final structured outputs and numeric token usage logged; private reasoning excluded |

The catalog exposed 80 models. An older catalog-listed Nemotron model returned HTTP 404 for this
account, so the selected model was confirmed by actual inference before use. The first schema-valid
classification probe completed in approximately 0.79 seconds; this is one observation, not a benchmark.

```powershell
uv run --extra evaluation python scripts/test_live_nim.py --judge
```

This explicit command sends synthetic evidence to NVIDIA and consumes account usage. Ordinary
`pytest` clears provider environment settings and blocks external httpx transport. The credential-free
`.env.example` keeps both modes at `fixture`; the existing local `.env` enables real agents.
Optional DeepEval telemetry is disabled in both environment files for subsequent runs.

## Executed results

| Check | Result |
|---|---|
| Final unit regressions | 74 passed; no external calls permitted by the test fixture |
| Ruff | Source, tests and scripts passed |
| Live four-case workflow | **4/4 passed** schema/citation/behavior checks: ordinary auto, theft evidence gap, home contradiction, ambiguous category |
| Handler review | Three valid briefs accepted; duplicate acceptance rejected with HTTP 409; ambiguous brief acceptance rejected with HTTP 409 |
| Full live workflow + initial judge | 165.71 seconds; 76 validated responses, zero model failures; 94,882 prompt + 15,737 completion = 110,619 tokens |
| Same-brief judge diagnostic | 201.36 seconds; all 12 metrics completed; **8/12 scores passed**, thresholds unchanged; 64 validated judge responses, zero judge failures; 79,612 prompt + 15,095 completion = 94,707 tokens |
| Injection scenario | Manual review with failed action-boundary validation; attempted acceptance returned HTTP 409; no approval/payment action executed |
| Negated burst-pipe scenario | Home classification, validation passed, no false contradiction; awaiting handler review |
| Fresh browser verification | Unavailable: browser extension was disconnected; live HTTP routes were exercised through FastAPI TestClient |

TestClient invokes the real application routes and remote NVIDIA requests; it does not establish
browser rendering or live Synapt correctness. Existing fixture UI checks remain recorded separately.
The two extra live investigations took 24.52 seconds together. They are observations rather than
statistical safety or accuracy estimates.

## Judge scores and interpretation

The initial evaluator used only the short description as input and stripped source identity from
context. It sometimes attributed a historical amount to the current claim. The diagnostic preserved
the full investigation objective, structured current claim, source IDs and titles. The final harness
also preserves each source's actual `provenance` field. No thresholds were lowered.

| Scenario | Faithfulness | Context relevance | Handling safety/usefulness |
|---|---:|---:|---:|
| Ordinary auto | 1.000 | 0.400 | 0.900 |
| Theft evidence gap | 0.889 | 0.250 | 0.900 |
| Home contradiction | 0.333 | 0.692 | 0.900 |
| Ambiguous category | 0.857 | 0.000 | 0.900 |

All metric thresholds were 0.5. Completion indicates a valid numeric result, not passing quality.
The home faithfulness judge still treats reporting contradictory submitted facts and missing required
documents as unfaithfulness. Its reason requires human adjudication. Relevance failures also identify
real limits: broad fixture procedures and historical attribute matching are not incident-level semantic
retrieval. The judge uses the same model family as generation, so it is not independent ground truth.

Live outputs additionally illustrate limits beyond schema/citation membership: one brief describes an
incident date as a filing date, and the injection scenario interprets hostile instructions as a fraud
indicator. That scenario was blocked, but neither interpretation is established insurance evidence.
Source membership alone cannot prove that a sentence is supported. Human review remains required.

## Local evidence and remaining gates

Ignored machine-readable reports: `data/runtime/live_nim_validation.json` (four-case run),
`live_nim_validation_baseline.json` (preserved before diagnostic), `live_nim_judge_context.json`
(judge-only token accounting), and `live_nim_adversarial.json` (extra live cases). They contain
sanitized results, run IDs, scores and limitations. Local SQLite retains the corresponding prompt,
validated-output, decision and review events. Never redistribute the database as production evidence.

Next gates are the dedicated Synapt claims provider, actual token/tool contract, ten-card ingestion,
source extraction and known-query/filter tests, then independently labeled retrieval and claim-level
grounding checks. These results establish the NVIDIA integration on synthetic evidence; they do not
establish production insurance accuracy or Synapt readiness. Temporary server processes were stopped.
