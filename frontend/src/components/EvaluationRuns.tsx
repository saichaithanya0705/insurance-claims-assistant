import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api, type EvaluationRunItem, type EvaluationRuns as EvaluationRunsData } from '../lib/api'
import { label, num } from '../lib/format'
import { compactNumber, formatDuration, judgeWord } from '../lib/trace'
import { ErrorBox, Pill } from './ui'

// Each evaluation-suite run: the golden cases, and the LLM judge's scores when it was selected. The judge's model
// calls are traced under each case's own run, so a case's trace shows them too.

const when = (iso: string) =>
  new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })

const secondsText = (value: number | null) => (value === null ? '—' : formatDuration(value * 1000))

function Fact({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="evalruns-fact">
      <dt>{term}</dt>
      <dd>{children}</dd>
    </div>
  )
}

export function RunCard({ item, onOpenTrace }: { item: EvaluationRunItem; onOpenTrace?: (runId: string) => void }) {
  const { cases, judge } = item
  const [word, tone] = judgeWord(judge.status, judge.requested)
  const calls = judge.model_calls
  const expected = judge.expected_metrics ?? 0
  return (
    <article className="evalruns-card" aria-label={`Evaluation run ${when(item.time)}`}>
      <header className="evalruns-head">
        <h3 className="evalruns-title">{when(item.time)}</h3>
        <span className="evalruns-pills">
          <Pill tone={item.overall_passed ? 'teal' : 'amber'} dot>
            {item.overall_passed ? 'Passed' : 'Not passed'}
          </Pill>
          <Pill tone={tone}>Judge: {word}</Pill>
          {item.mode && <Pill tone="violet">{label(item.mode)}</Pill>}
        </span>
      </header>
      <dl className="evalruns-facts">
        <Fact term="Golden cases">
          {cases.passed ?? '—'} of {cases.total ?? '—'} passed
        </Fact>
        <Fact term="Took">{secondsText(item.duration_seconds)}</Fact>
        {judge.requested && (
          <>
            <Fact term="Judge model">
              {judge.model ?? '—'}
              {judge.independent === false ? ' (same as the writing model)' : ''}
            </Fact>
            <Fact term="Metrics scored">
              {judge.completed_metrics ?? 0} of {expected || '—'}, {judge.passed_metrics ?? 0} met the {judge.threshold ?? 0.5} threshold
            </Fact>
            <Fact term="Mean score">{num(judge.mean_score)}</Fact>
            <Fact term="Judge model calls">
              {calls.traced
                ? `${calls.calls} calls · ${compactNumber(calls.tokens)} tokens · ${formatDuration(calls.total_ms)} of model time`
                : 'Not traced (this run was saved before judge calls were traced)'}
            </Fact>
          </>
        )}
      </dl>
      {judge.metrics.length > 0 && (
        <table className="evalruns-metrics">
          <thead>
            <tr>
              <th scope="col">Judge metric</th>
              <th scope="col">Scored</th>
              <th scope="col">Met threshold</th>
              <th scope="col">Mean score</th>
            </tr>
          </thead>
          <tbody>
            {judge.metrics.map((m) => (
              <tr key={m.metric}>
                <td className="evalruns-metric-name">{m.metric.replace(/ \[GEval\]$/, '')}</td>
                <td data-label="Scored">{m.completed}{m.failed + m.skipped > 0 ? ` (+${m.failed + m.skipped} not scored)` : ''}</td>
                <td data-label="Met threshold">{m.passed}</td>
                <td data-label="Mean score">{num(m.mean_score)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {cases.items.length > 0 && onOpenTrace && (
        <div className="evalruns-cases" role="group" aria-label="Open a case's trace">
          <span className="evalruns-cases-label">Open a case trace</span>
          {cases.items.map((c) =>
            c.run_id ? (
              <button key={c.run_id} className="btn evalruns-case" type="button" onClick={() => onOpenTrace(c.run_id as string)}>
                {label(c.case)}
              </button>
            ) : null,
          )}
        </div>
      )}
    </article>
  )
}

export function EvaluationRuns({ onOpenTrace }: { onOpenTrace?: (runId: string) => void }) {
  const [data, setData] = useState<EvaluationRunsData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refresh, setRefresh] = useState(0)
  const [loadedFor, setLoadedFor] = useState(-1)
  const loading = loadedFor !== refresh
  useEffect(() => {
    const controller = new AbortController()
    api<EvaluationRunsData>('/api/observability/evaluations?limit=20', { signal: controller.signal })
      .then((result) => {
        if (!Array.isArray(result?.items)) throw new Error('The evaluation list was invalid.')
        if (!controller.signal.aborted) {
          setData(result)
          setError(null)
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError((e as Error).message)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadedFor(refresh)
      })
    return () => controller.abort()
  }, [refresh])

  return (
    <section className="evalruns" aria-labelledby="evalruns-heading">
      <div className="evalruns-top">
        <div>
          <h2 className="evalruns-heading" id="evalruns-heading">Evaluation runs</h2>
          <p className="evalruns-desc">
            Each run of the evaluation suite: the golden cases and, when selected, the LLM judge scoring every case's brief.
            Evaluation cases also appear as "Evaluation suite" runs in the overview and under Query traces; the judge's model calls
            are recorded inside each case's own trace.
          </p>
        </div>
        <button className="btn" type="button" onClick={() => setRefresh((n) => n + 1)} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : undefined} /> Refresh
        </button>
      </div>
      <ErrorBox message={error} />
      {!data && !error && <div className="skeleton" style={{ height: 220 }} aria-busy="true" />}
      {data && data.items.length === 0 && (
        <div className="small-empty">No evaluation has been run yet. Start one from Quality &amp; models.</div>
      )}
      {data && data.items.map((item) => <RunCard key={item.id} item={item} onOpenTrace={onOpenTrace} />)}
    </section>
  )
}
