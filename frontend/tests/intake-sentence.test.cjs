const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const ts = require('typescript')
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')

for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
      fileName: filename,
    })
    module._compile(outputText, filename)
  }
}
const { IntakeForm, EMPTY_FORM, EMPTY_FILTERS, buildClaim } = require('../src/components/IntakeForm.tsx')
const { applyMatch, compareCaption, display, marginNotes, matchFromFilters, missingList } = require('../src/lib/intakeView.ts')

const text = (html) => html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').replace(/ ([,.;])/g, '$1').trim()
const filled = {
  ...EMPTY_FORM,
  description: 'Rear-ended at a red light in Austin, TX.',
  claim_type: 'auto',
  state: 'TX',
  incident_date: '2026-03-03',
  claim_filed_date: '2026-03-07',
  claim_amount: '12400',
  deductible: '500',
  previous_claims_count: '1',
  policyholder_tenure_years: '6',
  provided_documents: ['police report', 'photos', 'repair estimate'],
}
const props = (form, extra = {}) => ({
  form, setForm() {}, filters: EMPTY_FILTERS, setFilters() {}, demoCases: [], demoLoading: false, demoError: null,
  onRetryDemos() {}, selectedDemo: null, onDemo() {}, busy: false, error: null, onSubmit() {}, onReset() {}, ...extra,
})

test('a filled claim reads as the approved sentence, and each blank is a labelled button', () => {
  const html = renderToStaticMarkup(React.createElement(IntakeForm, props(filled)))
  assert.match(
    text(html),
    /An auto claim from Texas, for \$12,400 against a \$500 deductible\. It happened on March 3, 2026 and was reported 4 days later\. The policyholder has been with us for 6 years and has 1 earlier claim\. They have sent a police report, photos and a repair estimate\./,
  )
  assert.match(html, /aria-label="State: Texas \(set by you\)\. Change"/)
  assert.match(html, /aria-haspopup="dialog"/)
  assert.match(html, /Ready\./)
})

test('an empty claim shows placeholders, counts what is missing and keeps the full form one click away', () => {
  const html = renderToStaticMarkup(React.createElement(IntakeForm, props(EMPTY_FORM)))
  assert.match(html, /aria-label="State: {2}\(not set yet\)\. Change"/)
  assert.match(text(html), /8 to go\. Next: what happened/)
  assert.match(html, /Use the full form/)
  assert.match(text(html), /0 \/ 6000/)
})

test('examples come from the demo cases, with loading and error states', () => {
  const demoCases = [{ id: 'auto-ready', title: 'Auto: repair evidence available', claim: filled }]
  assert.match(renderToStaticMarkup(React.createElement(IntakeForm, props(EMPTY_FORM, { demoCases }))), />Auto: repair evidence available</)
  assert.match(renderToStaticMarkup(React.createElement(IntakeForm, props(EMPTY_FORM, { demoLoading: true }))), /Loading examples/)
  const failed = renderToStaticMarkup(React.createElement(IntakeForm, props(EMPTY_FORM, { demoError: 'Demo cases unavailable' })))
  assert.match(failed, /Demo cases unavailable/)
  assert.match(failed, /Retry examples/)
})

test('values from a loaded example are shown as set by the handler, not as read from notes', () => {
  const html = renderToStaticMarkup(React.createElement(IntakeForm, props(filled)))
  assert.doesNotMatch(html, /read from your notes\)/)
  assert.doesNotMatch(html, /si-tok read/)
})

test('the sentence only ever fills the form buildClaim accepts', () => {
  assert.equal(missingList(filled).length, 0)
  assert.equal(buildClaim(filled).claim_amount, 12400)
  assert.deepEqual(missingList(EMPTY_FORM).map(([field]) => field), ['description', 'state', 'claim_amount', 'deductible', 'incident_date', 'claim_filed_date', 'policyholder_tenure_years', 'previous_claims_count'])
})

test('filing phrases adapt to the gap between the two dates', () => {
  assert.equal(display('claim_filed_date', { ...filled, claim_filed_date: '2026-03-03' }), 'the same day')
  assert.equal(display('claim_filed_date', { ...filled, claim_filed_date: '2026-03-04' }), 'the next day')
  assert.equal(display('claim_filed_date', { ...filled, incident_date: '' }), 'on March 7, 2026')
  assert.equal(display('policyholder_tenure_years', { ...filled, policyholder_tenure_years: '0.67' }), 'for under a year')
  assert.equal(display('previous_claims_count', { ...filled, previous_claims_count: '0' }), 'no earlier claims')
})

test('margin notes call out exposure, late reports, theft without a report and new policyholders', () => {
  const titles = (form, signals = { theft: false, missingDocs: [] }) => marginNotes(form, signals, 0).map(([, title]) => title)
  assert.ok(titles(filled).includes('Net exposure $11,900'))
  assert.ok(titles({ ...filled, claim_filed_date: '2026-05-01' }).some((t) => /Reported 59 days after/.test(t)))
  assert.ok(titles({ ...filled, deductible: '20000' }).includes('Deductible is larger than the claim'))
  assert.ok(titles({ ...filled, claim_amount: '90000' }).includes('Large loss'))
  assert.ok(titles({ ...filled, previous_claims_count: '4' }).includes('4 earlier claims'))
  assert.ok(titles({ ...filled, policyholder_tenure_years: '0.5' }).includes('New policyholder'))
  assert.ok(titles({ ...filled, provided_documents: ['photos'] }, { theft: true, missingDocs: ['police report'] }).includes('Theft, but no police report'))
  assert.ok(titles({ ...filled, provided_documents: ['photos'] }, { theft: false, missingDocs: ['invoice'] }).includes('Notes say the invoice is still missing'))
})

test('comparison chips map onto the existing search filters and follow the claim', () => {
  const on = { type: true, state: true, amount: true, history: true }
  const off = { type: false, state: false, amount: false, history: false }
  const applied = applyMatch(EMPTY_FILTERS, filled, on, off)
  assert.deepEqual(
    { ...applied },
    { ...EMPTY_FILTERS, claim_type: 'auto', state: 'TX', min_amount: '6200', max_amount: '18600', min_previous_claims: '0', max_previous_claims: '2' },
  )
  assert.deepEqual(matchFromFilters(applied, filled), on)
  // Turning one chip off clears only the filters it owns.
  const cleared = applyMatch(applied, filled, { ...on, amount: false }, on)
  assert.equal(cleared.min_amount, '')
  assert.equal(cleared.state, 'TX')
  // An outcome chosen in the full form is left alone.
  assert.equal(applyMatch({ ...EMPTY_FILTERS, claim_status: 'denied' }, filled, on, on).claim_status, 'denied')
  assert.equal(compareCaption(applied), 'Comparing against settled auto claims from Texas, between $6,200 and $18,600, with 0–2 earlier claims.')
  assert.equal(compareCaption({ ...EMPTY_FILTERS, claim_status: 'under_review' }), 'Comparing against claims of the same type under review.')
  assert.equal(compareCaption({ ...EMPTY_FILTERS, claim_status: 'denied' }), 'Comparing against denied claims of the same type.')
  assert.equal(compareCaption(EMPTY_FILTERS), 'Comparing against settled claims of the same type.')
})

const { IntakeReview } = require('../src/components/IntakeReview.tsx')
const { parseDocuments } = require('../src/lib/intakeView.ts')
const reviewProps = (form, extra = {}) => ({
  form, filters: EMPTY_FILTERS, today: '2026-10-10', json: '{ "claim": {} }',
  onField() {}, onDescription() {}, onDocs() {}, onFilter() {}, ...extra,
})
const review = (form, extra) => renderToStaticMarkup(React.createElement(IntakeReview, reviewProps(form, extra)))

test('the last look shows every value that will be sent as a labelled, editable box', () => {
  const html = review(filled)
  for (const label of ['Claim type', 'State', 'Claim amount (USD)', 'Deductible (USD)', 'Incident date', 'Filing date', 'Policyholder tenure (years)', 'Earlier claims', 'Documents received (separate with commas)', 'What happened'])
    assert.ok(html.includes(`">${label}</label>`), `missing the ${label} box`)
  assert.equal((html.match(/<label /g) || []).length, 17) // 10 claim boxes plus 7 comparison boxes
  assert.match(html, /type="number"[^>]*value="12400"/)
  assert.match(html, /type="date"[^>]*value="2026-03-03"/)
  assert.match(html, /value="police report, photos, repair estimate"/)
  assert.match(html, /<option value="TX" selected="">Texas \(TX\)<\/option>/)
  assert.match(html, /<textarea[^>]*>Rear-ended at a red light in Austin, TX\.<\/textarea>/)
  assert.match(html, /max="2026-10-10"/)
  assert.match(html, /min="2026-03-03"/) // the filing date cannot precede the incident
})

test('the request as JSON is collapsed behind a summary instead of shown by default', () => {
  const html = review(filled)
  assert.match(html, /<details class="ir-json"><summary>Show the exact request as JSON<\/summary><pre>/)
  assert.doesNotMatch(html.replace(/<details[\s\S]*<\/details>/, ''), /<pre/)
})

test('blank required boxes say they are still needed, and values read from notes ask for a glance', () => {
  const empty = review({ ...EMPTY_FORM, description: 'short' })
  assert.ok((empty.match(/Still needed/g) || []).length >= 7)
  assert.match(empty, /class="ir-box need"/)
  const read = review(filled, { hints: { claim_amount: 'Read from your notes. Please check it.' } })
  assert.match(read, /Read from your notes\. Please check it\./)
  assert.doesNotMatch(read, /Still needed/)
})

test('the comparison filters are editable boxes with the plain-English caption under them', () => {
  const html = review(filled, { filters: { ...EMPTY_FILTERS, claim_type: 'auto', state: 'TX', min_amount: '6200', max_amount: '18600' } })
  assert.match(html, /<option value="auto" selected="">Auto<\/option>/)
  assert.match(html, /type="number"[^>]*value="6200"/)
  assert.match(html, /type="number"[^>]*value="18600"/)
  assert.match(html, /Comparing against settled auto claims from Texas, between \$6,200 and \$18,600\./)
  assert.match(html, /<option value="">Any state<\/option>/)
})

test('typed documents become a clean list, without blanks or repeats', () => {
  assert.deepEqual(parseDocuments('police report, photos,, photos; invoice\n repair estimate '), ['police report', 'photos', 'invoice', 'repair estimate'])
  assert.deepEqual(parseDocuments('  '), [])
})

test('the dialog uses the review boxes, and the review styles are all prefixed', () => {
  const path = require('node:path')
  const sentence = fs.readFileSync(path.join(__dirname, '../src/components/IntakeSentence.tsx'), 'utf8')
  assert.match(sentence, /<IntakeReview/)
  assert.doesNotMatch(sentence, /<pre>\{preview\.json\}<\/pre>/)
  const source = fs.readFileSync(path.join(__dirname, '../src/components/IntakeReview.tsx'), 'utf8')
  for (const match of source.matchAll(/className=\{?(?:cx\()?['"]([^'"]+)['"]/g))
    for (const name of match[1].split(/\s+/)) assert.ok(name.startsWith('ir') || ['wide', 'need'].includes(name), `unprefixed class ${name}`)
  const css = fs.readFileSync(path.join(__dirname, '../src/index.css'), 'utf8')
  const block = css.slice(css.indexOf('/* The last look before an investigation starts'), css.indexOf('.si-dlg-foot {'))
  for (const selector of block.matchAll(/^\s*(?:\.si-dlg-body )?([.][a-z0-9-]+)/gm)) assert.ok(/^\.(ir|si-dlg-body)/.test(selector[1]) || selector[1].startsWith('.ir'), `unprefixed selector ${selector[1]}`)
  assert.match(block, /@media \(max-width: 560px\)\s*\{\s*\.ir-grid \{ grid-template-columns: minmax\(0, 1fr\); \}/)
})

test('the review column cannot be widened by the expanded JSON, which kept boxes from fitting narrow screens', () => {
  const css = fs.readFileSync(require('node:path').join(__dirname, '../src/index.css'), 'utf8')
  assert.match(css, /\.ir \{ display: grid; grid-template-columns: minmax\(0, 1fr\);/)
  assert.match(css, /\.si-dlg-body \.ir-json pre \{ margin-top: 10px; max-height: 32vh; \}/)
})

test('with no type chosen the comparison says it uses the same type, because that is what the search does', () => {
  assert.match(review(filled), /Comparing against settled claims of the same type\./)
  assert.match(review(filled), /<option value="" selected="">Same as the claim<\/option>/)
  assert.doesNotMatch(review(filled), /Any type/)
})
