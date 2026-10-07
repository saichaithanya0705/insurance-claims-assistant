import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  Bot,
  Calculator,
  CheckCircle2,
  CircleDashed,
  Database,
  Download,
  FileSearch,
  Hourglass,
  Loader2,
  Network,
  PlayCircle,
  Scale,
  Sparkles,
  UserCheck,
  Workflow,
} from 'lucide-react'
import { api, type AuditEvent, type Trace, type TraceSpan } from '../lib/api'
import { cx, label, num } from '../lib/format'
import { KIND_LABEL, PURPOSE_LABEL, compactNumber, formatDuration, spanLabel, ticksTo, waterfall } from '../lib/trace'
import { Bar, Card, DataView, ErrorBox, Pill } from './ui'

const KIND_ICON = {
  run: PlayCircle,
  stage: Workflow,
  llm: Bot,
  tool: Network,
  retrieval: Database,
  compute: Calculator,
  evaluation: Scale,
} as const

const iconFor = (span: TraceSpan) => (span.name === 'review' || span.name === 'handler_review' ? UserCheck : (KIND_ICON[span.kind as keyof typeof KIND_ICON] ?? CircleDashed))

const statusPill = (status: string) =>
  status === 'error' ? <Pill tone="rose">Error</Pill> : status === 'waiting' ? <Pill tone="amber">Waiting for a person</Pill> : <Pill tone="teal">Completed</Pill>

/* ---------- Full prompt and answer, fetched on demand (administrators) ---------- */
function Exchange({ runId, eventId, title }: { runId: string; eventId: number; title: string }) {
  const [open, setOpen] = useState(false)
  const [event, setEvent] = useState<AuditEvent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const toggle = async () => {
    setOpen((value) => !value)
    if (event || loading) return
    setLoading(true)
    setError(null)
    try {
      setEvent(await api<AuditEvent>(`/api/investigations/${encodeURIComponent(runId)}/audit/${eventId}`))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }
  const messages = Array.isArray(event?.body?.messages) ? (event!.body.messages as { role?: string; content?: unknown }[]) : null
  return (
    <div className="exchange">
      <button className="btn sm" type="button" onClick={toggle} aria-expanded={open}>
        {loading ? <Loader2 size={13} className="spin" /> : <FileSearch size={13} />} {open ? 'Hide' : 'Show'} {title}
      </button>
      {open && (
        <div className="exchange-body">
          <ErrorBox message={error} />
          {messages
            ? messages.map((m, i) => (
                <details key={i} className="disclose" open={i === messages.length - 1}>
                  <summary>
                    {label(m.role)} message · {String(m.content ?? '').length.toLocaleString('en-US')} characters
                  </summary>
                  <pre className="payload">{pretty(m.content)}</pre>
                </details>
              ))
            : event && <pre className="payload">{pretty(event.body?.output ?? event.body)}</pre>}
        </div>
      )}
    </div>
  )
}

const LIMIT = 24_000
function pretty(value: unknown) {
  let text: string
  if (typeof value === 'string') {
    try {
      text = JSON.stringify(JSON.parse(value), null, 2)
    } catch {
      text = value
    }
  } else text = JSON.stringify(value, null, 2) ?? ''
  return text.length > LIMIT ? `${text.slice(0, LIMIT)}\n… ${(text.length - LIMIT).toLocaleString('en-US')} more characters not shown` : text
}

type Attempt = { attempt: number; outcome: string; elapsed_ms?: number; status_code?: number }

function ModelCall({ span, runId }: { span: TraceSpan; runId: string }) {
  const a = span.attributes
  const attempts = (Array.isArray(a.attempt_log) ? a.attempt_log : []) as Attempt[]
  const prompts = (Array.isArray(a.prompt_events) ? a.prompt_events : []) as number[]
  const output = typeof a.output_event === 'number' ? a.output_event : null
  const tokens = ['prompt_tokens', 'completion_tokens', 'total_tokens'].map((k) => (typeof a[k] === 'number' ? (a[k] as number) : null))
  return (
    <>
      <dl className="kv">
        <div>
          <dt>Purpose</dt>
          <dd>{PURPOSE_LABEL[String(a.purpose)] ?? label(a.purpose)}</dd>
        </div>
        <div>
          <dt>Model</dt>
          <dd className="mono">{String(a.model ?? '—')}</dd>
        </div>
        <div>
          <dt>Attempts</dt>
          <dd>{String(a.attempts ?? 1)}</dd>
        </div>
        {typeof a.finish_reason === 'string' && (
          <div>
            <dt>Finish reason</dt>
            <dd>{a.finish_reason}</dd>
          </div>
        )}
        {typeof a.prompt_chars === 'number' && (
          <div>
            <dt>Prompt size</dt>
            <dd>{(a.prompt_chars as number).toLocaleString('en-US')} characters</dd>
          </div>
        )}
        {typeof a.output_chars === 'number' && (
          <div>
            <dt>Answer size</dt>
            <dd>{(a.output_chars as number).toLocaleString('en-US')} characters</dd>
          </div>
        )}
      </dl>
      {tokens[2] !== null || tokens[0] !== null ? (
        <>
          <h5 className="mini-title">Token usage</h5>
          <div className="bars">
            {([['Prompt', tokens[0]], ['Completion', tokens[1]]] as const).map(([name, value]) => (
              <div className="bar-row" key={name}>
                <span className="nm">{name}</span>
                <Bar value={(value ?? 0) / Math.max(tokens[2] ?? 1, 1)} />
                <span className="vl">{compactNumber(value)}</span>
              </div>
            ))}
          </div>
          <p className="footnote">Total {compactNumber(tokens[2])} tokens as reported by the provider.</p>
        </>
      ) : (
        <p className="footnote">The provider reported no token usage for this call.</p>
      )}
      {attempts.length > 0 && (
        <>
          <h5 className="mini-title">Attempts</h5>
          <ul className="attempts">
            {attempts.map((t) => (
              <li key={t.attempt} className={t.outcome === 'ok' ? 'ok' : 'bad'}>
                <b>#{t.attempt}</b> {t.outcome === 'ok' ? 'Answer accepted' : label(t.outcome)}
                {t.status_code ? ` (HTTP ${t.status_code})` : ''}
                <span className="mono">{formatDuration(t.elapsed_ms)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <div className="exchange-row">
        {prompts.map((id, i) => (
          <Exchange key={id} runId={runId} eventId={id} title={prompts.length > 1 ? `prompt (attempt ${i + 1})` : 'prompt'} />
        ))}
        {output !== null && <Exchange runId={runId} eventId={output} title="validated answer" />}
      </div>
    </>
  )
}

// Attributes the model-call panel already presents; the rest fall through to the generic list.
const SHOWN_FOR_MODEL_CALLS = new Set([
  'attempt_log', 'prompt_events', 'output_event', 'purpose', 'model', 'attempts', 'finish_reason', 'prompt_chars', 'output_chars',
  'prompt_tokens', 'completion_tokens', 'total_tokens', 'prompt_messages', 'max_attempts', 'structured', 'temperature', 'max_tokens',
])

export function SpanDetail({ span, runId }: { span: TraceSpan; runId: string }) {
  const isModel = span.kind === 'llm'
  const other = Object.fromEntries(Object.entries(span.attributes).filter(([k, v]) => v !== null && k !== 'reconstructed' && !(isModel && SHOWN_FOR_MODEL_CALLS.has(k))))
  return (
    <section className="span-detail" aria-label={`Details of ${spanLabel(span)}`}>
      <header>
        <h4>{spanLabel(span)}</h4>
        <div className="chips">
          <Pill>{KIND_LABEL[span.kind] ?? span.kind}</Pill>
          {statusPill(span.status)}
          {span.attributes.background === true && <Pill tone="sky">Background</Pill>}
          {span.attributes.reconstructed === true && <Pill tone="violet">Approximate</Pill>}
        </div>
      </header>
      <dl className="kv">
        <div>
          <dt>Recorded name</dt>
          <dd className="mono">{span.name}</dd>
        </div>
        <div>
          <dt>Started</dt>
          <dd>{span.offset_ms < 1 ? 'At the start of the trace' : `+${formatDuration(span.offset_ms)} into the trace`}</dd>
        </div>
        <div>
          <dt>Duration</dt>
          <dd>{formatDuration(span.duration_ms)}</dd>
        </div>
      </dl>
      {isModel && <ModelCall span={span} runId={runId} />}
      {Object.keys(other).length > 0 && (
        <details className="disclose" open={!isModel}>
          <summary>{isModel ? 'Other attributes' : 'What this step recorded'}</summary>
          <div className="disclose-body">
            <DataView value={other} />
          </div>
        </details>
      )}
    </section>
  )
}

/* ---------- Waterfall ---------- */
export function TraceBody({ trace, runId, onExplain }: { trace: Trace; runId: string; onExplain?: () => void }) {
  const [selected, setSelected] = useState<string | null>(null)
  const [showBackground, setShowBackground] = useState(false)
  const layout = useMemo(() => waterfall(trace, showBackground), [trace, showBackground])
  const active = trace.spans.find((s) => s.span_id === selected) ?? trace.spans.find((s) => s.kind === 'llm') ?? trace.spans[0]
  const summary = trace.summary
  const hasBackground = layout.rows.some((r) => r.background)
  const modelMs = (background: boolean) => trace.spans.filter((s) => s.kind === 'llm' && (s.attributes.background === true) === background).reduce((total, s) => total + s.duration_ms, 0)
  const waitedMs = modelMs(false)
  const backgroundMs = modelMs(true)
  const exportTrace = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(trace, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `trace-${runId}.json`
    link.click()
    URL.revokeObjectURL(url)
  }
  return (
    <>
      <div className="trace-kpis">
        <div className="kpi">
          <small>Run time</small>
          <strong>{formatDuration(summary?.duration_ms ?? trace.total_ms)}</strong>
          <span>until the brief was ready</span>
        </div>
        <div className="kpi">
          <small>Model calls</small>
          <strong>{summary?.llm.calls ?? 0}</strong>
          <span>
            {summary?.llm.retries ? `${summary.llm.retries} retried · ` : ''}
            {formatDuration(waitedMs)} waiting on models{backgroundMs > 0 ? ` + ${formatDuration(backgroundMs)} in the background` : ''}
          </span>
        </div>
        <div className="kpi">
          <small>Tokens</small>
          <strong>{compactNumber(summary?.llm.tokens.total)}</strong>
          <span>
            {compactNumber(summary?.llm.tokens.prompt)} in · {compactNumber(summary?.llm.tokens.completion)} out
          </span>
        </div>
        <div className="kpi">
          <small>Steps recorded</small>
          <strong>{trace.spans.length}</strong>
          <span>{summary?.errors.length ? `${summary.errors.length} with errors` : 'no errors'}</span>
        </div>
      </div>

      {trace.source === 'reconstructed' ? (
        <div className="notice" role="note">
          <AlertTriangle size={16} />
          <span>
            <b>Reconstructed trace.</b> {trace.note}
          </span>
        </div>
      ) : (
        <p className="footnote" style={{ marginTop: 0 }}>
          Recorded while the investigation ran. Timings are measured; a model call’s tokens are those the provider reported.
        </p>
      )}

      <Card className="wf-card" spot={false}>
        <div className="card-head">
          <h2>
            <span className="head-icon sky">
              <Hourglass size={15} />
            </span>
            Execution timeline
          </h2>
          <div className="actions-row" style={{ margin: 0 }}>
            {hasBackground && (
              <label className="switch">
                <input type="checkbox" checked={showBackground} onChange={(e) => setShowBackground(e.target.checked)} />
                <span className="track">
                  <span className="thumb" />
                </span>
                <span>Show background review to scale</span>
              </label>
            )}
            <button className="btn sm" type="button" onClick={exportTrace}>
              <Download size={13} /> Export JSON
            </button>
            {onExplain && (
              <button className="btn sm" type="button" onClick={onExplain}>
                <Sparkles size={13} /> Explain this answer
              </button>
            )}
          </div>
        </div>
        <div className="card-body">
          <div className="wf" aria-label="Execution timeline">
            <div className="wf-axis">
              <span className="wf-name">Step</span>
              <span className="wf-scale" aria-hidden="true">
                {ticksTo(layout.scaleMs, 4).map((tick, i) => (
                  <span key={i} style={{ left: `${i * 25}%` }} className={cx(i === 4 && 'end')}>
                    {formatDuration(tick)}
                  </span>
                ))}
              </span>
              <span className="wf-dur">Time</span>
            </div>
            <ol>
              {layout.rows.map((row) => {
                const { span } = row
                const Icon = iconFor(span)
                const on = span.span_id === active?.span_id
                return (
                  <li key={span.span_id}>
                    <button type="button" className={cx('wf-row', on && 'on', span.kind === 'stage' && 'stage', span.kind === 'run' && 'run', span.status)} aria-pressed={on} onClick={() => setSelected(span.span_id)}>
                      <span className="wf-name" style={{ paddingLeft: span.depth * 16 }}>
                        {span.status === 'error' ? <AlertTriangle size={13} /> : span.status === 'waiting' ? <Hourglass size={13} /> : <Icon size={13} />}
                        <span>{spanLabel(span)}</span>
                        {row.background && <small>background</small>}
                      </span>
                      <span className="wf-lane">
                        {row.deferred ? (
                          <em>recorded after the run</em>
                        ) : (
                          <i className={cx('wf-bar', span.status, row.clipped && 'clipped', row.background && 'bg')} style={{ left: `${row.left}%`, width: `${row.width}%` }} />
                        )}
                      </span>
                      <span className="wf-dur">{formatDuration(span.duration_ms)}</span>
                    </button>
                  </li>
                )
              })}
            </ol>
          </div>
          {!showBackground && hasBackground && <p className="footnote">The axis ends when the brief was ready. The independent review continues in the background; switch the option on to see it to scale.</p>}
        </div>
      </Card>

      {active && (
        <Card className="wf-detail" spot={false}>
          <div className="card-body">
            <SpanDetail span={active} runId={runId} />
          </div>
        </Card>
      )}
    </>
  )
}

/* ---------- Loader ---------- */
export function TraceView({ runId, onBack, onExplain, backLabel = 'All traces' }: { runId: string; onBack?: () => void; onExplain?: (runId: string) => void; backLabel?: string }) {
  const [trace, setTrace] = useState<Trace | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  // Callers key this component by run ID, so a new run always starts from a clean state.
  useEffect(() => {
    const controller = new AbortController()
    api<Trace>(`/api/investigations/${encodeURIComponent(runId)}/trace`, { signal: controller.signal })
      .then((result) => {
        if (!Array.isArray(result.spans)) throw new Error('The trace response was invalid.')
        if (!controller.signal.aborted) setTrace(result)
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError((e as Error).message)
      })
    return () => controller.abort()
  }, [runId, attempt])
  return (
    <section aria-label="Query trace">
      <div className="case-toolbar">
        <div className="case-toolbar-nav">
          {onBack && (
            <button className="btn ghost" type="button" onClick={onBack}>
              <ArrowLeft size={15} /> {backLabel}
            </button>
          )}
        </div>
        <span className="mono" title={runId}>
          Run {runId}
        </span>
      </div>
      <ErrorBox message={error} />
      {error && (
        <div className="case-tools">
          <button
            className="btn"
            type="button"
            onClick={() => {
              setError(null)
              setAttempt((n) => n + 1)
            }}
          >
            Retry
          </button>
        </div>
      )}
      {!trace && !error && <div className="skeleton" style={{ height: 320 }} aria-busy="true" />}
      {trace && <TraceBody trace={trace} runId={runId} onExplain={onExplain ? () => onExplain(runId) : undefined} />}
      {trace && trace.spans.length > 0 && (
        <p className="footnote">
          <CheckCircle2 size={12} style={{ verticalAlign: '-2px' }} /> {trace.spans.length} steps · started {new Date(trace.started_at ?? '').toLocaleString()} · {num(trace.total_ms / 1000, 2)} s end to end including background work.
        </p>
      )}
    </section>
  )
}
