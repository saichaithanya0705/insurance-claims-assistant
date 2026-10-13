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
const { KnowledgeGraphPanel } = require('../src/components/KnowledgeGraphPanel.tsx')
const { appliesLabel, callSummary, hitOutcome, shortChunk } = require('../src/lib/graphView.ts')

const text = (html) => html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').replace(/ ([,.;])/g, '$1').trim()

const police = {
  source_id: 'graph:procedure:145aa149', node_id: 'n1', name: 'Police report request', score: 0.934, applies_because: 'theft',
  intent: 'Request a police report for theft claims when applicable.',
  steps: [
    { number: 2, text: 'Confirm the relevance of the police report with the handler.', needs: 'The police report has been requested.', who: 'Claims support or intake staff' },
    { number: 1, text: 'Request a police report when the claim involves theft.', needs: 'A theft claim has been identified.', who: null },
  ],
  entities: [{ label: 'Human claims handler review', kind: 'Workflow', description: 'A required human review step.', confidence: 0.97 }],
  source_chunk_ids: ['chunk_bff73f13-3b06-4546-82c1-378c46c25365'],
}
const graph = {
  available: true, calls: 5, procedures: [police, { ...police, source_id: 'graph:procedure:2', name: 'Human claims handler review', applies_because: 'general', entities: [], source_chunk_ids: [] }],
  searches: [
    { scope: 'claim_type', query: 'Synthetic auto claim documentation procedure', found: [
      { name: 'Synthetic business loss documentation procedure', score: 0.882, used: false, applies_because: null },
      { name: 'Police report request', score: 0.934, used: true, applies_because: 'theft' },
    ] },
    { scope: 'general', query: 'Document tracking and human claims handler review', found: [] },
  ],
}
const render = (g, extra = {}) => renderToStaticMarkup(React.createElement(KnowledgeGraphPanel, { graph: g, claimType: 'auto', onOpen() {}, ...extra }))

test('no graph on the run, no panel: older runs and runs that never reached Synapt show nothing', () => {
  assert.equal(render(null), '')
  assert.equal(render(undefined), '')
})

test('an unavailable graph says so and gives the reason instead of showing an empty panel', () => {
  const html = render({ available: false, reason: 'The Synapt knowledge-graph lookup failed for this claim; handling guidance uses passages only.', procedures: [], searches: [], calls: 0 })
  assert.match(text(html), /knowledge graph was not read for this run: The Synapt knowledge-graph lookup failed/)
  assert.doesNotMatch(html, /kg-procedure/)
})

test('each procedure shows its steps in order, who does them, what comes first, its links and its source passage', () => {
  const html = render(graph)
  const body = text(html)
  assert.match(body, /Handling procedures from the Synapt knowledge graph/)
  assert.equal((html.match(/data-testid="kg-procedure"/g) || []).length, 2)
  const first = body.indexOf('Request a police report when the claim involves theft.')
  assert.ok(first > 0 && first < body.indexOf('Confirm the relevance of the police report'), 'steps are sorted by number')
  assert.match(body, /Needs first: A theft claim has been identified\./)
  assert.match(body, /Done by: Claims support or intake staff/)
  assert.match(body, /Linked in the graph Workflow Human claims handler review/)
  assert.match(body, /Extracted from passage chunk_bff73f13-3b0…/)
  assert.match(body, /Theft claims/)
  assert.match(body, /General handling, applies to every claim/)
})

test('a procedure with no linked entities or source passage renders without those sections', () => {
  const body = text(render({ ...graph, procedures: [graph.procedures[1]] }))
  assert.doesNotMatch(body, /Linked in the graph/)
  assert.doesNotMatch(body, /Extracted from passage/)
})

test('a search hit that was set aside says why, so nothing looks silently dropped', () => {
  const body = text(render(graph))
  assert.match(body, /Synthetic business loss documentation procedure · score 0\.88 Set aside: written for another claim type/)
  assert.match(body, /Police report request · score 0\.93 Used/)
  assert.match(body, /Nothing found/)
  assert.match(body, /5 read-only calls to Synapt \(trident_search ×2, trident_traverse ×3\)\. Nothing was written\./)
})

test('labels are plain words, never raw codes', () => {
  assert.equal(appliesLabel('claim_type', 'auto'), 'Written for auto claims')
  assert.equal(appliesLabel('claim_type', null), 'Written for this claim type')
  assert.equal(appliesLabel('theft'), 'Theft claims')
  assert.equal(hitOutcome({ name: 'x', score: null, used: false, applies_because: 'general' }), 'Not walked: already found by another search, or the limit was reached')
  assert.equal(callSummary({ ...graph, calls: 1, searches: [] }), '1 read-only call to Synapt (trident_search ×0, trident_traverse ×1). Nothing was written.')
  assert.equal(shortChunk('chunk_bff73f13-3b06-4546-82c1-378c46c25365'), 'chunk_bff73f13-3b0…')
  assert.equal(shortChunk('chunk_short'), 'chunk_short')
})

test('the Evidence tab mounts the panel above the library', () => {
  const source = fs.readFileSync(require.resolve('../src/components/Results.tsx'), 'utf8')
  assert.match(source, /<KnowledgeGraphPanel graph=\{run\.graph\}[^>]*\/>\s*<EvidencePanel/)
})

test('a condition-based procedure says in plain words what condition it is for', () => {
  const labels = {
    late_filing: 'Late-filed claims', large_loss: 'Large losses', repeat_claimant: 'Repeat claimants',
    new_policyholder: 'New policyholders', water_damage: 'Water damage', theft: 'Theft claims', fraud_signal: 'Fraud-flag review signal',
  }
  for (const [reason, words] of Object.entries(labels)) assert.equal(appliesLabel(reason), words)
  assert.equal(appliesLabel('general'), 'General handling, applies to every claim')
  assert.equal(appliesLabel('claim_type', 'home'), 'Written for home claims')
  assert.equal(
    hitOutcome({ name: 'x', score: 0.8, used: false, applies_because: null }),
    'Set aside: written for another claim type, or for a condition this claim does not meet',
  )
})

test('the conditions the claim meets are listed above the procedures so a reader sees why each conditional one is there', () => {
  const withCues = {
    ...graph,
    cues: [
      { key: 'late_filing', label: 'Filed more than 30 days after the incident' },
      { key: 'large_loss', label: 'Claimed amount of $50,000 or more' },
    ],
    procedures: [{ ...police, source_id: 'graph:procedure:late', name: 'Synthetic late-filed claim review procedure', applies_because: 'late_filing' }],
  }
  const html = render(withCues)
  const body = text(html)
  assert.match(body, /This claim meets Filed more than 30 days after the incident Claimed amount of \$50,000 or more/)
  assert.match(body, /Synthetic late-filed claim review procedure Late-filed claims/)
  assert.ok(html.indexOf('kg-cues') < html.indexOf('kg-procedure'))
  assert.doesNotMatch(render({ ...graph, cues: [] }), /kg-cues/)
  assert.doesNotMatch(render(graph), /This claim meets/)
})

test('what a model added after the standard searches is said in one sentence, and the read-only call count includes its searches', () => {
  const { followUpLine, callSummary: summary } = require('../src/lib/graphView.ts')
  const base = { available: true, procedures: [], searches: [{ scope: 'claim_type', query: 'q', found: [] }], calls: 6, tools: [], edge_types: [] }
  assert.equal(followUpLine(base), null)
  assert.equal(followUpLine({ ...base, followup: { searches: [], read: [], rounds: 1 } }), null)
  const found = { ...base, followup: { searches: [{ query: 'water damage documentation', found: 3, fitting: 2 }], read: ['Home water damage procedure'], rounds: 2 } }
  assert.match(followUpLine(found), /A model also searched for “water damage documentation” and read one more procedure: Home water damage procedure\./)
  assert.match(followUpLine({ ...found, followup: { ...found.followup, read: [] } }), /nothing new fit this claim/)
  // 1 standard search + 1 model search = 2 searches, so 6 calls are 2 searches and 4 walks
  assert.match(summary(found), /trident_search ×2, trident_traverse ×4/)
})
