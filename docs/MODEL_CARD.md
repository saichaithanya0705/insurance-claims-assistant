# Educational claims models

The analytics service trains three independent statistical models from a bounded original sample
of [ZiadataLabs FreeInsuranceClaims100M](https://huggingface.co/datasets/ziadatalabs/FreeInsuranceClaims100M).
The source is synthetic US property/casualty data, licensed CC-BY-NC-4.0. Attribution is retained in
the sample and model report. The implementation does not download 100 million records.

Run `python scripts/fetch_dataset.py --count 3000` from the project environment to fetch 30 pages
of 100 original records. Counts are bounded to 100–5000; each page has a 30-second timeout and
three attempts. Source rows are stored unchanged with endpoint, offset, timestamp, license and
canonical row-content SHA256. Download failure does not create a fabricated or partial sample.
A contiguous slice is reproducible, but is not a representative random sample. These source
claims are distinct from application-authored narrative fixtures.

## Targets and leakage controls

| Target | Meaning | Excluded inputs |
|---|---|---|
| Amount | Historical submitted claim amount in USD | Amount itself, status, duration, fraud flag, identifiers |
| Resolution | Days to resolution for approved/denied cases | Duration, status, fraud flag, identifiers |
| Fraud | Synthetic dataset fraud-flag risk | Flag, status, duration, identifiers |

Shared features: claim type, state, tenure, previous claim count, deductible, filing delay,
incident month. Resolution and fraud also use the submitted amount. Descriptions and case
documents are not statistical model features. Amount does not estimate a settlement or policy
entitlement. Resolution ignores unresolved cases and therefore has censoring/selection bias.

Validated, unique records are ordered by filing date into approximately 60% training, 20%
calibration and 20% held-out testing. Same-date cohorts stay together. Policies appearing in
later partitions are removed from earlier partitions, and IDs never enter the feature vector.
Resolved labels must be observable before the next partition's filing-date cutoff; records
with future dates or resolution dates are excluded. Fraud-label observation timestamps are
absent, so full point-in-time validity of fraud labels remains unverified.

At least 80 training and 20 calibration/test rows are needed per target. Fraud also requires
five positive and five negative labels per partition. Insufficient data yields an unavailable
response rather than an invented estimate. Unseen categories and out-of-range inputs produce
visible warnings.

## Estimators, uncertainty and evaluation

Regression compares a random forest with a training-median baseline and selects using
calibration MAE only. The untouched temporal test partition reports MAE against the baseline.
The selected model's 90th-percentile absolute calibration error defines an empirical residual
interval; held-out coverage is reported. This is not a guaranteed coverage or causal interval.
Calibration-based model selection also limits formal conformal interpretations.

Fraud uses a random forest with a sigmoid fitted on the temporal calibration scores. The
review threshold maximizes calibration F1. Held-out precision, recall, average precision
(PR-AUC), Brier score, baseline average precision and baseline Brier score are reported.
Sigmoid fitting on a small synthetic sample does not establish real-world calibration.
The score is an investigation signal, never proof of fraud or authorization to deny a claim.

Explanations are global calibration permutation importance: changes in scoring after a
feature is shuffled. One-hot categories are shuffled together as one original feature. Negative
values are preserved. They describe associations across the sample, not individual-claim
contributions or causal effects. Numeric predictions, fraud scores and Synapt retrieval
confidence are different quantities and must not be merged into one confidence value.

## Storage and operational limits

Locally generated model artifacts persist in ignored `artifacts/`; raw data is ignored under
`data/raw/`. Joblib files must only be loaded from a trusted local artifact directory. A SHA256
checks source-row consistency, not source authenticity. Reproducibility assumes the pinned
environment and original sample. Model quality is exposed through service status and must
not be called production-ready solely because synthetic validation passes.

Before real-world use: establish permitted real data, representative sampling, outcome
timestamps, fairness/error analysis across cohorts, independent probability calibration,
censoring-aware resolution models, drift monitoring and qualified insurance review. No live
Synapt call is required to validate these isolated statistical models; separate integration
testing is still required for provider retrieval, citations and access permissions.
