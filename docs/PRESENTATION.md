# Panel presentation: ten-minute script

This is a complete local application with a separately gated live integration. Present the mode badge
first. Do not show fixture results as live Synapt evidence.

| Slide | Time | Message and demonstration |
|---|---:|---|
| 1. The investigation problem | 0:00–1:00 | Historical claims are hard to compare; handlers need meaningful differences and useful next evidence, not an unexplained verdict. |
| 2. Synapt at the center | 1:00–2:00 | Show ARCHITECTURE.md: shared source knowledge, procedures and graph context through MCP; LangGraph controls execution and review. |
| 3. Data and hybrid retrieval | 2:00–3:00 | Explain the 3,000-row synthetic sample, exact filters, historical availability and BM25/feature ranks; live Synapt IDs enable semantic fusion after ingestion. |
| 4. Ordinary claim | 3:00–4:15 | Run Auto: repair evidence available. Show comparisons, amount difference, sources and explicit prediction intervals. |
| 5. The next useful evidence | 4:15–5:30 | Run auto theft. Show the missing police report and filing delay; explain why theft does not require a collision repair estimate. |
| 6. Contradiction and abstention | 5:30–7:00 | Show Home: conflicting descriptions, then ambiguous classification. Acceptance must stay disabled on an invalid brief. |
| 7. Review and learning | 7:00–8:00 | Accept a valid brief, save feedback and open the candidate lessons. Explain persistence and reviewed promotion rather than automatic truth. |
| 8. Evaluation and models | 8:00–9:00 | Show four golden cases, tests and model holdouts. DeepEval judge requires a configured model and actual run. |
| 9. Honest limits and expansion | 9:00–10:00 | Discuss weak fraud precision/recall, synthetic data, missing policy wording and pending provider access. Describe the dedicated-provider pilot and live gates. |

## Results to present accurately

The sampled model run reports amount MAE about $16,907 versus a $23,567 median baseline,
resolution MAE 6.49 days versus 7.19 days, and synthetic fraud-flag precision about 28% / recall
31% at the calibration-selected threshold. These are held-out sample metrics, not real insurance
accuracy. The amount interval's nominal 90% level covered about 86% of the holdout; do not describe
it as a guaranteed range. Global feature associations are not individual causal explanations.

Verify exact current values in MODEL_CARD.md and the app before presenting. Use VALIDATION.md for
the final test count and browser results. Do not claim live MCP authentication, ingestion, semantic
search quality or model-judge success until those gates are actually completed.

## Likely panel questions

**Why LangGraph?** This workflow needs explicit state, branching, checkpoints and a handler interrupt.
Role-based agent collaboration alone does not define those application boundaries.

**Why local history if Synapt is central?** Synapt retrieves domain knowledge; the local table enforces
numeric filters, temporal availability and statistical feature contracts without duplicating RAG.

**Can it detect fraud?** It estimates a synthetic fraud-flag label for investigation support. Current
sample accuracy is weak, and no score proves fraud or authorizes an adverse claim decision.

**What happens when a provider fails?** The run fails visibly. Live mode does not replace missing
evidence with fixtures. No external write or claim adjudication is part of the investigation.

**How does feedback improve it?** Reviewed feedback is stored as a candidate lesson. Promotion into
Synapt or retraining remains a reviewed change with regression evaluation.
