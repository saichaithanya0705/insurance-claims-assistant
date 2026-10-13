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
const trace = require('../src/lib/trace.ts')
const { ExplanationBody } = require('../src/components/ExplanationView.tsx')
const { ObservabilityDashboard, TraceTable } = require('../src/components/ObservabilityView.tsx')
const { TraceBody } = require('../src/components/TraceView.tsx')
const { ScoreContribution, ColumnChart, LatencyBars } = require('../src/components/Charts.tsx')
const { NAV } = require('../src/components/Sidebar.tsx')
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props))

/* ---------- helpers ---------- */
test('durations read naturally at every scale and never invent a value', () => {
  assert.equal(trace.formatDuration(0.4), '<1 ms')
  assert.equal(trace.formatDuration(850), '850 ms')
  assert.equal(trace.formatDuration(1530), '1.53 s')
  assert.equal(trace.formatDuration(14_250), '14.3 s')
  assert.equal(trace.formatDuration(74_000), '1 m 14 s')
  for (const missing of [null, undefined, NaN, Infinity]) assert.equal(trace.formatDuration(missing), '—')
})

test('counts compact the way a stat tile expects and axis ticks land on clean numbers', () => {
  assert.equal(trace.compactNumber(1284), '1,284')
  assert.equal(trace.compactNumber(12_900), '12.9K')
  assert.equal(trace.compactNumber(4_200_000), '4.2M')
  assert.equal(trace.compactNumber(null), '—')
  assert.deepEqual([0.9, 1, 1.4, 3, 7, 12, 86, 0].map(trace.niceCeil), [1, 1, 2, 5, 10, 20, 100, 1])
  assert.deepEqual(trace.ticksTo(10, 2), [0, 5, 10])
})

test('span names are readable and a model call says what it was for', () => {
  assert.equal(trace.spanLabel({ name: 'llm.investigation', attributes: {} }), 'Model call · investigation')
  assert.equal(trace.spanLabel({ name: 'history.search', attributes: {} }), 'Search comparable claims')
  assert.equal(trace.spanLabel({ name: 'synapt.call_tool', attributes: { purpose: 'claim_cards' } }), 'Synapt search · claim cards')
  assert.equal(trace.spanLabel({ name: 'something.new', attributes: {} }), 'something.new')
})

const span = (id, parent, name, kind, offset, duration, extra = {}) => ({
  span_id: id, parent_id: parent, name, kind, status: extra.status ?? 'ok', started_at: '2026-10-07T14:00:00+00:00',
  offset_ms: offset, duration_ms: duration, depth: parent ? 1 : 0, attributes: extra.attributes ?? {},
})
const sampleTrace = (source = 'recorded') => ({
  run_id: 'run-1', source, started_at: '2026-10-07T14:00:00+00:00', total_ms: 9000, note: 'Rebuilt from the audit log.',
  summary: { started_at: '2026-10-07T14:00:00+00:00', duration_ms: 1000, stages: [], errors: [], llm: { calls: 2, total_ms: 6500, retries: 1, failures: 0, tokens: { prompt: 900, completion: 100, total: 1000 }, by_purpose: {} } },
  spans: [
    span('root', null, 'investigation', 'run', 0, 1000),
    span('s1', 'root', 'classify', 'stage', 0, 400),
    span('l1', 's1', 'llm.classification', 'llm', 20, 350, { attributes: { purpose: 'classification', model: 'm1', attempts: 2, total_tokens: 150, prompt_tokens: 100, completion_tokens: 50, attempt_log: [{ attempt: 1, outcome: 'http_failure', status_code: 503, elapsed_ms: 80 }, { attempt: 2, outcome: 'ok', elapsed_ms: 270 }], prompt_events: [11], output_event: 12 } }),
    span('s2', 'root', 'review', 'stage', 1000, 0, { status: 'waiting' }),
    span('bg', 's2', 'judge.review', 'evaluation', 1000, 8000, { attributes: { background: true } }),
    span('hr', null, 'handler_review', 'run', 3_600_000, 3),
  ],
})

test('the waterfall ends the axis at the run, draws background work running off the edge and parks later work', () => {
  const t = sampleTrace()
  const { rows, scaleMs, runMs } = trace.waterfall(t, false)
  assert.equal(scaleMs, 1000)
  assert.equal(runMs, 1000)
  const by = Object.fromEntries(rows.map((r) => [r.span.span_id, r]))
  assert.equal(by.root.left, 0)
  assert.equal(by.root.width, 100)
  assert.equal(by.s1.width, 40)
  assert.equal(by.l1.left, 2)
  assert.equal(by.bg.clipped, true)
  assert.equal(by.bg.background, true)
  assert.equal(by.hr.deferred, true)
  assert.equal(by.hr.width, 0)
  for (const row of rows) assert.ok(row.left >= 0 && row.left + row.width <= 100.0001, row.span.span_id)
  // Scaled to include the background review, nothing is clipped and the stages shrink.
  const full = trace.waterfall(t, true)
  assert.equal(full.scaleMs, 9000)
  assert.equal(full.rows.find((r) => r.span.span_id === 'bg').clipped, false)
  assert.ok(full.rows.find((r) => r.span.span_id === 's1').width < 5)
})

test('the timeline shows the recorded steps, the model call detail and whether timings were measured', () => {
  const html = render(TraceBody, { trace: sampleTrace(), runId: 'run-1' })
  assert.match(html, /Execution timeline/)
  assert.match(html, /Classify the claim/)
  assert.match(html, /Model call · classification/)
  assert.match(html, /Show background review to scale/)
  assert.match(html, /Recorded while the investigation ran/)
  assert.doesNotMatch(html, /Reconstructed trace/)
  // The first model call is selected by default; its attempts and token usage are explained.
  assert.match(html, /Http failure \(HTTP 503\)/)
  assert.match(html, /Answer accepted/)
  assert.match(html, /Total 150 tokens as reported by the provider/)
  assert.match(html, /Show prompt/)
  assert.match(html, /Show validated answer/)
  const rebuilt = render(TraceBody, { trace: sampleTrace('reconstructed'), runId: 'run-1' })
  assert.match(rebuilt, /Reconstructed trace\./)
  assert.match(rebuilt, /Rebuilt from the audit log/)
})

/* ---------- charts ---------- */
test('every chart exposes its values without a tooltip', () => {
  const columns = render(ColumnChart, { data: [{ key: 'a', label: 'Mon 5 Oct', value: 4, failed: 1 }, { key: 'b', label: 'Tue 6 Oct', value: 0 }], axisLabel: (d) => d.label })
  assert.match(columns, /aria-label="Mon 5 Oct: 4 queries, 1 failed"/)
  assert.match(columns, /aria-label="Tue 6 Oct: 0 queries"/)
  const latency = render(LatencyBars, { rows: [{ key: 'retrieve', label: 'Retrieve', p50: 1200, p95: 3400, count: 6, errors: 1 }] })
  assert.match(latency, /1\.20 s/)
  assert.match(latency, /p95 3\.40 s/)
  assert.match(latency, /6 runs, 1 with errors/)
})

test('the ranking chart states every number it draws and says when a breakdown was not recorded', () => {
  const html = render(ScoreContribution, {
    rows: [
      { key: 'A', label: '#1 CLM-1', total: 0.0412, points: { keyword: 0.0164, feature: 0.0164, semantic: 0.0084 }, ranks: { keyword: 1, feature: 1, semantic: 2 } },
      { key: 'B', label: '#2 CLM-2', total: 0.03, points: null, ranks: { keyword: null, feature: null, semantic: null } },
    ],
  })
  assert.match(html, /keyword #1 · numeric #1 · semantic #2/)
  assert.match(html, /0\.0412/)
  assert.match(html, /Combined score only/)
  assert.match(html, /keyword 0\.0164, numeric 0\.0164, semantic 0\.0084, total 0\.0412/)
})

/* ---------- explanation ---------- */
const explanation = (overrides = {}) => ({
  run_id: 'run-1', status: 'awaiting_review', generation: 'rules', headline: '4 findings and 2 recommendations drawn from 9 sources; handling priority high (40/100).',
  pipeline: [
    { stage: 'classify', title: 'Classify the claim', kind: 'rules', what: 'Decides the claim type.', how: 'Uses the submitted category.', inputs: ['Submitted claim'], outputs: ['Claim type: auto'], duration_ms: 1.2, status: 'complete' },
    { stage: 'judge', title: 'Independent review', kind: 'off', what: 'A second model reviews.', how: 'Not run for this brief.', inputs: ['Brief'], outputs: ['Not run'], duration_ms: null, status: 'skipped' },
    { stage: 'review', title: 'Handler review', kind: 'human', what: 'A person decides.', how: 'The workflow pauses.', inputs: ['Brief'], outputs: ['Waiting for a handler'], duration_ms: 0, status: 'waiting' },
  ],
  lineage: [
    { type: 'finding', index: 0, kind: 'gap', text: 'Missing police report.', stage: 'investigate', method: 'rules', unsupported: false, sources: [{ source_id: 'claim:input', label: 'Submitted claim', category: 'claim' }, { source_id: 'p1', label: 'Auto procedure', category: 'procedure', excerpt: 'Request a police report for theft.' }] },
    { type: 'finding', index: 1, kind: 'fact', text: 'An unsupported statement.', stage: 'investigate', method: 'rules', unsupported: true, sources: [] },
    { type: 'finding', index: 2, kind: 'limitation', text: 'Outcomes do not establish coverage.', stage: 'investigate', method: 'rules', unsupported: false, sources: [] },
    { type: 'recommendation', index: 0, kind: 'Verify submitted facts', text: 'Check the dates.', stage: 'recommend', method: 'rules', unsupported: false, sources: [{ source_id: 'claim:input', label: 'Submitted claim', category: 'claim' }] },
  ],
  retrieval: {
    recorded: true, pool: 'Settled claims (approved or denied) of the same type, closed before this claim was filed', filters: { claim_type: 'auto' },
    methods: [{ id: 'keyword', name: 'Keyword match', weight: 1, how: 'k' }, { id: 'feature', name: 'Numeric similarity', weight: 1, how: 'n' }, { id: 'semantic', name: 'Semantic rank', weight: 0.5, how: 's' }],
    formula: 'score = 1/(60 + keyword rank) + 1/(60 + numeric rank) + 0.5/(60 + semantic rank)',
    candidates: { sql_candidates: 300, semantic_added: 2, pool_size: 302, top_k: 5 }, semantic: { semantic_candidates: 20, semantic_eligible: 8, semantic_in_results: 2 },
    ranked: [{ rank: 1, claim_id: 'CLM-1', claim_type: 'auto', state: 'TX', claim_amount: 8000, outcome: 'approved', surfaced_by: 'fusion', total: 0.0412, keyword_rank: 1, feature_rank: 1, semantic_rank: 2, points: { keyword: 0.0164, feature: 0.0164, semantic: 0.0084 }, reasons: [], differences: [] }],
    evidence_by_category: { claim: 1, procedure: 3, history: 5 }, note: null,
  },
  priority: {
    score: 40, tier: 'high', tiers: [{ tier: 'critical', from: 60 }, { tier: 'high', from: 40 }, { tier: 'medium', from: 20 }, { tier: 'low', from: 0 }], next_tier: { tier: 'critical', points_needed: 20 },
    factors: [{ id: 'amount', label: 'Claimed amount', max_points: 30, rule: '$25k earns 15', points: 15, applied: true }, { id: 'delay', label: 'Filing delay', max_points: 15, rule: 'More than 14 days earns 10', points: 0, applied: false }],
    components: [{ points: 15, reason: 'Claimed amount $42,000 is at least $25,000' }], unmatched_components: [], policy: 'Illustrative scoring rule.',
  },
  estimates: { available: false, reason: 'No trained models are available.', tasks: [] },
  evaluation: { layers: [
    { id: 'validation', title: 'Mechanical validation', kind: 'rules', gate: true, summary: 'Deterministic checks.', state: 'passed', checks_source: 'recorded', scope: 'schema and citations', rechecked: { matches_saved: true, source: 'x' }, issues: [],
      checks: [{ id: 'findings_cited', label: 'Findings cite a source', description: 'Each names a source.', passed: true, inspected: 2, failed: 0 }, { id: 'text_boundary', label: 'Text stays inside the boundary', description: 'No decisions.', passed: false, inspected: 6, failed: 1 }] },
    { id: 'grounding', title: 'Evidence grounding', kind: 'rules', gate: false, summary: 'Counts.', metrics: { findings: 3, substantive_findings: 2, substantive_cited: 1, recommendations: 1, recommendations_cited: 1, citations: 3, citations_resolved: 3, sources_available: 9, sources_cited: 2, external_sources_available: 8, external_sources_cited: 1, uncited_sources: [] } },
    { id: 'judge', title: 'Independent AI review', kind: 'ai', gate: false, summary: 'A second model.', state: 'completed', passed: false, grounded: true, boundary_respected: true, recommendations_supported: false, score: 0.55, issues: ['Recommendation 2 is unsupported.'], verdict: 'Mostly grounded.', criteria: 'Passes when grounded.', model: 'judge-model-x', independent: true },
    { id: 'human', title: 'Handler review', kind: 'human', gate: true, summary: 'A person decides.', state: 'awaiting', decision: null, note: null },
  ] },
  boundaries: ['The brief never approves, denies or pays a claim, and never states that fraud is proven.', 'Every finding must cite a supplied source.'],
  timeline: { source: 'recorded', total_ms: 90, stages: [{ stage: 'classify', duration_ms: 1.2, status: 'ok' }] }, limitations: ['Synthetic data only.'],
  ...overrides,
})

test('the explanation covers generation, sources, ranking, priority, evaluation and limits', () => {
  const html = render(ExplanationBody, { data: explanation() })
  for (const heading of ['How the brief was generated', 'Where each statement came from', 'How comparable claims were found and ranked', 'Why this handling priority', 'How the brief was evaluated', 'Boundaries and limitations']) assert.match(html, new RegExp(heading))
  assert.match(html, /Drafted by fixed rules \(demonstration mode\)/)
  assert.match(html, /Waiting for a handler/)
  assert.match(html, /Fixed rules/)
  assert.match(html, /No trained models are available/)
  assert.match(html, /The brief never approves, denies or pays a claim/)
})

test('statements without a source are flagged, and limitations are not asked for one', () => {
  const html = render(ExplanationBody, { data: explanation() })
  assert.match(html, /No source cited/)
  assert.match(html, /A limitation states what is not known, so it needs no source/)
  assert.match(html, /Request a police report for theft\./) // the excerpt is on the source chip for hover and focus
  assert.match(html, /written by fixed rules/)
})

test('ranking shows the formula, every method, the candidate funnel and the per-method ranks', () => {
  const html = render(ExplanationBody, { data: explanation() })
  assert.match(html, /score = 1\/\(60 \+ keyword rank\)/)
  assert.match(html, /Keyword match/)
  assert.match(html, /weight ×0\.5/)
  assert.match(html, /300 chosen by exact filters and numeric closeness \+ 2 added from the knowledge store/)
  assert.match(html, /keyword #1 · numeric #1 · semantic #2/)
  assert.match(html, /Scores are ranks, not probabilities/)
})

test('priority names the tier, the points to the next one and the factors that did not apply', () => {
  const html = render(ExplanationBody, { data: explanation() })
  assert.match(html, /20 more points would reach critical/)
  assert.match(html, /aria-label="Did not apply"/)
  assert.match(html, /aria-label="Applied"/)
  assert.match(html, /<b>15<\/b> \/ 30/)
})

test('evaluation lists each validation rule with its result, the grounding counts and the review verdict', () => {
  const html = render(ExplanationBody, { data: explanation() })
  assert.match(html, /Findings cite a source/)
  assert.match(html, /1 of 6 failed/)
  assert.match(html, /Re-running them now gives the same verdict as the one saved/)
  assert.match(html, /Substantive findings that cite a source/)
  assert.match(html, /Passing line 0\.70/)
  assert.match(html, /Recommendation 2 is unsupported\./)
  assert.match(html, /Awaiting a handler/)
})

test('technical detail appears for administrators only', () => {
  const data = explanation({ technical: { llm: { calls: 3, total_ms: 10, retries: 1, failures: 0, tokens: { prompt: 1, completion: 1, total: 450 }, by_purpose: {} }, trace_source: 'recorded', classification_method: 'live_model' } })
  const user = render(ExplanationBody, { data })
  assert.doesNotMatch(user, /judge-model-x|Open full trace|Technical:|450 tokens/)
  const admin = render(ExplanationBody, { data, admin: true, onOpenTrace: () => {} })
  assert.match(admin, /judge-model-x/)
  assert.match(admin, /a different model from the author/)
  assert.match(admin, /Open full trace/)
  assert.match(admin, /3 model calls, 450 tokens, 1 retried/)
})

test('estimates list only the features that moved them, and say so when none did', () => {
  const task = (drivers) => ({ id: 'amount', title: 'Claim amount', available: true, unit: 'USD', estimate: 8393, interval: [0, 45183], drivers, learned: [], important_features: [] })
  const flat = render(ExplanationBody, { data: explanation({ estimates: { available: true, tasks: [task([{ feature: 'deductible', value: 500, typical_value: 1000, effect: 0 }, { feature: 'filing_delay_days', value: 17, typical_value: 7, effect: 0.2 }])] } }) })
  assert.doesNotMatch(flat, /\+\$0|−\$0|Filing delay days/)
  assert.match(flat, /Nothing about this claim moved the estimate away from a typical claim/)
  const moved = render(ExplanationBody, { data: explanation({ estimates: { available: true, tasks: [task([{ feature: 'claim_type', value: 'business', typical_value: 'auto', effect: 52000 }, { feature: 'deductible', value: 500, typical_value: 1000, effect: 0 }])] } }) })
  assert.match(moved, /\+\$52,000/)
  assert.match(moved, /Claim type/)
  assert.doesNotMatch(moved, /Nothing about this claim moved/)
})

test('an AI-drafted brief says so', () => {
  assert.match(render(ExplanationBody, { data: explanation({ generation: 'ai' }) }), /Drafted by an AI model/)
})

/* ---------- dashboard and trace list ---------- */
const stats = (p50, p95, count = 4) => ({ count, p50, p95, max: p95, mean: p50 })
const summary = (overrides = {}) => ({
  window: '7d', origin: 'all', generated_at: '2026-10-07T15:00:00+00:00',
  queries: { total: 4, by_status: { awaiting_review: 2, failed: 1, reviewed: 1 }, failed: 1, success_rate: 0.75, by_origin: { user: 3, evaluation: 1 }, by_mode: { live: 3, fixture: 1 } },
  latency_ms: stats(8200, 21_000), stages: [{ stage: 'classify', errors: 0, ...stats(900, 1500) }, { stage: 'retrieve', errors: 1, ...stats(5200, 9000) }],
  operations: [{ name: 'history.search', kind: 'retrieval', errors: 0, ...stats(800, 1200) }],
  llm: { calls: 9, failures: 1, retries: 2, tokens: { prompt: 9000, completion: 3000, total: 12_000 }, tokens_per_query: 3000, by_purpose: [{ purpose: 'investigation', model: 'm1', calls: 4, tokens: 8000, prompt_tokens: 6000, completion_tokens: 2000, failures: 1, retries: 2, latency_ms: stats(3300, 5000) }] },
  quality: { validated: 4, validation_passed: 3, validation_pass_rate: 0.75, judge: { completed: 2, passed: 1, failed: 0, pending: 1, skipped: 1, pass_rate: 0.5, mean_score: 0.8 }, handler: { accepted: 1, revision_requested: 0, awaiting: 2 } },
  errors: [{ run_id: 'run-9', time: '2026-10-07T14:00:00+00:00', span: 'investigate', kind: 'stage', error_type: 'CompletionError' }],
  series: [{ bucket: '2026-10-06T00:00:00+00:00', queries: 1, failed: 0, p50_ms: 8000 }, { bucket: '2026-10-07T00:00:00+00:00', queries: 3, failed: 1, p50_ms: 9000 }],
  api: { requests: 120, server_errors: 0, client_errors: 3, latency_ms: stats(12, 80, 120), routes: [{ method: 'POST', route: '/api/investigations', client_errors: 0, server_errors: 0, ...stats(8000, 21_000, 4) }] },
  coverage: { recorded: 3, reconstructed: 1, note: 'Reconstructed runs are approximate.' },
  ...overrides,
})

test('the dashboard leads with the figures an operator needs and gives every chart a table twin', () => {
  const html = render(ObservabilityDashboard, { summary: summary(), onOpenTrace: () => {} })
  for (const text of ['Queries', 'Median run time', 'Model calls', 'Tokens per query', 'Validation', 'Independent review']) assert.match(html, new RegExp(text))
  assert.match(html, /1 failed · 75% completed/)
  assert.match(html, /8\.20 s/)
  assert.match(html, /3K|3,000/)
  assert.match(html, /Queries over time/)
  assert.match(html, /Where the time goes/)
  assert.match(html, />Table</) // the table twin toggle
  assert.match(html, /Open trace/)
  assert.match(html, /CompletionError/)
  assert.match(html, /3 recorded|3 runs were recorded live and 1 reconstructed/)
  assert.match(html, /Reconstructed runs are approximate/)
})

test('an empty window says so instead of drawing empty charts', () => {
  const html = render(ObservabilityDashboard, { summary: summary({ queries: { total: 0, by_status: {}, failed: 0, success_rate: null, by_origin: {}, by_mode: {} }, series: [], stages: [] }) })
  assert.match(html, /No queries were traced in this window/)
  assert.doesNotMatch(html, /Queries over time/)
})

const item = (extra = {}) => ({ run_id: 'abcdef12-0000', title: 'Rear-ended at a junction', description: '', status: 'awaiting_review', trace_source: 'recorded', started_at: '2026-10-07T14:00:00+00:00', duration_ms: 8200, llm_calls: 3, tokens: 1200, errors: 0, origin: 'user', mode: 'live', agent_mode: 'live', validation_passed: true, judge_status: 'completed', judge_passed: true, judge_score: 0.9, ...extra })

test('the trace list marks reconstructed runs, evaluation-suite runs and untraced runs', () => {
  const html = render(TraceTable, { items: [item(), item({ run_id: 'b', trace_source: 'reconstructed' }), item({ run_id: 'c', origin: 'evaluation', agent_mode: 'fixture', llm_calls: 0, tokens: 0, judge_status: 'skipped' }), item({ run_id: 'd', trace_source: null, duration_ms: null, llm_calls: null })] })
  assert.match(html, /Reconstructed/)
  assert.match(html, /Evaluation suite/)
  assert.match(html, /No trace/)
  assert.match(html, /rule-based/)
  assert.match(html, /1\.2K tokens|1,200 tokens/)
  assert.match(html, /aria-label="Open trace: Rear-ended at a junction"/)
  assert.match(html, /No concerns/)
})

/* ---------- navigation ---------- */
test('explainability and the agents page are open to handlers; observability and the rest stay administrator tools', () => {
  const byView = Object.fromEntries(NAV.map((n) => [n.view, n]))
  assert.equal(byView.explain.admin, undefined)
  assert.equal(byView.agents.admin, undefined)
  assert.equal(byView.observability.admin, true)
  // Shortcut numbers follow the order shown, with no duplicates.
  assert.deepEqual(NAV.map((n) => n.key), ['1', '2', '3', '4', '5', '6', '7', '8'])
  assert.deepEqual(NAV.filter((n) => !n.admin).map((n) => n.view), ['workspace', 'cases', 'explain', 'agents'])
})
