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
const { QueryAgentPanel } = require('../src/components/QueryAgentPanel.tsx')

const text = (html) => html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').replace(/ ([,.;:])/g, '$1').trim()
const evidence = [{ source_id: 'chunk_bff73f13', title: 'Synthetic auto documentation and theft procedure', text: 'x', provenance: 'synapt' }]
const QUESTION = 'For an auto claim involving theft, which documents should a claims handler request and in what order, who is responsible for each step, and what must a human claims handler review before any decision?'
const RUN_ID = '11111111-1111-4111-8111-111111111111'
const adminPart = {
  source: 'synapt', title: 'From Synapt’s knowledge base', status: 'ok', facts: [], items: [], table: null, cites: ['chunk_bff73f13'],
  text: 'Request documents in this order:\n\n1. Incident statement\n2. Police report', notes: [],
  synapt: {
    confidence: { label: 'High', overall: 0.76, passages: 0.8, procedures: 0.87, graph: 0.62 }, trust: { degraded: false, reasons: [] },
    passages: [{ chunk_id: 'chunk_bff73f13', title: 'Synthetic auto documentation and theft procedure', source: 'SOP-AUTO-001', score: 0.836, in_evidence: true }],
    procedures: ['Police report request'], graph: { nodes: 25, edges: 26, by_label: { Procedure: 3 }, top: [] },
    query_id: '4af2de76-8a69-4f27-9424-2e161dd8475f', task_id: RUN_ID, stores: ['graph'], latency_ms: 725, warnings: [],
  },
}
const userPart = JSON.parse(JSON.stringify(adminPart))
userPart.title = 'From the knowledge base'
userPart.synapt = { confidence: { label: 'High' }, passages: userPart.synapt.passages.map(({ score, ...c }) => c), procedures: ['Police report request'], graph: adminPart.synapt.graph, warnings: [] }

const render = (queryAgent, admin = true) => renderToStaticMarkup(React.createElement(QueryAgentPanel, { queryAgent, admin, evidence, onOpen() {} }))

test('no query agent on the run, no panel: older runs and runs that made no call show nothing', () => {
  assert.equal(render(null), '')
  assert.equal(render(undefined), '')
})

test('an unavailable answer says so in one sentence and that the brief does not depend on it', () => {
  const admin = text(render({ available: false, reason: 'The Synapt query agent did not answer for this claim; the brief does not depend on it.', question: null, part: null }))
  assert.match(admin, /Synapt query agent did not answer for this run: The Synapt query agent did not answer for this claim/)
  assert.match(admin, /The brief does not depend on it\.$/)
  const person = text(render({ available: false, reason: 'The knowledge base query agent did not answer for this claim; the brief does not depend on it.', question: null, part: null }, false))
  assert.doesNotMatch(person, /Synapt/)
  assert.match(person, /^Knowledge base did not answer for this run/)
})

test('an administrator sees the exact question, what was and was not sent, the answer and how to find the call in Synapt', () => {
  const html = render({ available: true, question: QUESTION, part: adminPart, task_id: RUN_ID })
  const body = text(html)
  assert.match(body, /Synapt query agent: how to handle this kind of claim/)
  assert.match(body, /Synapt’s query agent was asked one fixed question about this claim type/)
  assert.match(body, /The brief’s findings do not use it and its validation does not check it\./)
  assert.ok(body.includes(`What was asked ${QUESTION}`), 'the exact question that was sent is shown')
  assert.match(body, /Sent: the claim type only\. The description, names, amounts and dates never leave this application\./)
  assert.match(html, /class="side-text">1\. Incident statement\n2\. Police report/)
  assert.match(body, /Confidence: High 0\.76 overall · knowledge store 0\.80 · procedure store 0\.87 · context graph 0\.62/)
  assert.match(body, /Find this call in Synapt Explainability, then search for query ID 4af2de76-8a69-4f27-9424-2e161dd8475f\. Its task ID is this run’s ID, 11111111-1111-4111-8111-111111111111\./)
  assert.equal((html.match(/class="side-cite"/g) || []).length, 1) // the one passage the brief also holds, beside its entry in "Passages it used"
})

test('everyone but an administrator gets the answer with no vendor name, scores, query ID or task ID', () => {
  const html = render({ available: true, question: QUESTION, part: userPart }, false)
  const body = text(html)
  assert.match(body, /Knowledge base: how to handle this kind of claim/)
  assert.match(body, /The knowledge base was asked one fixed question/)
  assert.match(body, /Request documents in this order/)
  assert.match(body, /Confidence: High(?! \d)/)
  assert.doesNotMatch(html, /Synapt|4af2de76|11111111|0\.76|0\.87|Find this call|query ID|task ID/)
})

test('the Evidence tab shows the query agent first, above the graph and the library', () => {
  const results = fs.readFileSync(require.resolve('../src/components/Results.tsx'), 'utf8')
  assert.match(results, /<QueryAgentPanel queryAgent=\{run\.query_agent\}[^>]*\/>\s*<KnowledgeGraphPanel[^>]*\/>\s*<EvidencePanel/)
})

test('a slow answer shows what was asked and says the brief did not wait, then the real answer replaces it', () => {
  const waiting = { available: false, pending: true, reason: null, question: QUESTION, part: null, task_id: RUN_ID }
  const admin = text(render(waiting))
  assert.match(admin, /Synapt query agent: how to handle this kind of claim/)
  assert.match(admin, /Synapt’s query agent is still writing its answer\. The brief did not wait for it/)
  assert.ok(admin.includes(QUESTION))
  assert.doesNotMatch(admin, /did not answer/)  // waiting is not failing
  assert.match(render(waiting), /aria-busy="true"/)
  const person = text(render({ ...waiting, task_id: undefined }, false))
  assert.doesNotMatch(person, /Synapt|task|query ID/i)
  assert.match(person, /The knowledge base is still writing its answer/)
  // once the answer arrives the same panel shows it, with no waiting text left
  const arrived = text(render({ available: true, question: QUESTION, part: adminPart, task_id: RUN_ID }))
  assert.doesNotMatch(arrived, /still writing/)
  assert.match(arrived, /Incident statement/)
})

test("the query agent's markdown bold is shown as bold, and anything else in the answer stays plain text", () => {
  const part = { ...adminPart, text: '1. **Request the core documents**\n- <b>not html</b> and a lone ** stays' }
  const html = render({ available: true, question: QUESTION, part, task_id: RUN_ID })
  assert.match(html, /<strong>Request the core documents<\/strong>/)
  assert.doesNotMatch(html, /\*\*Request/)
  assert.match(html, /&lt;b&gt;not html&lt;\/b&gt; and a lone \*\* stays/)
})
