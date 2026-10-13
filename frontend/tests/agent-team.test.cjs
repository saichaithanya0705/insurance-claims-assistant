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
const live = require('../src/lib/liveProgress.ts')
const team = require('../src/lib/agentTeam.ts')
const { AgentTeamView } = require('../src/components/AgentTeam.tsx')
const { LiveActivityView } = require('../src/components/LiveActivity.tsx')

const text = (html) => html.replace(/<!-- -->/g, '').replace(/&amp;/g, '&').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').replace(/ ([,.;])/g, '$1').trim()

const agent = (id, name, stage, method, canUse = [], kind = 'agent') => ({
  id, name, kind, method, stage, purpose: `${name} does its part.`, cannot: '', can_use: canUse,
})
const ROSTER = [
  agent('triage', 'Claim Triage Agent', 'classify', 'model'),
  agent('passage_retriever', 'Policy Passage Retriever', 'retrieve', 'rules', ['Knowledge-base passage search']),
  agent('graph_navigator', 'Procedure Graph Navigator', 'retrieve', 'rules', ['Knowledge-base search', 'Knowledge-graph walk']),
  agent('knowledge_qa', 'Knowledge Q&A Agent', 'retrieve', 'rules', ['Knowledge-base question answering']),
  agent('judge', 'Independent Judge', 'judge', 'model'),
  agent('operator', 'Operator', '', 'none', ['Knowledge-base statistics'], 'system'),
]

let seq = 0
const span = (id, parent, kind, label, status, startedMs, durationMs = null, extra = {}) => ({
  id, parent, kind, name: kind === 'stage' ? extra.name : null, label, detail: null, result: null, status,
  started_ms: startedMs, duration_ms: status === 'running' ? null : durationMs, background: false, agent: null, seq: ++seq, ...extra,
})
const progress = (spans, over = {}) => ({
  run_id: 'r', state: 'running', outcome: null, now_ms: 9000, running_ms: 100, next: seq, truncated: false, spans,
  counts: { knowledge_calls: 2, model_calls: 1, open: 2 }, ...over,
})
const view = (spans, over = {}) => live.applyProgress(live.emptyView(), progress(spans, over), 1000)

const RUN = span('root', null, 'run', 'Investigation', 'running', 0)
const CLASSIFY = span('c', 'root', 'stage', 'Classify the claim', 'ok', 100, 900, { name: 'classify' })
const RETRIEVE = span('r', 'root', 'stage', 'Gather evidence and compare past claims', 'running', 1000, null, { name: 'retrieve' })
const TRIAGE = span('a1', 'c', 'agent', 'Claim Triage Agent', 'ok', 120, 800, { agent: 'triage', result: 'Done' })
const PASSAGES = span('a2', 'r', 'agent', 'Policy Passage Retriever', 'running', 1010, null, { agent: 'passage_retriever' })
const SEARCH = span('s2', 'a2', 'tool', 'Look up handling procedures', 'running', 1500, null, { agent: 'passage_retriever' })
const GRAPH = span('a3', 'r', 'agent', 'Procedure Graph Navigator', 'ok', 1010, 3000, { agent: 'graph_navigator', result: '2 tool calls' })
const WALK = span('s3', 'a3', 'tool', 'Walk a procedure\'s steps in the graph', 'ok', 1200, 800, { agent: 'graph_navigator' })

const cards = (spans, over, now = 5000) => Object.fromEntries(team.agentCards(view(spans, over), ROSTER, now).map((c) => [c.agent.id, c]))

test('an agent is working only while a step of its own is open, and done once its steps closed', () => {
  const c = cards([RUN, CLASSIFY, RETRIEVE, TRIAGE, PASSAGES, SEARCH, GRAPH, WALK])
  assert.equal(c.triage.state, 'done')
  assert.equal(c.passage_retriever.state, 'working')
  assert.equal(c.graph_navigator.state, 'done')
  assert.equal(c.knowledge_qa.state, 'waiting') // no step yet
  assert.equal(c.judge.state, 'waiting')
})

test('agents that gather evidence at the same moment are shown working together', () => {
  const asking = span('a4', 'r', 'agent', 'Knowledge Q&A Agent', 'running', 1015, null, { agent: 'knowledge_qa' })
  const walking = span('a5', 'r', 'agent', 'Procedure Graph Navigator', 'running', 1012, null, { agent: 'graph_navigator' })
  const c = cards([RUN, RETRIEVE, PASSAGES, asking, walking])
  assert.deepEqual(['passage_retriever', 'graph_navigator', 'knowledge_qa'].map((id) => c[id].state), ['working', 'working', 'working'])
  assert.deepEqual(team.teamSummary(Object.values(c)), { working: 3, done: 0, total: 5 })
})

test('a card says what its agent is doing now, what it finished with, and how many steps it took', () => {
  const c = cards([RUN, CLASSIFY, RETRIEVE, TRIAGE, PASSAGES, SEARCH, GRAPH, WALK])
  assert.equal(c.passage_retriever.doing, 'Look up handling procedures')
  assert.equal(c.passage_retriever.steps, 1)
  assert.equal(c.graph_navigator.doing, null)
  assert.equal(c.graph_navigator.result, '2 tool calls')
  assert.equal(c.graph_navigator.steps, 1)
})

test('time is the server clock carried forward for a running agent and the real duration for a finished one', () => {
  const c = cards([RUN, RETRIEVE, PASSAGES, GRAPH], undefined, 1000) // the browser clock has not moved since the answer arrived
  assert.equal(c.graph_navigator.elapsedMs, 3000)
  assert.equal(Math.round(c.passage_retriever.elapsedMs), 9000 - 1010) // the server said it was 9000 ms into the run
  const later = cards([RUN, RETRIEVE, PASSAGES, GRAPH], undefined, 3000) // two more seconds in the browser
  assert.equal(Math.round(later.passage_retriever.elapsedMs), 11000 - 1010)
})

test('when the run has ended an agent that never started did not run, and a failed one says so', () => {
  const failed = span('a6', 'r', 'agent', 'Policy Passage Retriever', 'error', 1010, 400, { agent: 'passage_retriever' })
  const c = cards([RUN, RETRIEVE, TRIAGE, failed], { state: 'done' })
  assert.equal(c.judge.state, 'skipped')
  assert.equal(c.knowledge_qa.state, 'skipped')
  assert.equal(c.passage_retriever.state, 'failed')
})

test('the independent review is shown as running in the background', () => {
  const judge = span('a7', 'r', 'agent', 'Independent Judge', 'running', 6000, null, { agent: 'judge', background: true })
  assert.equal(cards([RUN, judge]).judge.state, 'background')
})

test('only investigation agents are on the team; the operator and the reviewer are not', () => {
  assert.deepEqual(team.teamOf(ROSTER).map((a) => a.id), ['triage', 'passage_retriever', 'graph_navigator', 'knowledge_qa', 'judge'])
})

test('what an agent can use is said in plain words, and an agent with no tools says so', () => {
  assert.equal(team.canUseLine(ROSTER[0]), 'Holds no tools')
  assert.equal(team.canUseLine(ROSTER[2]), 'Can use: Knowledge-base search, Knowledge-graph walk')
  assert.equal(team.methodWord(ROSTER[0]), 'Language model')
  assert.equal(team.methodWord(ROSTER[1]), 'Fixed rules')
})

test('the team panel lists every agent with its state, role, current step and tools', () => {
  const html = renderToStaticMarkup(React.createElement(AgentTeamView, { view: view([RUN, CLASSIFY, RETRIEVE, TRIAGE, PASSAGES, SEARCH, GRAPH, WALK]), roster: ROSTER, now: 5000 }))
  const body = text(html)
  for (const name of ['Claim Triage Agent', 'Policy Passage Retriever', 'Procedure Graph Navigator', 'Knowledge Q&A Agent', 'Independent Judge']) assert.ok(body.includes(name), name)
  assert.ok(!body.includes('Operator'))
  assert.equal((html.match(/data-testid="agent-card"/g) ?? []).length, 5)
  assert.match(html, /data-agent="passage_retriever" data-state="working"/)
  assert.match(html, /data-agent="triage" data-state="done"/)
  assert.ok(body.includes('Look up handling procedures'))
  assert.ok(body.includes('Holds no tools') && body.includes('Can use: Knowledge-base passage search'))
  assert.ok(body.includes('1 working now') || body.includes('1 working now ·'))
  assert.ok(body.includes('2 of 5 done') || body.includes('1 of 5 done'))
})

test('the live page shows the team when it has the roster, and its step list does not repeat the agents', () => {
  const v = view([RUN, CLASSIFY, RETRIEVE, TRIAGE, PASSAGES, SEARCH])
  const withTeam = renderToStaticMarkup(React.createElement(LiveActivityView, { view: v, now: 5000, wall: 20_000, startedAt: 10_000, admin: false, roster: ROSTER }))
  const without = renderToStaticMarkup(React.createElement(LiveActivityView, { view: v, now: 5000, wall: 20_000, startedAt: 10_000, admin: false }))
  assert.match(withTeam, /data-testid="agent-team"/)
  assert.doesNotMatch(without, /data-testid="agent-team"/)
  // the steps list shows the step, not a row for the agent that took it
  const rows = (html) => (html.match(/data-testid="live-row"/g) ?? []).length
  assert.equal(rows(withTeam), 1)
  assert.equal(rows(without), 1)
})

// ----- a finished run, one lane per agent ---------------------------------------------------------------------------------

const lanes = require('../src/lib/agentLanes.ts')
const ran = (id, over = {}) => ({ id, name: id, method: 'rules', stage: 'retrieve', purpose: '', ran: true, status: 'ok', started_ms: 0, duration_ms: 1000, tool_calls: 0, refused: 0, tokens: 0, ...over })

test('agents that worked at the same time get overlapping lanes, and one that did not run gets none', () => {
  const result = lanes.swimlanes([
    ran('triage', { started_ms: 0, duration_ms: 1000, method: 'model', tokens: 150 }),
    ran('passage_retriever', { started_ms: 1000, duration_ms: 3000, tool_calls: 2 }),
    ran('graph_navigator', { started_ms: 1000, duration_ms: 2000, tool_calls: 5 }),
    { id: 'knowledge_qa', name: 'knowledge_qa', method: 'rules', stage: 'retrieve', purpose: '', ran: false },
  ])
  const by = Object.fromEntries(result.map((l) => [l.id, l]))
  assert.equal(by.passage_retriever.left, by.graph_navigator.left) // they began together
  assert.ok(by.passage_retriever.width > by.graph_navigator.width)
  assert.ok(by.passage_retriever.left + by.passage_retriever.width <= 100.0001)
  assert.equal(by.triage.left, 0)
  assert.equal(by.knowledge_qa.ran, false)
  assert.equal(by.graph_navigator.toolLine, '5 tool calls')
  assert.equal(by.triage.toolLine, 'no tool calls')
})

test('a refused call is counted for everyone and named only when the server named it', () => {
  const [plain] = lanes.swimlanes([ran('judge', { refused: 1 })])
  assert.equal(plain.toolLine, 'no tool calls · 1 refused')
  assert.deepEqual(plain.refused, [])
  const [admin] = lanes.swimlanes([ran('judge', { refused: 1, tools_refused: ['trident_get_chunks'], tools_used: { b: 2, a: 1 } })])
  assert.deepEqual(admin.refused, ['trident_get_chunks'])
  assert.deepEqual(admin.toolsUsed, [['a', 1], ['b', 2]])
})

test('a short step still shows as a visible bar and the bar never runs off the lane', () => {
  const [tiny, late] = lanes.swimlanes([ran('a', { started_ms: 0, duration_ms: 1 }), ran('b', { started_ms: 99_999, duration_ms: 5000 })])
  assert.ok(tiny.width >= 1.2)
  assert.ok(late.left + late.width <= 100.0001)
})

// ----- the graph the agents run in ----------------------------------------------------------------------------------------

const graph = require('../src/lib/agentGraph.ts')

test('the stages are put in running order from the compiled graph, whatever order the nodes arrive in', () => {
  const nodes = [{ id: 'review', agents: [] }, { id: 'classify', agents: ['triage'] }, { id: 'retrieve', agents: ['passage_retriever', 'graph_navigator', 'knowledge_qa'] }]
  const edges = [{ from: 'classify', to: 'retrieve' }, { from: 'retrieve', to: 'review' }]
  assert.deepEqual(graph.runningOrder(nodes, edges), ['classify', 'retrieve', 'review'])
  const boxes = graph.stageBoxes({ nodes, edges, mermaid: '' }, ROSTER)
  assert.deepEqual(boxes.map((b) => b.id), ['classify', 'retrieve', 'review'])
  assert.deepEqual(boxes.map((b) => b.parallel), [false, true, false])
  assert.deepEqual(boxes[1].agents.map((a) => a.name), ['Policy Passage Retriever', 'Procedure Graph Navigator', 'Knowledge Q&A Agent'])
  assert.equal(boxes[2].human, true) // the handler gate has no agent
})

test('a node no edge reaches is kept, not lost', () => {
  assert.deepEqual(graph.runningOrder([{ id: 'a' }, { id: 'b' }, { id: 'x' }], [{ from: 'a', to: 'b' }]), ['a', 'b', 'x'])
})

test("the graph's own start and end markers are not drawn as stages", () => {
  const nodes = [{ id: 'classify', agents: ['triage'] }, { id: 'review', agents: [] }]
  const edges = [{ from: '__start__', to: 'classify' }, { from: 'classify', to: 'review' }, { from: 'review', to: '__end__' }]
  assert.deepEqual(graph.runningOrder(nodes, edges), ['classify', 'review'])
  assert.deepEqual(graph.stageBoxes({ nodes, edges, mermaid: '' }, ROSTER).map((b) => b.id), ['classify', 'review'])
})

test('the loop inside the supervise stage is described from its compiled graph, and only when the graph has it', () => {
  const loop = { nodes: [{ id: 'review', agents: ['supervisor'] }, { id: 'revise', agents: [] }], mermaid: '', edges: [
    { from: '__start__', to: 'review' }, { from: 'review', to: '__end__', conditional: true }, { from: 'review', to: 'revise', conditional: true }, { from: 'revise', to: 'review' },
  ] }
  assert.match(graph.superviseLine(loop), /sends the findings back once/)
  assert.equal(graph.superviseLine(undefined), null)
  assert.equal(graph.superviseLine({ ...loop, edges: loop.edges.filter((e) => e.from !== 'revise') }), null)
})
