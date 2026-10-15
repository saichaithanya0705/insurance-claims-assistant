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
| Accounts | **Synapt** login email, password and provider ID: required, the application does not start without them. An NVIDIA API key is needed only for model-written briefs |
| Node.js | Not needed. The compiled UI is committed. Install it only if you edit `frontend/` |

Synapt is not optional. It is the knowledge layer (procedures, past claims in its ticket store, handler lessons), and
there is no mode, setting or fallback that runs the application without it: with the Synapt login
missing the application refuses to start, and with Synapt unreachable an investigation fails visibly
and produces no brief. `AGENT_MODE=fixture` (the default) needs no NVIDIA account; it replaces only
the model-written brief with deterministic rules, and the evidence still comes from live Synapt.

## 1. Get the code and dependencies

```powershell
git clone <your-repository-url> synapt_capstone
Set-Location synapt_capstone
uv sync --locked --extra evaluation --extra search
```

`--extra evaluation` installs DeepEval; `--extra search` installs the small local embedding model
library used by the saved-case search box. Both are optional but recommended.

## 2. Configure

`.env` holds credentials, so it is **not in Git** (it is git-ignored). Create it from the template
and fill in your own values:

```powershell
Copy-Item .env.example .env
notepad .env
```

All paths in `.env` are relative to the repository, so it works unchanged on any machine. Keep keys
in `.env` or `.env.local` (both git-ignored), never in a tracked file.
For the full system the values are (the three Synapt values are required):

| Key | Value |
|---|---|
| `SYNAPT_USERNAME` | your Synapt login **email** (the field name is already set to `email`) |
| `SYNAPT_PASSWORD` | your Synapt password |
| `SYNAPT_PROVIDER_ID` | `synapt_capstone1` (procedures as documents, past claims in its ticket store) |
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
| `corpus` | Writes 10,000 profile cards (2,000 per claim type) and the 5 original procedures under `artifacts/synapt/corpus-profile-balanced-2026-10-09`. Local only: its `claim_cards.parquet` is what the degraded-mode fallback searches. The cards are no longer in Synapt (since 13 October 2026) and must not be uploaded to `synapt_capstone1` | about 25 s |
| `check` | Reports what is ready and what is missing | a few seconds |

Run any step alone with `uv run python scripts/bootstrap.py data|train|corpus|check`.
Re-running is safe: a verified download is reused, and models are retrained only with `--retrain`.
(`ingest` also exists but uploads the card batches; do not run it against `synapt_capstone1`, see step 4.)

**Recommended, about 30 s: the cohort summary.** The "how were claims like this settled?" figures are an exact count over all 100 million rows,
which takes 4 to 10 s per investigation. Counting every group once makes it take 4 ms, with the same numbers:

```powershell
uv run python scripts/build_cohort_summary.py        # writes data/derived/cohort_summary.duckdb (git-ignored)
```

The script then compares 25 random descriptions with the full scan (about 3 minutes) and deletes the file if one number differs
(`--verify 0` skips this). The application uses the file only if it was built from this very dataset (SHA-256), cutoff date and band edges; if
it is missing or stale it says nothing and scans as before, so skipping this step changes speed, never an answer.

**Recommended, about 5 to 9 minutes, 2.6 GB: the sorted copy.** The search for the 300 closest past claims reads every claim of the new
claim's type (35 million for auto). A copy of the dataset in DuckDB's own format, sorted by type, state and amount, with each claim's closing
date stored once, makes it about twice as fast or better:

```powershell
uv run python scripts/build_claims_copy.py           # writes data/derived/claims_sorted.duckdb (git-ignored)
```

The script then runs 20 searches on both the copy and the Parquet file (random claims, with and without a state, an outcome or an amount
range) and deletes the copy if a single row or its order differs. The application uses it only if it records this dataset's SHA-256, row count
and layout; otherwise it searches the Parquet file as before, so skipping this step changes speed, never an answer.

## 4. Synapt provider

The knowledge lives in Synapt's cloud, not on your machine. The provider `synapt_capstone1` already holds the
17 procedures as documents (18 documents, 39 chunks; the 18th is Synapt's own episode store) and 2,000 past claims
in its ticket store, so on a second computer you do **not** upload anything. Confirm that it is reachable and populated:

```powershell
uv run python scripts/verify_synapt_store.py
uv run python scripts/synapt_ingest.py status
```

`verify_synapt_store.py` is the authoritative check (and what `bootstrap.py check` runs): it reads
document sizes from Synapt's graph and compares them with the committed
`data/synapt/expected_inventory.json`, so it gives the same answer on every machine. Expect
`procedures: 17/17 found by source id`, `ticket store: 2,000 tickets (400 held out by Synapt), labels fraud_flag, resolution`
and `18 documents in all, 39 chunks: procedures and Synapt's own episode memory`. It fails if a large document that is not
a procedure (a leftover card batch) is still in the provider. `status` prints document and chunk
counts (expect 18 documents and 39 chunks; the total may grow as Synapt records further episodes from handler
ratings and query-agent sessions, and `ledger_batches: 0` on a second machine is normal).

**Do not upload claim cards to `synapt_capstone1`.** Until 13 October 2026 it also held 10,000 profile cards as
20 documents; they were removed because past claims belong in the ticket store, not among the procedures (see
[SYNAPT_INTEGRATION.md](SYNAPT_INTEGRATION.md#how-the-data-is-split-across-synapt-corrected-13-october-2026)).
`synapt_ingest.py ingest` (without `--procedures-only`) and `ingest_expanded_cards.py` still upload card batches and
must not be pointed at this provider. `bootstrap.py ingest` uploads only the procedures (from 13 October 2026) and prints
how to add the ticket workbook through the console. `synapt_ingest.py verify` measured the card search and
has nothing to measure here now.

**The past-claim tickets.** The ticket store was filled from the workbook
`artifacts/synapt/ticketing-capstone1/claims_tickets_capstone1.xlsx` (2,000 settled claims, 400 per claim type, the
dataset's own fraud and denial rates), built with:

```powershell
uv run python scripts/make_ticketing_sample.py --output artifacts/synapt/ticketing-capstone1 --per-type 400 --natural --name claims_tickets_capstone1
```

and uploaded in the Synapt console (Data Ingestion, Ticketing): ID column `ticket_id`; Embed `title`, `description`,
`category`, `region`; Predict `resolution`, `fraud_flag`; every other column Store only.

**Rebuilding the card file gives the same cards.** `bootstrap.py corpus` (or `scripts/build_profile_corpus.py`) is
deterministic: a rebuild produced 20 of 20 batches byte-identical to the ones once uploaded, so the local fallback
index holds exactly the cards the provider held. Which claims are chosen, and why, is in
[CORPUS_STRATEGY.md](CORPUS_STRATEGY.md).

To populate a **new, empty** provider, use the same split: the procedures as documents (`synapt_ingest.py ingest
--procedures-only --corpus <folder>`, for the 5 original procedures in the profile-corpus folder and the 12 written by
`scripts/build_procedures.py`), then the ticket workbook through the console as above. This path has not been re-run
since the split was corrected, and the committed inventory describes `synapt_capstone1` only.

The earlier provider `synapt_final_capstone` (1,000 + 19,887 cards) is untouched; its inventory is kept as
`data/synapt/expected_inventory.synapt_final_capstone.json`. Do not upload into it again.

## 5. Optional: local saved-case search model

```powershell
uv run --extra search python scripts/prepare_case_search.py
```

Downloads a small (about 90 MB) embedding model so the header search can match by meaning. Without
it the search falls back to ID and text matching.

## 6. Run

```powershell
uv run uvicorn claims.api.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. On first use choose an administrator username and a password of at
least 15 characters (accounts are stored in `data/runtime/auth.sqlite` on that machine only).
Under **Accounts** you can add ordinary users. API documentation is at `/docs`.

## 7. Verify that everything works

```powershell
uv run pytest -q                                   # backend: offline, about 2 minutes
uv run python scripts/bootstrap.py check           # data, models, local card file, Synapt store
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
| `artifacts/synapt/` | local card file (fallback), procedure folders, ticket workbook, old upload ledgers | no (built) |
| `data/runtime/` | databases: saved cases, accounts, checkpoints | no (created on first run) |
| `data/bootstrap/` | credential-free seed databases copied on first run | yes |
| `.env` | secrets and mode switches | no (git-ignored; create it from `.env.example`) |

## Troubleshooting

For the 7 October corpus and training refresh, see [data expansion](DATA_EXPANSION_2026-10-07.md),
[ML verification](ML_RETRAINING_2026-10-07.md), and [evaluation audit](EVAL_AUDIT_2026-10-07.md).
Those reports describe card uploads to earlier providers (the 40 expanded batches went to `synapt_final_capstone`);
`synapt_capstone1` holds no cards since 13 October 2026. To re-check the current provider:

```powershell
uv run python scripts/verify_synapt_store.py
```

This command makes no provider writes and is exact (it reads document sizes from Synapt's graph and the
ticket count from its statistics). Restart a running API after retraining to load the new
model artifact and backend changes.

| Symptom | Cause and fix |
|---|---|
| `uv` is not recognised | Restart the terminal after installing, or run `winget install --id astral-sh.uv` |
| `bootstrap.py data` is slow or stops | Run it again; the download resumes. Use `--redownload` only if the SHA256 check fails |
| `SHA256 differs from the published file` | The file is corrupt. Delete `data/raw/parquet/insurance_claims_100M.parquet` and re-run `data` |
| Out-of-memory error from DuckDB | Set `CLAIMS_DUCKDB_MEMORY=1500MB` in `.env` |
| Each search takes 3 to 5 seconds | Expected: it scans 100 million rows. The first query after a reboot is slower while the file cache warms |
| `Synapt request failed` | Synapt rate-limits logins (HTTP 429). The client now reuses one login and honours `Retry-After`; wait a minute and retry. Run `bootstrap.py check` to see which call fails |
| `Provider ... already contains historical claim cards` | A card uploader was pointed at a provider that holds cards. `synapt_capstone1` should hold none: do not upload cards to it. Run `verify_synapt_store.py` |
| `leftover document ...: not a procedure, and too large for one` | A card batch (or another large document) is in the provider. Past claims belong in the ticket store; delete the document in the Synapt console, then re-run `verify_synapt_store.py` |
| `ticket store: the provider has no ticket store` (or a ticket count other than 2,000) | The ticket workbook is missing or was uploaded differently; see step 4, "The past-claim tickets" |
| Brief says "Independent review: Failed" | The judge model timed out (60 s per attempt, two attempts; the endpoint is slower when several briefs run at once). The brief is unaffected. Raise `JUDGE_TIMEOUT_SECONDS` (max 120), pick a faster `JUDGE_MODEL`, or set `JUDGE_MODE=off` |
| Model estimates show "not trained" | Run `bootstrap.py train`, or press **Train models** on the Quality page (about 80 s) |
| Low on disk space | Use the 3,000-row fallback instead: `uv run python scripts/fetch_dataset.py --count 3000`, and leave `CLAIMS_PARQUET_PATH` pointing at a missing file. Retrieval and models then use that small sample |
| `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain` (also `winget` certificate errors, or `Synapt request failed` on every call) | A corporate proxy that inspects TLS (for example Netskope or Zscaler) re-signs traffic with a CA that Windows trusts but Python's bundled `certifi` list does not. Do not disable verification. Make Python use the Windows certificate store: save `import importlib.util; importlib.util.find_spec('truststore') and __import__('truststore').inject_into_ssl()` as one line in `.venv\Lib\site-packages\system_certs.pth` (`truststore` is already a dependency; the `.venv` is not in Git; recreate the file after rebuilding the venv). For `npm`, export the proxy's CA certificates to a PEM file and set `NODE_EXTRA_CA_CERTS` to it |
| `npm run build` fails with `Cannot find module '@rolldown/binding-win32-x64-msvc'` | The Windows binding is optional and requires Node 20.19+ (or 22.12+). On an older Node, `npm ci` skips it silently (look for `EBADENGINE` warnings). Install a newer Node and run `npm ci` again |
| `npm run test` says `Could not find '...tests\*.test.cjs'` | Node 20 on Windows does not expand the glob. Run `node --test tests/ui-regressions.test.cjs` instead |
