const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

// Use the project's existing compiler to test its real TS/TSX components.
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
      fileName: filename,
    })
    module._compile(outputText, filename)
  }
}
const { CountUp } = require('../src/components/ui.tsx')
const { TracePanel, LoadingState, EmptyState } = require('../src/components/Results.tsx')
const { EvaluationProgressPanel, EvaluationVerdict } = require('../src/components/EvaluationPanels.tsx')
const { STAGES } = require('../src/components/Pipeline.tsx')
const { ModelComparison } = require('../src/components/ModelComparison.tsx')
const { CohortPanel } = require('../src/components/CohortPanel.tsx')
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props))
// React's static markup separates adjacent text pieces with comments; strip them to read sentences.
const plainText = (html) => html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

test('initial render exposes actual estimates without waiting for a viewport', () => {
  assert.equal(render(CountUp, { value: 10264, format: value => `$${value.toLocaleString('en-US')}` }), '<span>$10,264</span>')
  assert.equal(render(CountUp, { value: 11.7, format: value => `${value.toFixed(1)} days` }), '<span>11.7 days</span>')
})
test('missing validation never claims a failed run has no issues', () => {
  const html = render(TracePanel, { run: { status: 'failed', trace: [] } })
  assert.match(html, /Validation results are unavailable/)
  assert.doesNotMatch(html, /No validation issues reported|Validation passed/)
})
test('failed validation with empty issues stays failed', () => {
  assert.match(render(TracePanel, { run: { validation: { passed: false, issues: [] } } }), /Validation did not pass/)
})
test('passed validation states its scope and failed issues remain visible', () => {
  assert.match(render(TracePanel, { run: { validation: { passed: true, issues: [], scope: 'citation checks only' } } }), /citation checks only/)
  assert.match(render(TracePanel, { run: { validation: { passed: false, issues: ['Missing citation'] } } }), /Missing citation/)
})
test('request loading does not manufacture completed workflow stages', () => {
  const html = render(LoadingState)
  assert.match(html, /aria-busy="true"/)
  assert.doesNotMatch(html, /Classify: done|Retrieve: done|indefinite/)
})
test('empty state uses flow content instead of a fixed orbit illustration', () => {
  const html = render(EmptyState)
  assert.match(html, /Start an investigation/)
  assert.doesNotMatch(html, /class="orbit"|repeatCount="indefinite"|width="240"/)
})

const { findingText, readable, sourceExcerpt, sourceTitle } = require('../src/lib/presentation.ts')
const { buildClaim, formFromClaim } = require('../src/components/IntakeForm.tsx')
const { stateCode } = require('../src/lib/states.ts')
const { validateSuggestions } = require('../src/lib/savedSearch.ts')
const { CaseSearch } = require('../src/components/CaseSearch.tsx')
test('autocomplete starts collapsed with combobox semantics and no Open action', () => {
  const html = render(CaseSearch, { onOpen: () => {}, onQueryChange: () => {}, disabled: false })
  assert.match(html, /role="combobox"/)
  assert.match(html, /aria-autocomplete="list"/)
  assert.match(html, /aria-expanded="false"/)
  assert.doesNotMatch(html, />Open<|role="listbox"/)
})
test('suggestion schema rejects malformed values and duplicate navigation targets', () => {
  const item = { run_id: 'case-1', title: 'Rear-ended', description: 'Car struck', status: 'reviewed', claim_type: 'auto', state: 'TX', claim_amount: 8500, claim_filed_date: '', match_kind: 'Title match' }
  const page = { items: [item], total: 1, semantic_status: 'ready' }
  assert.equal(validateSuggestions(page), page)
  assert.throws(() => validateSuggestions({ ...page, items: [item, item], total: 2 }))
  assert.throws(() => validateSuggestions({ ...page, items: [{ ...item, run_id: '' }] }))
  assert.throws(() => validateSuggestions({ ...page, items: [{ ...item, claim_amount: NaN }] }))
  assert.throws(() => validateSuggestions({ ...page, semantic_status: 'success' }))
})
test('technical activity is rendered only for administrators', () => {
  const run = { mode: 'live', agent_mode: 'live', trace: [{ stage: 'retrieve', status: 'done', detail: 'Synapt provider diagnostics' }] }
  assert.doesNotMatch(render(TracePanel, { run }), /Synapt|Agents:|provider diagnostics/)
  assert.match(render(TracePanel, { run, admin: true }), /Synapt provider diagnostics/)
})
test('state names normalize without silently accepting an unknown jurisdiction', () => {
  assert.equal(stateCode('texas'), 'TX')
  assert.equal(stateCode('New York'), 'NY')
  const input = { description: 'A rear-end collision at a junction.', state: 'Texas', incident_date: '2026-09-01', claim_filed_date: '2026-09-02', claim_amount: 8500, deductible: 500, previous_claims_count: 0, policyholder_tenure_years: 4, provided_documents: [] }
  assert.equal(buildClaim(formFromClaim(input)).state, 'TX')
  assert.throws(() => buildClaim(formFromClaim({ ...input, state: 'ZZ' })), /state code/)
})
test('legacy generated document assertions become reported availability without changing originals', () => {
  const finding = { kind: 'fact', text: 'The claimant provided an incident statement and a repair estimate as supporting documents.', source_ids: ['claim:input'] }
  const copy = JSON.stringify(finding)
  assert.match(findingText(finding, { claim: { provided_documents: ['incident statement', 'repair estimate'] } }), /Only names were recorded; content was not received or reviewed/)
  assert.equal(JSON.stringify(finding), copy)
  const qualified = { ...finding, text: 'The claimant reports documents available; content is unverified.' }
  assert.equal(findingText(qualified, {}), qualified.text)
})
test('readable source labels and technical warnings preserve original evidence', () => {
  const source = { title: '01_auto_claim_procedure.json', source_id: 'chunk_abc', text: 'Exact original quotation', provenance: 'synapt' }
  assert.equal(sourceTitle(source), '01 auto claim procedure')
  assert.equal(source.text, 'Exact original quotation')
  assert.match(readable('Optional Synapt trident_search response lacks supported provenance'), /excluded/)
  assert.equal(readable('Same previous_claims_count: 0'), 'No previous claims in either case')
  assert.equal(readable('Same claim_type: auto'), 'Same claim type: auto')
  const raw = '# File name\n\nsource_id: opaque-uuid\nprovenance: synapt\n\nRequest an incident statement and repair estimate when applicable.'
  assert.equal(sourceExcerpt({ text: raw }), 'Request an incident statement and repair estimate when applicable.')
  assert.equal(raw.includes(sourceExcerpt({ text: raw })), true)
  const packed = '# File name\nsource_id: opaque-uuid\nprovenance: synapt\nRequest an incident statement and repair estimate when applicable.'
  assert.equal(sourceExcerpt({ text: packed }), 'Request an incident statement and repair estimate when applicable.')
})

const { Explanation } = require('../src/components/Results.tsx')
const presentation = require('../src/lib/presentation.ts')
test('explanations show what moved this claim and the learned direction without claiming causality', () => {
  const html = render(Explanation, {
    item: {
      local_explanation: { method: 'One-at-a-time substitution; not additive or causal', unit: 'USD', contributions: [{ feature: 'claim_type', value: 'business', typical_value: 'auto', effect: 52000 }, { feature: 'deductible', value: 500, typical_value: 1000, effect: -300 }] },
      global_explanation: { features: [{ feature: 'claim_type', score_drop: 13488.7 }], summary: ['claim type: highest predicted claim amount (USD) for business (107,013.55 USD), lowest for renters (4,271.00 USD).'], effects_method: 'Partial dependence; associations, not causal effects' },
    },
  })
  assert.match(html, /For this claim, compared with a typical one/)
  assert.match(html, /\+\$52,000/)
  assert.match(html, /−\$300/)
  assert.match(html, /typical auto/)
  assert.match(html, /What the model learned across the sample/)
  assert.match(html, /highest predicted claim amount[^<]*business[^<]*lowest for renters/)
  assert.match(html, /not additive or causal/)
  assert.match(html, /associations, not causal effects/)
  assert.equal(render(Explanation, { item: {} }), '')
})
test('fraud flags and open claims are labelled as dataset labels, never as outcomes or proof', () => {
  const flagged = presentation.comparisonSnapshot({ claim_id: 'CLM-1', claim_type: 'auto', state: 'TX', claim_amount: 100, claim_status: 'under_review', days_to_resolution: null, open_case: true, dataset_fraud_flag: true, previous_claims_count: 2, similarity_score: 0.03, match_reasons: [], differences: [] })
  assert.equal(flagged.historical_outcome, 'under_review (no final outcome)')
  assert.match(flagged.dataset_fraud_flag, /synthetic label, not proof/)
  assert.equal(flagged.previous_claims, 2)
  assert.equal(presentation.comparisonSnapshot({ claim_id: 'CLM-2', claim_type: 'home', state: 'FL', claim_amount: 1, claim_status: 'approved', days_to_resolution: 5, similarity_score: 0, match_reasons: [], differences: [] }).dataset_fraud_flag, 'not recorded')
  assert.equal(presentation.provenanceLabel('handler_lesson'), 'Reviewed handler lesson')
  assert.match(presentation.directionLabel('higher_values_increase'), /higher estimate/)
  assert.equal(presentation.directionLabel('little_effect'), 'Little effect')
})
test('trace shows the audited queue priority and flags a concerned independent review', () => {
  const run = { status: 'awaiting_review', trace: [{ stage: 'validate', status: 'complete', detail: '' }, { stage: 'judge', status: 'complete', detail: '' }], validation: { passed: true, issues: [] }, judge: { status: 'completed', passed: false }, priority: { service_urgency: 'urgent', investigation_priority: 'elevated', score: 72, tier: 'critical' } }
  const html = render(TracePanel, { run })
  assert.match(html, /Queue priority: Critical \(72\/100\)/)
  assert.match(html, /Judge: warn/)
  assert.match(html, /Validate: done/)
  const clean = render(TracePanel, { run: { ...run, judge: { status: 'completed', passed: true } } })
  assert.match(clean, /Judge: done/)
})
test('a pending independent review is shown as in progress, not as a failure or a pass', () => {
  const run = { status: 'awaiting_review', trace: [{ stage: 'validate', status: 'complete', detail: '' }, { stage: 'judge', status: 'complete', detail: '' }], validation: { passed: true, issues: [] }, judge: { status: 'pending', reason: 'running' } }
  const html = render(TracePanel, { run })
  assert.match(html, /Judge: active/)
  assert.doesNotMatch(html, /Judge: warn|Judge: done/)
})

const step = (id, label, state, detail = null) => ({ id, label, state, started_at: null, ended_at: null, detail })
const progress = (extra = {}) => ({
  state: 'running', judge_requested: true, started_at: '2026-10-10T10:00:00Z', finished_at: null, phase: 'judge',
  current: 'Case 2 · Faithfulness', total_steps: 16, done_steps: 6,
  steps: [step('golden:auto', 'Golden case · auto', 'done', '9/9 checks passed'), step('judge:2:Faithfulness', 'Case 2 · Faithfulness', 'running'), step('judge:2:Contextual Relevancy', 'Case 2 · Contextual Relevancy', 'pending')],
  events: [{ at: '2026-10-10T10:00:05Z', text: 'Judging case 2: Faithfulness (asking the judge model)' }], ...extra,
})
test('a running evaluation shows what it is doing, step by step, instead of a blank wait', () => {
  const html = render(EvaluationProgressPanel, { progress: progress(), now: Date.parse('2026-10-10T10:01:30Z') })
  assert.match(html, /Evaluation running/)
  assert.match(html, /6 of 16 steps done/)
  assert.match(html, /now: Case 2 · Faithfulness/)
  assert.match(html, /Golden case · auto/)
  assert.match(html, /9\/9 checks passed/)
  assert.match(html, /Judging case 2: Faithfulness/)
  assert.match(html, /1m 30s/)
})
const finished = { status: 'completed', judge_status: 'completed', judge_requested: true, passed: 4, total: 4, judge_expected_metrics: 12, judge_completed_metrics: 12, judge_passed_metrics: 3, judge_model: 'judge-x', judge_threshold: 0.5, overall_passed: false }
test('a judge that ran but scored below the pass line is reported as having run, not as skipped', () => {
  const html = render(EvaluationVerdict, { evals: finished })
  assert.match(html, /Overall: not passed/)
  assert.match(html, /4\/4 passed/)
  assert.match(html, /Ran: 12\/12 metrics scored by judge-x/)
  assert.match(html, /9 of 12 judge scores were below the 0\.5 pass line/)
  assert.match(html, /The judge did run/)
})
test('a judge that could not start says why, and an unselected judge says so', () => {
  const unavailable = render(EvaluationVerdict, { evals: { ...finished, judge_status: 'unavailable: install evaluation extra and configure judge model/key', judge_expected_metrics: undefined } })
  assert.match(unavailable, /Could not start \(install evaluation extra/)
  const off = render(EvaluationVerdict, { evals: { ...finished, judge_requested: false, judge_status: 'not_run', overall_passed: true } })
  assert.match(off, /Not selected for this run/)
  assert.match(off, /Overall: passed/)
})
test('the page stage counts come from the one stage list, so they cannot disagree', () => {
  assert.equal(STAGES.length, 9)
  const connection = fs.readFileSync(require('node:path').join(__dirname, '../src/components/ConnectionView.tsx'), 'utf8')
  const explain = fs.readFileSync(require('node:path').join(__dirname, '../src/components/ExplainabilityView.tsx'), 'utf8')
  assert.doesNotMatch(connection, /\d-stage workflow/)
  assert.match(connection, /STAGES\.length/)
  assert.doesNotMatch(explain, /same (?:one|two|three|four|five|six|seven|eight|nine) stages/)
  assert.match(explain, /countWord\(STAGES\.length\)/)
})

test('the evaluation verdict has its own class and cannot pick up the brief page verdict tiles layout', () => {
  const html = render(EvaluationVerdict, { evals: finished })
  assert.match(html, /class="eval-verdict warn"/)
  assert.doesNotMatch(html, /class="verdict[ "]/)
  const css = fs.readFileSync(require('node:path').join(__dirname, '../src/index.css'), 'utf8')
  // `.verdict` is the brief page's four-column tile grid; nothing else may restyle it.
  assert.equal((css.match(/^\.verdict\s*\{/gm) || []).length, 1)
  assert.doesNotMatch(css, /^\.verdict\.(?:ok|warn)\b|^\.verdict ul|^\.verdict li/m)
})
test('a model that beats its baseline says so, and a winning simple rule is explained, with every candidate listed', () => {
  const amount = render(ModelComparison, { task: 'amount', metric: { available: true, selected_model: 'claim_type_median', mae: 15105, baseline_mae: 22630,
    candidate_selection_maes: { random_forest: 16017, claim_type_median: 15148, histogram_boosting_absolute_error: 15154, median_baseline: 22495 } } })
  assert.match(amount, /Error is 33% lower than the baseline/)
  assert.match(amount, /A plain rule won here/)
  assert.match(amount, /Claim type median · chosen/)
  assert.match(amount, /Random forest/)
  const fraud = render(ModelComparison, { task: 'fraud', metric: { available: true, selected_model: 'random_forest', pr_auc_average_precision: 0.3207, baseline_pr_auc: 0.0772, brier_score: 0.0605, baseline_brier_score: 0.0712,
    candidate_selection_scores: { random_forest: { pr_auc: 0.316 }, prior_baseline: { pr_auc: 0.075 } } } })
  assert.match(fraud, /PR-AUC is 4\.2× the baseline/)
  assert.match(fraud, /Brier score is 15% lower than the baseline/)
  assert.doesNotMatch(fraud, /A plain rule won here/)
})

const cohortFigures = (key, overrides) => ({
  key,
  definition: `${key} definition`,
  claims: 30,
  approved_share: 0.8,
  denied_share: 0.2,
  median_days: 31,
  p25_days: 16.5,
  p75_days: 45.5,
  flag_rate: 0.1,
  sufficient: true,
  ...overrides,
})
const cohortRun = {
  available: true,
  source: 'duckdb_parquet',
  eligibility: 'approved or denied claims closed before 1 January 2026',
  dataset_claims: 100000000,
  elapsed_seconds: 5.9,
  cohorts: [
    cohortFigures('exact', { definition: 'auto claims in Texas, amount 5,000-10,000 USD, tenure 1-3 years, no prior claims, filed 8-15 days after the incident' }),
    cohortFigures('type_amount_history', { claims: 12, approved_share: 0.5, sufficient: false }),
    cohortFigures('type', { claims: 65, median_days: 26, p25_days: 4, p75_days: 50, flag_rate: 0.2 }),
  ],
  synapt_cross_check: { source: 'local_fallback', cards_returned: 3, in_exact_cohort: 2, in_type_amount_history_cohort: 3 },
  notes: ['They are computed by DuckDB over the full claims dataset in one pass. They do not come from Synapt.', 'The fraud figure is a synthetic label, not proof of fraud.'],
}

test('cohort panel gives exact figures with their definitions and says DuckDB computed them, not Synapt', () => {
  const text = plainText(render(CohortPanel, { cohort: cohortRun }))
  assert.match(text, /How claims like this were settled/)
  assert.match(text, /Exact statistics from the full dataset, computed by DuckDB\. They describe past claims with similar details and do not decide, predict or assess coverage for this claim\./)
  assert.match(text, /Computed by DuckDB over 100,000,000 claims in 5\.9 s, not by Synapt\./)
  assert.match(text, /auto claims in Texas, amount 5,000-10,000 USD, tenure 1-3 years, no prior claims, filed 8-15 days after the incident/)
  assert.match(text, /80\.0%/)
  assert.match(text, /31\.0 days p25–p75 16\.5–45\.5 days/)
  assert.match(text, /Counted: approved or denied claims closed before 1 January 2026\./)
  assert.match(text, /a synthetic label, not proof of fraud/)
})

test('a cohort below the sufficiency line is muted and says it is too few claims for a stable figure', () => {
  const html = render(CohortPanel, { cohort: cohortRun })
  assert.match(html, /class="cohort-row-muted"/)
  assert.equal((html.match(/Too few claims for a stable figure/g) || []).length, 1)
  assert.equal((html.match(/cohort-row-muted/g) || []).length, 1)
})

test('the cross-check names the real source of the past claims and never calls the local copy Synapt', () => {
  const degraded = plainText(render(CohortPanel, { cohort: cohortRun }))
  assert.match(degraded, /Of the 3 claim cards returned by the local fallback copy, not Synapt, 2 describe this exact cohort and 3 are in the same type, amount and prior-claims bands\./)
  assert.doesNotMatch(degraded, /returned by Synapt/)
  const live = plainText(render(CohortPanel, { cohort: { ...cohortRun, synapt_cross_check: { source: 'synapt', cards_returned: 1, in_exact_cohort: 1, in_type_amount_history_cohort: 1 } } }))
  assert.match(live, /Of the 1 similar past claim returned by Synapt(?:'|&#x27;)s ticket store, 1 describes this exact cohort and 1 is in the same type, amount and prior-claims bands\./)
  const none = plainText(render(CohortPanel, { cohort: { ...cohortRun, synapt_cross_check: null } }))
  assert.doesNotMatch(none, /Cross-check against retrieved past claims/)
  const unlabelled = plainText(render(CohortPanel, { cohort: { ...cohortRun, synapt_cross_check: { source: 'unknown', cards_returned: 2, in_exact_cohort: 0, in_type_amount_history_cohort: 0 } } }))
  assert.doesNotMatch(unlabelled, /Of the 2 claim cards/)
})

test('a run saved without a cohort shows nothing, and an unavailable cohort shows its reason, without crashing', () => {
  assert.equal(render(CohortPanel, { cohort: undefined }), '')
  assert.equal(render(CohortPanel, { cohort: null }), '')
  assert.match(plainText(render(CohortPanel, { cohort: { available: false, reason: 'The full claims dataset is not loaded, so cohort statistics are unavailable.' } })), /Cohort statistics are not shown for this run: The full claims dataset is not loaded/)
  assert.match(plainText(render(CohortPanel, { cohort: { available: true } })), /How claims like this were settled/)
})

test('the cohort panel uses only cohort- classes, each with its own rule in the stylesheet', () => {
  const html = render(CohortPanel, { cohort: cohortRun })
  const tokens = [...html.matchAll(/class="([^"]*)"/g)].flatMap((m) => m[1].split(' '))
  assert.ok(tokens.length > 0)
  for (const token of new Set(tokens)) assert.match(token, /^cohort-/, token)
  const css = fs.readFileSync(require('node:path').join(__dirname, '../src/index.css'), 'utf8')
  for (const token of new Set(tokens)) assert.ok(css.includes(`.${token}`), `no stylesheet rule for ${token}`)
  const source = fs.readFileSync(require('node:path').join(__dirname, '../src/components/CohortPanel.tsx'), 'utf8')
  const literals = [...source.matchAll(/className=(?:\{[^}]*?)?["']([^"']*)["']/g)].flatMap((m) => m[1].split(' ')).filter(Boolean)
  assert.ok(literals.length >= 10, 'the panel names its classes in source')
  for (const token of literals) assert.match(token, /^cohort-/, token)
})

test('the cohort wording avoids conclusions and fraud rates, and names the figure as a synthetic flag', () => {
  const source = fs.readFileSync(require('node:path').join(__dirname, '../src/components/CohortPanel.tsx'), 'utf8')
  assert.doesNotMatch(source, /\b(?:covered|eligible|valid|likely|expected|predicted|probability|fraud rate|fraud risk)\b/i)
  assert.match(source, /DuckDB/)
  assert.match(source, /not by Synapt/)
  assert.match(source, /Synthetic fraud flag/)
  const text = plainText(render(CohortPanel, { cohort: cohortRun })).toLowerCase()
  for (const word of ['covered', 'eligible', 'valid', 'likely', 'expected', 'predicted', 'probability of approval', 'fraud rate']) {
    assert.ok(!text.includes(word), word)
  }
})

test('the cohort panel sits in the Comparisons tab above the similar cases, and the stacked narrow layout is a media query', () => {
  const results = fs.readFileSync(require('node:path').join(__dirname, '../src/components/Results.tsx'), 'utf8')
  const branch = results.indexOf("{tab === 'comparisons' && (")
  assert.ok(branch > 0)
  assert.ok(results.indexOf('<CohortPanel cohort={run.cohort} />', branch) < results.indexOf('<ComparisonsPanel cases={comparisons} />', branch))
  const css = fs.readFileSync(require('node:path').join(__dirname, '../src/index.css'), 'utf8')
  const narrow = css.slice(css.search(/@media \(max-width: 640px\)\s*\{\s*\.cohort-table thead/))
  assert.ok(narrow.length > 0, 'the stacked layout is missing')
  assert.match(narrow, /\.cohort-table thead\s*\{\s*display: none;\s*\}/)
  assert.match(narrow, /content: attr\(data-label\)/)
})

const { RunCard } = require('../src/components/EvaluationRuns.tsx')
const { judgeWord } = require('../src/lib/trace.ts')
const evaluationItem = {
  id: 11, time: '2026-10-10T08:46:42+00:00', started_at: '2026-10-10T08:40:00+00:00', finished_at: '2026-10-10T08:46:42+00:00',
  duration_seconds: 402, mode: 'live', agent_mode: 'live', overall_passed: true,
  cases: { passed: 4, total: 4, items: [{ case: 'auto_theft', passed: true, run_id: 'run-a' }, { case: 'water_damage', passed: true, run_id: null }] },
  judge: {
    requested: true, status: 'completed', model: 'judge-model', independent: true, threshold: 0.5,
    expected_metrics: 12, completed_metrics: 12, passed_metrics: 11, mean_score: 0.86,
    metrics: [
      { metric: 'Faithfulness', completed: 4, passed: 4, failed: 0, skipped: 0, mean_score: 0.9 },
      { metric: 'Claims handling safety and usefulness [GEval]', completed: 3, passed: 2, failed: 1, skipped: 0, mean_score: 0.7 },
    ],
    model_calls: { traced: true, calls: 36, tokens: 14200, total_ms: 130000 },
  },
}

test('an evaluation run card states the cases, the judge, its scores and the traced model calls', () => {
  const text = plainText(render(RunCard, { item: evaluationItem, onOpenTrace: () => {} }))
  assert.match(text, /Passed/)
  assert.match(text, /Judge: Completed/)
  assert.match(text, /4 of 4 passed/)
  assert.match(text, /12 of 12, 11 met the 0\.5 threshold/)
  assert.match(text, /36 calls · 14\.2K tokens/)
  assert.match(text, /Claims handling safety and usefulness/)
  assert.doesNotMatch(text, /\[GEval\]/)
  assert.match(text, /3 \(\+1 not scored\)/)
  assert.match(text, /Open a case trace/)
})

test('only cases that have a run can be opened as a trace', () => {
  const html = render(RunCard, { item: evaluationItem, onOpenTrace: () => {} })
  assert.match(html, /Auto theft/)
  assert.doesNotMatch(html, /Water damage/)
  assert.doesNotMatch(render(RunCard, { item: evaluationItem }), /Open a case trace/)
})

test('a run saved before judge calls were traced says so instead of showing zero calls', () => {
  const old = { ...evaluationItem, judge: { ...evaluationItem.judge, model_calls: { traced: false, calls: 0, tokens: 0, total_ms: 0 } } }
  assert.match(plainText(render(RunCard, { item: old })), /Not traced \(this run was saved before judge calls were traced\)/)
})

test('a run without the judge shows no judge facts or metric table', () => {
  const none = { ...evaluationItem, overall_passed: false, judge: { ...evaluationItem.judge, requested: false, status: 'not_run', metrics: [] } }
  const html = render(RunCard, { item: none })
  assert.match(plainText(html), /Judge: Not selected/)
  assert.match(plainText(html), /Not passed/)
  assert.doesNotMatch(html, /Metrics scored|Judge model calls|evalruns-metrics/)
})

test('judge statuses map to plain words, including long unavailable messages', () => {
  assert.deepEqual(judgeWord('completed', true), ['Completed', 'teal'])
  assert.deepEqual(judgeWord('partial', true), ['Partly completed', 'amber'])
  assert.equal(judgeWord('unavailable: install evaluation extra and configure judge model/key', true)[0], 'Unavailable')
  assert.equal(judgeWord('failed: judge transport or schema validation failed', true)[0], 'Failed')
  assert.equal(judgeWord('completed', false)[0], 'Not selected')
})

test('the evaluation runs tab is wired into Observability and its styles are prefixed and stack when narrow', () => {
  const path = require('node:path')
  const page = fs.readFileSync(path.join(__dirname, '../src/components/ObservabilityView.tsx'), 'utf8')
  assert.match(page, /key: 'evaluations', label: 'Evaluation runs'/)
  assert.match(page, /<EvaluationRuns onOpenTrace=\{openTrace\} \/>/)
  const source = fs.readFileSync(path.join(__dirname, '../src/components/EvaluationRuns.tsx'), 'utf8')
  const shared = new Set(['btn', 'spin', 'skeleton', 'small-empty'])
  for (const match of source.matchAll(/className="([^"]+)"/g)) {
    for (const name of match[1].split(/\s+/)) assert.ok(name.startsWith('evalruns') || shared.has(name), `unprefixed class ${name}`)
  }
  const css = fs.readFileSync(path.join(__dirname, '../src/index.css'), 'utf8')
  const block = css.slice(css.indexOf('/* Evaluation runs (Observability)'), css.indexOf('/* ---------- Evidence ---------- */'))
  for (const selector of block.matchAll(/^\s*([.][a-z0-9-]+)/gm)) assert.ok(selector[1].startsWith('.evalruns'), `unprefixed selector ${selector[1]}`)
  assert.match(block, /@media \(max-width: 640px\)\s*\{\s*\.evalruns-metrics thead\s*\{\s*display: none;\s*\}/)
  assert.match(block, /content: attr\(data-label\)/)
})
test('the agent access matrix scroller contains its hidden labels, so the page cannot be stretched sideways on a phone', () => {
  const css = fs.readFileSync(require('node:path').join(__dirname, '../src/index.css'), 'utf8')
  // The table holds one absolutely positioned .sr-only label per cell. They are clipped by the scroller only when
  // the scroller itself is positioned; otherwise they anchor to the outer card and widen the whole page.
  assert.match(css, /^\.sr-only\s*\{[^}]*position:\s*absolute/m)
  const scroller = css.match(/^\.agent-matrix-scroll\s*\{([^}]*)\}/m)
  assert.ok(scroller, 'the .agent-matrix-scroll rule exists')
  assert.match(scroller[1], /position:\s*relative/)
  assert.match(scroller[1], /overflow-x:\s*auto/)
})
