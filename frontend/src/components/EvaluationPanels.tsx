import { useEffect, useState } from 'react'
import { Check, Circle, Loader2, Minus, X } from 'lucide-react'
import type { EvaluationProgress, EvaluationStatus, EvaluationStep } from '../lib/api'
import { Pill } from './ui'

const clock = (seconds: number) => (seconds >= 60 ? `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s` : `${seconds}s`)
const since = (from: string | null, now: number) => (from ? Math.max(0, Math.round((now - Date.parse(from)) / 1000)) : 0)

/** A once-a-second clock that only re-renders the component that uses it, never the whole page. */
function useClock(active: boolean, override?: number) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active || override !== undefined) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [active, override])
  return override ?? now
}

function StepIcon({ state }: { state: EvaluationStep['state'] }) {
  if (state === 'running') return <Loader2 size={14} className="spin" aria-hidden="true" />
  if (state === 'done') return <Check size={14} aria-hidden="true" />
  if (state === 'failed') return <X size={14} aria-hidden="true" />
  if (state === 'skipped') return <Minus size={14} aria-hidden="true" />
  return <Circle size={12} aria-hidden="true" />
}

/** What the evaluation is doing right now: overall progress, every step, and a running log. */
export function EvaluationProgressPanel({ progress, now: fixedNow }: { progress: EvaluationProgress; now?: number }) {
  const now = useClock(progress.state === 'running', fixedNow)
  const total = Math.max(progress.total_steps, 1)
  const running = progress.state === 'running'
  const elapsed = since(progress.started_at, progress.finished_at ? Date.parse(progress.finished_at) : now)
  // The index in the full list is the key, so a new line never renames the existing ones.
  const recent = progress.events.map((event, index) => ({ event, index })).slice(-10).reverse()
  const title = running ? 'Evaluation running' : progress.state === 'failed' ? 'Evaluation stopped early' : 'What happened in this run'
  return (
    <section className="eval-progress" aria-live="polite" aria-label="Evaluation progress">
      <div className="eval-progress-head">
        <b>{title}</b>
        <span className="eval-elapsed">{clock(elapsed)}</span>
      </div>
      <div className="eval-meter" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={progress.done_steps} aria-label="Evaluation steps completed">
        <span style={{ width: `${Math.min(1, progress.done_steps / total) * 100}%` }} />
      </div>
      <p className="footnote">
        {progress.done_steps} of {progress.total_steps} steps done{progress.current && running ? ` · now: ${progress.current}` : ''}.{' '}
        {progress.judge_requested
          ? 'The LLM judge asks a second model to score each brief, so each of its steps can take about a minute.'
          : 'The LLM judge was not selected for this run.'}
      </p>
      <ol className="eval-steps">
        {progress.steps.map((step) => (
          <li key={step.id} className={`eval-step ${step.state}`}>
            <StepIcon state={step.state} />
            <div className="eval-step-body">
              <span className="eval-step-label">{step.label}</span>
              <small>{step.detail ?? (step.state === 'running' ? `running for ${clock(since(step.started_at, now))}` : step.state)}</small>
            </div>
          </li>
        ))}
      </ol>
      <details className="eval-log" open={running}>
        <summary>Activity log</summary>
        <ul>
          {recent.map(({ event, index }) => (
            <li key={index}>
              <time>{new Date(event.at).toLocaleTimeString()}</time> {event.text}
            </li>
          ))}
        </ul>
      </details>
    </section>
  )
}

/** One-line summary of the judge for its section heading. */
export function judgeSummary(evals: EvaluationStatus): { text: string; tone?: string } {
  const expected = evals.judge_expected_metrics ?? 0
  const completed = evals.judge_completed_metrics ?? 0
  const passed = evals.judge_passed_metrics ?? 0
  if (!evals.judge_requested) return { text: 'Not selected' }
  const status = evals.judge_status
  if (status === 'completed') return { text: `Ran · ${passed}/${expected} met the pass line`, tone: passed === expected ? 'teal' : 'amber' }
  if (status === 'partial') return { text: `Partly ran · ${completed}/${expected} scored`, tone: 'amber' }
  if (status.startsWith('unavailable')) return { text: 'Could not start', tone: 'rose' }
  return { text: 'Could not run', tone: 'rose' }
}

/** The overall result in plain words, so a passing rule-based check cannot hide the judge. */
export function EvaluationVerdict({ evals }: { evals: EvaluationStatus }) {
  const total = evals.total ?? 0
  const goldenPassed = evals.passed ?? 0
  const goldenOk = total > 0 && goldenPassed === total
  const expected = evals.judge_expected_metrics ?? 0
  const passed = evals.judge_passed_metrics ?? 0
  const completed = evals.judge_completed_metrics ?? 0
  const threshold = evals.judge_threshold ?? 0.5
  const judgeRan = evals.judge_status === 'completed' || evals.judge_status === 'partial'
  const overall = evals.overall_passed === true
  return (
    <div className={`eval-verdict ${overall ? 'ok' : 'warn'}`} role="status">
      <div className="eval-verdict-head">
        <b>{overall ? 'Overall: passed' : 'Overall: not passed'}</b>
        <Pill tone={overall ? 'teal' : 'amber'}>{overall ? 'All requested checks passed' : 'Needs review'}</Pill>
      </div>
      <ul>
        <li>
          <span>Golden cases (rule-based checks)</span>
          <b>
            {goldenPassed}/{total} passed
          </b>
        </li>
        <li>
          <span>LLM judge</span>
          <b>
            {!evals.judge_requested
              ? 'Not selected for this run'
              : judgeRan
                ? `Ran: ${completed}/${expected} metrics scored by ${evals.judge_model ?? 'the judge model'} · ${passed} met the ${threshold} pass line`
                : evals.judge_status.startsWith('unavailable')
                  ? `Could not start (${evals.judge_status.replace(/^unavailable:\s*/, '')})`
                  : `Could not complete (${evals.judge_status.replace(/^failed:\s*/, '')})`}
          </b>
        </li>
      </ul>
      {!overall && judgeRan && goldenOk && passed < expected && (
        <p className="footnote">
          The result is “not passed” because {expected - passed} of {expected} judge scores were below the {threshold} pass line, even though every golden check passed. The judge did run: open the bars below for the
          reason it gave for each score.
        </p>
      )}
      {!overall && !goldenOk && total > 0 && <p className="footnote">At least one golden case failed a rule-based check. Its failed checks are marked below.</p>}
      {!evals.judge_requested && <p className="footnote">Tick “LLM judge” and run again to have a second model score each brief. Without it only the rule-based checks run.</p>}
    </div>
  )
}
