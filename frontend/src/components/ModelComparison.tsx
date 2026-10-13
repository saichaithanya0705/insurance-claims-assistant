import { label, num, pct } from '../lib/format'
import type { TaskMetric } from '../lib/api'

const SIMPLE_RULES = new Set(['median_baseline', 'claim_type_median', 'prior_baseline'])

/** How the chosen model compares with its baseline, in words, plus every candidate that competed. */
export function ModelComparison({ task, metric }: { task: string; metric: TaskMetric }) {
  const lines: string[] = []
  if (task === 'fraud') {
    if (metric.pr_auc_average_precision !== undefined && metric.baseline_pr_auc) {
      lines.push(`PR-AUC is ${num(metric.pr_auc_average_precision / metric.baseline_pr_auc, 1)}× the baseline (${pct(metric.pr_auc_average_precision)} against ${pct(metric.baseline_pr_auc)}).`)
    }
    if (metric.brier_score !== undefined && metric.baseline_brier_score) {
      lines.push(`Brier score is ${pct(1 - metric.brier_score / metric.baseline_brier_score, 0)} lower than the baseline.`)
    }
  } else if (metric.mae !== undefined && metric.baseline_mae) {
    const gain = 1 - metric.mae / metric.baseline_mae
    lines.push(gain > 0.005 ? `Error is ${pct(gain, 0)} lower than the baseline.` : 'Error is no better than the baseline.')
  }
  const candidates: [string, number][] = Object.entries(metric.candidate_selection_maes ?? {}).map(([name, v]) => [name, v])
  const scores: [string, number][] = Object.entries(metric.candidate_selection_scores ?? {}).map(([name, v]) => [name, v.pr_auc ?? 0])
  const rows = task === 'fraud' ? scores : candidates
  const lowerIsBetter = task !== 'fraud'
  const rule = metric.selected_model && SIMPLE_RULES.has(metric.selected_model)
  return (
    <div className="model-compare">
      {lines.map((line) => (
        <p key={line} className="model-gain">{line}</p>
      ))}
      {rule && (
        <p className="footnote">
          A plain rule won here ({label(metric.selected_model)}): the machine-learning candidates below did not beat it on the selection cohort, so the app uses the simpler, more explainable choice.
        </p>
      )}
      {rows.length > 1 && (
        <details className="disclose">
          <summary>Models compared on the selection cohort</summary>
          <div className="disclose-body">
            <ul className="model-candidates">
              {rows
                .sort((a, b) => (lowerIsBetter ? a[1] - b[1] : b[1] - a[1]))
                .map(([name, value]) => (
                  <li key={name} className={name === metric.selected_model ? 'chosen' : undefined}>
                    <span>{label(name)}{name === metric.selected_model ? ' · chosen' : SIMPLE_RULES.has(name) ? ' · simple baseline' : ''}</span>
                    <b>{task === 'fraud' ? `PR-AUC ${pct(value)}` : task === 'amount' ? `$${Math.round(value).toLocaleString('en-US')}` : `${num(value, 2)}d`}</b>
                  </li>
                ))}
            </ul>
            <p className="footnote">{lowerIsBetter ? 'Mean absolute error; lower is better.' : 'Average precision on the selection cohort; higher is better.'}</p>
          </div>
        </details>
      )}
    </div>
  )
}
