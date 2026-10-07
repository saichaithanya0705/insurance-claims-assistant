# Models

Three statistical models estimate historical **claimed amount**, **days to resolution**, and the
synthetic dataset's **fraud flag**. They are educational investigation aids, not settlement,
coverage, or fraud decisions. Current artifact: **7 October 2026, 10:09:09 IST**; amount and resolution
remain from 09:32:39 IST, while fraud was refitted after the weighting/training-size experiment.

See [the retraining and verification report](ML_RETRAINING_2026-10-07.md) for complete metrics,
cohorts, hashes, change rationale and limitations, and [the current fraud experiment](FRAUD_IMPROVEMENT_2026-10-07.md)
for the latest fraud metrics and comparison with the previous artifact.

The subsequent [ratio/CatBoost experiment](FRAUD_FEATURE_EXPERIMENT_2026-10-07.md) passed
independent artifact/source verification but **failed its validation promotion gate**; the
active model remains the forest described here. On a new policy-disjoint 17,666-claim cohort,
this active model has **92.2563% accuracy, 49.6027% precision and 32.1087% recall**, versus
**92.2959% accuracy and zero recall** for always predicting non-fraud. The rejected ratio
CatBoost candidate has 92.0186% accuracy, 47.3797% precision and 32.5496% recall on that same
cohort. Its small recall gain does not establish a better model. The figures below retain
their original 120,158-claim benchmark denominator.

The [richer-data pipeline and source-specific benchmark](RICHER_DATA_PIPELINE_2026-10-07.md)
subsequently imported 1,000 original Mendeley auto claims and audited 50,000 Kaggle records.
Neither produced an eligible model upgrade: the richer assessment benchmark's accuracy was
72.54% versus its own 81.35% majority baseline, with 55.56% recall and 35.09% precision.
These are different-population results, not the active model's metrics. A reviewed-data importer
now cross-checks supplied intake snapshots against separate human adjudication evidence and
observation times; the active artifact and its amount/resolution models remain unchanged.

## Data

| Item | Current artifact |
|---|---|
| Source | [ZiadataLabs FreeInsuranceClaims100M](https://huggingface.co/datasets/ziadatalabs/FreeInsuranceClaims100M), synthetic US property and casualty claims, CC BY-NC 4.0 |
| File | `insurance_claims_100M.parquet`, 2,519,982,987 bytes, **100,000,000 rows** |
| Training sample | **600,000** valid unique source records, seed 42, uniform reservoir sampling, one DuckDB thread |
| Artifact | `artifacts/models/claims_models.joblib`, **3,649,182 bytes** |
| Verification | Artifact reloaded; source sample and held-out predictions independently reconstructed; all primary metrics matched |

No labels were generated or changed. Rich Synapt cards serve evidence retrieval; the statistical
models train on original outcome-bearing structured records. Earlier versions used a 3,000-row
contiguous sample, then a 200,000-row random sample; those historical results are superseded here.

The fraud experiment draws an additional 600,000 source records using seed 142, admitting 221,413
new training claims after filtering. Its 443,885-row training pool is saved as
`data/processed/ml/fraud_training_expanded.parquet`, with no duplicate claim IDs. The larger pool
did not win validation; the current fraud model fits 100,000 original training rows plus 41,608
selection rows (141,608 final fit rows). The dataset class ratio remains about 7.6% flagged.

## Targets and leakage controls

| Target | Meaning | Inputs excluded |
|---|---|---|
| Amount | Historical claimed amount in USD | The amount itself, status, duration, fraud flag, identifiers |
| Resolution | Days to resolution, approved/denied claims only | Duration, status, fraud flag, identifiers |
| Fraud | Dataset fraud flag | Flag, status, duration, identifiers |

Inputs are claim type, state, tenure, previous claims, deductible, filing delay and incident month.
Resolution and fraud additionally use the claimed amount. Unknown categories and numeric values
outside the training range produce warnings.

Filing-date cohorts are divided about 60/20/20; policies found in later partitions are purged from
earlier ones. Train/calibration/test counts are **222,472 / 94,188 / 120,158** for amount,
**100,000 / 94,188 / 120,158** for the selected fraud configuration, and
**179,115 / 73,410 / 98,270** for eligible resolved durations. Calibration starts 2024-05-13;
test starts 2025-06-24. Duration labels must be observable before the next relevant cutoff.

Calibration decisions use separate chronological and policy-disjoint cohorts. Regression selects
on the earlier selection cohort and calibrates intervals on the later cohort. Fraud uses distinct
selection, probability-calibration and review-threshold cohorts. Test labels never select a model,
fit a sigmoid or choose an interval/threshold.

## Estimators

- **Amount:** selection among a claim-type median estimator, histogram gradient boosting with
  absolute-error loss, a bounded forest and a global median by selection-cohort MAE. The current
  artifact selects the claim-type median and forms its empirical interval from later residuals.
- **Duration:** histogram gradient boosting with absolute-error loss, 160 maximum iterations, 15
  leaves, minimum leaf 40 and L2 regularization 10, selected over a bounded forest and median
  baseline by selection-cohort MAE. Separate calibration residuals form an empirical interval with
  a finite-sample quantile correction.
- **Fraud:** an unweighted 80-tree forest, maximum depth 12 and minimum leaf 32, retained after
  comparing balanced/balanced-subsample forests, balanced boosting and training sizes of 100,000,
  222,472 and 443,885 on the same selection cohort. The decision rule is highest selection average
  precision, smaller training size on exact ties, then raw Brier. A log-odds sigmoid is fitted on
  a later cohort; the exact precision-recall curve selects the F1 threshold on a third cohort.
- Training forests and native numerical libraries use two workers/threads. The standalone
  retraining command caps DuckDB at 1GB and uses one sampling thread for repeatability.

Old probability-input sigmoid artifacts still load and predict; new artifacts record their
log-odds transform explicitly. Load only locally generated trusted joblib artifacts.

## Held-out results and stronger baselines

| Target | Saved model | Global baseline | Feature-aware comparison |
|---|---:|---:|---:|
| Amount MAE | **$15,105.13** | $22,629.80 | **$15,105.18**, train claim-type median |
| Duration MAE | **6.30900 days** | 7.26102 days | **6.47820 days**, train filing-delay regression |
| Fraud PR-AUC / average precision | **0.320733** | 0.077165 | Previous model: 0.322248 |
| Fraud Brier score | **0.060478** | 0.071213 | Previous model: 0.060374 |

Amount and duration errors improve **33.25%** and **13.11%** over their global median baselines.
Fraud average precision is **4.16 times** the prior baseline. The amount artifact intentionally
selects the claim-type-median comparator because it has no demonstrated advantage over the more
complex candidates. Duration's advantage over
the filing-delay comparator is only **2.61%**. Bigger samples cannot guarantee better results when
the supplied fields lack additional predictive signal.

Fraud precision **50.98%**, recall **31.86%**, F1 **0.39214**, balanced accuracy **64.65%**;
threshold **0.287266**. Raw accuracy is **92.38%**, versus **92.28%** for an all-negative classifier.
This is no material improvement over the previous model: precision/accuracy rise slightly while
recall, balanced accuracy and average precision fall slightly. Do not report 92.38% as fraud recall.

Nominal 90% intervals cover **89.92%** of held-out amounts and **88.82%** of durations. Amount
error varies sharply by type: business MAE is **$55,323.17**, while renters MAE is **$2,186.96**.

## Explanations

Global explanations combine grouped calibration permutation importance with partial dependence
on a bounded calibration sample. Amount's type-median model uses claim type; other claimed amount
associations from the superseded boosted model no longer apply. Duration primarily uses filing delay;
the fraud artifact supplies its own measured associations. These are associations within the model,
not causes; partial dependence can evaluate
unrealistic combinations of correlated fields.

Per-claim explanations replace one feature at a time with the training-set typical value and
report the prediction change. They are **not additive or causal** and depend on remaining features.
Explanations do not establish that a claim is valid, fraudulent or entitled to payment.

## Limitations and next useful data

- Synthetic property and casualty data, not validated on real claims or health insurance.
- No settlement target; amount predicts what was claimed. Fraud-label observation timestamps
  are missing, so point-in-time label validity remains unverified.
- Duration covers resolved approved/denied claims; unresolved censoring is not modeled.
- Empirical intervals have no future coverage guarantee; duration held-out coverage is below nominal.
- Probability calibration uses independent cohorts but has no guarantee under future drift.
- Amount has no material gain over a transparent feature-aware comparator; business claims
  retain large absolute errors. Raw fraud accuracy hides the imbalance.
- Synapt similarity, model scores, prediction intervals and LLM-judge scores remain separate.

Further gains need representative permitted real claims, trustworthy outcome timestamps, richer
pre-outcome loss and incident features, censoring-aware duration models, cohort calibration,
fairness/error analysis and drift monitoring. More generated narratives or changed labels are
not evidence of better predictive accuracy.

## Reproduce

```powershell
uv run python scripts/retrain_models.py --rows 600000 --memory-limit 1GB
uv run python scripts/improve_fraud_model.py
uv run python scripts/experiment_fraud_features.py --verify-only
uv run pytest tests/test_analytics.py tests/test_fraud_improvement.py -q
```

The full-model run took 229.50 seconds; the later fraud experiment and independent verification took
241.52 seconds. Reports are `artifacts/models/retraining_report.json` and
`artifacts/models/fraud_improvement_report.json`; the latter records the full experiment and operating
points. Verification also recomputes all fraud classification metrics and confusion counts. A running
app must reinitialize its analytics service to display a newly saved artifact.
