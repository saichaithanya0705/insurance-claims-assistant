import type { Trace, TraceSpan } from './api'
import { label } from './format'

/** 0.4 ms -> "<1 ms", 850 -> "850 ms", 1530 -> "1.53 s", 74 000 -> "1 m 14 s". */
export const formatDuration = (ms: number | null | undefined): string => {
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return '—'
  if (ms < 1) return '<1 ms'
  if (ms < 1000) return `${Math.round(ms)} ms`
  if (ms < 10_000) return `${(ms / 1000).toFixed(2)} s`
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`
  const seconds = Math.round(ms / 1000)
  return `${Math.floor(seconds / 60)} m ${String(seconds % 60).padStart(2, '0')} s`
}

/** 1284 -> "1,284", 12 900 -> "12.9K", 4 200 000 -> "4.2M". */
export const compactNumber = (value: number | null | undefined): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
  if (abs >= 10_000) return `${(value / 1000).toFixed(1).replace(/\.0$/, '')}K`
  return Math.round(value).toLocaleString('en-US')
}

/** Smallest 1/2/5 x 10^k at or above `value`, so axis ticks land on clean numbers. */
export const niceCeil = (value: number): number => {
  if (!(value > 0) || !Number.isFinite(value)) return 1
  const magnitude = 10 ** Math.floor(Math.log10(value))
  const fraction = value / magnitude
  const step = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10
  return step * magnitude
}

/** Evenly spaced tick values from 0 to `max`, inclusive. */
export const ticksTo = (max: number, count = 4): number[] =>
  Array.from({ length: count + 1 }, (_, i) => (max / count) * i)

export const clamp = (value: number, low: number, high: number) => Math.min(high, Math.max(low, value))

/** Readable name for a span, keeping the recorded name available for administrators. */
const SPAN_LABELS: Record<string, string> = {
  investigation: 'Investigation run',
  handler_review: 'Handler review submitted',
  classify: 'Classify the claim',
  retrieve: 'Retrieve evidence',
  investigate: 'Investigate',
  risk: 'Estimate and prioritise',
  recommend: 'Recommend next steps',
  validate: 'Validate the brief',
  judge: 'Independent review',
  judge_metric: 'Evaluation judge',
  review: 'Handler review',
  'knowledge.retrieve': 'Fetch handling procedures',
  'synapt.retrieve': 'Synapt retrieval (with retries)',
  'synapt.login': 'Synapt sign-in',
  'synapt.initialize': 'Synapt session start',
  'synapt.list_tools': 'Synapt tool discovery',
  'synapt.call_tool': 'Synapt search call',
  'history.search': 'Search comparable claims',
  'feedback.lessons': 'Apply reviewed handler lessons',
  'models.predict': 'Statistical model estimates',
  'priority.score': 'Priority scoring',
  'judge.review': 'Independent review (background)',
}

export const spanLabel = (span: Pick<TraceSpan, 'name' | 'attributes'>): string => {
  if (span.name.startsWith('llm.')) {
    const purpose = span.name.slice(4)
    return `Model call · ${purpose}`
  }
  if (span.name === 'synapt.call_tool' && typeof span.attributes.purpose === 'string')
    return `Synapt search · ${span.attributes.purpose.replace(/_/g, ' ')}`
  return SPAN_LABELS[span.name] ?? span.name
}

export const KIND_LABEL: Record<string, string> = {
  run: 'Run',
  stage: 'Stage',
  llm: 'Model',
  tool: 'Service call',
  retrieval: 'Retrieval',
  compute: 'Computation',
  evaluation: 'Evaluation',
}

export interface WaterfallRow {
  span: TraceSpan
  /** Percent of the axis, clamped to 0..100. */
  left: number
  width: number
  /** The span runs past the right edge of the visible axis. */
  clipped: boolean
  /** Recorded after the run finished (a handler's review): shown by time, not on the axis. */
  deferred: boolean
  /** Work that continues after the brief is shown (the independent review). */
  background: boolean
}

/**
 * Lay a trace out on one axis. By default the axis ends when the run did, so a slow background
 * review does not squash the stages a handler waited for; it is drawn running off the edge.
 * Spans recorded under a later root (the handler's review, hours afterwards) sit off the axis.
 */
export function waterfall(trace: Trace, showBackground: boolean) {
  const byId = new Map(trace.spans.map((s) => [s.span_id, s]))
  const top = (span: TraceSpan): string => {
    let current = span
    for (let hops = 0; current.parent_id && byId.has(current.parent_id) && hops < 20; hops += 1) current = byId.get(current.parent_id)!
    return current.span_id
  }
  const firstRoot = trace.spans.find((s) => !s.parent_id)
  const main = (span: TraceSpan) => !firstRoot || top(span) === firstRoot.span_id
  const isBackground = (span: TraceSpan) => span.attributes.background === true
  const runMs = firstRoot ? firstRoot.duration_ms : trace.total_ms
  const mainEnd = Math.max(
    1,
    ...trace.spans.filter((s) => main(s)).map((s) => (showBackground || !isBackground(s) ? s.offset_ms + s.duration_ms : 0)),
  )
  const scale = showBackground ? mainEnd : Math.max(runMs, 1)
  const rows: WaterfallRow[] = trace.spans.map((span) => {
    const deferred = !main(span)
    const end = span.offset_ms + span.duration_ms
    const start = deferred ? 0 : clamp((span.offset_ms / scale) * 100, 0, 100)
    const right = deferred ? 0 : clamp((Math.min(end, scale) / scale) * 100, 0, 100)
    // A bar is always at least a sliver wide, and never leaves the lane: one that starts at the
    // very end of the axis is drawn against the right edge.
    const width = deferred ? 0 : Math.max(right - start, 0.6)
    const left = Math.min(start, 100 - width)
    return { span, left, width, clipped: !deferred && end > scale * 1.001, deferred, background: isBackground(span) }
  })
  return { rows, scaleMs: scale, runMs }
}

/** The three ranking methods, in the fixed order of the validated chart colours (series 1 to 3). */
export const CONTRIBUTION_SERIES = [
  { id: 'keyword', name: 'Keyword match', swatch: 'series-1' },
  { id: 'feature', name: 'Numeric similarity', swatch: 'series-2' },
  { id: 'semantic', name: 'Semantic rank', swatch: 'series-3' },
] as const

/** The kind of stage a model call belongs to, for the pill beside it. */
export const PURPOSE_LABEL: Record<string, string> = {
  classification: 'Classification',
  investigation: 'Investigation',
  recommendation: 'Recommendation',
  judge: 'Independent review',
  completion: 'Completion',
}

/** A plain word and a tone for an evaluation judge's status, however long the stored message is. */
const JUDGE_WORDS: Record<string, [string, string]> = {
  completed: ['Completed', 'teal'],
  partial: ['Partly completed', 'amber'],
  failed: ['Failed', 'rose'],
  unavailable: ['Unavailable', 'rose'],
  no_outputs: ['No outputs', 'amber'],
  not_run: ['Not run', 'violet'],
}

export function judgeWord(status: string | null | undefined, requested: boolean): [string, string] {
  if (!requested) return ['Not selected', 'violet']
  const key = String(status ?? 'not_run').split(':')[0].trim()
  return JUDGE_WORDS[key] ?? [label(key), 'amber']
}
