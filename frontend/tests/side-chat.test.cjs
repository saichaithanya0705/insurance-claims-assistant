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
const side = require('../src/lib/sideChat.ts')
const { AnswerCard, SideChatPanel } = require('../src/components/SideChat.tsx')

const text = (html) => html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').replace(/ ([,.;:])/g, '$1').trim()

const evidence = [
  { source_id: 'claim:input', title: 'Submitted claim', text: 'x', provenance: 'user_input' },
  { source_id: 'graph:procedure:p1', title: 'Knowledge graph procedure: Police report request', text: 'x', provenance: 'synapt' },
  { source_id: 'chunk_bff73f13-3b06-4546', title: 'Synthetic auto documentation and theft procedure', text: 'x', provenance: 'synapt' },
]
const part = (over) => ({ source: 'claim', title: 'x', status: 'ok', text: '', facts: [], items: [], table: null, notes: [], cites: [], synapt: null, ...over })

const claimPart = part({ source: 'claim', text: 'Claimed amount $12,000.00.', facts: [{ label: 'Claimed amount', value: '$12,000.00' }, { label: 'Deductible', value: '$500.00' }], notes: ['As submitted; not independently verified.'], cites: ['claim:input'] })
const briefPart = part({ source: 'brief', text: '1 gap or concern to resolve.', items: [{ text: 'No incident statement has been reported.', cites: ['claim:input', 'graph:procedure:p1', 'not-in-evidence'], tag: 'gap' }] })
const historyPart = part({ source: 'history', text: 'Among 10,605 past claims, 88.9% were approved.', table: { columns: ['Past claims compared', 'Claims'], rows: [['Same description', '10,605']] }, notes: ['Computed by DuckDB.'] })
const synaptPart = part({
  source: 'synapt', title: 'From Synapt’s knowledge base', text: 'Request documents in this order:\n\n1. Incident statement\n2. Repair estimate', notes: ['Synapt marked part of the graph it used as low-confidence.'],
  cites: ['chunk_bff73f13-3b06-4546'],
  synapt: {
    confidence: { label: 'Medium', overall: 0.76, passages: 0.8, procedures: 0.87, graph: 0.62 }, trust: { degraded: true, reasons: ['low_confidence_nodes'] },
    passages: [{ chunk_id: 'chunk_bff73f13-3b06-4546', title: 'Synthetic auto documentation and theft procedure', source: 'SOP-AUTO-001', score: 0.836, in_evidence: true }, { chunk_id: 'chunk_x', title: 'Another passage', source: null, score: 0.7, in_evidence: false }],
    procedures: ['Police report request'], graph: { nodes: 25, edges: 26, by_label: { Procedure: 3, Step: 4 }, top: [{ label: 'Procedure', name: 'Police report request', relevance: 0.9 }] },
    query_id: '4af2de76-8a69-4f27-9424-2e161dd8475f', stores: ['graph', 'knowledge'], latency_ms: 725, warnings: [],
  },
})
const answer = (parts, over = {}) => ({ id: 1, asked_at: '2026-10-12T10:00:00Z', question: 'Which documents should I request?', route: { intents: ['handling'], fallback: false }, parts, notice: 'Side chat: not added to the brief and not used by the investigation.', repeat: false, ...over })
const card = (a, admin = true) => renderToStaticMarkup(React.createElement(AnswerCard, { answer: a, admin, evidence, onOpen() {}, onCopy() {} }))

// ----- wording and rules --------------------------------------------------------------------------------------------

test('each source has its own name, and only an administrator sees the vendor’s', () => {
  assert.equal(side.sourceLabel('synapt', true), 'Synapt knowledge base')
  assert.equal(side.sourceLabel('synapt', false), 'Knowledge base')
  assert.deepEqual(['claim', 'brief', 'history', 'estimates', 'evidence', 'boundary', 'outside', 'unknown'].map((s) => side.sourceLabel(s, false)),
    ['Submitted claim', 'This brief', 'Past claims · exact figures', 'Model estimates', 'Retrieved evidence', 'Decision boundary', 'Outside this tool', 'Not understood'])
  for (const source of ['claim', 'brief', 'history', 'estimates', 'evidence', 'synapt', 'boundary', 'outside']) assert.doesNotMatch(side.sourceNote(source, false), /Synapt/)
  assert.match(side.sourceNote('outside', false), /nothing was guessed/)
  assert.equal(side.sourceTone('outside'), 'neutral')
  assert.match(side.sourceNote('history', false), /No model was used/)
  assert.match(side.sourceNote('synapt', true), /not checked by the brief/)
  assert.match(side.sourceNote('synapt', false), /not checked by the brief/)
})

test('a citation is named from the evidence list, never shown as a raw identifier when a name is known', () => {
  assert.equal(side.citeLabel('claim:input', evidence), 'Submitted claim')
  assert.equal(side.citeLabel('graph:procedure:p1', evidence), 'Procedure: Police report request')
  assert.equal(side.citeLabel('chunk_bff73f13-3b06-4546', evidence), 'Synthetic auto documentation and theft procedure')
  assert.equal(side.citeLabel('history:CLM-0001'), 'Past case CLM-0001')
  assert.equal(side.citeLabel('graph:procedure:zzz'), 'Graph procedure')
  assert.equal(side.citeLabel('chunk_unknown'), 'Source passage')
  assert.equal(side.citeLabel('x'.repeat(40)), `${'x'.repeat(26)}…`)
})

test('only citations the brief also holds can be opened as evidence', () => {
  assert.deepEqual(side.openableCites(briefPart, evidence), ['claim:input', 'graph:procedure:p1'])
  assert.deepEqual(side.openableCites(historyPart, evidence), [])
})

test('a question is checked before it is sent, with a message that says what to fix', () => {
  assert.equal(side.questionProblem('  hi ', 500), 'Write a question first.')
  assert.equal(side.questionProblem('x'.repeat(501), 500), 'Keep it under 500 characters.')
  assert.equal(side.questionProblem('What is the deductible?', 500), null)
})

test('the line under an answer names every source it used, once, and says when the knowledge base was a fallback', () => {
  const mixed = answer([historyPart, synaptPart, part({ source: 'history' })])
  assert.equal(side.consultedLine(mixed, false), 'Answered from: Past claims · exact figures + Knowledge base')
  assert.equal(side.consultedLine(mixed, true), 'Answered from: Past claims · exact figures + Synapt knowledge base')
  assert.match(side.consultedLine(answer([synaptPart], { route: { intents: ['handling'], fallback: true } }), false), /no specific pattern matched, so the knowledge base was asked/)
})

test('an answer copies as plain text with its sources named and a reminder that it is not part of the brief', () => {
  const copied = side.answerAsText(answer([claimPart, historyPart]), false)
  assert.match(copied, /^Q: Which documents should I request\?/)
  assert.match(copied, /\[Submitted claim\]\nClaimed amount \$12,000\.00\.\n- Claimed amount: \$12,000\.00/)
  assert.match(copied, /Past claims compared \| Claims\nSame description \| 10,605/)
  assert.match(copied, /Note: Computed by DuckDB\./)
  assert.match(copied, /Side chat answer: not part of the investigation brief\.$/)
})

test('a failed question gets a message that says what to do', () => {
  const err = (status, message) => Object.assign(new Error(message ?? ''), { status })
  assert.match(side.askErrorMessage(err(429, 'Slow down a little: too many side questions in a minute. Try again shortly.')), /Slow down/)
  assert.match(side.askErrorMessage(err(404)), /could not be found/)
  assert.match(side.askErrorMessage(err(401)), /sign in again/)
  assert.match(side.askErrorMessage(err(500, '')), /Try again in a moment/)
  assert.equal(side.confidenceTone('High'), 'teal')
  assert.equal(side.confidenceTone('Medium'), 'amber')
  assert.equal(side.confidenceTone('Low'), 'rose')
})

// ----- rendering ----------------------------------------------------------------------------------------------------

test('a claim answer shows exact facts, its source, and the note that it is not verified', () => {
  const body = text(card(answer([claimPart])))
  assert.match(body, /You asked Which documents should I request\?/)
  assert.match(body, /Submitted claim Read from the saved claim\. No model was used\./)
  assert.match(body, /Claimed amount \$12,000\.00 Deductible \$500\.00/)
  assert.match(body, /As submitted; not independently verified\./)
})

test('a brief answer lists what the brief says with only the citations that can be opened', () => {
  const html = card(answer([briefPart]))
  assert.match(text(html), /gap No incident statement has been reported\. Submitted claim Procedure: Police report request/)
  assert.doesNotMatch(html, /not-in-evidence/)
  assert.equal((html.match(/class="side-cite"/g) || []).length, 4) // two beside the item, two under "Evidence behind this"
})

test('past-claim figures render as a table with the source named', () => {
  const html = card(answer([historyPart]))
  assert.match(html, /<table class="side-table"/)
  assert.match(text(html), /Past claims compared Claims Same description 10,605/)
  assert.match(text(html), /Computed by the full dataset|Exact statistics from the full dataset, computed by DuckDB/)
})

test('the knowledge base’s answer keeps its own formatting and shows its confidence, passages, procedures and graph', () => {
  const html = card(answer([synaptPart]), true)
  const body = text(html)
  assert.match(html, /class="side-text">1\. Incident statement\n2\. Repair estimate/)
  assert.match(body, /Confidence: Medium 0\.76 overall · knowledge store 0\.80 · procedure store 0\.87 · context graph 0\.62/)
  assert.match(body, /Passages it used Synthetic auto documentation and theft procedure · SOP-AUTO-001 · 0\.84/)
  assert.match(body, /Procedures it found Police report request/)
  assert.match(body, /25 nodes and 26 connections: 3 procedure, 4 step\./)
  assert.match(body, /How it was answered Query ID \(shown in Synapt’s Explainability\) 4af2de76/)
  assert.equal((html.match(/class="side-cite"/g) || []).length, 1) // only the passage the brief also holds can be opened
})

test('everyone but an administrator gets the knowledge base without the vendor name, scores or query ID', () => {
  const stripped = JSON.parse(JSON.stringify(synaptPart))
  stripped.title = 'From the knowledge base'
  stripped.notes = ['The knowledge base marked part of the graph it used as low-confidence.']
  stripped.synapt = { confidence: { label: 'Medium' }, passages: stripped.synapt.passages.map(({ score, ...c }) => c), procedures: ['Police report request'], graph: stripped.synapt.graph, warnings: [] }
  const html = card(answer([stripped]), false)
  const body = text(html)
  assert.match(body, /Knowledge base Written by the knowledge base from its own passages/)
  assert.match(body, /Confidence: Medium(?! \d)/)
  assert.doesNotMatch(html, /Synapt|0\.76|query|4af2de76|How it was answered/)
})

test('a declined or unavailable part says so and a repeated question says it is the saved answer', () => {
  const body = text(card(answer([part({ source: 'boundary', status: 'declined', text: 'A human claims handler decides.' }), part({ source: 'synapt', status: 'unavailable', text: 'The knowledge base could not answer this right now.' })], { repeat: true }), false))
  assert.match(body, /Decision boundary Declined/)
  assert.match(body, /Knowledge base Not available/)
  assert.match(body, /You asked this before; this is the saved answer\./)
})

const run = { run_id: 'r1', evidence }
const panel = (props = {}) => renderToStaticMarkup(React.createElement(SideChatPanel, { run, admin: false, open: true, onClose() {}, onOpenSource() {}, ...props }))

test('the panel says plainly that it is not part of the investigation and is a non-modal dialog', () => {
  const html = panel()
  assert.match(html, /role="dialog" aria-modal="false" aria-labelledby="side-title"/)
  assert.match(text(html), /Ask on the side About this claim\. Not part of the investigation: nothing here changes the brief, its evidence or its checks\./)
  assert.match(html, /aria-label="Your question"/)
  assert.match(text(html), /Enter to send · Shift\+Enter for a new line · Don’t type names or ID numbers; they are masked before anything is sent\. 500/)
  assert.match(html, /role="log" aria-live="polite"/)
  assert.doesNotMatch(html, /Synapt/)
})

test('a closed panel is hidden, not removed, so a draft and the thread survive', () => {
  assert.match(panel({ open: false }), /<aside id="side-panel"[^>]* hidden=""/)
  assert.doesNotMatch(panel({ open: true }), / hidden=""/)
})

// ----- wiring -------------------------------------------------------------------------------------------------------

test('the run view opens the side chat from a button, from Alt+B and from the mobile bar, and only mounts it once used', () => {
  const results = fs.readFileSync(require.resolve('../src/components/Results.tsx'), 'utf8')
  assert.match(results, /Ask on the side/)
  assert.match(results, /e\.altKey && !e\.ctrlKey && !e\.metaKey && e\.code === 'KeyB'/)
  assert.match(results, /\{sideMounted && <SideChatPanel run=\{run\} admin=\{admin\} open=\{sideOpen\}/)
  assert.match(results, /onClick=\{toggleSide\}>Ask<\/button>/)
  const component = fs.readFileSync(require.resolve('../src/components/SideChat.tsx'), 'utf8')
  assert.match(component, /requested\.current/) // the history is fetched once, the first time it opens
  assert.match(component, /e\.key === 'Escape'/)
})
