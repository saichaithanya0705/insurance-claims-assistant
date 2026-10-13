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
const { SynaptStatsView } = require('../src/components/SynaptStatsCard.tsx')
const { statNote, statTiles } = require('../src/lib/synaptStats.ts')

const text = (html) => html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()

const STATS = {
  available: true, provider_id: 'synapt_capstone1', kind: 'knowledge', has_ticket_store: false,
  documents: 38, passages: 10038, graph_nodes: 10314, connections: 10598, procedures: 21, steps: 93, entities: 117, concepts: 6,
  knowledge_by_kind: [{ kind: 'Step', count: 93 }, { kind: 'Procedure', count: 21 }],
  episodes: { store_exists: true, count: 1 }, fetched_at: '2026-10-12T09:30:00+00:00',
}

test('the tiles carry the provider figures in a fixed reading order, with thousands separators', () => {
  const tiles = statTiles(STATS)
  assert.deepEqual(tiles.map((t) => t.label), ['Documents', 'Passages', 'Graph nodes', 'Connections', 'Procedures', 'Steps', 'Entities', 'Episodes'])
  const value = Object.fromEntries(tiles.map((t) => [t.label, t.value]))
  assert.equal(value.Passages, '10,038')
  assert.equal(value.Connections, '10,598')
  assert.equal(value.Steps, '93')
  assert.equal(value.Episodes, '1')
  assert.ok(tiles.every((t) => t.hint.length > 0))
})

test('a figure the response did not carry is a dash, never a made-up zero', () => {
  const value = Object.fromEntries(statTiles({ available: true, documents: null, episodes: null }).map((t) => [t.label, t.value]))
  assert.equal(value.Documents, '—')
  assert.equal(value.Steps, '—')
  assert.equal(value.Episodes, '—')
  const none = Object.fromEntries(statTiles({ available: true, episodes: { store_exists: false, count: null } }).map((t) => [t.label, t.value]))
  assert.equal(none.Episodes, '0')
})

test('the note says what kind of provider it is, whether it has tickets, and warns when the figures are old', () => {
  assert.match(statNote(STATS), /^knowledge provider · no ticket store · read \d{2}:\d{2}/)
  assert.match(statNote({ ...STATS, has_ticket_store: true }), /ticket store present/)
  assert.match(statNote({ ...STATS, stale: true }), /last known figures — Synapt could not be reached just now$/)
  assert.equal(statNote({ available: true }), 'no ticket store')
})

test('the card shows the figures, the knowledge kinds and the provider id', () => {
  const html = renderToStaticMarkup(React.createElement(SynaptStatsView, { stats: STATS, loading: false }))
  const t = text(html)
  assert.match(t, /Knowledge base contents/)
  assert.match(t, /synapt_capstone1/)
  assert.match(t, /Documents 38/)
  assert.match(t, /Passages 10,038/)
  assert.match(t, /Step 93/)
  assert.match(t, /Procedure 21/)
})

test('while loading it shows a placeholder, and an unavailable provider is a sentence, not an error box', () => {
  assert.match(renderToStaticMarkup(React.createElement(SynaptStatsView, { stats: null, loading: true })), /Loading knowledge base contents/)
  const down = renderToStaticMarkup(React.createElement(SynaptStatsView, { stats: { available: false, reason: 'Synapt could not be reached just now.' }, loading: false }))
  assert.match(text(down), /Synapt could not be reached just now\./)
  assert.doesNotMatch(down, /role="alert"/)
  assert.match(text(renderToStaticMarkup(React.createElement(SynaptStatsView, { stats: null, loading: false }))), /unavailable/)
})
