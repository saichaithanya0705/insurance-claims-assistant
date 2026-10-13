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
const { LiveActivityView } = require('../src/components/LiveActivity.tsx')

const text = (html) => html.replace(/<!-- -->/g, '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').replace(/ ([,.;])/g, '$1').trim()

let seq = 0
const span = (id, parent, kind, label, status, startedMs, durationMs = null, extra = {}) => ({
  id, parent, kind, name: kind === 'stage' ? extra.name : null, label, detail: null, result: null, status,
  started_ms: startedMs, duration_ms: status === 'running' ? null : durationMs, background: false, seq: ++seq, ...extra,
})
const progress = (spans, over = {}) => ({
  run_id: 'r', state: 'running', outcome: null, now_ms: 9000, running_ms: 100, next: seq, truncated: false, spans,
  counts: { knowledge_calls: 2, model_calls: 1, open: 2 }, ...over,
})

const RUN = span('root', null, 'run', 'Investigation', 'running', 0)
const CLASSIFY = span('c', 'root', 'stage', 'Classify the claim', 'ok', 100, 900, { name: 'classify', result: 'Auto claim' })
const RETRIEVE = span('r', 'root', 'stage', 'Gather evidence and compare past claims', 'running', 1000, null, { name: 'retrieve' })
const SESSION = span('s1', 'r', 'tool', 'Open a session', 'ok', 1100, 300)
const KNOWLEDGE = span('k', 'r', 'tool', 'Search the knowledge store', 'running', 1500, null)
const CALL = span('k1', 'k', 'tool', 'Look up handling procedures', 'ok', 1600, 800, { result: '10 passages', detail: 'trident_get_chunks · “q” · top 10' })
const CARDS = span('k2', 'k', 'tool', 'Find similar past claims', 'running', 2500, null, { detail: 'trident_query · “auto claim in regionkey_ae.”' })

const view = (spans, receivedAt = 1000, over = {}) => live.applyProgress(live.emptyView(), progress(spans, over), receivedAt)

// ----- merging --------------------------------------------------------------------------------------------------

test('merging an answer twice, or a late older copy of a span, never moves a finished span back to running', () => {
  const first = view([RUN, CLASSIFY, RETRIEVE])
  const again = live.applyProgress(first, progress([RUN, CLASSIFY, RETRIEVE]), 2000)
  assert.equal(again.spans.size, 3)
  const finished = { ...RETRIEVE, status: 'ok', duration_ms: 5000, seq: RETRIEVE.seq + 50 }
  const done = live.applyProgress(again, progress([finished], { next: finished.seq }), 3000)
  assert.equal(done.spans.get('r').status, 'ok')
  const late = live.applyProgress(done, progress([RETRIEVE], { next: RETRIEVE.seq }), 4000) // an old answer arriving late
  assert.equal(late.spans.get('r').status, 'ok')
  assert.equal(late.cursor, finished.seq)
})

test('the cursor only moves forward and the server clock is carried with the time it arrived', () => {
  const v = view([RUN], 5000, { now_ms: 7777, next: 12 })
  assert.equal(v.cursor, 12)
  assert.equal(v.serverNowMs, 7777)
  assert.equal(v.receivedAt, 5000)
  const older = live.applyProgress(v, progress([], { next: 3, now_ms: 8000 }), 6000)
  assert.equal(older.cursor, 12)
})

test('a running span counts up from the server clock; a finished one reports what it took', () => {
  const v = view([RUN, RETRIEVE, CALL], 1000, { now_ms: 5000 })
  assert.equal(live.elapsedMs(v.spans.get('r'), v, 1000), 4000) // 5000 now on the server, started at 1000
  assert.equal(live.elapsedMs(v.spans.get('r'), v, 3500), 6500) // 2.5 s later on the browser's clock
  assert.equal(live.elapsedMs(v.spans.get('k1'), v, 99999), 800)
  assert.equal(live.elapsedMs(v.spans.get('r'), v, -50), 4000) // a clock that went backwards never gives a negative time
})

// ----- grouping -------------------------------------------------------------------------------------------------

test('stages light up in the workflow order from the spans that have opened', () => {
  const v = view([RUN, CLASSIFY, RETRIEVE, span('rv', 'root', 'stage', 'Wait for a handler', 'waiting', 8000, 1, { name: 'review' }), span('x', 'root', 'stage', 'Check', 'error', 8100, 1, { name: 'validate' })])
  assert.deepEqual(live.stageStates(v), { classify: 'done', retrieve: 'active', review: 'waiting', validate: 'warn' })
  assert.equal(live.activeStage(v), 'retrieve')
  assert.equal(live.activeStage(view([RUN, CLASSIFY])), null)
})

test('each call sits under the stage it ran in, nested by depth, in the order it started', () => {
  const v = view([CARDS, CALL, KNOWLEDGE, SESSION, RETRIEVE, CLASSIFY, RUN]) // deliberately out of order
  const groups = live.buildGroups(v)
  assert.deepEqual(groups.map((g) => g.key), ['classify', 'retrieve'])
  const rows = groups[1].rows.map((r) => [r.span.label, r.depth])
  assert.deepEqual(rows, [
    ['Open a session', 0],
    ['Search the knowledge store', 0],
    ['Look up handling procedures', 1],
    ['Find similar past claims', 1],
  ])
  assert.deepEqual(groups[0].rows, [])
})

test('a span whose parent has not arrived yet, or that belongs to no stage, is shown last under other steps', () => {
  const orphan = span('o', 'not-yet-seen', 'tool', 'Late background step', 'running', 9000)
  const background = span('b', 'root', 'evaluation', 'Independent review in the background', 'running', 9100, null, { background: true })
  const groups = live.buildGroups(view([RUN, RETRIEVE, orphan, background]))
  assert.deepEqual(groups.map((g) => g.key), ['retrieve', 'other'])
  assert.deepEqual(groups[1].rows.map((r) => r.span.label), ['Late background step', 'Independent review in the background'])
  const loop = [span('a', 'b2', 'tool', 'loop a', 'ok', 1, 1), span('b2', 'a', 'tool', 'loop b', 'ok', 2, 1)]
  assert.doesNotThrow(() => live.buildGroups(view(loop))) // a malformed parent loop cannot hang the page
})

test('the page says what is happening in plain words for every state', () => {
  const states = ['connecting', 'queued', 'running', 'done', 'failed', 'unavailable']
  const lines = states.map((state) => live.stateLine({ ...live.emptyView(), state }, false))
  assert.equal(new Set(lines).size, 6)
  assert.match(lines[1], /Waiting for another investigation/)
  assert.match(live.stateLine({ ...live.emptyView(), state: 'running', paused: true }, false), /paused.*keeps running on the server/)
  assert.doesNotMatch(live.stateLine({ ...live.emptyView(), state: 'running' }, false), /call/)
  assert.match(live.stateLine({ ...live.emptyView(), state: 'running' }, true), /call this investigation is making/)
  assert.equal(live.isLive({ ...live.emptyView(), state: 'running' }), true)
  assert.equal(live.isLive({ ...live.emptyView(), state: 'done' }), false)
})

test('a run ID built without a secure context is still a valid version 4 UUID', () => {
  assert.match(live.newRunId(), /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  const original = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  Object.defineProperty(globalThis, 'crypto', { value: { getRandomValues: (a) => { a.fill(255); return a } }, configurable: true })
  try {
    assert.equal(live.newRunId(), 'ffffffff-ffff-4fff-bfff-ffffffffffff')
  } finally {
    Object.defineProperty(globalThis, 'crypto', original)
  }
})

// ----- the polling loop -----------------------------------------------------------------------------------------

const idle = () => Promise.resolve()
const httpError = (status) => Object.assign(new Error(`HTTP ${status}`), { status })

function follow(script, over = {}) {
  const calls = []
  const waits = []
  const updates = []
  let finish
  const finished = new Promise((resolve) => { finish = resolve })
  const follower = live.followProgress({
    load: async (after, signal) => {
      calls.push(after)
      const step = script.shift()
      if (!step) { finish(); return new Promise(() => {}) } // the script ran out: hold the request open until stop()
      if (step instanceof Error) throw step
      return typeof step === 'function' ? step(signal) : step
    },
    onUpdate: (v) => { updates.push(v); if (v.state === 'done' || v.state === 'failed' || v.state === 'unavailable') finish() },
    wait: async (ms) => { waits.push(ms) },
    ...over,
  })
  return { follower, calls, waits, updates, finished }
}

test('each poll asks only for what changed, and the loop ends by itself when the run is done', async () => {
  const { calls, updates, finished } = follow([
    progress([RUN], { next: 4, state: 'queued' }),
    progress([RUN, CLASSIFY], { next: 9 }),
    progress([span('r2', 'root', 'stage', 'Done', 'ok', 1, 1, { name: 'retrieve' })], { next: 15, state: 'done', outcome: 'awaiting_review' }),
  ])
  await finished
  assert.deepEqual(calls, [0, 4, 9])
  assert.deepEqual(updates.map((u) => u.state), ['queued', 'running', 'done'])
  await idle()
  assert.equal(calls.length, 3, 'no request is made after the run ends')
})

test('a 404 before the first answer only means the request has not arrived yet, so it keeps trying', async () => {
  let clock = 0
  const { calls, updates, waits, finished } = follow([httpError(404), httpError(404), progress([RUN], { next: 2, state: 'done' })], {
    clock: () => clock, graceMs: 10_000,
  })
  await finished
  assert.equal(calls.length, 3)
  assert.equal(updates.length, 1) // nothing is announced for the early 404s
  assert.deepEqual(waits, [700, 700])
  assert.equal(clock, 0)
})

test('a 404 after the grace period, or after any answer, means the server has no record, and the panel says so', async () => {
  let clock = 0
  const late = follow([httpError(404), () => { clock = 11_000; throw httpError(404) }], { clock: () => clock, graceMs: 10_000 })
  await late.finished
  assert.equal(late.updates.at(-1).state, 'unavailable')
  const after = follow([progress([RUN], { next: 2 }), httpError(404)], { clock: () => 0 })
  await after.finished
  assert.deepEqual(after.updates.map((u) => u.state), ['running', 'unavailable'])
})

test('failed requests back off, pause the view after two, and recover on the next good answer without losing what was shown', async () => {
  const { updates, waits, finished } = follow([
    progress([RUN, RETRIEVE], { next: 6 }),
    httpError(500), httpError(500), httpError(500),
    progress([RUN, RETRIEVE, CALL], { next: 8, state: 'done' }),
  ])
  await finished
  assert.deepEqual(waits, [700, 1400, 2800, 4000]) // doubling, capped
  // good answer; the 1st failure is silent; the 2nd and 3rd pause the view; the recovery un-pauses it
  assert.deepEqual(updates.map((u) => [u.state, u.paused]), [['running', false], ['running', true], ['running', true], ['done', false]])
  assert.equal(updates.at(-1).spans.size, 3)
  assert.equal(updates.find((u) => u.paused).spans.size, 2, 'the last known steps stay on screen while paused')
})

test('stop() ends the loop and a request still in flight is cancelled', async () => {
  let aborted = false
  const { follower, calls, finished } = follow([
    (signal) => new Promise((_, reject) => { signal.addEventListener('abort', () => { aborted = true; reject(new Error('aborted')) }) }),
  ])
  await idle()
  follower.stop()
  await idle()
  assert.equal(aborted, true)
  assert.equal(calls.length, 1)
  void finished
})

// ----- the panel ------------------------------------------------------------------------------------------------

const render = (v, over = {}) => renderToStaticMarkup(React.createElement(LiveActivityView, { view: v, now: 1000, wall: 12_000, startedAt: 0, admin: true, ...over }))

test('the panel shows the running stage open with its calls, a finished stage collapsed to a summary, and what is in progress', () => {
  const v = view([RUN, CLASSIFY, RETRIEVE, SESSION, KNOWLEDGE, CALL, CARDS])
  const html = render(v)
  const body = text(html)
  assert.match(body, /Building the investigation/)
  assert.match(body, /Running\. Each line below is a call this investigation is making now\./)
  assert.match(body, /12s/)
  assert.match(body, /2 knowledge-store calls · 1 model call · 2 in progress now/)
  assert.match(body, /Classify the claim Auto claim 0 steps · 900 ms/) // finished stage: collapsed to its summary
  assert.match(body, /Gather evidence and compare past claims 4 steps/)
  assert.match(body, /Look up handling procedures 10 passages 800 ms/)
  assert.match(body, /trident_get_chunks · “q” · top 10/) // an administrator sees the technical line
  assert.match(body, /Find similar past claims/)
  assert.equal((html.match(/data-testid="live-row"/g) || []).length, 4)
  assert.equal((html.match(/data-status="running"/g) || []).length, 2)
  assert.match(html, /aria-expanded="true"/)
  assert.match(html, /aria-expanded="false"/)
  assert.match(html, /Every line is a call this investigation really made, shown as it happens; nothing here is simulated/)
})

test('a running call counts up on the page from the server clock', () => {
  const v = view([RUN, RETRIEVE, KNOWLEDGE, CARDS], 1000, { now_ms: 6000 })
  assert.match(text(render(v, { now: 1000 })), /Find similar past claims.*3\.50 s/) // 6000 - 2500
  assert.match(text(render(v, { now: 3000 })), /Find similar past claims.*5\.50 s/) // two seconds later
})

test('before any answer the panel waits for the server, and a queued run says so without inventing steps', () => {
  const before = text(render(live.emptyView()))
  assert.match(before, /Sending the request…/)
  assert.doesNotMatch(before, /knowledge-store calls/)
  const queued = text(render(view([], 1000, { state: 'queued', running_ms: null })))
  assert.match(queued, /Waiting for another investigation to finish\. Investigations run one at a time\./)
  assert.doesNotMatch(queued, /live-row/)
})

test('a paused connection, an unavailable run and a truncated list each tell the person plainly', () => {
  assert.match(text(render({ ...view([RUN, RETRIEVE]), paused: true })), /Live updates are paused/)
  assert.match(text(render({ ...live.emptyView(), state: 'unavailable' })), /Live steps are not available for this run/)
  assert.match(text(render(view([RUN, RETRIEVE], 1000, { truncated: true }))), /more steps than are listed here/)
})

test('everyone but an administrator sees the plain wording and no technical line', () => {
  const plain = [
    span('k1', 'r', 'tool', 'Look up handling procedures', 'ok', 1600, 800, { result: '10 passages' }),
  ]
  const html = render(view([RUN, RETRIEVE, ...plain]), { admin: false })
  assert.match(text(html), /Each line below is a step this investigation is taking now/)
  assert.doesNotMatch(html, /trident|Synapt|live-detail/)
})

test('the page is wired to follow the run it started, and the old "after completion" promise is gone', () => {
  const app = fs.readFileSync(require.resolve('../src/App.tsx'), 'utf8')
  assert.match(app, /run_id: runId/)
  assert.match(app, /<LiveActivity key=\{liveRunId\} runId=\{liveRunId\}/)
  assert.match(app, /setLiveRunId\(null\)/)
  const component = fs.readFileSync(require.resolve('../src/components/LiveActivity.tsx'), 'utf8')
  assert.doesNotMatch(component, /appear after completion/)
})
