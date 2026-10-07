# AI-Powered Insurance Claims Assistant

An evidence-led claims investigation service. A handler describes a claim; the system finds
comparable historical claims among **100 million synthetic claims**, retrieves handling procedures
and semantically similar claims from **Synapt**, estimates amount, resolution time and fraud-flag
risk, and prepares a cited brief that a person reviews. It never approves, denies or pays a claim.

![Architecture](docs/architecture.svg)

The **[original approved project plan](docs/PROJECT_PLAN.md)** preserves the Synapt-centered direction,
feature priorities, LangGraph decision and both diagrams. An **[offline HTML copy](docs/PROJECT_PLAN.html)**
includes the images and complete original transcript in a single file.

## What it does

| Capability | How |
|---|---|
| **Hybrid retrieval over 100M claims** | The Parquet file is queried in place with DuckDB. Exact filters (claim type, state, status, amount range, prior-claims range) run in SQL, then keyword, numeric-similarity and Synapt semantic ranks are fused. About 3 to 5 s per search |
| **Synapt knowledge** | Handling procedures, the original 1,000 historical claim cards and a 19,887-card expansion with submission/verification bookkeeping, plus reviewed handler lessons, retrieved over MCP |
| **Multi-stage workflow** | LangGraph: classify, retrieve, investigate, risk, recommend, validate, independent judge, human review gate. Checkpointed, resumable |
| **Guardrails** | Strict input validation; every finding and recommendation must cite a supplied source; boundary checks block coverage, fraud and payment decisions |
| **Predictions with explanations** | Amount, resolution time and fraud flag, each with an interval or threshold, a direction-of-effect summary and a per-claim breakdown |
| **Audited priority** | A 0 to 100 score where every point is attributed to a stated factor; a priority-ordered queue |
| **Evaluation** | Golden cases plus DeepEval (faithfulness, relevancy, a custom safety metric) and an independent LLM judge on every live brief |
| **Closed feedback loop** | Handler feedback, administrator promotion, then cited evidence in later investigations and ingestion into Synapt |
| **Interface** | React app served by the same FastAPI service; login, user and administrator roles |

## Run it

Full procedure, with timings and troubleshooting: **[docs/SETUP.md](docs/SETUP.md)**.

```powershell
git clone <your-repository-url> synapt_capstone
Set-Location synapt_capstone
uv sync --locked --extra evaluation --extra search
Copy-Item .env.example .env          # then fill in the Synapt and NVIDIA keys for live mode
uv run python scripts/bootstrap.py all
uv run uvicorn claims.api:app --host 127.0.0.1 --port 8000
```

`bootstrap.py all` downloads and verifies the 2.5 GB dataset, trains the models and builds the
Synapt corpus. With `SYNAPT_MODE=fixture` and `AGENT_MODE=fixture` (the defaults) no external
service is called at all. Open <http://127.0.0.1:8000> and create the administrator on first use.

## Verify it

```powershell
uv run pytest -q                                  # backend, offline
uv run python scripts/bootstrap.py check          # data, models, corpus, Synapt
uv run python scripts/synapt_ingest.py verify     # Synapt semantic precision against chance
Set-Location frontend; npm run test; Set-Location ..
```

Results and the evidence behind each claim are recorded in [docs/VALIDATION.md](docs/VALIDATION.md).

The 7 October refresh has dated reports for [data expansion and upload status](docs/DATA_EXPANSION_2026-10-07.md),
[model retraining](docs/ML_RETRAINING_2026-10-07.md), and [evaluation correctness](docs/EVAL_AUDIT_2026-10-07.md).
Keep Parquet as the local dataset; upload its generated text cards to this Synapt knowledge provider.
An accepted upload is not evidence that extraction has finished. See the expansion report before uploading
any batch again.

## Documentation

| Document | Purpose |
|---|---|
| [SETUP.md](docs/SETUP.md) | Exact steps for a fresh machine |
| [REQUIREMENTS.md](docs/REQUIREMENTS.md) | Every requirement of the brief, mapped to code and evidence |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Design, data flow and decisions |
| [SYNAPT_INTEGRATION.md](docs/SYNAPT_INTEGRATION.md) | What Synapt does here, what was measured, what to know |
| [MODEL_CARD.md](docs/MODEL_CARD.md) | Models, splits, metrics, explanations and limits |
| [VALIDATION.md](docs/VALIDATION.md) | Test results and live end-to-end evidence |
| [PRESENTATION.md](docs/PRESENTATION.md) | The ten-minute panel script and slide deck |
| [CHANGE_DECISIONS.md](docs/CHANGE_DECISIONS.md) | Why things are the way they are |

## Limits

Educational decision support on **synthetic** data. Scores, similar-case outcomes and model
estimates do not determine coverage, prove fraud or authorize payment. The dataset is
[ZiadataLabs FreeInsuranceClaims100M](https://huggingface.co/datasets/ziadatalabs/FreeInsuranceClaims100M),
licensed CC BY-NC 4.0 (non-commercial, attribution required). The service is a single-process local
application: SQLite, per-run ownership, CSRF and role checks are implemented; password reset, MFA
and multi-tenant isolation are not. Do not load model artifacts from untrusted sources (joblib is
executable).
