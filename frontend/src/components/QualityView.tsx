import { motion } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { BookmarkPlus, BrainCircuit, Check, FlaskConical, Lightbulb, Loader2, Play, RefreshCw, Star, X } from 'lucide-react'
import { api, post, type EvaluationStatus, type Lessons, type ModelStatus, type TaskMetric } from '../lib/api'
import { label, money, num, pct } from '../lib/format'
import { Bar, Card, DataView, ErrorBox, Pill, Ring, itemVariants, listVariants, useToast } from './ui'

const TASKS: { key: 'amount' | 'resolution' | 'fraud'; title: string }[] = [
  { key: 'amount', title: 'Claim amount' },
  { key: 'resolution', title: 'Resolution time' },
  { key: 'fraud', title: 'Fraud-flag risk' },
]

/** Lower-is-better comparison of model vs baseline (MAE / Brier). */
function CompareLower({ name, model, baseline, fmt }: { name: string; model?: number; baseline?: number; fmt: (v: number) => string }) {
  if (model === undefined || baseline === undefined) return null
  const max = Math.max(model, baseline, 1e-9)
  return (
    <div className="compare">
      <div style={{ fontSize: 12, color: 'var(--text-2)' }}>{name} · lower is better</div>
      <div className="compare-row">
        <span>Model</span>
        <Bar value={model / max} />
        <span className="vl">{fmt(model)}</span>
      </div>
      <div className="compare-row">
        <span>Baseline</span>
        <Bar value={baseline / max} tone="muted" delay={0.1} />
        <span className="vl">{fmt(baseline)}</span>
      </div>
    </div>
  )
}

function TaskCard({ task, title, metric }: { task: string; title: string; metric?: TaskMetric }) {
  if (!metric || !metric.available)
    return (
      <motion.div className="metric-card" variants={itemVariants}>
        <h4>
          {title} <Pill tone="amber">Unavailable</Pill>
        </h4>
        <p style={{ fontSize: 12, color: 'var(--text-3)' }}>{metric?.reason || 'Not trained.'}</p>
      </motion.div>
    )
  const fmt = task === 'amount' ? (v: number) => money(v) : (v: number) => `${num(v, 1)}d`
  return (
    <motion.div className="metric-card" variants={itemVariants}>
      <h4>
        {title} <Pill tone="teal">{metric.selected_model ? label(metric.selected_model) : 'Random forest'}</Pill>
      </h4>
      {task === 'fraud' ? (
        <div style={{ display: 'grid', gap: 12 }}>
          <div className="bars">
            {(
              [
                ['Precision', metric.precision],
                ['Recall', metric.recall],
                ['PR-AUC', metric.pr_auc_average_precision],
                ['Baseline PR-AUC', metric.baseline_pr_auc],
              ] as const
            ).map(([n, v], i) => (
              <div className="bar-row" key={n} style={{ gridTemplateColumns: '120px 1fr 64px' }}>
                <span className="nm">{n}</span>
                <Bar value={v ?? 0} tone={n.startsWith('Baseline') ? 'muted' : undefined} delay={i * 0.06} />
                <span className="vl">{pct(v)}</span>
              </div>
            ))}
          </div>
          <CompareLower name="Brier score" model={metric.brier_score} baseline={metric.baseline_brier_score} fmt={(v) => num(v, 4)} />
          <p style={{ fontSize: 12, color: 'var(--text-3)' }}>Review threshold {pct(metric.review_threshold)}</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          <CompareLower name="Test MAE" model={metric.mae} baseline={metric.baseline_mae} fmt={fmt} />
          <div className="compare-row" style={{ gridTemplateColumns: '120px 1fr 64px' }}>
            <span>Interval coverage</span>
            <Bar value={metric.heldout_interval_coverage ?? 0} delay={0.2} />
            <span className="vl">{pct(metric.heldout_interval_coverage, 0)}</span>
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-3)' }}>{metric.interval_label}</p>
        </div>
      )}
      {metric.counts && (
        <p style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 10, fontFamily: 'var(--font-mono)' }}>
          {Object.entries(metric.counts)
            .map(([k, v]) => `${k} ${v}`)
            .join(' · ')}
        </p>
      )}
      {!!metric.global_explanation?.summary?.length && (
        <details className="disclose">
          <summary>What drives {title.toLowerCase()}</summary>
          <div className="disclose-body">
            <ul className="effects plain">
              {metric.global_explanation.summary.map((line) => (
                <li key={line}>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
            {metric.global_explanation.effects_method && <p className="footnote">{metric.global_explanation.effects_method}</p>}
          </div>
        </details>
      )}
    </motion.div>
  )
}

export function QualityView() {
  const toast = useToast()
  const [models, setModels] = useState<ModelStatus | null>(null)
  const [evals, setEvals] = useState<EvaluationStatus | null>(null)
  const [lessons, setLessons] = useState<Lessons | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<null | 'train' | 'eval' | 'refresh'>(null)
  const [judge, setJudge] = useState(false)
  const [promoting, setPromoting] = useState<number | null>(null)

  const refresh = useCallback(async () => {
    setError(null)
    setBusy((b) => b ?? 'refresh')
    const results = await Promise.allSettled([api<ModelStatus>('/api/models/status'), api<EvaluationStatus>('/api/evaluations/status'), api<Lessons>('/api/feedback/lessons')])
    if (results[0].status === 'fulfilled') setModels(results[0].value)
    if (results[1].status === 'fulfilled') setEvals(results[1].value)
    if (results[2].status === 'fulfilled') setLessons(results[2].value)
    const failed = results.find((r) => r.status === 'rejected') as PromiseRejectedResult | undefined
    if (failed) setError((failed.reason as Error).message)
    setBusy((b) => (b === 'refresh' ? null : b))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const train = async () => {
    setBusy('train')
    setError(null)
    try {
      const result = await post<ModelStatus>('/api/models/train')
      setModels(result)
      toast(result.available ? 'Model training completed. Review the reported metrics.' : 'Training returned no available models. Review the reported reason.', result.available ? 'ok' : 'info')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const evaluate = async () => {
    setBusy('eval')
    setError(null)
    try {
      const result = await post<EvaluationStatus>('/api/evaluations/run', { judge })
      setEvals(result)
      toast('Evaluation returned. Review the checks and judge status.')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  const promote = async (id: number) => {
    setPromoting(id)
    setError(null)
    try {
      await post(`/api/feedback/lessons/${id}/promote`)
      toast('Lesson promoted. Later investigations of the same claim type will cite it.')
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPromoting(null)
    }
  }

  const passRatio = evals?.total ? (evals.passed ?? 0) / evals.total : 0

  return (
    <motion.section aria-labelledby="quality-title" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Checks & calibration</div>
          <h1 id="quality-title" className="display" tabIndex={-1}>
            Quality &amp; models
          </h1>
          <p className="subtitle">Inspect model readiness and run evidence checks before trusting a result.</p>
        </div>
        <button className="btn" onClick={refresh} disabled={busy !== null}>
          <RefreshCw size={14} className={busy === 'refresh' ? 'spin' : undefined} /> Refresh
        </button>
      </div>
      {error && (
        <div style={{ marginBottom: 18 }}>
          <ErrorBox message={error} />
        </div>
      )}

      <div className="grid-2">
        <Card>
          <div className="card-head">
            <h2>
              <span className="head-icon sky">
                <BrainCircuit size={15} />
              </span>
              Prediction models
            </h2>
            {models && <Pill tone={models.available ? 'teal' : 'amber'} dot>{models.available ? 'Trained' : 'Not available'}</Pill>}
          </div>
          <div className="card-body">
            <div className="actions-row">
              <button className="btn primary" onClick={train} disabled={busy !== null}>
                {busy === 'train' ? <Loader2 size={15} className="spin" /> : <Play size={15} />} Train models
              </button>
              {models?.trained_at && <span style={{ fontSize: 12, color: 'var(--text-3)' }}>Trained {new Date(models.trained_at).toLocaleString()}</span>}
            </div>
            {!models ? (
              <div className="skeleton" style={{ height: 160 }} />
            ) : models.available ? (
              <>
                <div className="grid-3" style={{ marginBottom: 14 }}>
                  <div className="status-tile">
                    <small>Valid rows</small>
                    <b>{num(models.valid_rows, 0)}</b>
                  </div>
                  <div className="status-tile">
                    <small>Excluded</small>
                    <b>{num(models.excluded_rows, 0)}</b>
                  </div>
                  <div className="status-tile">
                    <small>Split</small>
                    <b>Temporal</b>
                  </div>
                </div>
                <motion.div style={{ display: 'grid', gap: 10 }} variants={listVariants} initial="hidden" animate="show">
                  {TASKS.map((t) => (
                    <TaskCard key={t.key} task={t.key} title={t.title} metric={models.metrics?.[t.key]} />
                  ))}
                </motion.div>
              </>
            ) : (
              <div className="small-empty">
                {models.reason || 'Models are unavailable.'}
                {models.data_present === false && (
                  <p style={{ marginTop: 8 }}>
                    Download the dataset first: <code className="mono">uv run python scripts/bootstrap.py data</code>
                  </p>
                )}
              </div>
            )}
            {models && (
              <details className="disclose">
                <summary>Limitations & raw report</summary>
                <div className="disclose-body">
                  <DataView value={{ limitations: models.limitations, split: models.split, origin: models.origin, feature_contracts: models.feature_contracts }} />
                </div>
              </details>
            )}
          </div>
        </Card>

        <Card>
          <div className="card-head">
            <h2>
              <span className="head-icon violet">
                <FlaskConical size={15} />
              </span>
              Investigation evaluations
            </h2>
            {evals && <Pill tone={evals.overall_passed === true ? 'teal' : evals.status === 'completed' ? 'amber' : undefined}>{evals.overall_passed === true ? 'Checks passed' : evals.status === 'completed' ? 'Review results' : label(evals.status)}</Pill>}
          </div>
          <div className="card-body">
            <div className="actions-row">
              <button className="btn primary" onClick={evaluate} disabled={busy !== null}>
                {busy === 'eval' ? <Loader2 size={15} className="spin" /> : <Play size={15} />} Run evaluations
              </button>
              <label className="switch">
                <input type="checkbox" checked={judge} onChange={(e) => setJudge(e.target.checked)} />
                <span className="track">
                  <span className="thumb" />
                </span>
                <span>LLM judge {evals && !evals.judge_configured && <span style={{ color: 'var(--text-3)' }}>(not configured)</span>}</span>
              </label>
            </div>
            {!evals ? (
              <div className="skeleton" style={{ height: 160 }} />
            ) : evals.status !== 'completed' ? (
              <div className="small-empty">Evaluations have not run in this server session. Run them to execute the golden demo cases.</div>
            ) : (
              <>
                <div className="ring-wrap">
                  <div style={{ position: 'relative', width: 92, height: 92 }}>
                    <Ring value={passRatio} tone={passRatio === 1 ? 'teal' : passRatio > 0.5 ? 'amber' : 'rose'} />
                    <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', fontFamily: 'var(--font-mono)', fontSize: 12 }}>{pct(passRatio, 0)}</div>
                  </div>
                  <div>
                    <div className="ring-label">
                      {evals.passed}/{evals.total}
                    </div>
                    <p style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4 }}>
                      golden cases passed · {label(evals.mode)} · agents {label(evals.agent_mode)}
                    </p>
                  </div>
                </div>
                <motion.div className="case-list" variants={listVariants} initial="hidden" animate="show">
                  {evals.cases?.map((c) => (
                    <motion.div key={c.case} className="case" variants={itemVariants}>
                      <div className="case-head">
                        <b>{label(c.case)}</b>
                        <Pill tone={c.passed ? 'teal' : 'rose'}>{c.passed ? 'Passed' : 'Failed'}</Pill>
                      </div>
                      <div className="checks">
                        {Object.entries(c.checks).map(([k, ok]) => (
                          <span key={k} className={ok ? 'check' : 'check fail'}>
                            {ok ? <Check size={11} /> : <X size={11} />}
                            {label(k)}
                          </span>
                        ))}
                      </div>
                    </motion.div>
                  ))}
                </motion.div>
                <div style={{ marginTop: 16 }}>
                  <div className="section-title">
                    <h3>LLM judge</h3>
                    <Pill tone={evals.judge_quality_passed === true ? 'teal' : evals.judge_status === 'not_run' ? undefined : 'amber'}>{evals.judge_quality_passed === true ? 'Quality checks passed' : label(evals.judge_status)}</Pill>
                  </div>
                  {evals.judge_expected_metrics !== undefined && <p className="footnote">{evals.judge_completed_metrics ?? 0}/{evals.judge_expected_metrics} metrics completed · {evals.judge_passed_metrics ?? 0} passed. Completion reports execution; individual scores determine quality.</p>}
                  {!!evals.judge_results?.length && (
                    <div className="bars">
                      {evals.judge_results.map((r, i) => (
                        <div className="bar-row" key={`${r.run_id}-${r.metric}`} title={r.reason}>
                          <span className="nm">{r.metric}</span>
                          <Bar value={r.score ?? 0} tone={r.passed === false ? 'amber' : undefined} delay={i * 0.04} />
                          <span className="vl">{r.score === null ? 'failed' : num(r.score, 2)}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {evals.scope && <p className="footnote">{evals.scope}</p>}
              </>
            )}
          </div>
        </Card>
      </div>

      <Card style={{ marginTop: 20 }}>
        <div className="card-head">
          <h2>
            <span className="head-icon amber">
              <Lightbulb size={15} />
            </span>
            Feedback candidates
          </h2>
          <span className="step-tag">{lessons?.candidate_lessons.length ?? 0} {(lessons?.candidate_lessons.length ?? 0) === 1 ? "candidate" : "candidates"}</span>
        </div>
        <div className="card-body">
          <p className="section-desc">Handler feedback on accepted briefs. Promote a lesson to make it reusable: later investigations of the same claim type cite it as a reviewed handler lesson, and live mode also ingests it into the Synapt provider. Nothing is promoted automatically, and promoted notes never decide a claim.</p>
          {!lessons ? (
            <div className="skeleton" style={{ height: 60 }} />
          ) : lessons.candidate_lessons.length === 0 ? (
            <div className="small-empty">No feedback candidates yet. Review a brief and leave feedback to populate this list.</div>
          ) : (
            <motion.div variants={listVariants} initial="hidden" animate="show">
              {lessons.candidate_lessons.map((l) => (
                <motion.div key={l.id} className="lesson" variants={itemVariants}>
                  <div className="stars" aria-label={`${l.rating} of 5`}>
                    {[1, 2, 3, 4, 5].map((n) => (
                      <Star key={n} size={13} color={n <= l.rating ? 'var(--amber)' : 'rgba(148,163,184,0.3)'} fill={n <= l.rating ? 'var(--amber)' : 'none'} />
                    ))}
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <p>{l.note}</p>
                    <span className="mono" style={{ color: 'var(--text-3)', fontSize: 12 }}>
                      {l.claim_type ? `${l.claim_type} · ${l.state ?? ''} · ` : ''}
                      {l.run_id}
                    </span>
                  </div>
                  <div className="lesson-action">
                    {l.promoted ? (
                      <Pill tone="teal" dot>
                        Promoted
                      </Pill>
                    ) : (
                      <button className="btn" onClick={() => promote(l.id)} disabled={promoting !== null} aria-label={`Promote lesson ${l.id} for reuse`}>
                        {promoting === l.id ? <Loader2 size={14} className="spin" /> : <BookmarkPlus size={14} />} Promote
                      </button>
                    )}
                  </div>
                </motion.div>
              ))}
            </motion.div>
          )}
          {lessons?.promotion && <p className="footnote">{lessons.promotion}</p>}
        </div>
      </Card>
      <p className="footnote">Synthetic data checks validate this implementation. They do not establish accuracy on real insurance claims.</p>
    </motion.section>
  )
}
