# Third-party notices

The MIT License in [LICENSE](LICENSE) covers this project's source code, documentation and original
assets. It does **not** relicense the third-party material below, which keeps its own terms.

## Data

| Material | Where it appears here | Licence |
|---|---|---|
| [ZiadataLabs FreeInsuranceClaims100M](https://huggingface.co/datasets/ziadatalabs/FreeInsuranceClaims100M), synthetic US property and casualty claims | Not in this repository: `scripts/bootstrap.py data` downloads it. Material derived from it is: `data/processed/ml/fraud_training_expanded.parquet`, `data/processed/ml/fraud_feature_holdout.parquet`, the claim records and outcomes quoted in the saved investigations in `data/bootstrap/claims.sqlite`, and the figures in `docs/` | **CC BY-NC 4.0**: attribution required, **non-commercial use only**. Anything derived from this data keeps that restriction |
| *insurance_claims* v2, Abdelrahim Aqqad (2023), Mendeley Data, [doi:10.17632/992mh7dk9y.2](https://doi.org/10.17632/992mh7dk9y.2) | `data/processed/ml/richer/mendeley_992mh7dk9y_v2/`: the original CSV, a converted and audited Parquet copy, manifests and a saved copy of the dataset page. How the copy was produced is in its `manifest.json` and `docs/RICHER_DATA_PIPELINE_2026-10-07.md` | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): attribution required; changes must be indicated |
| Kaggle *Insurance Claims Dataset 2026* (mmumairkhattak) | Not redistributed: its licence is only a publisher claim and its archive carries no licence file. Only this project's own JSON audit notes are kept in `data/processed/ml/richer/kaggle_claims_2026_v1/` | Not applicable |

## Fonts

The compiled UI (`src/claims/static/app/assets`) bundles Geist, JetBrains Mono and Source Serif 4, served
through the `@fontsource-variable` packages under the SIL Open Font License 1.1
(<https://openfontlicense.org>). Each font remains the property of its authors.

## Software dependencies

Python and JavaScript dependencies keep their own open-source licences (see `uv.lock` and
`frontend/package-lock.json`). The compiled UI bundle contains code from npm packages under those licences.

## Names

Synapt, NVIDIA, Hugging Face, Mendeley, Kaggle and other product or service names belong to their owners and are
used here only to identify the services and data this project works with.
