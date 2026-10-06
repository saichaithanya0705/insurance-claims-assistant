# Synapt Claims Investigator

Claims investigation capstone with Synapt at the knowledge boundary and LangGraph controlling
the workflow. Includes comparisons, missing evidence, contradiction fixtures, urgency/risk separation,
statistical models, saved handler review, feedback, API, frontend and evaluation.

**The example defaults to fixture mode. The current local `.env` enables live Synapt retrieval
and live NVIDIA agents.** Seven synthetic end-to-end cases passed workflow/API checks against
`synapt_final_capstone` on 2026-10-06. See [LIVE_PROJECT_EVALUATION.md](docs/LIVE_PROJECT_EVALUATION.md)
for evidence, content-quality findings and expansion blockers; functional success does not certify
semantic accuracy or production readiness. Prior NVIDIA-only fixture results remain in
[LIVE_NIM_VALIDATION.md](docs/LIVE_NIM_VALIDATION.md).
The original dataset is synthetic US property-and-casualty data. Neither scores nor past outcomes
determine coverage, prove fraud or authorize claim payments.

## Run on Windows

From `D:\projects\synapt_capstone`, install dependencies using the existing `uv` tool:

```powershell
uv sync --locked
# Optional related-meaning case search (local CPU inference):
uv sync --locked --extra search
uv run --extra search python scripts/prepare_case_search.py
# First setup only; preserve an existing .env.
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
uv run uvicorn claims.api:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. On first use, choose an administrator username and a
password of at least 15 characters. As an administrator, open **Accounts** to create
user or additional admin credentials. Sign in using the same login page for either role.
Use demo cases or submit a claim. The API docs are at `/docs`.
With both switches set to `fixture`, no outbound model/Synapt calls occur. With `AGENT_MODE=live`,
investigations send the supplied claim and retrieved evidence to the configured model provider.
Statistical models are unavailable until trained.

Header search suggests saved claims as you type an ID fragment, title or incident
description. Choose a result directly, or use arrow keys and Enter; Escape, Tab and
outside clicks dismiss the floating results. Literal matches precede **Related meaning**
matches. Semantic search uses a local MiniLM embedding model and never sends search
queries or saved claim text to an external provider; missing model files fall back to
ID/text search. Model download is an explicit setup step, not part of a query.

Users can submit and read their own claims. Administrators can read all saved claims,
review briefs, manage accounts, inspect technical Activity, and use model/evaluation/
connection tools. Existing unowned claims are admin-only. Session cookies are HttpOnly,
revocable, expire after 12 hours and require a CSRF token for API writes. A configured
legacy API key cannot bypass login or roles. `CLAIMS_AUTH_ENABLED=false` is available
only for deliberately isolated service tests; authentication defaults to enabled.

The committed SQLite files in `data/bootstrap/` include the current saved-case snapshot
and a credential-free account schema. An empty default checkout copies the saved-case
snapshot to `data/runtime/claims.sqlite`; existing databases are preserved. Login accounts
and sessions stay in the separate local `data/runtime/auth.sqlite`. Regenerate the
saved-case snapshot with `uv run python scripts/snapshot_local_databases.py`; the script
checks for configured credentials before reporting success. Review any newly added
case data before a later public handoff. See [SEARCH_AND_RBAC_2026-10-06.md](docs/SEARCH_AND_RBAC_2026-10-06.md).
This run downloaded/trained a 3,000-row sample locally; ignored data/artifacts must be regenerated
in another checkout. Do not load model artifacts from untrusted sources (joblib is executable).

```powershell
uv run python scripts/fetch_dataset.py --count 3000
```

Then use **Train models** in the app or POST `/api/models/train`. Global explanations describe
calibration-set feature associations, not individual claims or causal effects. Inspect
[MODEL_CARD.md](docs/MODEL_CARD.md) for metrics, splits and limitations.

## Live credentials and access later

Set `SYNAPT_MODE=live`, username/password and a **dedicated claims provider ID** in local `.env`.
Credentials remain server-side. The `SYNAPT_AUTH_BASE` variable contains the entire token endpoint.
The beta login uses JSON with `SYNAPT_AUTH_USERNAME_FIELD=email`; follow [SYNAPT_CONTRACT.md](docs/SYNAPT_CONTRACT.md).
Do not reuse unrelated provider data as a claims corpus. No provider is created automatically.

```powershell
uv run python scripts/synapt_setup.py discover
uv run python scripts/prepare_synapt_pack.py --cutoff 2026-01-01 --limit 10
# Explicit ingestion, only after provider access is confirmed:
uv run python scripts/synapt_setup.py ingest artifacts/synapt/claims.md
uv run python scripts/synapt_setup.py stats
```

Ingesting returns submission status, not completed extraction. Verify chunks, entities, ordered
procedures and provenance in the console before expansion. The prepared pack excludes fraud labels
and invented narrative. Supplement it with reviewed procedures and labeled synthetic evidence cases.
After the ten-card pilot passes, generate a larger batch with `--limit 100`; use `--offset` and a
different output filename for later batches. Respect advertised tool size limits and tenant quotas.

## NVIDIA NIM agents

The agents and optional DeepEval judge use the same bounded chat-completions client. Configure the
ignored local `.env` as follows, supplying your key only there:

```dotenv
SYNAPT_MODE=fixture
AGENT_MODE=live
NVIDIA_API_KEY=
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_MODEL=nvidia/nemotron-3-super-120b-a12b
LLM_TIMEOUT_SECONDS=60
LLM_MAX_TOKENS=4096
LLM_ENABLE_THINKING=false
DEEPEVAL_MODEL=nvidia/nemotron-3-super-120b-a12b
DEEPEVAL_TELEMETRY_OPT_OUT=1
```

This model was verified with the supplied account. A catalog listing alone does not establish
inference access. NVIDIA's [hosted API quickstart](https://docs.api.nvidia.com/nim/docs/api-quickstart)
documents the endpoint and bearer authentication. For a different compatible provider, explicitly
set `LLM_API_KEY`, base URL and model; the NVIDIA key is selected only for NVIDIA's hostname.
Independent fixture/live switches are displayed.
No silent fallback occurs on provider errors. Logs contain prompts/final structured outputs locally,
not secrets or private model chain-of-thought; secure/remove those logs per the data retention policy.

## Testing

```powershell
uv run pytest -q
uv run ruff check src tests scripts
# Explicit full live test; requires both modes live and consumes provider usage:
uv run python scripts/test_live_project.py
# Resume only a saved interrupted evaluator checkpoint:
uv run python scripts/test_live_project.py --resume
uv run python scripts/prepare_synapt_pack.py
# Optional judge dependency; model requests incur provider usage only when explicitly invoked:
uv sync --extra evaluation
# Explicit live NVIDIA test on synthetic evidence, with optional paid/limited provider usage:
uv run --extra evaluation python scripts/test_live_nim.py --judge
```

Set `DEEPEVAL_MODEL` plus model key/base URL and request `{"judge":true}` at `/api/evaluations/run`.
Without them, the report states judge unavailable. Normal pytest runs clear local provider settings
and reject external HTTP transport, so a live `.env` cannot silently turn regressions into API calls.
Judge reports distinguish completed metrics from passing scores; failed metrics preserve partial results.
LLM judgments are probabilistic; deterministic
schema/citation checks and handler review remain. [TEST_PLAN.md](docs/TEST_PLAN.md) defines all gates.
[IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) maps stages. [VALIDATION.md](docs/VALIDATION.md)
records results. [CHANGE_DECISIONS.md](docs/CHANGE_DECISIONS.md) explains choices and alternatives.
See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for the architecture/design and
[PRESENTATION.md](docs/PRESENTATION.md) for the timed panel demonstration.
[REQUIREMENTS.md](docs/REQUIREMENTS.md) maps every capstone requirement to code and evidence.

## Operational limits

Bind to loopback for this single-process educational demo. SQLite login, per-run ownership,
user/admin roles, CSRF protection and role-boundary tests are implemented. The legacy API key
is used only when authentication is deliberately disabled for isolated service testing.
Password reset, MFA, enterprise identity and organization tenancy are not implemented.
SQLite runs are serialized; this is not a benchmarked multi-worker service. No regulatory/commercial
or real-world insurance accuracy claims are made. Dataset license: CC BY-NC 4.0, ZiadataLabs,
https://huggingface.co/datasets/ziadatalabs/FreeInsuranceClaims100M.

## React frontend

The main route serves the compiled React application; `/classic` keeps the original UI available.
After editing the frontend, rebuild the static bundle from `frontend`:

```powershell
Set-Location frontend
npm ci
npm run test
npm run lint
npm run build
Set-Location ..
```

No additional server is needed for the compiled frontend. Refresh the application after building.
For development, `npm run dev` proxies `/api` to the running backend on port 8000.
See [UI_VALIDATION.md](docs/UI_VALIDATION.md) for the light-theme and interaction checks.

## Prepared Synapt upload corpus

The [upload guide](docs/SYNAPT_UPLOAD_GUIDE.md) covers the 15-document pilot and the
2,163-record expansion in 38 batches. Generate both with
`.venv/Scripts/python.exe scripts/prepare_synapt_corpus.py`; upload only the designated
TXT files, excluding manifests and QA expectations. The pilot combined TXT is an alternative
to its individual files. The user reports uploading two pilot files to `synapt_final_capstone`;
that ID is configured locally. Supplied answers match source values/procedure content but lack
verified claim identity and source attribution and contain graph-confidence warnings.
Application MCP verification remains open; Synapt mode stays fixture pending credentials and checks.
See [direct browser tests](docs/SYNAPT_BROWSER_TESTS.md) for four fresh-chat results, the displayed
identifier redaction and missing historical document linkage; bulk expansion remains gated.
The [additional SOP tests](docs/SYNAPT_SOP_TESTS.md) validate all four new procedures and
targeted cross-procedure retrieval, with mixed-query citation and metadata limits recorded.
