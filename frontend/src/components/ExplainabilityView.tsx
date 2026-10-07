import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { ChevronRight, Eye, ShieldCheck } from 'lucide-react'
import { api } from '../lib/api'
import { label, money, shortTitle } from '../lib/format'
import { Card, ErrorBox, Pill } from './ui'
import { CaseSearch } from './CaseSearch'
import { ExplanationView } from './ExplanationView'
import { Pipeline, type NodeState, STAGES } from './Pipeline'

interface RecentItem {
  run_id: string
  title: string
  status: string
  claim_type?: string | null
  state?: string
  claim_amount?: number
  priority_tier?: string | null
}

// A diagram of the method, not a run: stages are shown neutral rather than completed.
const NEUTRAL: Record<string, NodeState> = Object.fromEntries(STAGES.map((s) => [s.key, 'idle' as NodeState]))

const WHO = [
  { tone: 'violet', name: 'AI model', text: 'Reads the claim and the evidence and drafts findings and next steps. Its output must fit a fixed schema and cite supplied sources.' },
  { tone: 'sky', name: 'Fixed rules', text: 'Deterministic logic: validation, boundary checks, and the demonstration drafting used when no model is configured.' },
  { tone: 'teal', name: 'Search and ranking', text: 'Finds procedures and comparable historical claims, then combines three ranked lists into one order.' },
  { tone: 'amber', name: 'Statistical models', text: 'Estimate claim amount, resolution time and a dataset fraud-flag score from historical patterns.' },
  { tone: 'teal', name: 'A person', text: 'A handler reviews the brief and decides whether it is usable. Nobody here decides the claim itself.' },
]

function Overview() {
  return (
    <div className="xp-overview">
      <Card spot={false}>
        <div className="card-head">
          <h2>
            <span className="head-icon">
              <Eye size={15} />
            </span>
            How every brief is built
          </h2>
        </div>
        <div className="card-body">
          <Pipeline states={NEUTRAL} />
          <p className="section-desc">The same eight stages run for every query. Pick a query above to see what each stage did for it, which sources stand behind each statement, and how the result was checked.</p>
          <ul className="xp-who">
            {WHO.map((w) => (
              <li key={w.name}>
                <Pill tone={w.tone}>{w.name}</Pill>
                <p>{w.text}</p>
              </li>
            ))}
          </ul>
        </div>
      </Card>
      <Card spot={false}>
        <div className="card-head">
          <h2>
            <span className="head-icon sky">
              <ShieldCheck size={15} />
            </span>
            How a brief is evaluated
          </h2>
        </div>
        <div className="card-body">
          <ol className="xp-eval-list">
            <li>
              <b>Mechanical validation</b> <Pill tone="amber">Gate</Pill>
              <p>Rules check the schema, that every citation resolves to supplied evidence, that no decision language appears and that no document content is claimed. A brief that fails cannot be accepted.</p>
            </li>
            <li>
              <b>Evidence grounding</b>
              <p>Counts how much of the brief points back to supplied sources and how much of the retrieved evidence it uses.</p>
            </li>
            <li>
              <b>Independent AI review</b>
              <p>A second, different model checks that the brief is grounded, stays in bounds and supports its recommendations. It is advisory and probabilistic.</p>
            </li>
            <li>
              <b>Handler review</b> <Pill tone="amber">Gate</Pill>
              <p>A person accepts the brief or asks for a revision. This records a judgement about the brief, never about the claim.</p>
            </li>
          </ol>
          <p className="footnote">Administrators can also run a suite of golden claims end to end on the Quality &amp; models page to check the system itself.</p>
        </div>
      </Card>
    </div>
  )
}

export function ExplainabilityView({ admin, runId, onSelect, onOpenTrace }: { admin: boolean; runId: string | null; onSelect: (runId: string) => void; onOpenTrace: (runId: string) => void }) {
  const [recent, setRecent] = useState<RecentItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const controller = new AbortController()
    api<{ items: RecentItem[] }>('/api/investigations?limit=6', { signal: controller.signal })
      .then((page) => {
        if (!controller.signal.aborted) setRecent(Array.isArray(page.items) ? page.items : [])
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError((e as Error).message)
      })
    return () => controller.abort()
  }, [])
  return (
    <motion.section aria-labelledby="xp-title" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Transparency</div>
          <h1 id="xp-title" className="display" tabIndex={-1}>
            Explainability
          </h1>
          <p className="subtitle">See how a brief was generated, which sources stand behind each statement, and how it was checked before anyone relied on it.</p>
        </div>
        <div className="case-search-wrap">
          <CaseSearch onOpen={onSelect} disabled={false} onQueryChange={() => undefined} />
        </div>
      </div>

      <ErrorBox message={error} />
      {recent && recent.length > 0 && (
        <div className="xp-recent" role="group" aria-label="Recent queries">
          <span className="xp-recent-label">Recent queries</span>
          {recent.map((item) => (
            <button key={item.run_id} type="button" className={item.run_id === runId ? 'xp-chip on' : 'xp-chip'} aria-pressed={item.run_id === runId} onClick={() => onSelect(item.run_id)} title={item.title}>
              <span>{shortTitle(item.title, 44) || 'Untitled claim'}</span>
              <small>
                {label(item.claim_type)} · {item.state ?? '—'} · {money(item.claim_amount)}
              </small>
            </button>
          ))}
        </div>
      )}

      {runId ? <ExplanationView key={runId} runId={runId} admin={admin} onOpenTrace={admin ? onOpenTrace : undefined} /> : <Overview />}
      {runId && (
        <p className="footnote">
          <ChevronRight size={12} style={{ verticalAlign: '-2px' }} /> This explanation is built from what was saved with the brief. No model is called and no search is repeated; only the validation rules are recomputed, to confirm the saved verdict. Anything that was not recorded is marked as such.
        </p>
      )}
    </motion.section>
  )
}
