# ML retraining and independent verification — 7 October 2026

This report records the full-model run at 09:32 IST. The later fraud-only weighting and training-size
experiment supersedes the fraud metrics below; see [the current fraud report](FRAUD_IMPROVEMENT_2026-10-07.md)
and [model card](MODEL_CARD.md). Amount and resolution models were preserved unchanged.

The corrected pipeline beats the original global baselines on the held-out claims. The stronger
baseline comparison also shows a real limit: claim-type medians already explain almost all the
predictable amount signal in this synthetic dataset. More rows or richer retrieval cards cannot
create missing predictive information or prove real-world insurance accuracy.

## Verified results

| Target / metric | Saved model | Global baseline | Stronger simple comparison |
|---|---:|---:|---:|
| Claim amount MAE, USD | **15,105.13** | 22,629.80, training median | **15,105.18**, training claim-type medians |
| Resolution MAE, days | **6.30900** | 7.26102, training median | **6.47820**, training-fitted filing-delay linear regression |
| Fraud average precision / PR-AUC | **0.322248** | 0.077165, training prior | Not measured |
| Fraud Brier score, lower is better | **0.060374** | 0.071212, training prior | Not measured |

Amount MAE is 33.23% lower than the global baseline, and duration MAE is 13.12% lower. Fraud average
precision is 4.18 times the prior baseline and Brier loss is 15.21% lower. The corrected amount model
now matches the claim-type-median comparator within sampling/calibration rounding ($15,105.13 vs
$15,105.18). The pipeline selects that comparator rather than forcing a more complex model.
Duration is 2.61% better than the filing-delay-only comparator; this is a modest gain.
Those two comparators were fitted only on training rows and measured after model selection; they were
not used to tune a model against the test outcomes.

The final candidate decisions were `claim_type_median` for amount, `histogram_boosting_absolute_error`
for resolution, and `random_forest` for fraud. The amount candidate set now includes the type-conditioned
median, so the model cannot claim a complex-model win when the transparent comparator is at least as good.

Fraud precision is **50.00%**, recall **32.23%**, F1 **0.39192**, and balanced accuracy **64.77%**.
Raw accuracy is **92.33%**, versus **92.28%** for an all-negative majority classifier. Raw accuracy is
therefore a poor description of screening usefulness here. The review threshold is **0.273465**;
these scores estimate the synthetic flag, not proven fraud or permission to reject a claim.

The nominal 90% empirical intervals cover **89.91%** of held-out amounts and **88.81%** of held-out
durations. They remain empirical intervals with no guaranteed future coverage. Duration coverage is
below nominal, and unresolved-claim censoring and distribution shift still need work for real use.

## Source, partitions and provenance

- Source: [ZiadataLabs FreeInsuranceClaims100M](https://huggingface.co/datasets/ziadatalabs/FreeInsuranceClaims100M),
  100,000,000 synthetic US property and casualty claims; CC BY-NC 4.0.
- Source file: `data/raw/parquet/insurance_claims_100M.parquet`, 2,519,982,987 bytes.
- Source SHA256: `dfdca2bbbd9599bd8927c3bd3debdf1ffd2687d4c528d5eb26fa6649a9b1820a`.
- Sample: **600,000** unique valid source rows, uniform reservoir sampling, seed 42, **one DuckDB
  sampling thread**; zero source rows failed validation. No outcome labels were generated or changed.
- Sample claim-ID SHA256: `8a5792e4dc18304e7dbed9d3a0a27c7ad1efcfb2a9e984a89d6cee029de0464e`.
- Saved artifact: `artifacts/models/claims_models.joblib`, **4,822,754 bytes**.
- Artifact SHA256: `e72b4ef418f0a3d9c02a06c7161cf002ccaf0d7e5bb2d1f34f888bb0c6a575ac`.
- Trained: **7 October 2026, 09:32:39 IST**; full training plus independent verification took
  **229.50 seconds** in the successful bounded run.

| Partition | Amount / fraud rows | Eligible resolved duration rows |
|---|---:|---:|
| Train, before 2024-05-13 | 222,472 | 179,115 |
| Calibration, 2024-05-13 through 2025-06-23 | 94,188 | 73,410 |
| Test, from 2025-06-24 | 120,158 | 98,270 |

The original 60/20/20 date cohorts keep filing-date peers together. Policies appearing in later
partitions are removed from earlier ones; **no policy overlaps remain**. This removes 163,182
sampled rows from earlier outer partitions. Duration labels require approved/denied status, a finite
nonnegative duration, and observation before the next partition's deadline.

Calibration is further separated by date and policy:

| Model | Selection rows | Probability / interval calibration rows | Threshold rows |
|---|---:|---:|---:|
| Amount | 41,608 | 45,929 | Not applicable |
| Duration | 30,078 | 35,959 | Not applicable |
| Fraud | 41,608 | 22,261 | 23,668 |

Amounts use 2024-12-02 as the selection/uncertainty boundary. Duration uses 2024-11-23. Fraud uses
2024-12-02 and 2025-03-14 to separate selection, probability calibration, and threshold decisions.
Additional repeated-policy purging and duration-label availability account for the smaller totals.

## Cohort results

| Claim type | Amount test rows | Amount MAE, USD | Duration MAE, days | Fraud PR-AUC |
|---|---:|---:|---:|---:|
| Auto | 42,205 | 5,442.06 | 6.32267 | 0.30889 |
| Business | 11,984 | **55,333.69** | 6.28060 | 0.35078 |
| Home | 29,774 | 16,336.39 | 6.30668 | 0.33639 |
| Property | 17,958 | 22,073.49 | 6.31205 | 0.31481 |
| Renters | 18,237 | 2,187.14 | 6.29676 | 0.30997 |

Business amounts remain particularly uncertain. An overall score must not hide that error or imply
that the point estimate is appropriate for settlement decisions.

## Change transparency

### What I did

Added MAE-aligned histogram boosting and explicit baseline-inclusive candidate selection (including
the claim-type median estimator), retrained
from 600,000 original records, separated calibration decisions, corrected an interval deadline bias,
removed random internal validation from temporal early stopping, refit the selected winner on the
selection rows, bounded compute, preserved legacy artifact inference, and added independent
source/artifact verification.

### Why this approach

Amount and duration are scored by absolute error, so an absolute-error objective better matches the
evaluation target. Candidate selection uses calibration labels; numerical intervals and fraud
calibration/thresholds use later disjoint labels. The [scikit-learn histogram boosting
documentation](https://scikit-learn.org/1.7/modules/generated/sklearn.ensemble.HistGradientBoostingRegressor.html)
documents the default random `validation_fraction` behavior and the explicit chronological validation
arguments used here; the [calibration documentation](https://scikit-learn.org/stable/modules/calibration.html)
requires calibration data independent of classifier fitting. The source card confirms this is a
100M-row synthetic claims dataset, so the [dataset schema and provenance](https://huggingface.co/datasets/ziadatalabs/FreeInsuranceClaims100M)
must not be read as real-world representativeness.

### Why not the alternative

Adding fabricated outcomes, including the amount target as an input, using future claim status,
or choosing a candidate from held-out scores would make apparently better predictions invalid.
An unconstrained larger forest also wastes this workstation's resources without demonstrating more signal.

### What was the issue / root cause

The earlier pipeline used a squared-error forest objective while evaluation used MAE, selected one
fixed fraud candidate, and reused calibration labels for sigmoid fitting and threshold selection. It
also let histogram boosting use its default random internal validation slice, which is inappropriate
for a filing-date benchmark, and left the selection rows out of the final selected-model fit. An
artificial intermediate duration-label deadline censored slow claims from interval calibration.
Parallel source sampling and unbounded native threads also made repeatable verification and concurrent
work fragile. A full-source profile found near-zero amount correlations with deductible, tenure and
prior-claim count within every claim type, explaining why the claim-type median remains tied with the
model.

### Why this works best

Selection remains separate from evaluation, all comparisons use the same reconstructed held-out
claims, regression calibration uses outcomes observable by test start, chronological early stopping
avoids random temporal leakage, and the selected model uses both fit and selection rows before final
calibration. Two native/model workers plus a single 1GB DuckDB scanner keep the successful run bounded.
The stronger comparator exposes the amount model's signal ceiling instead of claiming a nonexistent
improvement.

### Other valid patterns

Claim-type medians are a simpler valid amount estimator with essentially identical error here.
A filing-delay-only regression is a transparent duration estimator with slightly higher MAE.
Representative permitted real claims, richer pre-outcome features, independent outcome timestamps,
survival models for unresolved durations, cohort calibration and drift monitoring are valid next steps;
they require appropriate data and evaluation rather than more generated labels.

## Reproduce and validation

```powershell
uv run python scripts/retrain_models.py --rows 600000 --memory-limit 1GB
uv run pytest tests/test_analytics.py -q
uv run ruff check src/claims/ml/analytics.py scripts/retrain_models.py tests/test_analytics.py
```

Evidence is in `artifacts/models/retraining_report.json`, with progress logs in
`retraining.stdout.log` and `retraining.stderr.log`. The stderr log was empty on successful exit.
The script reloads the saved artifact, reconstructs the source sample and test cohorts, verifies the
sample-ID digest and policy disjointness, then recomputes all three reported primary metrics within
absolute tolerance 1e-9. **All three stored metrics matched independently recomputed predictions.**
It also reports test claim-ID hashes and cohort scores. **20 focused ML tests passed; the full project suite passed 232 tests**;
Ruff passed. Tests include outcome-leakage invariance, independent calibration cohorts, no-signal
baseline preference, old-artifact compatibility and independent holdout reconstruction.

No task-created training process remains. Existing API processes were not terminated. A running
application that loaded the previous artifact needs reinitialization to display these saved models.
