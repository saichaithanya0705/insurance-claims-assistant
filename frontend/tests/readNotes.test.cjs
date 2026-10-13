const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const ts = require('typescript')

// Same loader as ui-regressions.test.cjs: compile the project's real TS with its own compiler.
for (const extension of ['.ts', '.tsx']) {
  require.extensions[extension] = (module, filename) => {
    const { outputText } = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
      fileName: filename,
    })
    module._compile(outputText, filename)
  }
}
const { readNotes, quoteIn } = require('../src/lib/readNotes.ts')

// A fixed "today" keeps relative dates and the future-date rule deterministic.
const TODAY = '2026-10-10'
const read = (text) => readNotes(text, TODAY)
const values = (reading) => Object.fromEntries(Object.entries(reading.fields).map(([key, hit]) => [key, hit.value]))

// The three examples offered by the approved prototype (docs/prototypes/intake-sentence.html).
const EXAMPLES = [
  'Rear-ended at a red light on I-35 in Austin, TX on March 3, 2026. Other driver admitted fault at the scene. Repair estimate from Northside Collision came to $12,400; the policy has a $500 deductible. Reported to us on March 7. Customer for 6 years, 1 prior claim. She sent photos, the police report and the repair estimate.',
  'Insured says his 2021 Honda Civic was stolen from his driveway overnight in Phoenix, Arizona on 2026-08-14. Reported 2026-09-20. Claiming $24,000 with a $1,000 deductible. Policyholder for 8 months, 3 previous claims. Has photos of the driveway but no police report yet.',
  'Pipe burst under the kitchen sink while the family was away, flooding the kitchen and part of the basement. House in Columbus, Ohio. Happened 9/28/2026, called in 9/29/2026. Contractor invoice for $8,750; $1,000 deductible. With us for 12 years, no prior claims. Sent photos, an invoice and an inspection report.',
]

test('example 1: rear-end collision in Texas', () => {
  const r = read(EXAMPLES[0])
  assert.deepEqual(values(r), {
    deductible: 500,
    claim_amount: 12400,
    incident_date: '2026-03-03',
    claim_filed_date: '2026-03-07',
    state: 'TX',
    claim_type: 'auto',
    previous_claims_count: 1,
    policyholder_tenure_years: 6,
    provided_documents: ['police report', 'photos', 'repair estimate'],
  })
  assert.equal(r.theft, false)
  assert.deepEqual(r.missingDocs, [])
})

test('example 2: theft in Arizona with a missing police report', () => {
  const r = read(EXAMPLES[1])
  assert.deepEqual(values(r), {
    deductible: 1000,
    claim_amount: 24000,
    incident_date: '2026-08-14',
    claim_filed_date: '2026-09-20',
    state: 'AZ',
    claim_type: 'auto',
    previous_claims_count: 3,
    policyholder_tenure_years: 0.67,
    provided_documents: ['photos'],
  })
  assert.equal(r.theft, true)
  assert.deepEqual(r.missingDocs, ['police report'])
})

test('example 3: burst pipe in Ohio', () => {
  const r = read(EXAMPLES[2])
  assert.deepEqual(values(r), {
    deductible: 1000,
    claim_amount: 8750,
    incident_date: '2026-09-28',
    claim_filed_date: '2026-09-29',
    state: 'OH',
    claim_type: 'home',
    previous_claims_count: 0,
    policyholder_tenure_years: 12,
    provided_documents: ['photos', 'invoice', 'inspection report'],
  })
  assert.equal(r.theft, false)
})

test('the figure nearest the word deductible is the deductible, wherever it appears', () => {
  const before = values(read('Claim for $9,000 in repairs. A $250 deductible applies. Also paid $40 for a rental.'))
  assert.equal(before.deductible, 250)
  assert.equal(before.claim_amount, 9000)
  const after = values(read('The deductible is $2,500 and the insured is claiming $31,000 for the roof.'))
  assert.equal(after.deductible, 2500)
  assert.equal(after.claim_amount, 31000)
  // No mention of a deductible: the largest figure is the claim and nothing is guessed for the rest.
  const none = values(read('Windshield replacement quoted at $480 and $1,150 for the bumper.'))
  assert.equal(none.claim_amount, 1150)
  assert.equal('deductible' in none, false)
})

test('"no prior claims" reads as zero earlier claims', () => {
  assert.equal(values(read('Customer for 4 years with no prior claims.')).previous_claims_count, 0)
  assert.equal(values(read('This is her first claim with us.')).previous_claims_count, 0)
  assert.equal(values(read('He has two previous claims on file.')).previous_claims_count, 2)
})

test('negated documents are reported missing, not received', () => {
  const r = read('Photos attached, but no police report and we are still waiting for the repair estimate.')
  assert.deepEqual(values(r).provided_documents, ['photos'])
  assert.deepEqual(r.missingDocs.sort(), ['police report', 'repair estimate'])
  const without = read('The claim arrived without photos.')
  assert.equal('provided_documents' in without.fields, false)
  assert.deepEqual(without.missingDocs, ['photos'])
})

test('a document mentioned as both received and missing counts as received', () => {
  const r = read('No photos at first. Later she sent photos of the damage.')
  assert.deepEqual(values(r).provided_documents, ['photos'])
  assert.deepEqual(r.missingDocs, [])
})

test('future dates are ignored', () => {
  const r = read('Loss on 2026-03-03, and an inspection is booked for 2027-01-15. Also 12/25/2026.')
  assert.equal(values(r).incident_date, '2026-03-03')
  assert.equal('claim_filed_date' in r.fields, false)
  assert.equal('incident_date' in read('Appointment on 2099-01-01 about the damage.').fields, false)
})

test('a month and day without a year never lands in the future', () => {
  assert.equal(values(read('The tree fell on December 5 and damaged the fence.')).incident_date, '2025-12-05')
  assert.equal(values(read('The tree fell on March 5 and damaged the fence.')).incident_date, '2026-03-05')
})

test('relative dates are read against today', () => {
  const r = read('Pipe burst yesterday. Reported to us today.')
  assert.equal(values(r).incident_date, '2026-10-09')
  assert.equal(values(r).claim_filed_date, '2026-10-10')
})

test('West Virginia beats Virginia and a state code needs a leading comma or "in"', () => {
  assert.equal(values(read('Hail damage to a roof in Charleston, West Virginia last month.')).state, 'WV')
  assert.equal(values(read('Hail damage to a roof in Richmond, Virginia last month.')).state, 'VA')
  assert.equal(values(read('Garage fire in Tulsa, OK on 2026-05-01.')).state, 'OK')
  assert.equal('state' in read('The OK was given by the adjuster.').fields, false)
})

test('every value carries the words it came from', () => {
  const r = read(EXAMPLES[1])
  assert.match(r.fields.state.snip, /Arizona/)
  assert.match(r.fields.deductible.snip, /\$1,000 deductible/)
  for (const hit of Object.values(r.fields)) assert.ok(hit.snip.length > 0)
})

test('quoteIn matches the way the server does: whitespace and case insensitive', () => {
  assert.equal(quoteIn('Rear-ended at a   red light', 'RED light'), true)
  assert.equal(quoteIn('Rear-ended at a red light', 'blue light'), false)
  assert.equal(quoteIn('anything', ''), false)
})

test('text with nothing to read gives nothing', () => {
  const r = read('Something happened to the insured last week.')
  assert.deepEqual(r.fields, {})
  assert.equal(r.theft, false)
})
