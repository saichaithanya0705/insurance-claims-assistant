# Fraud ratios and CatBoost experiment

## Protocol

This experiment compares raw and ratio-enhanced random forests, ratio-enhanced histogram
boosting, and raw and ratio-enhanced CatBoost. Each configuration averages two fixed seeds,
42 and 73, using 100,000 original pre-cutoff training claims. Boosting iteration counts are
chosen on the chronological final 10% of training, then refitted on the training partition.
CatBoost receives categorical strings directly and uses chronological ordering.

An additional deterministic 600,000-record reservoir sample uses seed 314159. Every policy
present in the earlier 600,000-record benchmark or expanded training pool is excluded.
Remaining policies are separated across five filing-date cohorts, with later cohorts taking
precedence when a policy repeats. The boundaries are 2024-05-13, 2024-09-01, 2024-12-02,
2025-03-14 and 2025-06-24. The first two cohorts evaluate candidates, the third calibrates
probabilities, the fourth chooses review thresholds, and the fifth is the frozen final test.

The promotion rule is frozen before fitting: mean validation recall at precision >=50% must
gain at least two percentage points, average precision must gain at least 0.01, recall at a
10% review cap must not fall, and average precision must not fall on either validation date
cohort. Comparisons use the raw forest ensemble. The selected candidate is evaluated against
the actual incumbent on the same fresh final cohort only after selection is frozen.
Test outcomes do not select the model, seeds, iteration counts, calibration or threshold.
A feasible precision-floor threshold on the tuning cohort is also required for activation.

## Results

**No challenger passed the promotion rule. The existing artifact remains active.**
The complete run and independent verification took 286.50 seconds.

| Configuration | Mean validation average precision | Recall at >=50% precision | Recall at <=10% review |
|---|---:|---:|---:|
| Raw forest ensemble | **0.326193** | **31.55%** | 38.50% |
| Forest with ratios | 0.325391 | 31.09% | 39.07% |
| Histogram boosting with ratios | 0.316892 | 30.87% | 38.61% |
| Raw CatBoost | 0.319554 | 31.33% | 36.59% |
| CatBoost with ratios | 0.321012 | 31.33% | **40.19%** |

The ratio CatBoost candidate was chosen for final reporting among the failed challengers,
not approved for activation. Its extra recall at the validation review cap came with worse
ranking and no gain at the precision floor. The final fit used 105,914 claims; 3,210 later
claims calibrated probabilities and 3,435 other claims selected thresholds.

The fresh final cohort contains **17,666 claims**, including **1,361 fraud labels (7.7041%)**.
All results below use this same cohort and thresholds fixed before inspecting it.

| Final metric | Active incumbent | Ratio CatBoost candidate | Always-negative / constant-score baseline |
|---|---:|---:|---:|
| Accuracy | **92.2563%** | 92.0186% | **92.2959%** |
| Balanced accuracy | 64.6928% | 64.7661% | 50% |
| Precision | **49.6027%** | 47.3797% | Undefined: no flags |
| Recall | 32.1087% | **32.5496%** | 0% |
| F1 | **0.389831** | 0.385889 | 0 |
| Average precision | 0.317147 | 0.318950 | 0.077041 |
| Brier loss | 0.060166 | **0.058837** | 0.071107, final-fit prior |
| Claims flagged | 881 (4.99%) | 935 (5.29%) | 0 |
| True positives / false positives | 437 / 444 | 443 / 492 | 0 / 0 |
| False negatives / true negatives | 924 / 15,861 | 918 / 15,813 | 1,361 / 16,305 |

The candidate catches six additional labelled positives while flagging 48 additional negatives.
Recall rises only **0.4409 percentage points**, precision falls **2.2220 points**, and F1 falls.
Average precision and Brier improve slightly on this cohort, but the validation gate already
failed. The candidate's tuning precision of 50.31% falls to 47.38% on final test: a tuning
precision floor is not a future guarantee. Its threshold tuned for <=10% review produces
9.31% review, 39.53% recall and 32.73% precision on final test. These alternatives are reported
without selecting a new default from final-test labels.

The active artifact's earlier 120,158-claim benchmark remains **92.3784% accuracy, 31.8594%
recall and 50.9838% precision**. Those values and the fresh-cohort values are different
evaluations, not conflicting predictions or evidence of a newly activated model.

## Validation and preserved artifacts

Fresh cohort counts are 3,153 early validation, 2,761 late validation, 3,210 probability
calibration, 3,435 threshold calibration and 17,666 test. The 426,425 prior policies excluded
512,434 sampled records; another 52,509 records preceded validation and 4,832 earlier-cohort
records repeated later policies. No remaining claims failed input/label/duplicate validation.

Independent verification reloaded the candidate, reconstructed regression holdouts and looked
up every frozen fraud test record in the original 100M-row source. All three primary metrics,
fraud classification metrics, Brier loss, frozen operating thresholds and confusion counts
matched within 1e-9. Fraud test/training policy overlap is zero. The source and snapshot
record digests match. Inference with local explanations passed for the saved CatBoost candidate.

The full suite initially found a pre-existing bit-equality assertion comparing two parallel
forest reductions that differed by about 1e-17. The test now uses absolute tolerance 1e-12
with zero relative tolerance while still checking that mutated test labels cannot affect
model selection or tuning thresholds. Its focused rerun passed. The subsequent full suite
passed: **254 tests in 85.31 seconds**. Ruff and scoped whitespace checks pass. The experiment
process has exited, and its temporary PID file was removed.

- Active artifact SHA256 (unchanged): `0126a4f630c05af0f13f6eec5099a2ba4c47a681e72c06d393989d54c8ab20c1`.
- Candidate SHA256: `123e7110b06e6622eae6e9a204248e9b916ae43977a5c1816621755f0b0b1b5b`.
- Holdout Parquet SHA256: `bcfd03cc42c3e4f1510b34a8cab9350b051dbd0450285a6e6163603ce6c0c22f`.
- Amount model hash, both artifacts: `aab1b3f62f75a3225e6ed98b729bc0c8`.
- Resolution model hash, both artifacts: `b0d7e3caa44673a763f7741c1ea4369c`.

## Recommended next data

Stop expanding the same generator merely to change the headline row count. Seek independently
labelled permitted claims with original pre-outcome incident type, damage/severity, item/vehicle
details, verified document availability, and trustworthy fraud outcome and observation timestamps.
Keep unavailable values missing; do not invent incident details or labels from generated cards.
Audit provenance, duplicate claims and policies, feature availability at intake, dates, units,
domain and label meaning before a separate Parquet-backed experiment. Fraud-positive examples
should add independent information; retain natural prevalence in calibration and testing.
The bounded experiments do not prove an achievable performance ceiling.

Public candidates were checked, but none was silently pooled into the active dataset:

| Candidate | Publisher's stated content | Decision |
|---|---|---|
| [Mendeley insurance_claims v2](https://data.mendeley.com/datasets/992mh7dk9y/2) | Fraud-labelled claim records, customer/policy fields; CC BY 4.0; publisher claims insurance-provider origin | Investigate original files and timestamp/feature provenance first. Publisher claims alone do not verify real-world origin or compatibility. |
| [Insurance Claims Dataset 2026](https://www.kaggle.com/datasets/mmumairkhattak/insurance-claims-dataset-2026-fd-and-ra) | 50,000 claims, 40 fields, Fraud_Flag and accident/policy fields; MIT | Possible separate pilot after inspecting original README/data dictionary and label generation. A larger public row count is not proof of stronger real labels. |
| [Healthcare Fraud Detection](https://www.kaggle.com/datasets/nudratabbas/healthcare-fraud-detection-dataset) | 10,000 healthcare claims; explicitly synthetic | Different domain and generator; unsuitable for claiming improved US property-and-casualty fraud accuracy through pooling. |

## What I did

Added an encoder for claim amount divided by deductible and by the training claim-type
median, native categorical CatBoost, a bounded two-seed ensemble, a frozen experiment runner,
and source-based holdout verification. Added regression tests for feature statistics,
outcome isolation, inference recalculation, cohort separation, promotion gates, probability
validation, CatBoost artifact reload and holdout label tampering. Added CatBoost to the
project dependencies and lockfile. Corrected the brittle exact-float leakage test described
above and documented the new result in the model card.

## Why this approach

Ratios represent relative claim size across deductible levels and claim types. Medians use
fitting rows only, and every inference or explanation recalculates the ratios. Separate
chronological calibration and threshold cohorts preserve natural class prevalence. A new
policy-disjoint final cohort avoids using the previously examined benchmark for new tuning.

## Why not the alternative

Generating more card narratives does not create trustworthy fraud labels. Uniformly adding
more rows of the same generator already failed to improve validation. Balancing the final
test or selecting a threshold from its labels would misstate performance. Native CatBoost
category handling avoids a manual one-hot encoding stage for that model.

## What was the issue / root cause

Fraud is rare, so ordinary accuracy rewards predicting the majority class. The available
fields provide limited measured signal, and earlier weighting and training-size experiments
did not improve it materially. This experiment tests whether relative-size features and a
different categorical learner recover useful interactions; improvement is an empirical
question, not a promised result.

## Why this works best

Promotion is validation-based, with a material-gain gate. The artifact is reloaded and its
predictions recomputed before activation. Frozen test records are checked against the original
source, including labels, file and record digests; duplicate IDs and training-policy overlap
are rejected. Amount and resolution models are preserved. Prediction probabilities are
validated, and fitting/prediction threads are bounded.

## Other valid patterns

Cost-based threshold selection, training-only resampling, richer verified pre-outcome loss
features and independently labelled permitted claims are valid alternatives. They require
the same leakage controls and a new natural-prevalence evaluation. This synthetic source
still lacks fraud-label observation timestamps, so neither result establishes real-world
fraud accuracy or point-in-time label maturity.

## Reproduction and evidence

```powershell
uv sync
uv run python scripts/experiment_fraud_features.py --verify-only
uv run pytest -q
uv run ruff check src/claims/fraud_features.py scripts/experiment_fraud_features.py scripts/retrain_models.py tests/test_fraud_features.py
```

The default experiment command refuses to retune a reserved or consumed holdout.
The protocol is `artifacts/models/fraud_feature_protocol.json`; full validation and final
results are `artifacts/models/fraud_feature_experiment.json`. The candidate is
`artifacts/models/claims_models.feature_candidate.joblib`, and the frozen cohort is
`data/processed/ml/fraud_feature_holdout.parquet`. Progress logs are
`artifacts/models/fraud_feature_run.log` and `fraud_feature_run.err`.

Implementation follows official guidance on
[CatBoost categorical features](https://catboost.ai/docs/en/features/categorical-features),
[CatBoost fitting and early stopping](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier_fit),
[threshold selection](https://scikit-learn.org/stable/modules/classification_threshold.html),
and [independent probability calibration](https://scikit-learn.org/stable/modules/calibration.html).
