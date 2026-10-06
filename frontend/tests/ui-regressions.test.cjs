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
