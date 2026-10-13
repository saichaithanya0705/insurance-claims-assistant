import type { LiveProgress, LiveSpan } from './api'

// The live view of an investigation in progress. Everything here is plain functions so it can be tested without a
// browser: merging what the server sends, grouping spans under their stage, working out how long a running span has
// been running, and the polling loop with its backoff.

export const STAGE_ORDER = ['classify', 'retrieve', 'investigate', 'risk', 'recommend', 'validate', 'supervise', 'judge', 'review'] as const

/** An ID the page chooses for the investigation it is about to start, so it can follow it before the server answers.
 *  `randomUUID` needs a secure context; the fallback builds a version 4 UUID from `getRandomValues`, which does not. */
export function newRunId(): string {
  const c = globalThis.crypto
  if (typeof c?.randomUUID === 'function') return c.randomUUID()
  const bytes = new Uint8Array(16)
  c.getRandomValues(bytes)
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

/** connecting: the request may not have reached the server yet. unavailable: the server has no record of this run. */
export type FollowState = 'connecting' | 'queued' | 'running' | 'done' | 'failed' | 'unavailable'

export interface LiveView {
  state: FollowState
  spans: ReadonlyMap<string, LiveSpan>
  /** Pass to the next request as `after`. */
  cursor: number
  /** The server's clock (ms since the run was registered) when the last answer was built. */
  serverNowMs: number
  /** The browser clock (`performance.now()`) when that answer arrived. */
  receivedAt: number
  runningMs: number | null
  counts: LiveProgress['counts']
  truncated: boolean
  /** Polling is failing; what is shown is the last thing the server said. */
  paused: boolean
}

export const emptyView = (): LiveView => ({
  state: 'connecting',
  spans: new Map(),
  cursor: 0,
  serverNowMs: 0,
  receivedAt: 0,
  runningMs: null,
  counts: { knowledge_calls: 0, model_calls: 0, open: 0 },
  truncated: false,
  paused: false,
})

/** Merge one server answer into the view. A span arrives whole each time it changes, so merging is replacing by id and
 *  is safe to repeat: a duplicated or late answer cannot move a finished span back to running. */
export function applyProgress(view: LiveView, data: LiveProgress, receivedAt: number): LiveView {
  const spans = new Map(view.spans)
  for (const incoming of data.spans) {
    const known = spans.get(incoming.id)
    if (!known || incoming.seq >= known.seq) spans.set(incoming.id, incoming)
  }
  return {
    state: data.state,
    spans,
    cursor: Math.max(view.cursor, data.next),
    serverNowMs: data.now_ms,
    receivedAt,
    runningMs: data.running_ms,
    counts: data.counts,
    truncated: data.truncated,
    paused: false,
  }
}

/** How long a span has been going, on the server's clock carried forward by the browser's. */
export function elapsedMs(span: LiveSpan, view: LiveView, clockNow: number): number {
  if (span.duration_ms !== null) return span.duration_ms
  const serverNow = view.serverNowMs + Math.max(0, clockNow - view.receivedAt)
  return Math.max(0, serverNow - span.started_ms)
}

export type StageState = 'idle' | 'active' | 'done' | 'waiting' | 'warn'

export function stageStates(view: LiveView): Record<string, StageState> {
  const states: Record<string, StageState> = {}
  for (const span of view.spans.values()) {
    if (span.kind !== 'stage' || !span.name) continue
    states[span.name] = span.status === 'running' ? 'active' : span.status === 'ok' ? 'done' : span.status === 'waiting' ? 'waiting' : 'warn'
  }
  return states
}

export interface LiveRow {
  span: LiveSpan
  /** 0 for a span directly under its stage. */
  depth: number
}

export interface LiveGroup {
  key: string
  stage: LiveSpan | null
  rows: LiveRow[]
}

/** Spans grouped under the stage they ran in, stages in the workflow's order, rows in the order they started.
 *  Spans that belong to no stage (a late background step) are collected last under `other`. */
export function buildGroups(view: LiveView): LiveGroup[] {
  const spans = [...view.spans.values()].sort((a, b) => a.started_ms - b.started_ms || a.seq - b.seq)
  const byId = new Map(spans.map((s) => [s.id, s]))
  const stageOf = (span: LiveSpan): { stage: LiveSpan | null; depth: number } => {
    let depth = 0
    let current: LiveSpan | undefined = span
    const seen = new Set<string>()
    while (current && !seen.has(current.id)) {
      seen.add(current.id)
      const parent: LiveSpan | undefined = current.parent ? byId.get(current.parent) : undefined
      if (!parent) return { stage: null, depth }
      if (parent.kind === 'stage') return { stage: parent, depth }
      if (parent.kind === 'run') return { stage: null, depth }
      depth += 1
      current = parent
    }
    return { stage: null, depth }
  }
  const groups = new Map<string, LiveGroup>()
  for (const span of spans.filter((s) => s.kind === 'stage' && s.name)) {
    groups.set(span.id, { key: span.name as string, stage: span, rows: [] })
  }
  const other: LiveGroup = { key: 'other', stage: null, rows: [] }
  for (const span of spans) {
    if (span.kind === 'stage' || span.kind === 'run' || span.kind === 'agent') continue // agents have their own panel (agentTeam.ts)
    const { stage, depth } = stageOf(span)
    const group = stage ? groups.get(stage.id) : undefined
    ;(group ?? other).rows.push({ span, depth })
  }
  const order = (g: LiveGroup) => {
    const index = STAGE_ORDER.indexOf(g.key as (typeof STAGE_ORDER)[number])
    return index === -1 ? STAGE_ORDER.length : index
  }
  const ordered = [...groups.values()].sort((a, b) => order(a) - order(b) || (a.stage?.started_ms ?? 0) - (b.stage?.started_ms ?? 0))
  return other.rows.length ? [...ordered, other] : ordered
}

/** The stage that is running now, if any. */
export function activeStage(view: LiveView): string | null {
  const running = [...view.spans.values()].filter((s) => s.kind === 'stage' && s.status === 'running' && s.name)
  return running.length ? (running.sort((a, b) => b.started_ms - a.started_ms)[0].name as string) : null
}

/** Whether anything on the page is still moving, so a clock only ticks while it has something to show. */
export function isLive(view: LiveView): boolean {
  return view.state === 'connecting' || view.state === 'queued' || view.state === 'running'
}

/** Wording for the one-line state under the title. */
export function stateLine(view: LiveView, admin: boolean): string {
  if (view.paused) return 'Live updates are paused. The investigation keeps running on the server; reconnecting…'
  switch (view.state) {
    case 'connecting': return 'Sending the request…'
    case 'queued': return 'Waiting for another investigation to finish. Investigations run one at a time.'
    case 'running': return admin ? 'Running. Each line below is a call this investigation is making now.' : 'Running. Each line below is a step this investigation is taking now.'
    case 'done': return 'Finished. Opening the brief…'
    case 'failed': return 'Stopped. The brief explains what failed.'
    default: return 'Live steps are not available for this run; it is still being built.'
  }
}

// ----- polling ------------------------------------------------------------------------------------------------------

export interface FollowOptions {
  /** Fetch what changed after `after`. Rejects with an error carrying `status` for an HTTP failure. */
  load: (after: number, signal: AbortSignal) => Promise<LiveProgress>
  onUpdate: (view: LiveView) => void
  intervalMs?: number
  maxBackoffMs?: number
  /** A 404 this soon after starting only means the request has not reached the server yet. */
  graceMs?: number
  /** Injected in tests. */
  wait?: (ms: number, signal: AbortSignal) => Promise<void>
  clock?: () => number
}

const defaultWait = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms)
    signal.addEventListener('abort', () => { clearTimeout(timer); resolve() }, { once: true })
  })

/** Poll until the run ends, the server has no record of it, or `stop()` is called. A request that fails does not end it:
 *  the view is marked paused and the poll backs off, then carries on from the same cursor. */
export function followProgress(options: FollowOptions): { stop: () => void } {
  const { load, onUpdate, intervalMs = 700, maxBackoffMs = 4000, graceMs = 10_000, wait = defaultWait } = options
  const clock = options.clock ?? (() => performance.now())
  const controller = new AbortController()
  const startedAt = clock()
  let view = emptyView()
  let failures = 0
  const publish = (next: LiveView) => { view = next; onUpdate(view) }
  void (async () => {
    while (!controller.signal.aborted) {
      let delay = intervalMs
      try {
        const data = await load(view.cursor, controller.signal)
        if (controller.signal.aborted) return
        failures = 0
        publish(applyProgress(view, data, clock()))
        if (data.state === 'done' || data.state === 'failed') return
      } catch (error) {
        if (controller.signal.aborted) return
        if ((error as { status?: number }).status === 404) {
          // Before the first answer a 404 only means the request has not reached the server yet. After one, or once
          // the grace period is over, the server has no record of this run (it restarted, or the run was never made).
          if (view.state !== 'connecting' || clock() - startedAt >= graceMs) { publish({ ...view, state: 'unavailable', paused: false }); return }
        } else {
          failures += 1
          if (failures >= 2) publish({ ...view, paused: true })
          delay = Math.min(intervalMs * 2 ** failures, maxBackoffMs)
        }
      }
      await wait(delay, controller.signal)
    }
  })()
  return { stop: () => controller.abort() }
}
