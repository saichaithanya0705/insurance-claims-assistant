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
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props))

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
