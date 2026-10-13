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
const { BriefPreviewView } = require('../src/components/BriefPreview.tsx')
const { previewParts, queryLine } = require('../src/lib/preview.ts')

const text = (html) => html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').replace(/ ([,.;:])/g, '$1').trim()

const retrieval = {
  passages: 5, procedures: ['Police report request', 'Late-filed claim review'], similar_total: 8,
  similar_cases: [{ claim_type: 'auto', state: 'TX', claim_amount: 9000.4, claim_status: 'approved', days_to_resolution: 12 }],
  cohort: '1,913 past claims with the same description, 88.9% approved, median 12 days to settle',
  query_agent: { state: 'pending', question: 'Q?' },
}
const base = { run_id: 'r', status: 'running', stages: ['classify', 'retrieve'], claim_type: 'auto', retrieval, findings: null, priority: null, recommendations: null }

test('nothing is shown until retrieval has finished, then each part appears as its stage lands', () => {
  assert.deepEqual(previewParts(null), [])
  assert.deepEqual(previewParts({ ...base, retrieval: null }), [])
  assert.deepEqual(previewParts(base).map((p) => p.key), ['search'])
  const withFindings = { ...base, stages: [...base.stages, 'investigate'], findings: [{ kind: 'gap', text: 'No police report' }] }
  assert.deepEqual(previewParts(withFindings).map((p) => p.key), ['search', 'findings'])
  const all = { ...withFindings, priority: { tier: 'medium', score: 25, reasons: ['Claimed amount is at least $10,000'] }, recommendations: [{ action: 'Request focused clarification or evidence', reason: 'Ask for it' }] }
  assert.deepEqual(previewParts(all).map((p) => p.key), ['search', 'findings', 'priority', 'recommendations'])
  assert.match(previewParts(all)[2].summary, /^Medium \(25\/100\)\. It only orders handler attention/)
})

test('the search section lists what was found with the exact past-claim figures, and says it is not the brief', () => {
  const html = renderToStaticMarkup(React.createElement(BriefPreviewView, { preview: base, admin: false }))
  const t = text(html)
  assert.match(t, /Coming together/)
  assert.match(t, /This is not the brief yet: it has not been completed, checked or reviewed/)
  assert.match(t, /Found 5 passages, 2 procedures, 8 closest past claims\./)
  assert.match(t, /Police report request/)
  assert.match(t, /1,913 past claims with the same description, 88\.9% approved, median 12 days to settle/)
  assert.match(t, /auto in TX, \$9,000, approved in 12 days/)
  assert.doesNotMatch(t, /Findings so far/)  // not landed yet, so not shown
})

test('findings, priority and actions are shown once they have landed', () => {
  const all = {
    ...base, findings: [{ kind: 'gap', text: 'No police report has been reported as available.' }],
    priority: { tier: 'high', score: 55, reasons: ['Claimed amount $118,000 is at least $100,000'] },
    recommendations: [{ action: 'Request focused clarification or evidence', reason: 'Ask for the police report.' }],
  }
  const t = text(renderToStaticMarkup(React.createElement(BriefPreviewView, { preview: all, admin: false })))
  assert.match(t, /Findings so far gap No police report has been reported as available\./)
  assert.match(t, /Handling priority High \(55\/100\)/)
  assert.match(t, /Claimed amount \$118,000 is at least \$100,000/)
  assert.match(t, /Recommended actions Request focused clarification or evidence: Ask for the police report\./)
})

test('the query agent line is plain for a person and names the vendor only for an administrator', () => {
  const pending = { state: 'pending', question: 'Q?' }
  assert.equal(queryLine(pending, false), 'The knowledge base is still writing its answer; it will appear in the brief.')
  assert.equal(queryLine(pending, true), 'Synapt’s query agent is still writing its answer; it will appear in the brief.')
  assert.match(queryLine({ state: 'answered' }, false), /^The knowledge base has answered/)
  assert.match(queryLine({ state: 'unavailable' }, false), /did not answer for this run; the brief does not depend on it\.$/)
  const person = text(renderToStaticMarkup(React.createElement(BriefPreviewView, { preview: base, admin: false })))
  assert.doesNotMatch(person, /Synapt/)
  assert.match(text(renderToStaticMarkup(React.createElement(BriefPreviewView, { preview: base, admin: true }))), /Synapt’s query agent is still writing/)
})

test('an empty or missing preview renders nothing', () => {
  assert.equal(renderToStaticMarkup(React.createElement(BriefPreviewView, { preview: null, admin: false })), '')
  assert.equal(renderToStaticMarkup(React.createElement(BriefPreviewView, { preview: { ...base, retrieval: null }, admin: false })), '')
})
