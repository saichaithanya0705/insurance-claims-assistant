import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { Activity, AlertTriangle, ChevronRight, Gauge, ListTree, RefreshCw, Search } from 'lucide-react'
import { api, type ObservabilitySummary, type TraceList, type TraceListItem } from '../lib/api'
import { cx, label, num, pct, shortTitle } from '../lib/format'
import { compactNumber, formatDuration } from '../lib/trace'
import { Card, ErrorBox, Pill } from './ui'
import { ChartFrame, ColumnChart, LatencyBars } from './Charts'
import { TraceView } from './TraceView'
import { STAGES } from './Pipeline'

const WINDOWS = [
  { key: '24h', label: 'Last 24 hours' },
  { key: '7d', label: 'Last 7 days' },
  { key: '30d', label: 'Last 30 days' },
  { key: 'all', label: 'All time' },
]
const ORIGINS = [
  { key: 'all', label: 'All runs' },
  { key: 'user', label: 'Handler queries' },
  { key: 'evaluation', label: 'Evaluation suite' },
]
const STATUS_ORDER = ['awaiting_review', 'needs_manual_review', 'reviewed', 'revision_requested', 'failed']
const STATUS_TONE: Record<string, string> = { awaiting_review: 'amber', needs_manual_review: 'amber', reviewed: 'teal', revision_requested: 'violet', failed: 'rose' }
const stageName = (key: string) => STAGES.find((s) => s.key === key)?.name ?? label(key)

function Kpi({ title, value, sub, tone }: { title: string; value: string; sub?: string; tone?: 'ok' | 'warn' | 'bad' }) {
  return (
    <div className={cx('kpi', tone)}>
      <small>{title}</small>
      <strong>{value}</strong>
      {sub && <span>{sub}</span>}
    </div>
  )
}

function Meter({ value, tone }: { value: number | null; tone?: 'amber' }) {
  return (
    <div className="meter" role="img" aria-label={value === null ? 'No data' : `${Math.round(value * 100)} percent`}>
      <i className={tone} style={{ width: `${Math.max(0, Math.min(1, value ?? 0)) * 100}%` }} />
    </div>
  )
}

const axisLabel = (windowKey: string) => (d: { key: string }) => {
  const moment = new Date(d.key)
  return windowKey === '24h' ? moment.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }) : moment.toLocaleDateString([], { month: 'short', day: 'numeric' })
}
const bucketText = (windowKey: string, key: string) => {
  const moment = new Date(key)
  return windowKey === '24h' ? moment.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : moment.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
}

/* ======================================================================
   Dashboard body (presentational: it renders whatever summary it is given)
   ====================================================================== */
export function ObservabilityDashboard({ summary, onOpenTrace }: { summary: ObservabilitySummary; onOpenTrace?: (runId: string) => void }) {
  const { queries, latency_ms: latency, llm, quality, coverage } = summary
  const stageRows = summary.stages
  const empty = queries.total === 0
  return (
    <>
      <div className="kpi-row" aria-label="Headline figures">
        <Kpi title="Queries" value={String(queries.total)} sub={empty ? 'none in this window' : `${queries.failed} failed · ${pct(queries.success_rate, 0)} completed`} tone={queries.failed ? 'warn' : undefined} />
        <Kpi title="Median run time" value={formatDuration(latency.p50)} sub={`95th percentile ${formatDuration(latency.p95)}`} />
        <Kpi title="Model calls" value={String(llm.calls)} sub={`${llm.retries} retried · ${llm.failures} failed`} tone={llm.failures ? 'warn' : undefined} />
        <Kpi title="Tokens per query" value={compactNumber(llm.tokens_per_query)} sub={`${compactNumber(llm.tokens.total)} in total`} />
        <Kpi title="Validation" value={quality.validation_pass_rate === null ? '—' : pct(quality.validation_pass_rate, 0)} sub={`${quality.validation_passed} of ${quality.validated} briefs passed`} />
        <Kpi title="Independent review" value={quality.judge.pass_rate === null ? '—' : pct(quality.judge.pass_rate, 0)} sub={quality.judge.completed ? `${quality.judge.completed} reviewed · mean score ${num(quality.judge.mean_score, 2)}` : 'no completed reviews'} />
      </div>

      {empty ? (
        <div className="small-empty">No queries were traced in this window. Run an investigation, or widen the time range.</div>
      ) : (
        <>
          <div className="obs-grid">
            <Card spot={false}>
              <div className="card-body">
                <ChartFrame
                  title="Queries over time"
                  subtitle={`Investigations started per ${summary.window === '24h' ? 'hour' : 'day'}`}
                  table={{ columns: [summary.window === '24h' ? 'Hour' : 'Day', 'Queries', 'Failed', 'Median run time'], rows: summary.series.map((b) => [bucketText(summary.window, b.bucket), b.queries, b.failed, formatDuration(b.p50_ms)]) }}
                >
                  <ColumnChart data={summary.series.map((b) => ({ key: b.bucket, label: bucketText(summary.window, b.bucket), value: b.queries, failed: b.failed }))} axisLabel={axisLabel(summary.window)} />
                </ChartFrame>
              </div>
            </Card>
            <Card spot={false}>
              <div className="card-head">
                <h2>
                  <span className="head-icon teal">
                    <Gauge size={15} />
                  </span>
                  Outcomes
                </h2>
              </div>
              <div className="card-body">
                <ul className="outcomes">
                  {STATUS_ORDER.filter((s) => queries.by_status[s]).concat(Object.keys(queries.by_status).filter((s) => !STATUS_ORDER.includes(s))).map((status) => (
                    <li key={status}>
                      <Pill tone={STATUS_TONE[status]} dot>
                        {label(status)}
                      </Pill>
                      <span className="meter-wrap">
                        <Meter value={queries.by_status[status] / queries.total} tone={status === 'failed' ? 'amber' : undefined} />
                      </span>
                      <b>{queries.by_status[status]}</b>
                    </li>
                  ))}
                </ul>
                <p className="footnote">
                  {queries.by_origin.user ?? 0} handler {queries.by_origin.user === 1 ? 'query' : 'queries'} · {queries.by_origin.evaluation ?? 0} from the evaluation suite · {queries.by_mode.live ?? 0} with live models · {queries.by_mode.fixture ?? 0} in rule-based mode.
                </p>
              </div>
            </Card>
          </div>

          <div className="obs-grid even">
            <Card spot={false}>
              <div className="card-body">
                <ChartFrame
                  title="Where the time goes"
                  subtitle="Median and 95th percentile per workflow stage"
                  table={{ columns: ['Stage', 'Runs', 'Median', '95th percentile', 'Slowest', 'With errors'], rows: stageRows.map((s) => [stageName(s.stage), s.count, formatDuration(s.p50), formatDuration(s.p95), formatDuration(s.max), s.errors]) }}
                >
                  <LatencyBars rows={stageRows.map((s) => ({ key: s.stage, label: stageName(s.stage), p50: s.p50, p95: s.p95, count: s.count, errors: s.errors }))} />
                </ChartFrame>
                <p className="footnote">The review stage only marks the pause for a handler. The independent review runs in the background and is shown under model usage.</p>
              </div>
            </Card>
            <Card spot={false}>
              <div className="card-head">
                <h2>
                  <span className="head-icon violet">
                    <Activity size={15} />
                  </span>
                  Model usage
                </h2>
                <span className="step-tag">{compactNumber(llm.tokens.total)} tokens</span>
              </div>
              <div className="card-body">
                {llm.by_purpose.length === 0 ? (
                  <div className="small-empty">No model calls in this window. Rule-based runs call no language model.</div>
                ) : (
                  <div className="chart-table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th scope="col">Purpose</th>
                          <th scope="col">Calls</th>
                          <th scope="col">Median</th>
                          <th scope="col">Tokens</th>
                        </tr>
                      </thead>
                      <tbody>
                        {llm.by_purpose.map((row) => (
                          <tr key={`${row.purpose}-${row.model}`}>
                            <td className="nowrap">
                              {label(row.purpose)}
                              <small className="cell-sub mono clip" title={row.model ?? undefined}>
                                {row.model ?? 'unknown model'}
                              </small>
                            </td>
                            <td>
                              {row.calls}
                              {row.retries > 0 && <small className="cell-sub">{row.retries} retried</small>}
                              {row.failures > 0 && <small className="cell-sub txt-bad">{row.failures} failed</small>}
                            </td>
                            <td>{formatDuration(row.latency_ms.p50)}</td>
                            <td>{compactNumber(row.tokens)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </Card>
          </div>

          <div className="obs-grid">
            <Card spot={false}>
              <div className="card-head">
                <h2>
                  <span className="head-icon amber">
                    <AlertTriangle size={15} />
                  </span>
                  Recent errors
                </h2>
                <span className="step-tag">{summary.errors.length}</span>
              </div>
              <div className="card-body">
                {summary.errors.length === 0 ? (
                  <div className="small-empty">No errors were recorded in this window.</div>
                ) : (
                  <ul className="error-list">
                    {summary.errors.map((e, i) => (
                      <li key={`${e.run_id}-${e.span}-${i}`}>
                        <span>
                          <b>{e.span}</b> <Pill tone="rose">{e.error_type ?? 'Error'}</Pill>
                        </span>
                        <small>{new Date(e.time).toLocaleString()}</small>
                        {onOpenTrace && (
                          <button className="btn sm ghost" type="button" onClick={() => onOpenTrace(e.run_id)}>
                            Open trace <ChevronRight size={13} />
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                <p className="footnote">Only the error type is recorded; provider messages are never copied into a trace.</p>
              </div>
            </Card>
            <Card spot={false}>
              <div className="card-head">
                <h2>
                  <span className="head-icon sky">
                    <ListTree size={15} />
                  </span>
                  Quality gates
                </h2>
              </div>
              <div className="card-body">
                <dl className="kv gates">
                  <div>
                    <dt>Mechanical validation passed</dt>
                    <dd>
                      {quality.validation_passed} of {quality.validated}
                    </dd>
                  </div>
                  <div>
                    <dt>Independent review</dt>
                    <dd>
                      {quality.judge.passed} clear · {quality.judge.completed - quality.judge.passed} with concerns · {quality.judge.failed} failed · {quality.judge.pending} pending · {quality.judge.skipped} not run
                    </dd>
                  </div>
                  <div>
                    <dt>Handler decisions</dt>
                    <dd>
                      {quality.handler.accepted} accepted · {quality.handler.revision_requested} revision · {quality.handler.awaiting} awaiting
                    </dd>
                  </div>
                </dl>
                <p className="footnote">The independent review is advisory and probabilistic. Validation is deterministic and gates acceptance. Neither decides a claim.</p>
              </div>
            </Card>
          </div>

          <details className="disclose obs-details">
            <summary>Every operation · {summary.operations.length}</summary>
            <div className="disclose-body">
              <div className="chart-table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">Operation</th>
                      <th scope="col">Kind</th>
                      <th scope="col">Calls</th>
                      <th scope="col">Median</th>
                      <th scope="col">95th percentile</th>
                      <th scope="col">Errors</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.operations.map((op) => (
                      <tr key={op.name}>
                        <td className="mono">{op.name}</td>
                        <td>{label(op.kind)}</td>
                        <td>{op.count}</td>
                        <td>{formatDuration(op.p50)}</td>
                        <td>{formatDuration(op.p95)}</td>
                        <td>{op.errors || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {summary.operations.length === 0 && <p className="footnote">Operations are recorded for runs traced live. Reconstructed runs only have stage and model-call timings.</p>}
            </div>
          </details>
        </>
      )}

      <details className="disclose obs-details">
        <summary>API traffic · {summary.api.requests.toLocaleString('en-US')} requests</summary>
        <div className="disclose-body">
          <p className="section-desc">
            {summary.api.server_errors} server errors · {summary.api.client_errors} client errors (such as sign-in required or not found) · median {formatDuration(summary.api.latency_ms.p50)}, 95th percentile {formatDuration(summary.api.latency_ms.p95)}. Routes are shown as templates; identifiers are never stored.
          </p>
          <div className="chart-table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Route</th>
                  <th scope="col">Requests</th>
                  <th scope="col">Median</th>
                  <th scope="col">95th percentile</th>
                  <th scope="col">4xx</th>
                  <th scope="col">5xx</th>
                </tr>
              </thead>
              <tbody>
                {summary.api.routes.map((r) => (
                  <tr key={`${r.method} ${r.route}`}>
                    <td className="mono">
                      {r.method} {r.route}
                    </td>
                    <td>{r.count}</td>
                    <td>{formatDuration(r.p50)}</td>
                    <td>{formatDuration(r.p95)}</td>
                    <td>{r.client_errors || '—'}</td>
                    <td>{r.server_errors || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </details>

      <p className="footnote">
        {coverage.recorded} {coverage.recorded === 1 ? 'run was' : 'runs were'} recorded live and {coverage.reconstructed} reconstructed. {coverage.reconstructed > 0 && coverage.note}
      </p>
    </>
  )
}

/* ======================================================================
   Trace explorer
   ====================================================================== */
const judgePill = (item: TraceListItem) =>
  item.judge_status === 'completed' ? (
    <Pill tone={item.judge_passed ? 'teal' : 'amber'}>{item.judge_passed ? 'No concerns' : 'Concerns'}</Pill>
  ) : item.judge_status === 'pending' ? (
    <Pill tone="sky">In progress</Pill>
  ) : item.judge_status === 'failed' ? (
    <Pill tone="rose">Failed</Pill>
  ) : (
    <span className="txt-muted">Not run</span>
  )

export function TraceTable({ items, onOpen }: { items: TraceListItem[]; onOpen: (runId: string) => void }) {
  const slowest = Math.max(1, ...items.map((i) => i.duration_ms ?? 0))
  return (
    <ul className="trace-list">
      <li className="trace-list-head" aria-hidden="true">
        <span>Query</span>
        <span>Outcome</span>
        <span>Run time</span>
        <span>Model calls</span>
        <span>Checks</span>
      </li>
      {items.map((item) => (
        <li key={item.run_id}>
          <button className="trace-row" type="button" onClick={() => onOpen(item.run_id)} aria-label={`Open trace: ${item.title}`}>
            <span className="trace-main">
              <strong>{shortTitle(item.title, 84) || 'Untitled claim'}</strong>
              <span>
                {item.started_at ? new Date(item.started_at).toLocaleString() : 'Time unknown'} · <span className="mono">{item.run_id.slice(0, 8)}</span>
                {item.origin === 'evaluation' && <Pill tone="violet">Evaluation suite</Pill>}
                {item.trace_source === 'reconstructed' && <Pill tone="violet">Reconstructed</Pill>}
                {item.trace_source === null && <Pill>No trace</Pill>}
              </span>
            </span>
            <span className="trace-status">
              <Pill tone={STATUS_TONE[item.status]} dot>
                {label(item.status)}
              </Pill>
              {item.errors > 0 && <small className="txt-bad">{item.errors} error{item.errors === 1 ? '' : 's'}</small>}
            </span>
            <span className="trace-time">
              <b>{formatDuration(item.duration_ms)}</b>
              <i style={{ width: `${((item.duration_ms ?? 0) / slowest) * 100}%` }} aria-hidden="true" />
            </span>
            <span className="trace-llm">
              {item.llm_calls === null ? '—' : item.llm_calls}
              {item.tokens ? <small>{compactNumber(item.tokens)} tokens</small> : <small>{item.agent_mode === 'fixture' ? 'rule-based' : ' '}</small>}
            </span>
            <span className="trace-checks">
              {item.validation_passed === null ? <span className="txt-muted">—</span> : <Pill tone={item.validation_passed ? 'teal' : 'amber'}>{item.validation_passed ? 'Validated' : 'Needs attention'}</Pill>}
              {judgePill(item)}
            </span>
            <ChevronRight size={16} className="queue-chev" aria-hidden="true" />
          </button>
        </li>
      ))}
    </ul>
  )
}

function TraceExplorer({ onOpen }: { onOpen: (runId: string) => void }) {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<TraceList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  const limit = 15
  // Loading is whatever request has not finished yet; the previous page stays visible meanwhile.
  const requestKey = `${q.trim()}|${status}|${offset}|${tick}`
  const [loadedKey, setLoadedKey] = useState('')
  const loading = loadedKey !== requestKey
  useEffect(() => {
    const controller = new AbortController()
    const params = new URLSearchParams({ offset: String(offset), limit: String(limit) })
    if (q.trim()) params.set('q', q.trim())
    if (status) params.set('status', status)
    // A short pause lets typing settle before each search.
    const timer = window.setTimeout(() => {
      api<TraceList>(`/api/traces?${params}`, { signal: controller.signal })
        .then((result) => {
          if (!Array.isArray(result.items)) throw new Error('The trace list was invalid.')
          if (!controller.signal.aborted) {
            setPage(result)
            setError(null)
          }
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError((e as Error).message)
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoadedKey(requestKey)
        })
    }, 220)
    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [q, status, offset, tick, requestKey])
  return (
    <Card spot={false} className="case-library">
      <div className="queue-bar">
        <label className="queue-search">
          <Search size={16} aria-hidden="true" />
          <input className="input" type="search" value={q} placeholder="Search queries by description, type or state…" aria-label="Search traced queries" onChange={(e) => (setOffset(0), setQ(e.target.value))} />
        </label>
        <div className="field queue-sort">
          <select aria-label="Filter by outcome" value={status} onChange={(e) => (setOffset(0), setStatus(e.target.value))}>
            <option value="">All outcomes</option>
            {STATUS_ORDER.map((s) => (
              <option key={s} value={s}>
                {label(s)}
              </option>
            ))}
          </select>
        </div>
        <button className="btn" type="button" onClick={() => setTick((n) => n + 1)} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : undefined} /> Refresh
        </button>
      </div>
      <ErrorBox message={error} />
      <div className="queue-meta">
        {page ? `${page.total} traced ${page.total === 1 ? 'query' : 'queries'}` : 'Loading…'}
        <span>Newest first · open one to see every step</span>
      </div>
      <div className={cx('refetch', loading && page && 'dim')}>
        {page && page.items.length === 0 ? <div className="small-empty">No queries match. Clear the search or the outcome filter.</div> : page && <TraceTable items={page.items} onOpen={onOpen} />}
        {!page && !error && <div className="skeleton" style={{ height: 240 }} aria-busy="true" />}
      </div>
      {page && page.total > limit && (
        <div className="pager">
          <span>
            Showing {offset + 1}–{Math.min(offset + limit, page.total)} of {page.total}
          </span>
          <div>
            <button className="btn" type="button" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>
              Previous
            </button>
            <button className="btn" type="button" disabled={loading || offset + limit >= page.total} onClick={() => setOffset(offset + limit)}>
              Next
            </button>
          </div>
        </div>
      )}
    </Card>
  )
}

/* ======================================================================
   Page
   ====================================================================== */
type Tab = 'overview' | 'traces'

export function ObservabilityView({ focusRun, onExplain }: { focusRun?: string | null; onExplain: (runId: string) => void }) {
  const [tab, setTab] = useState<Tab>(focusRun ? 'traces' : 'overview')
  const [selected, setSelected] = useState<string | null>(focusRun ?? null)
  const [windowKey, setWindowKey] = useState('7d')
  const [origin, setOrigin] = useState('all')
  const [summary, setSummary] = useState<ObservabilitySummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)
  // The figures stay on screen, dimmed, until the request for the new scope finishes.
  const scopeKey = `${windowKey}|${origin}|${refresh}`
  const [loadedKey, setLoadedKey] = useState('')
  const loading = loadedKey !== scopeKey
  useEffect(() => {
    const controller = new AbortController()
    api<ObservabilitySummary>(`/api/observability/summary?window=${windowKey}&origin=${origin}`, { signal: controller.signal })
      .then((result) => {
        if (!result?.queries || !Array.isArray(result.series)) throw new Error('The metrics response was invalid.')
        if (!controller.signal.aborted) {
          setSummary(result)
          setError(null)
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError((e as Error).message)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadedKey(scopeKey)
      })
    return () => controller.abort()
  }, [windowKey, origin, scopeKey])

  const choose = (runId: string | null) => {
    setSelected(runId)
    window.scrollTo({ top: 0, behavior: 'instant' })
  }
  const openTrace = (runId: string) => {
    setTab('traces')
    choose(runId)
  }

  const tabs: { key: Tab; label: string; icon: typeof Activity }[] = [
    { key: 'overview', label: 'Overview', icon: Gauge },
    { key: 'traces', label: 'Query traces', icon: ListTree },
  ]

  return (
    <motion.section aria-labelledby="obs-title" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Operations</div>
          <h1 id="obs-title" className="display" tabIndex={-1}>
            Observability
          </h1>
          <p className="subtitle">Every query leaves a trace. See how the system is behaving, then open any query to see each step, model call and check it went through.</p>
        </div>
      </div>

      <div className="tabs flat" role="tablist" aria-label="Observability views">
        {tabs.map((t) => {
          const Icon = t.icon
          return (
            <button
              key={t.key}
              id={`obs-tab-${t.key}`}
              role="tab"
              aria-selected={tab === t.key}
              aria-controls={`obs-panel-${t.key}`}
              className={cx('tab', tab === t.key && 'active')}
              onClick={() => {
                setTab(t.key)
                if (t.key === 'traces') setSelected(null)
              }}
            >
              <Icon size={14} /> {t.label}
            </button>
          )
        })}
      </div>

      {tab === 'overview' && (
        <div id="obs-panel-overview" role="tabpanel" aria-labelledby="obs-tab-overview">
          <div className="filter-row" role="group" aria-label="Scope of every figure below">
            <div className="field">
              <label htmlFor="obs-window">Time range</label>
              <select id="obs-window" value={windowKey} onChange={(e) => setWindowKey(e.target.value)}>
                {WINDOWS.map((w) => (
                  <option key={w.key} value={w.key}>
                    {w.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="obs-origin">Runs</label>
              <select id="obs-origin" value={origin} onChange={(e) => setOrigin(e.target.value)}>
                {ORIGINS.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <button className="btn" type="button" onClick={() => setRefresh((n) => n + 1)} disabled={loading}>
              <RefreshCw size={14} className={loading ? 'spin' : undefined} /> Refresh
            </button>
            {summary && <span className="step-tag">Updated {new Date(summary.generated_at).toLocaleTimeString()}</span>}
          </div>
          <ErrorBox message={error} />
          {!summary && !error && <div className="skeleton" style={{ height: 360 }} aria-busy="true" />}
          {summary && (
            <div className={cx('refetch', loading && 'dim')}>
              <ObservabilityDashboard summary={summary} onOpenTrace={openTrace} />
            </div>
          )}
        </div>
      )}

      {tab === 'traces' && (
        <div id="obs-panel-traces" role="tabpanel" aria-labelledby="obs-tab-traces">
          {selected ? <TraceView key={selected} runId={selected} onBack={() => choose(null)} onExplain={onExplain} /> : <TraceExplorer onOpen={choose} />}
        </div>
      )}
    </motion.section>
  )
}
