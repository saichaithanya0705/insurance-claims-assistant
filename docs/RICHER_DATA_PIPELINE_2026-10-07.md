# Richer claims data pipeline and benchmark

Implemented a source-preserving Parquet import pipeline, a separate richer-feature fraud benchmark,
and an importer that checks original intake snapshots against separately supplied human adjudications.
**No new model was activated.** The public sources do not establish independent label adjudication or
intake-time feature availability, and the new benchmark did not establish a reliable accuracy gain.

## Actual data acquired

| Source | Imported data | Disposition |
|---|---|---|
| [Mendeley insurance_claims v2](https://data.mendeley.com/datasets/992mh7dk9y/2) | 1,000 original records; 247 original `fraud_reported=Y` labels; richer incident/vehicle fields | Canonical Parquet and separate retrospective auto-claim benchmark |
| [Kaggle Insurance Claims Dataset 2026](https://www.kaggle.com/datasets/mmumairkhattak/insurance-claims-dataset-2026-fd-and-ra) | 50,000 original records in staging Parquet | Excluded from the richer-feature experiment |

The Mendeley CSV download matches its publisher-provided SHA256:
`be11b9370c0cda353a4519832803d07bb90a494e91dfd9d56a85aa4093ba5378`.
Attribution: ABDELRAHIM AQQAD (2023), *insurance_claims*, Mendeley Data v2,
doi:10.17632/992mh7dk9y.2; CC BY 4.0. The publisher describes insurance-provider origin; that claim
has not been independently verified. The actual records contain vehicle features and incident dates
from January–March 2015, rather than the active 100M-record synthetic generator's source population.

The downloaded Kaggle file has **16 columns**, despite its page advertising 40. It lacks incident
dates, filing dates, severity, injury/witness counts and vehicle fields. Its dictionary repeats column
names without useful definitions; the archive contains CSV, dictionary and notebook, without the
advertised README/LICENSE files. The public page lists MIT, which is recorded as a publisher claim.
`Fraud_Risk_Score`, `Claim_Status` and `Settlement_Amount` are excluded from fraud-model input because
they could disclose assessment/outcome information. No source notebook was executed. These records
were preserved for audit rather than pooled into the active claims dataset or Synapt evidence corpus.

## Files and integrity

- Richer canonical data: `data/processed/ml/richer/mendeley_992mh7dk9y_v2/claims.parquet`,
  74,210 bytes; SHA256 `4a05bfe950eb5658e0d889a78fe27a00a7225fd5ad2628dfa83e609eff4f6d2d`.
- Original Kaggle staging: `data/processed/ml/richer/kaggle_claims_2026_v1/original_records.parquet`,
  1,535,139 bytes; SHA256 `8bed18ae8cce26f738ac9a96f96cc3122ad4eed793e4e8ecc2b571778753becc`.
- Each source directory retains the original download and a JSON manifest/audit. The Mendeley
  manifest records source attribution, excluded fields, missing values, original label counts,
  file/record digests and production blockers. Its 1,000 accepted records have unique claim IDs;
  no duplicates, conflicting claims or invalid rows were found.
- Experiment: `artifacts/models/richer/mendeley_992mh7dk9y_v2/report.json`, `protocol.json`,
  and `benchmark.joblib`. The artifact has its own scope and cannot overwrite `claims_models.joblib`.

Known missing values such as `?` stay missing. Filing dates, label dates, evidence references and
currency are not invented. Source rows and original labels are retained, and each canonical record
carries its original row digest. Exact duplicates collapse; all conflicting versions of a claim
are quarantined. Parquet exports use explicit types to preserve timestamps and timezones exactly.
Rerunning source preparation verifies and reuses existing files without changing a frozen manifest.

## Separate benchmark

Two fixed seeds (42/73) compare forests and native categorical CatBoost in three feature groups:

| Group | Inputs |
|---|---|
| Basic | Original amount, deductible, customer tenure, incident month, policy state |
| Incident | Basic plus incident/collision type, incident state/hour, vehicle make/model/age, vehicles involved, injury and witness counts |
| Assessment, exploratory | Incident plus recorded severity, police-report availability, property-damage indication and authorities contacted |

Identifier, label, protected/demographic, free-form location, hobby and settlement-like fields
are outside the model allowlists. Missing numeric values use training-only medians plus missing
indicators; categorical missing values remain explicit. Assessment fields are evaluated separately
because their availability at intake is unverified. Their performance cannot justify deployment.

Five policy-disjoint incident-date cohorts are frozen before candidate fitting. There are **496
training / 119 selection / 80 probability-calibration / 112 threshold-calibration / 193 final-test
records**; positive counts are **129 / 33 / 23 / 26 / 36**. The cutoffs are 2015-01-31, 2015-02-06,
2015-02-12 and 2015-02-18. Same-day records stay together. These are retrospective partitions;
missing filing/label observation timestamps prevent a point-in-time validity claim.

Model family and early-stop iterations are chosen without final-test labels. Each feature group's
winner is refitted on training + selection; independent later cohorts fit a positive-slope sigmoid
and choose a recall-maximizing threshold at >=50% tuning precision. A nonpositive calibration slope
leaves raw scores intact rather than reversing ranking. The test is evaluated only after these
choices are frozen, and a reserved/consumed holdout cannot be used to run another tuning pass.

| Final test metric, same 193 records | Basic CatBoost | Incident forest | Assessment forest | Constant/always-negative baseline |
|---|---:|---:|---:|---:|
| Accuracy | 79.79% | 76.17% | 72.54% | **81.35%** |
| Balanced accuracy | 50.12% | 47.89% | **65.99%** | 50% |
| Precision | 20.00% | 8.33% | **35.09%** | Undefined: no flags |
| Recall | 2.78% | 2.78% | **55.56%** | 0% |
| Average precision | 0.233807 | 0.184547 | **0.271941** | 0.186528 |
| Brier loss | 0.161121 | 0.164553 | 0.180948 | **0.157647** |
| Claims flagged | 5 | 12 | 57 | 0 |
| True positives / false positives | 1 / 4 | 1 / 11 | 20 / 37 | 0 / 0 |

Assessment fields improve recall and ranking on this particular cohort, but cause many false
positives and worse overall accuracy/Brier than the simple baseline. Assessment tuning precision
was 59.38%; final precision fell to 35.09%. The final test has only 36 positives, so uncertainty is
substantial. Incident-only fields did not improve the final result. This source-specific outcome
must not be compared directly with the active model's 92.26% accuracy on a different population.

The benchmark and independent verification took **33.42 seconds**. The saved artifact was reloaded,
original CSV labels/features were rebuilt and checked against Parquet, all stored metric and
confusion-count values matched within 1e-12, and all five cohorts have zero policy overlap.
The active artifact is unchanged, SHA256:
`0126a4f630c05af0f13f6eec5099a2ba4c47a681e72c06d393989d54c8ab20c1`.

## Reviewed claims importer

Use `data/templates/reviewed_claims.csv` as a header template; it contains **no generated records**.
Fill it only with original source facts. Required fields are claim/policy IDs, claim type, incident
date, filing and feature-snapshot timestamps, fraud label observation timestamp/evidence ID,
`is_fraud`, amount, deductible and customer tenure. Other richer fields remain empty when unavailable.
The CSV label vocabulary is exactly `true` or `false`. All timestamps need an explicit timezone.

Supply a separate JSON array following `data/templates/adjudications.json`. Each evidence record
requires `evidence_id`, original `claim_id`, strict Boolean `is_fraud`, `observed_at`, `adjudicator`,
`method` (`human_review` or `final_adjudication`) and an `evidence_reference` to the original reviewed
outcome. A record is admitted only when its claim ID, label and observation time match this evidence.
No LLM-generated adjudication method is accepted. The files' authenticity still needs source review;
structural cross-checking does not itself establish that a supplied adjudicator is independent.

The importer rejects unknown outcome/risk-score columns, invalid counts/ranges, missing timezones,
future timestamps, incident/filing/outcome order errors, feature snapshots after filing, absent or
disagreeing evidence, duplicate claims and reused evidence. It retains original files, evidence,
digests and rejection reasons. Duplicate/conflicting IDs quarantine every version. A new version
must use an empty directory. The same original/evidence/Parquet checks run again before fitting.

```powershell
uv run python scripts/import_reviewed_claims.py `
  --csv <original-intake-snapshots.csv> --evidence <human-adjudications.json> `
  --source-id reviewed_insurer_v1 --source-url <original-source-reference> `
  --license <permission-or-license> --domain us_auto `
  --output data/processed/ml/richer/reviewed_insurer_v1

uv run python scripts/train_richer_fraud.py `
  --manifest data/processed/ml/richer/reviewed_insurer_v1/manifest.json `
  --output artifacts/models/richer/reviewed_insurer_v1
```

For timestamped reviewed records, filing dates drive the five cohorts and labels observed on/after
the next cohort boundary are excluded from the earlier cohort. Insufficient dates, cohorts or
positive/negative support fail explicitly. An incident-feature experiment needs genuine observations
for its numeric fields; a completely unobserved field cannot provide a training median.

Production activation remains unavailable in this benchmark command. Before integration, verify
source permission/authenticity, independent adjudication, feature availability, label maturity,
representative domain and sufficient independent test support, then evaluate the matching runtime
input contract. The checked public sources do not meet those requirements. More generated cards
would not satisfy them.

## What I did

Added source download/audit, richer normalization, Parquet integrity checking, evidence-backed
reviewed import, a separate six-configuration benchmark, templates and regression tests. Recorded
the failed public-source checks and measured final results instead of treating extra row count as
an improvement. This work does not upload staged or unverified records to Synapt.

## Why this approach

Original evidence and labels remain traceable. Independent evidence files and observation times
make future source review possible; source-specific experiments isolate domain and feature changes
from the existing model. Canonical facts and ML imputation are separate.

## Why not the alternative

Pooling 50,000 poorly documented records, filling missing incident facts with invented narratives,
or using fraud risk/status/settlement as inputs could manufacture attractive metrics. A different
dataset's accuracy cannot establish improvement over the existing model. Repeated tuning against
the same final test would invalidate the benchmark.

## What was the issue / root cause

The extra synthetic rows did not add measured signal, and public descriptions overstated the
available richer data. Neither source supplies the observation/evidence information needed to
verify when labels and predictors became available. The benchmark additionally shows substantial
validation-to-test deterioration and a limited final sample.

## Why this works best

Admission, quarantine and verification precede fitting. Models use explicit feature allowlists and
training-only preprocessing; predictions are validated by the existing probability ensemble.
Frozen protocols and independent reload checks make the experiment reproducible, while separate
artifacts protect the current workflow and regression models.

## Other valid patterns

A permitted insurer dataset with adjudicated outcomes and intake-time snapshots is the preferred
next source. Reviewed feedback can contribute labels only after independent outcome confirmation.
Broader domain-specific benchmarks or carefully measured resampling are also possible; they need
new independent tests and cannot repair missing evidence or observation timestamps.

## Verification and reproduce

```powershell
uv run python scripts/prepare_richer_claims.py
uv run python scripts/train_richer_fraud.py --verify-only
uv run pytest -q
uv run ruff check src/claims/ml/richer_data.py src/claims/ml/richer_fraud.py src/claims/ml/reviewed_claims.py scripts/prepare_richer_claims.py scripts/train_richer_fraud.py scripts/import_reviewed_claims.py tests/test_richer_claims.py
```

Focused validation: **15 tests pass**, including source-label mutation, exact/ambiguous duplicates,
missing features, chronological policies, label maturity, evidence mismatch/tampering, timezone
preservation, invalid reviewed counts, training-only imputation, input allowlists and bounded source
download. The full suite passed: **269 tests in 85.05 seconds**; the focused tests also passed
after the final reviewed-input range checks. Ruff passes. The user subsequently deferred further
model work and requested website verification; all active statistical models remain unchanged.
