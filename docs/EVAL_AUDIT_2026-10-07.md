# Evaluation audit — 7 October 2026

This audit checks evaluator correctness separately from model/retrieval quality. The approved
the original project plan requires deterministic schemas, citations and action boundaries together with
DeepEval and an advisory independent judge. A completed provider request is not a quality pass.

## What I did

`EvaluationService` now independently checks evidence, findings, recommendations, source identity,
classification, declared execution mode, handler gate and the workflow validator's result. Missing,
blank or duplicate sources, uncited substantive findings and invalid recommendation schemas cannot
pass merely because a saved brief says `validation.passed=true`. Case exceptions produce safe failure
records and the rest of the suite continues. The theft and contradiction cases check their actual
objectives rather than accepting any unrelated gap or contradiction. A document gap may cite its
procedure while a separate fact cites claimant-reported absence; a contradiction must cite the
current conflicting statements.

DeepEval reports expected/completed/passed metrics separately. `judge_status=completed` means every
metric executed; `judge_quality_passed` requires every metric to pass. `overall_passed` combines the
golden checks with requested judge quality. Unavailable or malformed results do not count as passes.
The API also reports whether DeepEval's judge differs from the author.

The inline judge validates the brief before calling a model, reuses deterministic content/action
guards, preserves complete supplied evidence and refuses an oversized context instead of silently
cutting it. Verdict booleans must be booleans; scores must be finite numbers in [0, 1]. A verdict
listing issues cannot simultaneously pass. The prompt distinguishes historical claims from the
current claim, and document names from received/authenticated document content. Ambiguous claim
classification remains a handler-review concern and does not by itself prevent advisory judging.

The shared `validate_brief` document guard was also repaired with main-agent authorization. It now
recognizes both "submitted a repair estimate" and "a repair estimate was received", including
`received` and photograph variants. Qualification is scoped to the clause, and negation to the
specific receipt assertion; an unrelated "no contradictions" or "reported damage" cannot hide a
later claim that documents were reviewed. Fifteen positive/negative workflow tests cover that behavior.

`scripts/audit_evaluations.py` replays saved synthetic briefs through deterministic checks and optional
real judges, with an isolated audit database and resumable completed metrics. Failed metrics are
retried rather than reused. `scripts/audit_fresh_goldens.py` generates fresh live Synapt/author briefs
without loading the large ML artifacts or scanning the 100M-row file. Neither script accepts briefs,
promotes feedback or writes to Synapt.

## What was the issue / root cause

The old golden suite trusted the same workflow's stored pass flag and lacked independent schema,
category and mode checks. It could miss unrelated findings and stop on one case exception.
DeepEval execution completion had no aggregate quality gate. The advisory judge silently discarded
evidence after 1,500 characters per source and could pass a verdict that listed concrete problems.
A saved auto brief was a real false-pass example: it claimed document receipt while the intake had
only reported document names. Its stored validation passed, but current independent validation fails.

## Why this approach

The deterministic checks validate enforceable contracts; the probabilistic judges evaluate evidence
support and usefulness. Those responsibilities remain distinct, and a model cannot overrule a known
deterministic failure. The API's existing four-case contract is retained. Meaningful adverse tests
exercise forged passes, wrong categories/modes, source duplication, missing gates, unrelated findings,
malformed outputs, nonfinite scores, oversized evidence, exceptions and interrupted metric replay.

## Why not the alternative

Thresholds were not lowered and stale briefs were not edited to manufacture green results. A source
identifier resolving does not establish semantic truth, and a successful HTTP response does not show
that a recommendation is useful. Repeating all successful provider calls after interruption would
waste time; audited successful metric results can be reused under the same model and threshold.

## Why this works best

Local fixtures test controlled behavior and failure handling; actual provider calls prove the real
evaluation adapter executes. Separate execution and quality fields prevent weak scores from appearing
as overall success. Complete evidence and strict verdict validation remove avoidable false passes,
while preserving the human-review gate and honest semantic limits.

## Actual live measurements

The real DeepEval model was `nvidia/nemotron-3-super-120b-a12b`, the same model as the author;
this is explicitly reported as **not independent**. Threshold remains **0.5** for all three metrics.
These are saved synthetic briefs from `artifacts/evaluation/live-2026-10-06`, not regenerated claims
or measurements of the newly expanded corpus.

| Saved case | Faithfulness | Contextual relevance | Safety/usefulness |
| --- | ---: | ---: | ---: |
| Auto ready | 1.000, pass | 0.350, fail | 1.000, pass |
| Theft gap | 0.667, pass | 0.40625, fail | 0.900, pass |
| Home conflict | 0.800, pass | 0.53125, pass | 1.000, pass |
| Unknown | 1.000, pass | 0.0625, fail | 0.900, pass |

**12/12 actual metrics executed; 9/12 passed.** Context relevance passes 1/4. Therefore
`judge_quality_passed=false`. The saved goldens pass **3/4**, because the stale auto brief fails the
document-availability guard; the combined quality gate is false. Metric errors are logged separately
and no score is inferred for unavailable or skipped work.

The independent inline model was `openai/gpt-oss-20b`, with the existing pass score **0.7**.
Before the added deterministic precheck, it passed all four saved briefs (0.95, 0.90, 0.90, 0.90),
including the invalid auto brief. That concrete disagreement demonstrates why its verdict is advisory.
After the guard fix, auto is rejected **before a model call**, and theft/home/unknown complete and pass
at **0.95 / 0.90 / 0.95**. The existing DeepEval scores were reused for this guard-only replay.

Fresh live Synapt and author generation completed all four cases in **34.05 seconds**, with auto/theft/
home awaiting handler review and unknown requiring manual review. Rechecking those outputs against
the final objective-based rubric passes **4/4**: schemas, citations, availability wording, the police
report gap, conflicting pipe statements and category abstention. These fresh checks deliberately
exclude ML predictions, large-file searches and DeepEval; they do not establish all-domain accuracy.

Evidence files:

- `artifacts/evaluation/audit-2026-10-07/report.json`: guarded saved replay and the 12 real metric scores.
- `artifacts/evaluation/audit-2026-10-07/report-before-content-precheck.json`: preserved precheck disagreement.
- `artifacts/evaluation/audit-2026-10-07/audit-*.sqlite`: model prompts, validated outputs and decisions.
- `artifacts/evaluation/audit-2026-10-07/fresh/case-*.json`: fresh live source briefs.
- `artifacts/evaluation/audit-2026-10-07/fresh-contract/report.json`: final independent checks, 4/4.

## Commands and verification

```powershell
uv run pytest -q tests/test_evaluation.py tests/test_judge.py tests/test_workflow.py
uv run ruff check src/claims/evaluation/service.py src/claims/evaluation/judge.py tests/test_evaluation.py tests/test_judge.py scripts/audit_evaluations.py scripts/audit_fresh_goldens.py
uv run python scripts/audit_evaluations.py --snapshot-dir artifacts/evaluation/live-2026-10-06 --live
uv run python scripts/audit_evaluations.py --snapshot-dir artifacts/evaluation/live-2026-10-06 --live --resume
uv run python scripts/audit_fresh_goldens.py
uv run python scripts/audit_evaluations.py --snapshot-dir artifacts/evaluation/audit-2026-10-07/fresh --output-dir artifacts/evaluation/audit-2026-10-07/fresh-contract
```

**Final focused validation: 78 tests passed in 13.58 seconds; lint passed for all eight changed
code/test/script paths (documentation excluded).** Local artifact/report and audit-body checks found
no configured username, password, model key or application key. No provider secrets were printed.
The live scripts ran in hidden detached processes when the tool execution sessions were interrupted;
both finished normally. Their audit databases were closed, Python processes exited, and temporary PID
files were removed. Main-agent full-suite/UI validation is recorded separately from these focused checks.

## Other valid patterns and remaining limits

A reviewed larger golden set could assess all five claim categories, policy variants and evidence
formats; these four cases are a regression spine. A reference-answer-based contextual precision/recall
suite is useful when reviewed expected answers exist; invented reference answers would make the
measurement misleading. Semantic judges remain probabilistic, a text-size budget is not an exact token
budget, and fixed phrases do not exhaust all harmful actions. Weak context relevance still requires
retrieval/content improvements and a fresh DeepEval run after corpus integration. The fresh no-scan
goldens do not prove predictions, full-dataset filters, provider ingestion or real-world claim accuracy.
