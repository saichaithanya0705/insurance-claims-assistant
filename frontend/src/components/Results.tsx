import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  BookOpen,
  Check,
  ClipboardCopy,
  Download,
  FileSearch,
  Loader2,
  GitCompare,
  Layers,
  Link2,
  Minus,
  Route,
  Search,
  ShieldAlert,
  Target,
} from 'lucide-react'
import type { Evidence, Finding, FindingKind, GlobalExplanation, LocalExplanation, Predictions, EstimatePrediction, Run, SimilarCase } from '../lib/api'
import { cx, daysBetween, label, modeLabel, money, num, pct, shortTitle } from '../lib/format'
import { Bar, Card, CountUp, DataView, Gauge, Pill, ScoreRing, Tilt, itemVariants, listVariants, useToast } from './ui'
import { claimSnapshot, comparisonSnapshot, findingText, provenanceLabel, readable, sourceExcerpt, sourceTitle } from '../lib/presentation'
import { Inspector } from './Inspector'
import { AuditLog } from './AuditLog'
import { Pipeline, STAGES } from './Pipeline'


export const KIND_COLOR: Record<FindingKind, string> = {
  fact: 'var(--teal)',
  gap: 'var(--amber)',
  risk_indicator: 'var(--amber)',
  contradiction: 'var(--rose)',
  limitation: 'var(--violet)',
}
// Things a handler must act on come first; context and caveats follow.
const KIND_ORDER: FindingKind[] = ['contradiction', 'gap', 'risk_indicator', 'fact', 'limitation']
const ATTENTION: FindingKind[] = ['contradiction', 'gap', 'risk_indicator']

const TIER_TONE = { critical: 'rose', high: 'amber', medium: 'sky', low: 'teal' } as const

export const statusTone = (status?: string) =>
  status === 'failed' ? 'rose' : status === 'reviewed' ? 'teal' : status === 'revision_requested' ? 'violet' : 'amber'

/* ======================================================================
   Empty state
   ====================================================================== */
export function EmptyState() {
  return (
    <Card className="hero-empty">
      <FileSearch size={32} color="var(--teal)" aria-hidden="true" />
      <h2>Start an investigation</h2>
      <p>Choose a sample case or enter claim details. Your brief will bring together evidence, comparison cases and recommended next steps.</p>
      <div className="steps3">
        <div className="step3"><strong>1. Enter the claim</strong><p>Record the incident and available documents.</p></div>
        <div className="step3"><strong>2. Build the brief</strong><p>Compare evidence and identify gaps.</p></div>
        <div className="step3"><strong>3. Review the findings</strong><p>A handler decides what happens next.</p></div>
      </div>
    </Card>
  )
}

export function LoadingState({ startedAt }: { startedAt?: number } = {}) {
  const [elapsed, setElapsed] = useState(() => startedAt ? Math.floor((Date.now() - startedAt) / 1000) : 0)
  useEffect(() => { const started = startedAt || Date.now(); const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000); return () => window.clearInterval(timer) }, [startedAt])
  return (
    <Card className="loading-card" aria-live="polite" aria-busy="true">
      <Loader2 size={24} className="spin" aria-hidden="true" />
      <h2>Building the investigation</h2>
      <p>The request is in progress. Evidence, comparisons and validation results will appear when it completes.</p>
      <p className="footnote">Elapsed: {elapsed}s. You can visit other views and return to Investigation while this request continues. Keep this browser tab open; refreshing cannot resume an in-flight request. Actual stages appear after completion.</p>
    </Card>
  )
}

/* ======================================================================
   Run view
   ====================================================================== */
type Tab = 'brief' | 'comparisons' | 'evidence' | 'trace'

export function RunView({ run, onDetails, onReview, admin = false }: { run: Run; onDetails: () => void; onReview: () => void; admin?: boolean }) {
  const toast = useToast()
  const [tab, setTab] = useState<Tab>('brief')
  const [highlight, setHighlight] = useState<string | null>(null)
  const evidence = run.evidence ?? []
  const comparisons = run.similar_cases ?? []
  const claim = run.claim ?? ({} as Run['claim'])
  const classification = run.classification

  const openSource = (id: string) => {
    if (!evidence.some(e => e.source_id === id)) { toast('This source was not included in the returned evidence.', 'info'); return }
    setHighlight(id)
  }
  const inspected = evidence.find(e => e.source_id === highlight)
  const inspectedComparison = comparisons.find(c => inspected?.source_id === `history:${c.claim_id}`)

  const copyId = async () => {
    try {
      await navigator.clipboard.writeText(run.run_id)
      toast('Run ID copied to clipboard.')
    } catch {
      toast('Clipboard unavailable in this context.', 'err')
    }
  }
  const exportJson = () => {
    const blob = new Blob([JSON.stringify(run, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `investigation-${run.run_id}.json`
    a.click()
    URL.revokeObjectURL(url)
    toast('Brief exported as JSON.')
  }

  const delay = daysBetween(claim.incident_date, claim.claim_filed_date)
  const tabs: { key: Tab; label: string; icon: typeof BookOpen; count?: number }[] = [
    { key: 'brief', label: 'Brief', icon: BookOpen },
    { key: 'comparisons', label: 'Comparisons', icon: GitCompare, count: comparisons.length },
    { key: 'evidence', label: 'Evidence', icon: Layers, count: evidence.length },
    { key: 'trace', label: 'Activity', icon: Route },
  ]

  return (
    <>
      {/* ---------- Hero: identity, then the verdict band ---------- */}
      <Card className="run-hero">
        <div className="run-top">
          <div style={{ minWidth: 0 }}>
            <div className="eyebrow">Investigation brief</div>
            <h2 className="run-title" title={claim.description}>
              {shortTitle(claim.description, 96) || `${label(classification?.claim_type || claim.claim_type)} claim`}
            </h2>
            <div className="run-sub">
              <span className="run-chip">{label(classification?.claim_type || claim.claim_type)} · {claim.state || '—'}</span>
              <span><b>{money(claim.claim_amount, 2)}</b> claimed</span>
              <span className="sep" />
              <span>Filed {claim.claim_filed_date || '—'}{delay !== null ? ` · ${delay} ${delay === 1 ? 'day' : 'days'} after incident` : ''}</span>
              <span className="sep" />
              <span className="mono" title={run.run_id}>Run {run.run_id.slice(0, 8)}</span>
            </div>
          </div>
          <div className="run-actions">
            <Pill tone={statusTone(run.status)} dot>
              {label(run.status)}
            </Pill>
            <button className="icon-btn" onClick={copyId} aria-label="Copy run ID" title="Copy run ID">
              <ClipboardCopy size={15} />
            </button>
            <button className="icon-btn" onClick={exportJson} aria-label="Export brief as JSON" title="Export JSON">
              <Download size={15} />
            </button>
          </div>
        </div>

        {run.error && (
          <div className="error" role="alert" style={{ marginTop: 16 }}>
            <AlertTriangle size={16} />
            <span>{run.error}</span>
          </div>
        )}

        <VerdictBand run={run} admin={admin} onReview={onReview} onEvidence={() => setTab('evidence')} />
      </Card>

      <nav className={`mobile-case-nav${admin ? '' : ' user-nav'}`} aria-label="Current case navigation"><button onClick={onDetails}>Case</button><button onClick={() => { setTab('brief'); document.getElementById('tab-brief')?.focus() }}>Brief</button><button onClick={() => { setTab('evidence'); document.getElementById('tab-evidence')?.focus() }}>Evidence</button>{admin && <button onClick={onReview}>Review</button>}</nav>
      {/* ---------- Tabs ---------- */}
      <Card className="results-card" spot={false} aria-label="Investigation results">
        <div className="tabs" role="tablist" aria-label="Investigation views">
          {tabs.map((t) => {
            const active = tab === t.key
            const Icon = t.icon
            return (
              <button
                key={t.key}
                id={`tab-${t.key}`}
                role="tab"
                aria-selected={active}
                aria-controls={`panel-${t.key}`}
                tabIndex={active ? 0 : -1}
                className={cx('tab', active && 'active')}
                onClick={() => setTab(t.key)}
                onKeyDown={(e) => {
                  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return
                  e.preventDefault()
                  const i = tabs.findIndex((x) => x.key === tab)
                  const next = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
                  setTab(tabs[next].key)
                  document.getElementById(`tab-${tabs[next].key}`)?.focus()
                }}
              >
                {active && <motion.span layoutId="tab-bg" className="tab-bg" transition={{ type: 'spring', stiffness: 500, damping: 38 }} />}
                <Icon size={14} />
                {t.label}
                {t.count !== undefined && <span className="count">{t.count}</span>}
              </button>
            )
          })}
        </div>
        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            id={`panel-${tab}`}
            role="tabpanel"
            aria-labelledby={`tab-${tab}`}
            tabIndex={0}
            className="tab-panel"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
          >
            {tab === 'brief' && <BriefPanel run={run} onSource={openSource} admin={admin} />}
            {tab === 'comparisons' && <ComparisonsPanel cases={comparisons} />}
            {tab === 'evidence' && <EvidencePanel evidence={evidence} highlight={highlight} run={run} />}
            {tab === 'trace' && <TracePanel run={run} admin={admin} />}
          </motion.div>
        </AnimatePresence>
      </Card>
      {inspected && <Inspector title="Evidence alongside your finding" onClose={() => setHighlight(null)}>
        <h3>{sourceTitle(inspected)}</h3><Pill tone={provTone(inspected.provenance)}>{provenanceLabel(inspected.provenance)}</Pill>
        <p className="section-desc">{inspected.provenance === 'user_input' ? 'Claimant-reported information; not independently verified. Document names are reported availability only.' : inspected.provenance === 'handler_lesson' ? 'A handler note from an earlier investigation, approved for reuse by an administrator. Advisory context only; it does not decide this claim.' : inspected.provenance.includes('synthetic') ? 'Synthetic comparison material; not verified evidence for this claim.' : 'Retrieved source passage; provenance alone does not verify its accuracy or applicability.'}</p>
        {inspected.source_id === 'claim:input' ? <DataView value={claimSnapshot(run.claim)} /> : inspectedComparison ? <DataView value={comparisonSnapshot(inspectedComparison)} /> : sourceExcerpt(inspected) ? <><p className="footnote">Original source excerpt · Accuracy and applicability require review</p><blockquote className="ev-text">{sourceExcerpt(inspected)}</blockquote></> : <p>No narrative excerpt is available. Open the original source passage below.</p>}
        {admin && <p className="footnote">Original source passages and retrieval metadata are available in Activity.</p>}
        <div className="case-tools"><button className="btn" onClick={() => { const id = inspected.source_id; setHighlight(null); setTab('evidence'); window.setTimeout(() => { const el = document.querySelector<HTMLElement>(`[data-source-id="${CSS.escape(id)}"]`); el?.scrollIntoView({ block: 'center' }); el?.focus({ preventScroll: true }) }, 350) }}>Open full source in Evidence</button><button className="btn primary" onClick={() => setHighlight(null)}>Back to finding</button></div>
      </Inspector>}
    </>
  )
}

/* ---------- Verdict band: the four things a handler reads first ---------- */
function VerdictBand({ run, admin, onReview, onEvidence }: { run: Run; admin: boolean; onReview: () => void; onEvidence: () => void }) {
  const findings = run.findings ?? []
  const open = findings.filter(f => ATTENTION.includes(f.kind)).length
  const priority = run.priority
  const tier = priority?.tier ?? 'low'
  const fraud = run.predictions?.available !== false ? run.predictions?.fraud : undefined
  const next = run.recommendations?.[0]?.action
  return (
    <motion.div className="verdict" variants={listVariants} initial="hidden" animate="show" aria-label="Brief summary">
      <motion.div variants={itemVariants}>
        <Tilt className="verdict-tile priority" max={8}>
          {typeof priority?.score === 'number' ? (
            <div className="verdict-priority">
              <ScoreRing value={priority.score / 100} tone={TIER_TONE[tier]} size={92} stroke={9}>
                <b>{priority.score}</b><small>/100</small>
              </ScoreRing>
              <div>
                <small className="verdict-k">Handling priority</small>
                <strong className={cx('verdict-tier', TIER_TONE[tier])}>{label(tier)}</strong>
                <span className="verdict-sub">{label(priority.service_urgency)} urgency</span>
              </div>
            </div>
          ) : (
            <><small className="verdict-k">Handling priority</small><strong className="verdict-big">—</strong><span className="verdict-sub">Not scored for this run</span></>
          )}
        </Tilt>
      </motion.div>
      <motion.div variants={itemVariants}>
        <Tilt className={cx('verdict-tile', open ? 'warn' : 'ok')} max={8}>
          <small className="verdict-k"><Target size={13} /> To resolve</small>
          <strong className="verdict-big">{run.status === 'failed' ? '—' : open}</strong>
          <span className="verdict-sub">{run.status === 'failed' ? 'Run failed' : open === 1 ? 'evidence gap or concern' : 'evidence gaps or concerns'}</span>
        </Tilt>
      </motion.div>
      <motion.div variants={itemVariants}>
        <Tilt className={cx('verdict-tile', fraud?.review_signal && 'alert')} max={8}>
          <small className="verdict-k"><ShieldAlert size={13} /> Fraud-flag signal</small>
          {fraud?.available && typeof fraud.score === 'number' ? (
            <>
              <strong className="verdict-big">{(fraud.score * 100).toFixed(1)}<span>%</span></strong>
              <span className="verdict-sub">{fraud.review_signal ? 'Above' : 'Below'} the {pct(fraud.review_threshold)} review threshold</span>
            </>
          ) : (
            <><strong className="verdict-big">—</strong><span className="verdict-sub">Model estimate unavailable</span></>
          )}
        </Tilt>
      </motion.div>
      <motion.div variants={itemVariants} className="verdict-next">
        <small className="verdict-k">Next step</small>
        <p>{next ? readable(next) : 'Inspect the evidence, then review this brief.'}</p>
        <div className="verdict-cta">
          {admin && <button className="btn primary" onClick={onReview}>Review brief</button>}
          <button className="btn" onClick={onEvidence}><Layers size={14} /> Evidence</button>
        </div>
      </motion.div>
    </motion.div>
  )
}

/* ---------- Citations ---------- */
const Cites = ({ ids, onSource }: { ids: string[]; onSource: (id: string) => void }) =>
  ids.length ? (
    <div className="cites">
      {ids.map((id) => (
        <button key={id} type="button" className="cite" onClick={() => onSource(id)} title={`Open source: ${id}`} aria-label={`Open evidence source ${id}`}>
          <Link2 size={12} /> {id === 'claim:input' ? 'Submitted claim' : id.startsWith('history:') ? `Historical case ${id.slice(8)}` : id.startsWith('chunk_') ? `Source passage ${id.slice(6, 14)}` : label(id.replace(/:/g, ' '))}
        </button>
      ))}
    </div>
  ) : null

/* ---------- Brief ---------- */

function BriefPanel({ run, onSource, admin = false }: { run: Run; onSource: (id: string) => void; admin?: boolean }) {
  const findings = run.findings ?? []
  const recs = run.recommendations ?? []
  const [kind, setKind] = useState<FindingKind | 'all'>('all')
  const attention = findings.filter(f => ATTENTION.includes(f.kind))
  const shown = (kind === 'all' ? findings : findings.filter((f) => f.kind === kind)).toSorted((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind))
  const technicalWarnings = shown.filter(f => /Optional Synapt .*lacks supported provenance/i.test(f.text))
  const visibleFindings = shown.filter(f => !technicalWarnings.includes(f))
  const kinds = KIND_ORDER.filter((k) => findings.some((f) => f.kind === k))

  return (
    <>
      <section className={cx('attention-summary', attention.length > 0 && 'has-gaps')}><h3>What needs attention</h3><p>{run.status === 'failed' ? 'The investigation failed. Inspect the error and Activity details before retrying.' : attention.length ? `${attention.length} unresolved evidence ${attention.length === 1 ? 'gap or concern' : 'gaps or concerns'}. ${readable(attention[0].text)}` : 'No explicit gaps or contradictions were returned. Verify the evidence and policy terms before accepting the brief.'}</p><p><strong>Next step:</strong> {run.recommendations?.[0]?.action || 'Inspect the evidence, then review this brief.'}</p><p className="footnote">Validation: {run.validation ? run.validation.passed ? 'Mechanical checks passed' : 'Needs attention' : 'Unavailable'}. Scope: schema, citation membership and action boundaries; it does not establish truth. {run.claim?.provided_documents?.length ? 'Listed documents are reported available only; no document content was received or reviewed.' : ''}</p></section>
      <div className="section">
        <div className="section-title">
          <h3>What the evidence tells us</h3>
          <div className="chips" role="group" aria-label="Filter findings by kind">
            <button className={cx('chip', kind === 'all' && 'on')} onClick={() => setKind('all')}>
              All · {findings.length}
            </button>
            {kinds.map((k) => (
              <button key={k} className={cx('chip', kind === k && 'on')} onClick={() => setKind(k)}>
                <i style={{ background: KIND_COLOR[k] }} />
                {label(k)} · {findings.filter((f) => f.kind === k).length}
              </button>
            ))}
          </div>
        </div>
        {findings.length === 0 ? (
          <div className="small-empty">No findings were returned for this run.</div>
        ) : (
          <motion.div className="findings" variants={listVariants} initial="hidden" animate="show" key={kind}>
            {visibleFindings.map((f: Finding, i) => (
              <motion.article key={`${f.kind}-${i}`} className={cx('finding', `kind-${f.kind}`, ATTENTION.includes(f.kind) && 'attention')} variants={itemVariants} style={{ ['--k' as string]: KIND_COLOR[f.kind] }} layout>
                <div className="finding-head"><i aria-hidden="true" />{f.kind === 'risk_indicator' ? 'Risk indicator' : label(f.kind)}{ATTENTION.includes(f.kind) && <span className="finding-flag">Needs action</span>}</div>
                <p>{findingText(f, run)}</p>{findingText(f, run) !== f.text && <p className="footnote">Display wording clarifies the saved record. Original generated text is retained in Activity.</p>}{f.kind === 'fact' && /document|estimate|statement|photos|report/i.test(f.text) && <p className="footnote">Document names indicate reported availability, not attached or reviewed contents.</p>}
                <Cites ids={f.source_ids} onSource={onSource} />
              </motion.article>
            ))}
            {technicalWarnings.length > 0 && <motion.article className="finding" variants={itemVariants} style={{ ['--k' as string]: KIND_COLOR.limitation }}><div className="finding-head">Evidence limitation</div><p>Some retrieved material could not be linked to a supported source and was excluded. An administrator can inspect Activity for the retrieval details.</p></motion.article>}
          </motion.div>
        )}
      </div>

      <div className="section">
        <div className="section-title">
          <h3>Recommended next steps</h3>
          <span className="step-tag">{recs.length} {recs.length === 1 ? 'action' : 'actions'}</span>
        </div>
        {recs.length === 0 ? (
          <div className="small-empty">No actionable recommendations were returned.</div>
        ) : (
          <motion.div className="actions" variants={listVariants} initial="hidden" animate="show">
            {recs.map((r, i) => (
              <motion.article key={i} className="action" variants={itemVariants}>
                <div className="action-n">{String(i + 1).padStart(2, '0')}</div>
                <div style={{ minWidth: 0 }}>
                  <h4>{readable(r.action)}</h4>
                  <p>{readable(r.reason)}</p>
                  <Cites ids={r.source_ids} onSource={onSource} />
                </div>
              </motion.article>
            ))}
          </motion.div>
        )}
      </div>

      {run.priority && (typeof run.priority.score === 'number' || !!run.priority.reasons?.length) && (
        <div className="section">
          <div className="section-title">
            <h3>Handling priority</h3>
            {typeof run.priority.score === 'number' && (
              <Pill tone={TIER_TONE[run.priority.tier ?? 'low']} dot>
                {label(run.priority.tier)} · {run.priority.score}/100
              </Pill>
            )}
          </div>
          {typeof run.priority.score === 'number' ? (
            <>
              <p className="section-desc">Every point comes from a stated factor, so the ranking can be audited. Service urgency: {label(run.priority.service_urgency)} · Investigation priority: {label(run.priority.investigation_priority)}.</p>
              {run.priority.components?.length ? (
                <ul className="components" aria-label="How the priority score was built">
                  {run.priority.components.map((c, i) => (
                    <motion.li key={i} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.06 }}>
                      <b className="mono">+{c.points}</b>
                      <span>{c.reason}</span>
                    </motion.li>
                  ))}
                </ul>
              ) : (
                <div className="small-empty">No priority factors apply to this claim.</div>
              )}
            </>
          ) : (
            <ul className="reasons">
              {run.priority.reasons.map((reason, i) => (
                <motion.li key={i} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.08 }}>
                  <AlertTriangle size={14} />
                  <span>{reason}</span>
                </motion.li>
              ))}
            </ul>
          )}
          {run.priority.policy && <p className="footnote">{run.priority.policy}</p>}
        </div>
      )}

      {run.judge && (run.judge.status !== 'skipped' || admin) && (
        <div className="section">
          <div className="section-title">
            <h3>Independent review</h3>
            <Pill tone={run.judge.status === 'completed' ? (run.judge.passed ? 'teal' : 'amber') : run.judge.status === 'pending' ? 'sky' : undefined}>
              {run.judge.status === 'completed' ? (run.judge.passed ? 'No concerns' : 'Concerns flagged') : run.judge.status === 'pending' ? 'In progress' : label(run.judge.status)}
            </Pill>
          </div>
          {run.judge.status === 'completed' ? (
            <>
              <p className="section-desc">{run.judge.summary}</p>
              <div className="chips" role="list" aria-label="Independent review checks">
                {([['Grounded in the cited evidence', run.judge.grounded], ['Stays inside the decision boundary', run.judge.boundary_respected], ['Recommendations follow the findings', run.judge.recommendations_supported]] as const).map(([name, ok]) => (
                  <span key={name} role="listitem" className={cx('check', !ok && 'fail')}>
                    {ok ? <Check size={11} /> : <AlertTriangle size={11} />}
                    {name}
                  </span>
                ))}
                {typeof run.judge.score === 'number' && <span className="check">Quality {Math.round(run.judge.score * 100)}%</span>}
              </div>
              {!!run.judge.issues?.length && (
                <ul className="reasons" style={{ marginTop: 12 }}>
                  {run.judge.issues.map((issue) => (
                    <li key={issue}>
                      <AlertTriangle size={14} />
                      <span>{issue}</span>
                    </li>
                  ))}
                </ul>
              )}
              <p className="footnote">
                A second model reviewed this brief against its evidence{admin && run.judge.model ? ` (${run.judge.model}${run.judge.independent === false ? ', same model as the author, so not independent' : ', a different model from the author'})` : ''}. It is advisory and probabilistic; the handler decides.
              </p>
            </>
          ) : (
            <p className="section-desc">{run.judge.reason}</p>
          )}
        </div>
      )}

      <div className="section">
        <div className="section-title">
          <h3>Model estimates</h3>
        </div>
        <p className="section-desc">Amounts, resolution time and dataset fraud-flag risk are separate statistical signals. They do not decide the claim.</p>
        <PredictionsView predictions={run.predictions} />
      </div>
    </>
  )
}

/* ---------- Predictions ---------- */
function IntervalChart({ item, format }: { item: EstimatePrediction; format: (v: number) => string }) {
  const [lo, hi] = item.interval ?? [0, 0]
  const est = item.estimate ?? 0
  const max = Math.max(hi, est) * 1.15 || 1
  const left = (lo / max) * 100
  const width = ((hi - lo) / max) * 100
  return (
    <>
      <div className="interval" aria-hidden="true">
        <div className="rail" />
        <motion.div className="range" style={{ left: `${left}%` }} initial={{ width: 0 }} animate={{ width: `${width}%` }} transition={{ duration: 1, ease: [0.16, 1, 0.3, 1], delay: 0.2 }} />
        <motion.div className="point" initial={{ left: `${left}%`, opacity: 0 }} animate={{ left: `${(est / max) * 100}%`, opacity: 1 }} transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1], delay: 0.3 }} />
      </div>
      <div className="interval-labels">
        <span>{format(lo)}</span>
        <span>{format(hi)}</span>
      </div>
    </>
  )
}

const effectText = (value: number, unit: string) => {
  const size = Math.abs(value)
  const text = unit === 'USD' ? money(size) : `${num(size, unit === 'score' ? 3 : 1)} ${unit}`
  return `${value >= 0 ? '+' : '−'}${text}`
}

export function Explanation({ item }: { item?: { global_explanation?: GlobalExplanation; local_explanation?: LocalExplanation | null } }) {
  const global = item?.global_explanation
  const local = item?.local_explanation
  const features = global?.features ?? []
  if (!features.length && !local?.contributions?.length) return null
  const max = Math.max(...features.map((f) => Math.abs(f.score_drop)), 1e-9)
  return (
    <details className="disclose" style={{ marginTop: 'auto' }}>
      <summary>Why this estimate</summary>
      <div className="disclose-body">
        {!!local?.contributions?.length && (
          <>
            <h5 className="mini-title">For this claim, compared with a typical one</h5>
            <ul className="effects">
              {local.contributions.map((c) => (
                <li key={c.feature}>
                  <span>
                    {label(c.feature)}: <b>{String(c.value)}</b> <small>(typical {String(c.typical_value)})</small>
                  </span>
                  <b className={c.effect >= 0 ? 'up' : 'down'}>{effectText(c.effect, local.unit)}</b>
                </li>
              ))}
            </ul>
            <p className="footnote">{local.method}</p>
          </>
        )}
        {!!global?.summary?.length && (
          <>
            <h5 className="mini-title">What the model learned across the sample</h5>
            <ul className="effects plain">
              {global.summary.map((line) => (
                <li key={line}>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
            {global.effects_method && <p className="footnote">{global.effects_method}</p>}
          </>
        )}
        {!!features.length && (
          <>
            <h5 className="mini-title">How much each feature matters</h5>
            <div className="bars">
              {features.map((f, i) => (
                <div className="bar-row" key={f.feature}>
                  <span className="nm" title={f.feature}>
                    {label(f.feature)}
                  </span>
                  <Bar value={Math.abs(f.score_drop) / max} tone={f.score_drop < 0 ? 'muted' : undefined} delay={i * 0.05} />
                  <span className="vl">{num(f.score_drop, 4)}</span>
                </div>
              ))}
            </div>
            {global?.interpretation && <p className="footnote">{global.interpretation}</p>}
          </>
        )}
      </div>
    </details>
  )
}

export function PredictionsView({ predictions }: { predictions?: Predictions }) {
  if (!predictions || predictions.available === false)
    return (
      <>
        <div className="small-empty">{predictions?.reason || 'No model estimates available for this run.'} An administrator can review model readiness.</div>
        {!!predictions?.limitations?.length && (
          <details className="disclose">
            <summary>Model limitations</summary>
            <div className="disclose-body">
              <DataView value={predictions.limitations} />
            </div>
          </details>
        )}
      </>
    )
  const { amount, resolution, fraud } = predictions
  const unavailable = (reason?: string) => <p className="cap">{reason || 'Unavailable'}</p>
  return (
    <>
      <motion.div className="pred-grid" variants={listVariants} initial="hidden" animate="show">
        <motion.article className="pred" variants={itemVariants}>
          <h4>
            <span className="status-dot teal" /> Historical claim amount
          </h4>
          {amount?.available ? (
            <>
              <div className="val">
                <CountUp value={amount.estimate ?? 0} format={(v) => money(v)} />
              </div>
              {amount.interval && <IntervalChart item={amount} format={(v) => money(v)} />}
              <p className="cap">{amount.interval_label}</p>
            </>
          ) : (
            unavailable(amount?.reason)
          )}
          <Explanation item={amount} />
        </motion.article>

        <motion.article className="pred" variants={itemVariants}>
          <h4>
            <span className="status-dot violet" /> Resolution time
          </h4>
          {resolution?.available ? (
            <>
              <div className="val">
                <CountUp value={resolution.estimate ?? 0} format={(v) => `${v.toFixed(1)} days`} />
              </div>
              {resolution.interval && <IntervalChart item={resolution} format={(v) => `${Math.round(v)}d`} />}
              <p className="cap">{resolution.interval_label}</p>
            </>
          ) : (
            unavailable(resolution?.reason)
          )}
          <Explanation item={resolution} />
        </motion.article>

        <motion.article className="pred" variants={itemVariants}>
          <h4>
            <span className={cx('status-dot', fraud?.review_signal ? 'rose' : 'teal')} /> Synthetic fraud-flag risk
          </h4>
          {fraud?.available && typeof fraud.score === 'number' ? (
            <div className="gauge-wrap">
              <Gauge value={fraud.score} threshold={fraud.review_threshold} />
              <div className="gauge-val">
                <div className="val">
                  <CountUp value={fraud.score * 100} format={(v) => `${v.toFixed(1)}%`} />
                </div>
              </div>
              <div style={{ display: 'flex', gap: 6, marginTop: 12, flexWrap: 'wrap', justifyContent: 'center' }}>
                <Pill tone={fraud.review_signal ? 'rose' : 'teal'}>{fraud.review_signal ? 'Above review threshold' : 'Below review threshold'}</Pill>
                <Pill>Threshold {pct(fraud.review_threshold)}</Pill>
              </div>
              <p className="cap" style={{ textAlign: 'center' }}>
                {fraud.meaning || 'Dataset flag estimate, not proven fraud.'}
              </p>
            </div>
          ) : (
            unavailable(fraud?.reason)
          )}
          <Explanation item={fraud} />
        </motion.article>
      </motion.div>
      {(!!predictions.warnings?.length || predictions.confidence_distinction || !!predictions.limitations?.length) && (
        <details className="disclose">
          <summary>Data origin, warnings &amp; limitations</summary>
          <div className="disclose-body">
            <DataView value={{ origin: predictions.origin, confidence_distinction: predictions.confidence_distinction, warnings: predictions.warnings, limitations: predictions.limitations }} />
          </div>
        </details>
      )}
    </>
  )
}

/* ---------- Comparisons ---------- */
function ComparisonsPanel({ cases }: { cases: SimilarCase[] }) {
  const flagged = cases.filter((c) => c.dataset_fraud_flag).length
  const semantic = cases.filter((c) => c.semantic_match).length
  return (
    <>
      <div className="section-title">
        <h3>Similar, but different</h3>
      </div>
      <p className="section-desc">The closest claims come first, ranked by keyword match on claim descriptors, numeric similarity and (at half weight) Synapt's semantic rank, fused by reciprocal rank. Claims marked “Related by meaning” follow: Synapt ranks them similar, but the numeric search would not have chosen them. Scores are not probabilities, and outcomes do not establish coverage or prove fraud.</p>
      {cases.length > 0 && (
        <div className="cmp-summary" role="status">
          <Pill tone={flagged >= 2 ? 'amber' : 'teal'}>
            {flagged} of {cases.length} carry the dataset fraud flag
          </Pill>
          <Pill tone={semantic ? 'violet' : undefined}>{semantic} semantic match{semantic === 1 ? '' : 'es'}</Pill>
          <span>The fraud flag is a synthetic dataset label, not proof. Use it to decide what to examine next, not to conclude.</span>
        </div>
      )}
      {cases.length === 0 ? (
        <div className="small-empty">No historical cases matched the current filters. Broaden the filters and rerun to explore comparisons.</div>
      ) : (
        <motion.div variants={listVariants} initial="hidden" animate="show">
          {cases.map((c, i) => (
            <motion.article key={c.claim_id} className="cmp" variants={itemVariants}>
              <details><summary className="cmp-head">
                <span className="cmp-rank">{i + 1}</span>
                <span><strong className="cmp-id">{c.claim_id}</strong><span style={{ display: 'block', fontSize: 14, color: 'var(--text-2)' }}>{label(c.claim_type)} · {c.state} · {money(c.claim_amount)} · {label(c.claim_status)} · {provenanceLabel(c.provenance)}</span></span>
                {c.semantic_match && <Pill tone="violet">{c.surfaced_by === 'semantic' ? 'Related by meaning' : 'Related meaning'}{typeof c.semantic_rank === 'number' ? ` · Synapt #${c.semantic_rank}` : ''}</Pill>}
                <span className="cmp-score mono">Rank score {typeof c.similarity_score === 'number' ? c.similarity_score.toFixed(4) : '—'}</span>
              </summary>
              <div className="cmp-body">
                <div className="cmp-metrics">
                  <div>
                    <small>Claimed</small>
                    <b>{money(c.claim_amount)}</b>
                  </div>
                  <div>
                    <small>Outcome</small>
                    <b style={{ color: c.claim_status === 'approved' ? 'var(--teal)' : c.claim_status === 'denied' ? 'var(--rose)' : undefined }}>{label(c.claim_status)}</b>
                  </div>
                  <div>
                    <small>Resolution</small>
                    <b>{c.days_to_resolution == null ? '—' : `${c.days_to_resolution} days`}</b>
                  </div>
                  <div>
                    <small>State</small>
                    <b>{c.state}</b>
                  </div>
                  <div>
                    <small>Prior claims</small>
                    <b>{c.previous_claims_count ?? '—'}</b>
                  </div>
                  <div>
                    <small>Dataset fraud flag</small>
                    <b style={{ color: c.dataset_fraud_flag ? 'var(--amber)' : undefined }}>{c.dataset_fraud_flag == null ? 'Not recorded' : c.dataset_fraud_flag ? 'Flagged' : 'Not flagged'}</b>
                  </div>
                </div>
                {c.open_case && <p className="footnote">This claim was already on file but has no final outcome, so no resolution time is available.</p>}
                <div className="match-grid">
                  <div>
                    <h5 style={{ color: 'var(--teal)' }}>
                      <Check size={12} /> Why it matches
                    </h5>
                    {c.match_reasons?.length ? (
                      <ul>
                        {c.match_reasons.map((r) => (
                          <li key={r}>
                            <Check size={12} color="var(--teal)" />
                            {readable(r)}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="cap" style={{ fontSize: 12, color: 'var(--text-3)' }}>
                        No match reasons supplied.
                      </p>
                    )}
                  </div>
                  <div>
                    <h5 style={{ color: 'var(--amber)' }}>
                      <Minus size={12} /> Meaningful differences
                    </h5>
                    {c.differences?.length ? (
                      <ul>
                        {c.differences.map((d) => (
                          <li key={d}>
                            <Minus size={12} color="var(--amber)" />
                            {readable(d)}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p style={{ fontSize: 12, color: 'var(--text-3)' }}>No differences supplied. This does not establish equivalence.</p>
                    )}
                  </div>
                </div>
              </div></details>
            </motion.article>
          ))}
        </motion.div>
      )}
    </>
  )
}

/* ---------- Evidence ---------- */
function Highlighted({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'))
  return (
    <>
      {parts.map((part, i) => (part.toLowerCase() === query.toLowerCase() ? <mark key={i}>{part}</mark> : <span key={i}>{part}</span>))}
    </>
  )
}

const provTone = (p: string) => (p === 'synapt' ? 'teal' : p === 'user_input' ? 'sky' : p === 'handler_lesson' ? 'violet' : 'amber')

function EvidencePanel({ evidence, highlight, run }: { evidence: Evidence[]; highlight: string | null; run: Run }) {
  const [query, setQuery] = useState('')
  const [prov, setProv] = useState<string>('all')
  const provenances = [...new Set(evidence.map((e) => e.provenance))]
  const q = query.trim().toLowerCase()
  const shown = evidence.filter((e) => (prov === 'all' || e.provenance === prov) && (!q || `${e.title} ${e.text} ${e.source_id}`.toLowerCase().includes(q)))
  return (
    <>
      <div className="section-title">
        <h3>Evidence library</h3>
        <div className="search-box field" style={{ margin: 0 }}>
          <Search size={14} />
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search this case’s evidence…" aria-label="Search this case’s evidence" />
        </div>
      </div>
      <p className="section-desc">Source passages returned by this investigation. Provenance is shown on every item; citations open a contextual inspector without leaving the finding.</p>
      <div className="chips" style={{ marginBottom: 14 }}>
        <button className={cx('chip', prov === 'all' && 'on')} onClick={() => setProv('all')}>
          All · {evidence.length}
        </button>
        {provenances.map((p) => (
          <button key={p} className={cx('chip', prov === p && 'on')} onClick={() => setProv(p)}>
            {provenanceLabel(p)} · {evidence.filter((e) => e.provenance === p).length}
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <div className="small-empty">{evidence.length ? 'No passages match this search.' : 'No source passages were returned. Treat unsupported findings as unverified.'}</div>
      ) : (
        <motion.div variants={listVariants} initial="hidden" animate="show">
          {shown.map((e) => {
            const comparable = run.similar_cases?.find((c) => e.source_id === `history:${c.claim_id}`)
            const structured = e.source_id === 'claim:input' ? claimSnapshot(run.claim) : comparable ? comparisonSnapshot(comparable) : undefined
            return (
              <motion.article
                key={JSON.stringify([e.source_id, e.text])}
                className={cx('ev', highlight === e.source_id && 'hl')}
                data-source-id={e.source_id}
                tabIndex={-1}
                variants={itemVariants}
              >
                <div className="ev-head">
                  <h4>
                    <Highlighted text={sourceTitle(e)} query={query.trim()} />
                  </h4>
                  <Pill tone={provTone(e.provenance)}>{provenanceLabel(e.provenance)}</Pill>
                </div>
                {structured ? (
                  <>
                    <p className="footnote">{e.source_id === 'claim:input' ? 'Submitted claim details' : 'Comparison summary from this run'}</p>
                    <DataView value={structured} />
                  </>
                ) : <div className="ev-text"><Highlighted text={sourceExcerpt(e) ?? 'No narrative passage is available. An administrator can inspect the original in Activity.'} query={query.trim()} /></div>}
                <p className="footnote">{e.provenance === 'user_input' ? 'Reported by claimant; not verified. Document names only.' : e.provenance === 'handler_lesson' ? 'Reviewed handler lesson; advisory context only.' : e.provenance.includes('synthetic') ? 'Synthetic material; verify applicability.' : 'Retrieved passage; accuracy and applicability require review.'}</p>
              </motion.article>
            )
          })}
        </motion.div>
      )}
    </>
  )
}

/* ---------- Trace ---------- */
export function TracePanel({ run, admin = false }: { run: Run; admin?: boolean }) {
  const trace = run.trace ?? []
  return (
    <>
      <div className="section">
        <p className="section-desc">{admin ? `${modeLabel(run.mode)} · Agents: ${label(run.agent_mode)} · ` : ''}Service urgency: {label(run.priority?.service_urgency)} · Investigation priority: {label(run.priority?.investigation_priority)}{typeof run.priority?.score === 'number' ? ` · Queue priority: ${label(run.priority.tier)} (${run.priority.score}/100)` : ''}</p>
        {admin && <details className="disclose"><summary>Original findings and source metadata</summary><DataView value={{ findings: run.findings, sources: run.evidence }} /></details>}
        {admin && <AuditLog runId={run.run_id} />}
        <Pipeline states={Object.fromEntries(STAGES.map(stage => [stage.key, stage.key === 'review' ? run.review ? 'done' : ['awaiting_review', 'needs_manual_review'].includes(run.status) ? 'waiting' : 'idle' : trace.some(t => t.stage === stage.key) ? (stage.key === 'validate' && !run.validation?.passed) || (stage.key === 'judge' && run.judge?.status === 'completed' && !run.judge.passed) ? 'warn' : stage.key === 'judge' && run.judge?.status === 'pending' ? 'active' : 'done' : 'idle']))} />
        <div className="section-title">
          <h3>Execution trace</h3>
          <span className="step-tag">{trace.length} {trace.length === 1 ? 'stage' : 'stages'}</span>
        </div>
        {trace.length === 0 ? (
          <div className="small-empty">No execution trace was returned.</div>
        ) : (
          <ol className="trace">
            {trace.map((t, i) => {
              const stage = STAGES.find((s) => s.key === t.stage)
              const Icon = stage?.icon ?? Check
              return (
                <motion.li key={i} initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.1 + i * 0.12 }}>
                  <span className="trace-dot">
                    <Icon size={15} />
                  </span>
                  <div style={{ minWidth: 0 }}>
                    <h4>
                      {label(t.stage)} <Pill tone="teal">{label(t.status)}</Pill>
                    </h4>
                    {admin && (typeof t.detail === 'object' ? <DataView value={t.detail} /> : <p>{t.detail || 'No details returned'}</p>)}
                  </div>
                </motion.li>
              )
            })}
          </ol>
        )}
      </div>
      <div className="section">
        <div className="section-title">
          <h3>Output validation</h3>
          {run.validation && <Pill tone={run.validation.passed ? 'teal' : 'amber'}>{run.validation.passed ? 'Passed' : 'Needs attention'}</Pill>}
        </div>
        {run.validation?.issues?.length ? (
          <ul className="reasons">
            {run.validation.issues.map((issue) => (
              <li key={issue}>
                <AlertTriangle size={14} />
                <span>{issue}</span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="small-empty" style={{ padding: 16 }}>
            {!run.validation
              ? 'Validation results are unavailable. This brief has not been verified.'
              : run.validation.passed
                ? 'Validation passed. No issues reported within the stated scope.'
                : 'Validation did not pass. No additional issue details were returned.'}
          </div>
        )}
        {run.validation?.scope && <p className="footnote">Scope: {run.validation.scope}</p>}
      </div>
      <div className="section">
        <div className="section-title">
          <h3>Classification details</h3>
        </div>
        <DataView value={admin ? run.classification : { claim_type: run.classification?.claim_type, needs_review: run.classification?.needs_review }} />
      </div>
    </>
  )
}
