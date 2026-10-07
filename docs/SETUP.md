# Setup on a new machine

This is the complete procedure for going from a fresh clone to a verified, running system. Every
command below was run end to end on a clean copy of the repository. Commands are PowerShell;
`uv` handles Python and the virtual environment, so no manual `pip` or `venv` is needed.

## 0. Requirements

| Need | Detail |
|---|---|
| Git and uv | `winget install --id Git.Git` and `winget install --id astral-sh.uv` (restart the terminal afterwards) |
| Disk | About 7 GB free: 2.5 GB dataset, 1.5 GB Python environment, models and corpus |
| Memory | 8 GB recommended. DuckDB is capped at 3 GB; lower `CLAIMS_DUCKDB_MEMORY` on small machines |
| Network | Hugging Face (dataset), NVIDIA (language models) and `synapt.example.com` (Synapt) |
| Accounts | Synapt login email, password and provider ID; an NVIDIA API key. Needed for live mode only |
| Node.js | Not needed. The compiled UI is committed. Install it only if you edit `frontend/` |

You can try the application with no accounts at all: leave `SYNAPT_MODE=fixture` and
`AGENT_MODE=fixture` (the defaults). Everything works except live Synapt retrieval and
model-written briefs.

## 1. Get the code and dependencies

```powershell
git clone <your-repository-url> synapt_capstone
Set-Location synapt_capstone
uv sync --locked --extra evaluation --extra search
```

`--extra evaluation` installs DeepEval; `--extra search` installs the small local embedding model
library used by the saved-case search box. Both are optional but recommended.

## 2. Configure

This private repository **tracks `.env`**, so a clone already contains the live configuration and
credentials and needs no editing. Only if `.env` is missing, start from the template:

```powershell
Copy-Item .env.example .env
notepad .env
```

All paths in `.env` are relative to the repository, so it works unchanged on any machine. Never
make this repository public while `.env` is tracked; if you do, untrack it and rotate every key.
For the full live system the values are:

| Key | Value |
|---|---|
| `SYNAPT_MODE` | `live` |
| `SYNAPT_USERNAME` | your Synapt login **email** (the field name is already set to `email`) |
| `SYNAPT_PASSWORD` | your Synapt password |
| `SYNAPT_PROVIDER_ID` | `synapt_final_capstone` (the provider that holds the claim cards) |
| `AGENT_MODE` | `live` |
| `NVIDIA_API_KEY` | your key from build.nvidia.com |
| `JUDGE_MODE` | `inline` to have a second, independent model review every brief (`off` to skip) |

Leave everything else at its default.

## 3. Download the data, train the models, build the corpus

```powershell
uv run python scripts/bootstrap.py all
```

This runs four steps and prints a result line for each:

| Step | What it does | Time |
|---|---|---|
| `data` | Downloads `insurance_claims_100M.parquet` (2.5 GB) from Hugging Face, then **verifies its SHA256 against the hash Hugging Face publishes**, the row count (100,000,000) and the 13 column names | 3 to 30 min, depending on bandwidth (180 s measured on a fast link). Interrupted downloads resume |
| `train` | Draws a repeatable 600,000-row sample (`CLAIMS_TRAIN_ROWS`) from the file and trains the amount, resolution-time and fraud-flag models | about 4 to 5 minutes (260 s measured in a fresh clone) |
| `corpus` | Writes 1,000 claim cards (200 per type) and the 5 procedures as upload batches under `artifacts/synapt/corpus-v3` | about 6 s |
| `check` | Reports what is ready and what is missing | a few seconds |

Run any step alone with `uv run python scripts/bootstrap.py data|train|corpus|ingest|check`.
Re-running is safe: a verified download is reused, and models are retrained only with `--retrain`.

## 4. Synapt provider

The cards live in Synapt's cloud, not on your machine. The provider `synapt_final_capstone`
already holds the 5 procedures, the 1,000 base claim cards and 19,887 expansion cards (63 documents,
20,914 chunks), so on a second computer you do **not**
upload anything. Confirm that it is reachable and populated:

```powershell
uv run python scripts/verify_synapt_store.py
uv run python scripts/synapt_ingest.py status
```

`verify_synapt_store.py` is the authoritative check (and what `bootstrap.py check` runs): it reads
document sizes from Synapt's graph and compares them with the committed
`data/synapt/expected_inventory.json`, so it gives the same answer on every machine. Expect
`base corpus: 10/10`, `expansion corpus: 40/40` and `procedures: 5/5`. `status` prints document and
chunk counts (expect 63 documents and 20,914 chunks; `ledger_batches: 0` on a second machine is normal).

`synapt_ingest.py verify --sample 20` is a semantic-precision spot check that only works on the machine
that performed the upload. It samples claims from the local upload ledger
(`artifacts/synapt/corpus-v3/ledger.jsonl`), which is not in Git, so anywhere else it exits with
`No submitted batches in the ledger yet`. That is expected, not a fault: use `verify_synapt_store.py`.
On the original machine it asks Synapt for cards similar to 20 sampled claims and reports how often the
returned cards share the claim's type, state, amount band and history, next to the rate expected by chance.

**The corpus built on a laptop is not the corpus in the provider.** `bootstrap.py corpus` rebuilds a
1,000-card sample deterministically (two builds on one machine and a fresh clone were identical), but
the sample uploaded earlier was selected differently (most likely by an earlier version of the builder,
which Git does not retain): only 52 of its 1,000 claims coincide with the rebuilt ones. Nothing at runtime reads the local corpus, so the application is
unaffected. It matters only if you populate a *new* provider with `bootstrap.py ingest`, which would
upload a different, equally valid sample. The exact uploaded batches exist only on the original laptop
(`artifacts/synapt/corpus-v3`, not in Git); `data/synapt/expected_inventory.json` records their sizes
and hashes.

To populate a **new, empty** provider (created in the Synapt console, knowledge kind), put its ID in
`.env` and run:

```powershell
uv run python scripts/bootstrap.py ingest --procedures
```

That uploads 10 batches, one at a time, waiting for each to finish (about 3 minutes per batch).
It records progress in `artifacts/synapt/corpus-v3/ledger.jsonl`, skips finished batches if you
re-run, and refuses to start if the provider already contains claim cards (override with `--force`).

## 5. Optional: local saved-case search model

```powershell
uv run --extra search python scripts/prepare_case_search.py
```

Downloads a small (about 90 MB) embedding model so the header search can match by meaning. Without
it the search falls back to ID and text matching.

## 6. Run

```powershell
uv run uvicorn claims.api:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. On first use choose an administrator username and a password of at
least 15 characters (accounts are stored in `data/runtime/auth.sqlite` on that machine only).
Under **Accounts** you can add ordinary users. API documentation is at `/docs`.

## 7. Verify that everything works

```powershell
uv run pytest -q                                   # backend: offline, about 2 minutes
uv run python scripts/bootstrap.py check           # data, models, corpus, Synapt
```

In the application: open **Quality & models** and press **Run evaluations** (golden cases). Tick
**LLM judge** first to also run the three DeepEval metrics on each brief; without the tick the judge
status stays `not_run`. With the judge the run takes several minutes (the page stays busy until it
returns). Then submit the "Auto theft" example. You should see cited findings, a **Handling priority** breakdown,
three model estimates with a "Why this estimate" explanation, and (when `JUDGE_MODE=inline`) an
**Independent review** verdict.

To rebuild the UI after editing `frontend/`: `Set-Location frontend; npm ci; npm run test;
npm run build; Set-Location ..` (the build writes into `src/claims/static/app`). This needs
**Node 20.19 or newer** (Vite 8); see Troubleshooting for the Windows notes.

## 8. Optional: reproduce the fraud experiments

`bootstrap.py train` trains the models the application serves. It does **not** run the fraud
experiments, and those need an extra ordered chain: `improve_fraud_model.py` stops with
`FileNotFoundError: retraining_report.json` unless `retrain_models.py` has run first. Run these
after `bootstrap.py data`. In a fresh clone on 2026-10-07 all four exited 0 in about 16 minutes:

```powershell
uv run python scripts/retrain_models.py --rows 600000 --memory-limit 1GB   # ~5 min; writes artifacts/models/retraining_report.json
uv run python scripts/improve_fraud_model.py                                 # ~5.5 min; regenerates fraud_training_expanded.parquet
uv run python scripts/experiment_fraud_features.py                           # ~4.5 min; regenerates fraud_feature_holdout.parquet
uv run python scripts/experiment_fraud_features.py --verify-only             # ~1 min; independent re-check
```

Expected result: both Parquet files in `data/processed/ml/` are rebuilt **byte for byte**.

| File | SHA256 |
|---|---|
| `fraud_training_expanded.parquet` | `d73c2665c25ae9434b516e2fd3e5fdd2ff058daf80b4aea09bfb3541f84933bf` |
| `fraud_feature_holdout.parquet` | `bcfd03cc42c3e4f1510b34a8cab9350b051dbd0450285a6e6163603ce6c0c22f` |

Check with `Get-FileHash -Algorithm SHA256 data/processed/ml/<file>.parquet`. The trained `.joblib`
files are **not** byte-identical across machines (they embed training timestamps), but their
embedded reports (every metric, split and sample hash, ignoring timestamps and timings) matched the
originals with zero differences.

Notes:

- Both Parquet files are committed, so a fresh clone already has them; the chain above is only
  needed to prove they can be regenerated from the 100M-row source.
- `experiment_fraud_features.py` is pre-registered and refuses to run twice against the same
  `artifacts/models` ("holdout is reserved/consumed"). To start over, delete
  `fraud_feature_protocol.json` and `fraud_feature_experiment.json` from `artifacts/models`.
- `--verify-only` loads the candidate model written by the full run, so run the full experiment
  once before using it.

## What is where

| Path | Contents | In Git? |
|---|---|---|
| `data/raw/parquet/` | the 100M-row dataset | no (downloaded) |
| `artifacts/models/` | trained models | no (trained) |
| `artifacts/synapt/` | built corpus and upload ledger | no (built) |
| `data/runtime/` | databases: saved cases, accounts, checkpoints | no (created on first run) |
| `data/bootstrap/` | credential-free seed databases copied on first run | yes |
| `.env` | secrets and mode switches | yes (private repository only) |

## Troubleshooting

For the 7 October corpus and training refresh, see [data expansion](DATA_EXPANSION_2026-10-07.md),
[ML verification](ML_RETRAINING_2026-10-07.md), and [evaluation audit](EVAL_AUDIT_2026-10-07.md).
The expanded `claim_cards.parquet` is a validated local artifact. This provider extracts its schema,
so use the paired `cards/expanded-*.txt` for semantic ingestion. All 40 batches have already been
submitted through MCP and verified (40 of 40, see step 4); do not upload them again. To re-check:

```powershell
uv run python scripts/verify_synapt_store.py
```

This command makes no provider writes and is exact (it reads document sizes from Synapt's graph).
A partial retrieval inventory cannot establish that a missing
card was never ingested. The script never automatically repeats an uncertain write; a retry of an
explicit rejection requires `--retry-rejected`. Restart a running API after retraining to load the new
model artifact and backend changes.

| Symptom | Cause and fix |
|---|---|
| `uv` is not recognised | Restart the terminal after installing, or run `winget install --id astral-sh.uv` |
| `bootstrap.py data` is slow or stops | Run it again; the download resumes. Use `--redownload` only if the SHA256 check fails |
| `SHA256 differs from the published file` | The file is corrupt. Delete `data/raw/parquet/insurance_claims_100M.parquet` and re-run `data` |
| Out-of-memory error from DuckDB | Set `CLAIMS_DUCKDB_MEMORY=1500MB` in `.env` |
| Each search takes 3 to 5 seconds | Expected: it scans 100 million rows. The first query after a reboot is slower while the file cache warms |
| `Synapt request failed` | Synapt rate-limits logins (HTTP 429). The client now reuses one login and honours `Retry-After`; wait a minute and retry. Run `bootstrap.py check` to see which call fails |
| `Provider ... already contains historical claim cards` | Intended: another machine uploaded them. Use `status` and `verify`; do not upload twice |
| Brief says "Independent review: Failed" | The judge model timed out (60 s per attempt, two attempts; the endpoint is slower when several briefs run at once). The brief is unaffected. Raise `JUDGE_TIMEOUT_SECONDS` (max 120), pick a faster `JUDGE_MODEL`, or set `JUDGE_MODE=off` |
| Model estimates show "not trained" | Run `bootstrap.py train`, or press **Train models** on the Quality page (about 80 s) |
| Low on disk space | Use the 3,000-row fallback instead: `uv run python scripts/fetch_dataset.py --count 3000`, and leave `CLAIMS_PARQUET_PATH` pointing at a missing file. Retrieval and models then use that small sample |
| `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain` (also `winget` certificate errors, or `Synapt request failed` on every call) | A corporate proxy that inspects TLS (for example Netskope or Zscaler) re-signs traffic with a CA that Windows trusts but Python's bundled `certifi` list does not. Do not disable verification. Make Python use the Windows certificate store: save `import importlib.util; importlib.util.find_spec('truststore') and __import__('truststore').inject_into_ssl()` as one line in `.venv\Lib\site-packages\system_certs.pth` (`truststore` is already a dependency; the `.venv` is not in Git; recreate the file after rebuilding the venv). For `npm`, export the proxy's CA certificates to a PEM file and set `NODE_EXTRA_CA_CERTS` to it |
| `npm run build` fails with `Cannot find module '@rolldown/binding-win32-x64-msvc'` | The Windows binding is optional and requires Node 20.19+ (or 22.12+). On an older Node, `npm ci` skips it silently (look for `EBADENGINE` warnings). Install a newer Node and run `npm ci` again |
| `npm run test` says `Could not find '...tests\*.test.cjs'` | Node 20 on Windows does not expand the glob. Run `node --test tests/ui-regressions.test.cjs` instead |
