# Validation record: 2026-10-06

Results of validating the system on the **full 100-million-row dataset**, the **real Synapt provider**
and the **real NVIDIA models**, on the Windows workstation that built it. Older records
([LIVE_NIM_VALIDATION.md](LIVE_NIM_VALIDATION.md), [LIVE_PROJECT_EVALUATION.md](LIVE_PROJECT_EVALUATION.md))
describe the earlier 3,000-row version.

## Summary

| Check | Result |
|---|---|
| Backend tests | **169** tests; all pass; no network and no real dataset used |
| Lint | `ruff check src tests scripts`: all checks passed |
| Frontend | 16 UI tests pass; TypeScript clean; oxlint reports 14 pre-existing warnings, 0 errors |
| Dataset | 2,519,982,987 bytes, **SHA256 equals the hash Hugging Face publishes**; exactly 100,000,000 rows; the 13 documented columns |
| Models (200,000-row sample) | Amount MAE $16,072 (baseline $22,364); resolution MAE 6.58 d (7.22); fraud precision 55.6%, PR-AUC 0.322 (0.078) |
| Search over 100M rows | 3 to 5 s per filtered, fused search |
| Synapt corpus | 1,000 cards in 10 batches, 1,000 chunks, one card per chunk |
| Synapt semantic precision | 1.7x chance on claim type; none on prior claims (60 queries) |
| Live golden cases | 4 of 4 pass |
| DeepEval (live) | 12 of 12 metrics completed; **8 pass** |
| Live feedback loop | Promote, then cited in the next brief; Synapt 21 to 22 documents |
| Fresh-clone reproduction | See the last section |

## Dataset

`bootstrap.py data` downloads `insurance_claims_100M.parquet`, compares its SHA256 with the one Hugging
Face publishes (`dfdca2bb...b1820a`), and checks the row count and column names. Mix by status:
approved 72.8%, under review 10.1%, denied 9.0%, pending 8.1%; 7.66% fraud-flagged. Pending claims store
their duration as **NaN, not null**, which the SQL handles (`TRY_CAST`).

## Retrieval at scale (real file)

* Type-restricted candidate scan with filters, a feature-similarity ordering and the historical-
  availability rule: 2.9 s; with type and state, 1.9 s; a full scan, 4.6 s. A persisted sorted copy
  ran out of memory and was not needed.
* Every filter dimension verified against 100M rows: type, state, status (all four), amount range and
  prior-claims range. `pending` and `under_review` return claims with no outcome.
* Semantic identifiers from Synapt are looked up under the same filters; ones that fail a filter are dropped.

## Models

| | Result | Baseline |
|---|---|---|
| Amount | MAE $16,072; 90% interval covers 90.1% | $22,364 |
| Resolution | MAE 6.58 days; interval covers 89.8% | 7.22 days |
| Fraud flag | precision 55.6%, recall 31.1%, PR-AUC 0.322, Brier 0.0602 | PR-AUC 0.0775, Brier 0.0715 |

Training takes about 80 s and is repeatable (the sample is deterministic: three runs returned the
same rows). See [MODEL_CARD.md](MODEL_CARD.md).

## Synapt

* Ingested 10 batches of 100 cards with `chunk_size=100`: chunks 24 to 1,024, one card per chunk.
* **Semantic precision** (`synapt_ingest.py verify --sample 60`, 60 queries, 0 failures): share of
  returned cards matching the query claim, against a random pair of cards:

  | | Synapt | Chance |
  |---|---:|---:|
  | Claim type | 33.5% | 20.1% |
  | State | 6.8% | 3.9% |
  | Amount band | 23.0% | 15.7% |
  | Prior-claims band | 35.2% | 34.9% |

* A live retrieval for the demo claims returned 48 to 55 matching cards, of which 10 to 52 were
  eligible under the filters; three were shown as "related by meaning".

## Live end-to-end (four demo cases, UI-equivalent API calls)

| Case | Brief returned | Outcome | Priority | Judge (background) |
|---|---:|---|---|---|
| Auto, repair evidence | 18 s | awaiting review after the wording fix (4 of 4 repeats) | Low | passed, 0.85 |
| Auto theft, missing evidence | 12.5 s | awaiting review; police-report gap cited | **High 55/100** | passed, 0.9 |
| Home, conflicting statements | 13.6 s | awaiting review; contradiction surfaced | **High 45/100** | passed, 0.9 |
| Ambiguous claim | 13.2 s | held for manual review; classification abstained | Low 15/100 | flagged |

The judge's flag on the ambiguous case was a complaint that a `limitation` finding had no citation;
limitations are designed not to need one, and the judge prompt now says so.

## Live feedback loop

Run on the test instance against the real provider: investigation, accepted brief, a rating of 5 with a
real handler note, **promotion** (HTTP 200, Synapt 21 to 22 documents and 1,024 to 1,025 chunks), a
new auto investigation that **cites `lesson:3`** in its findings and recommendations with validation
passing, a home claim that does **not** receive the auto lesson, and a second promotion refused with 409.

## Evaluation

* **Golden cases**: 4 of 4 pass, live (`POST /api/evaluations/run`).
* **DeepEval** (judge `nvidia/nemotron-3-super-120b-a12b`): 12 of 12 metrics completed.

  | Metric | Per case | Passed |
  |---|---|---:|
  | Faithfulness | 1.00, 1.00, 0.33, 1.00 | 3 of 4 |
  | Contextual Relevancy | 0.72, 0.39, 0.41, 0.15 | 1 of 4 |
  | Claims-handling safety and usefulness (GEval) | 1.00, 0.90, 0.90, 0.90 | 4 of 4 |

  Contextual Relevancy is the weak metric. The retrieval context deliberately includes comparison
  claims and procedures, which it counts as off-topic. Thresholds were not lowered.
* **Independent judge** (`openai/gpt-oss-20b`): 4 of 5 verdicts completed in 12 to 23 s in a reliability
  test; one failed schema validation. It runs in the background, so its latency does not delay the brief.

## Interface (driven in a browser)

Logged in as an administrator, walked the intake wizard, confirmed the filters (including the four
outcome statuses and their hint), built a live investigation, and inspected the saved-case library
(priority tier badges, sort and tier filters). Verified in the rendered brief: the **Handling priority**
breakdown, the model estimates with **Why this estimate**, and the **Independent review** moving from
"in progress" to a verdict. Screenshots: [live-priority-and-judge.jpg](screenshots/live-priority-and-judge.jpg),
[live-cited-findings.jpg](screenshots/live-cited-findings.jpg). Layout was checked at phone width.

## Problems found by live validation, and fixed

| Problem | Cause | Fix |
|---|---|---|
| A $3,393 New Jersey claim ranked above exact $8,500 Texas matches | BM25 IDF rewarded the rare terms of diverse semantic outliers in a pool of near-identical claims | No IDF in the keyword leg; weighted fusion; extras shown separately; regression test |
| Synapt returned HTTP 429 | A fresh login for every call | One cached token, `Retry-After` honoured |
| Half of the verification queries failed | The same rate limiting | Same fix |
| One brief took 67 s longer | The inline judge timed out, then retried | The judge runs in the background and its verdict is merged when ready |
| Ordinary auto brief held for manual review | The model wrote that a document "has been provided" | Prompt requires "reports ... is available"; 4 of 4 then pass |
| Identifiers and states unreadable in Synapt | PII masking | Letters-only alias and opaque region token, verified by a probe |
| A permanent "could not be linked to a source" warning | Two optional Synapt calls that can never be cited | Off by default |
| Tests took 6 minutes | They found the real dataset on the default path | Hermetic test configuration |

## Known limitations

Synthetic data; Synapt's semantic signal is mild; fraud recall is 31%; Contextual Relevancy is weak; the
judge is advisory and probabilistic. The Synapt web console and any console-side Parquet upload were
not tested. Docker packaging was not attempted (the daemon was not running).

## Fresh-clone reproduction

SETUP.md was followed literally in an empty directory containing only the files Git would ship (133
files, 9 MB, no `.env`, no environment, no data):

| Step | Result |
|---|---|
| `uv sync --locked --extra evaluation --extra search` | succeeded in 1 m 46 s (so `uv.lock` matches `pyproject.toml`) |
| `bootstrap.py all` (fixture-mode `.env`) | downloaded the 2.5 GB file in 265 s; SHA256 matched Hugging Face; 100,000,000 rows; trained in 86 s; built the corpus; ended **READY** |
| Models | **identical** to the main machine: amount MAE $16,072, resolution 6.58 d, fraud precision 55.6%, PR-AUC 0.322 |
| `uv run pytest -q` | 168 passed, **1 failed**: a test imported `tests.test_auth_rbac`, which only works under `python -m pytest`. Fixed; passes under both |
| First-run application | `setup_required: true`, administrator created, login, a real investigation over the 100M rows in 4.5 s |
| Reproducibility of results | the clean copy returned the same closest claims, amount estimate ($10,652.19) and fraud score (0.5412) as the main instance |

Not reproducible without credentials: live Synapt retrieval and model-written briefs (set the keys in
`.env`). The Synapt corpus is not re-uploaded: it already lives in the provider and the ingestion
script refuses to duplicate it.
