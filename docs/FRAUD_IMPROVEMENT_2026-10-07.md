# Fraud weighting, threshold and training-size experiment

The experiment uses fixed filing-date and policy-disjoint validation/test cohorts reconstructed from
the verified 600,000-record source sample. Class weighting changes fitting only: probability
calibration, threshold selection and final test keep the source's natural class ratios.

## Measured result

Neither weighting the forest nor doubling the training pool produced a material improvement.
The selected configuration is the unweighted 100,000-row forest, refitted with 41,608 selection rows.
It has slightly higher accuracy/precision, slightly lower recall/average precision, and essentially
unchanged F1 compared with the previous artifact. These small differences do not establish a general
improvement, and this synthetic-data benchmark does not establish real-world fraud detection.

| Held-out metric | Previous artifact | Selected artifact | Simple baseline |
|---|---:|---:|---:|
| Accuracy | 92.2835% | **92.3784%** | 92.2835%, always negative |
| Balanced accuracy | 64.7657% | **64.6491%** | 50%, always negative |
| Precision | 50.0000% | **50.9838%** | Undefined when no claims are flagged |
| Recall | 32.2261% | **31.8594%** | 0%, always negative |
| F1 | 0.391920 | **0.392141** | 0, always negative |
| Average precision | 0.322248 | **0.320733** | 0.077165, constant scores |
| Brier loss | 0.060374 | **0.060478** | 0.071213, training prior |

The default threshold (0.287265638) flags 5,794 of 120,158 test claims: 2,954 true positives and
2,840 false positives, with 6,318 false negatives and 108,046 true negatives. It misses 68.14% of
fraud-labelled claims. At the threshold selected for a 10% validation review cap, held-out review
workload is 9.24%, recall is 39.07%, and precision is 32.62%; this trade-off is reported, not silently
made the default. The 70% precision policy flags only seven test claims, so its observed 100%
precision with 0.0755% recall is not a useful high-accuracy fraud detector.

## Weight and training-size comparisons

Every row below uses the same naturally imbalanced selection cohort (41,608 claims, 3,120 flagged).
These values choose candidates; the test cohort does not choose a model or threshold.

| Configuration | Original training rows | Selection average precision |
|---|---:|---:|
| Unweighted boosting | 222,472 | 0.308592 |
| Balanced boosting | 222,472 | 0.313635 |
| Unweighted forest | 222,472 | 0.315414 |
| Balanced forest | 222,472 | 0.304362 |
| Balanced-subsample forest | 222,472 | 0.309001 |
| Prior baseline | 222,472 | 0.074986 |
| Unweighted forest, smaller pool | 100,000 | **0.315927** |
| Unweighted forest, expanded pool | 443,885 | 0.311810 |
| Balanced boosting, smaller pool | 100,000 | 0.311406 |
| Balanced boosting, expanded pool | 443,885 | 0.308500 |

The expanded source sample admitted **221,413** additional original claims. Exclusions: 240,426
claims filed at/after the training cutoff, 136,821 with reserved calibration/test policies, and
1,340 duplicate claim IDs; no remaining rows failed input/label validation. The saved Parquet has
**443,885 rows and 443,885 distinct claim IDs**, **33,910 original fraud labels**, and latest filing
date **2024-05-12**. The larger pool's 7.64% flagged ratio is nearly identical to the original
training ratio of 7.60%; adding random source rows does not reduce the class imbalance by itself.
The final selected model uses the original 100,000-row subset rather than the expanded pool.

Parquet SHA256: `d73c2665c25ae9434b516e2fd3e5fdd2ff058daf80b4aea09bfb3541f84933bf`.
Active artifact SHA256: `0126a4f630c05af0f13f6eec5099a2ba4c47a681e72c06d393989d54c8ab20c1`;
3,649,182 bytes. Fraud fitted at **7 October 2026, 10:09:09 IST**; regression models remain from
09:32:39 IST and have exactly matching model hashes before/after this experiment.

## Validation and limitations

Independent reconstruction of the original source holdout matches all three primary metrics and
all fraud precision, recall, F1, accuracy, balanced accuracy, Brier loss, operating thresholds and
confusion counts within 1e-9. **243 backend tests pass** (83.28 seconds), including test-label mutation
invariance, threshold exhaustive-search checks, malformed-probability rejection, training expansion
leakage/duplicate checks, Parquet round-trip and old-artifact inference. Ruff and whitespace checks pass.

The original artifact is backed up as `artifacts/models/claims_models.before_fraud_improvement.joblib`;
the previous report is `retraining_report.before_fraud_improvement.json`. New promotion is selected
on validation, not by choosing whichever model has the better test result. The holdout is the same
previously reported benchmark, not a newly collected independent real-world dataset. Further work
needs richer verified pre-outcome signal and independent labelled examples, not just another
larger random sample of this synthetic generator or manufactured balanced outcome labels.

## What I did

Added unweighted, balanced and balanced-subsample forest candidates and balanced histogram boosting.
Replaced the 101-quantile threshold search with an exact observed-score precision-recall curve.
Report F1, recall at precision floors of 50%/70%, review caps of 5%/10%, confusion counts and workload.
Compare the top two model families at 100,000 original training rows, the original training partition,
and an expanded training partition from an additional 600,000 original source records (seed 142).
Save admissible expanded records as Parquet; use only original labels, not generated narratives.

## Why this approach

Fixed evaluation cohorts isolate training-size effects from split changes. The candidate decision
is highest selection-cohort average precision, preferring fewer rows on an exact tie and raw Brier
only as a final tie-break. Only after selection are the winner's probabilities calibrated on a
disjoint cohort and its operating thresholds chosen on a later third cohort. Test outcomes cannot
select weights, sample size or thresholds. Precision floors and review caps apply to the tuning
cohort and may not hold under future shift.

## Why not the alternative

Randomly adding rows does not balance a dataset by itself. Duplicating fraud labels or generating
new labels would not add independent evidence. Resampling the complete dataset before splitting
would contaminate evaluation. Changing thresholds to meet a test-set target would overfit the
evaluation; F1 remains the saved default until a specific operating policy is chosen.

## What was the issue / root cause

The prior candidate set did not compare class-weighted learners. Its coarse threshold grid could
miss better attainable operating points. Fraud is naturally rare, so majority accuracy obscures
missed flagged claims and says little about review usefulness. Additional data must be tested for
incremental signal rather than assumed to improve accuracy.

## Why this works best

Training expansion removes duplicate claim IDs, post-cutoff claims, invalid records and policies
present in calibration/test. The old artifact and report are backed up; a candidate artifact is
reloaded and independently verified against the original source holdout before activation. Existing
amount and resolution estimators are preserved rather than needlessly retrained.

## Other valid patterns

Training-only undersampling or SMOTENC, balanced ensembles and cost-based threshold policies are
valid experiments. They change available information or calibration requirements and need the same
natural-prevalence holdout. Richer pre-outcome incident features and representative labelled data
may improve discrimination; class balancing alone does not guarantee this.

## Sources and reproduction

- [Random forest class weights](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html)
- [Histogram boosting class weights](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html)
- [Precision-recall threshold arrays](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.precision_recall_curve.html)
- [Threshold tuning](https://scikit-learn.org/stable/modules/classification_threshold.html)
- [Independent probability calibration](https://scikit-learn.org/stable/modules/calibration.html)
- [Resampling leakage pitfalls](https://imbalanced-learn.org/stable/common_pitfalls.html)

```powershell
uv run python scripts/improve_fraud_model.py
uv run pytest -q tests/test_analytics.py tests/test_fraud_improvement.py
```

Machine-readable results: `artifacts/models/fraud_improvement_report.json`.
Expanded training records: `data/processed/ml/fraud_training_expanded.parquet`.
Progress logs: `artifacts/models/fraud-improvement.stdout.log` and `fraud-improvement.stderr.log`.
