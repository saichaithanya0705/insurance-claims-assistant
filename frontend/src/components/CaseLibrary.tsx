import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { ChevronRight, Search, SlidersHorizontal } from 'lucide-react'
import { api } from '../lib/api'
import { cx, label, money, shortTitle } from '../lib/format'
import { Card, ErrorBox, Pill, itemVariants, listVariants } from './ui'
import { STATES } from '../lib/states'

interface SavedCase { run_id: string; title: string; description: string; status: string; claim_type: string; state: string; claim_amount: number; claim_filed_date: string; priority_score?: number | null; priority_tier?: 'critical' | 'high' | 'medium' | 'low' | null }
interface Page { items: SavedCase[]; total: number; offset: number; limit: number }
const empty = { q: '', status: '', claim_type: '', state: '', date_from: '', date_to: '', min_amount: '', max_amount: '', sort: '', tier: '' }
const TIER_TONE = { critical: 'rose', high: 'amber', medium: 'sky', low: 'teal' } as const
const STATUS_TONE: Record<string, string> = { reviewed: 'teal', failed: 'rose', revision_requested: 'violet', needs_manual_review: 'amber', awaiting_review: 'amber' }
const FILTER_KEYS = ['status', 'claim_type', 'state', 'tier', 'date_from', 'date_to', 'min_amount', 'max_amount'] as const

export function CaseLibrary({ onOpen, busy }: { onOpen: (id: string) => void; busy: boolean }) {
  const [filters, setFilters] = useState(empty)
  const [query, setQuery] = useState(empty)
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<Page | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [showFilters, setShowFilters] = useState(false)
  const activeFilters = FILTER_KEYS.filter(key => query[key]).length
  const search = (nextQuery: typeof empty, nextOffset = 0) => { setLoading(true); setError(null); setQuery({ ...nextQuery }); setOffset(nextOffset) }
  useEffect(() => {
    let active = true
    const params = new URLSearchParams({ offset: String(offset), limit: '20' })
    Object.entries(query).forEach(([key, value]) => { if (value) params.set(key, value) })
    api<Page>(`/api/investigations?${params}`).then(result => {
      if (!Array.isArray(result.items) || !Number.isInteger(result.total)) throw new Error('Saved-case response is invalid.')
      if (active) setPage(result)
    }).catch(e => { if (active) setError(e.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [query, offset])
  const field = (key: keyof typeof empty, title: string, type = 'text') => <div className="field"><label htmlFor={`cases-${key}`}>{title}</label><input id={`cases-${key}`} type={type} min={type === 'number' ? 0 : undefined} step={type === 'number' ? '0.01' : undefined} value={filters[key]} onChange={e => setFilters({ ...filters, [key]: e.target.value })} /></div>
  const select = (key: keyof typeof empty, title: string, all: string, options: [string, string][]) => <div className="field"><label htmlFor={`cases-${key}`}>{title}</label><select id={`cases-${key}`} value={filters[key]} onChange={e => setFilters({ ...filters, [key]: e.target.value })}><option value="">{all}</option>{options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></div>
  const opts = (values: string[]): [string, string][] => values.map(v => [v, label(v)])

  return <Card className="case-library">
    <form className="queue-bar" onSubmit={e => { e.preventDefault(); search(filters) }}>
      <div className="queue-search">
        <Search size={16} aria-hidden="true" />
        <label htmlFor="cases-q" className="sr-only">Search saved cases</label>
        <input id="cases-q" className="input" type="search" placeholder="Search by incident words, claim type, state or ID" value={filters.q} onChange={e => setFilters({ ...filters, q: e.target.value })} />
      </div>
      <div className="field queue-sort">
        <label htmlFor="cases-sort" className="sr-only">Order</label>
        <select id="cases-sort" value={filters.sort} onChange={e => { const next = { ...filters, sort: e.target.value }; setFilters(next); search(next) }}><option value="">Newest first</option><option value="priority">Highest priority first</option></select>
      </div>
      <button type="button" className={cx('btn', showFilters && 'on')} aria-expanded={showFilters} aria-controls="case-filters" onClick={() => setShowFilters(o => !o)}>
        <SlidersHorizontal size={15} /> Filters{activeFilters > 0 && <span className="count-badge">{activeFilters}</span>}
      </button>
      <button className="btn primary" type="submit">Search</button>
    </form>
    <div id="case-filters" className="queue-filters" hidden={!showFilters}>
      <div className="library-filters">
        {select('status', 'Review status', 'All statuses', opts(['awaiting_review', 'needs_manual_review', 'reviewed', 'revision_requested', 'failed']))}
        {select('claim_type', 'Claim type', 'All types', opts(['auto', 'home', 'renters', 'property', 'business']))}
        {select('state', 'State', 'All states', STATES.map(([code, name]) => [code, `${name} (${code})`]))}
        {select('tier', 'Priority tier', 'All tiers', opts(['critical', 'high', 'medium', 'low']))}
        {field('date_from', 'Filed from', 'date')}{field('date_to', 'Filed through', 'date')}{field('min_amount', 'Minimum amount ($)', 'number')}{field('max_amount', 'Maximum amount ($)', 'number')}
      </div>
      <div className="case-tools"><button className="btn primary" type="button" onClick={() => search(filters)}>Apply filters</button><button className="btn ghost" type="button" onClick={() => { setFilters(empty); search(empty) }}>Clear all</button></div>
    </div>

    <ErrorBox message={error} />{error && <button className="btn" onClick={() => search(query, offset)}>Retry search</button>}
    <div className="queue-meta" role="status">{loading ? 'Searching saved cases…' : !error ? `${page?.total ?? 0} saved ${page?.total === 1 ? 'case' : 'cases'}` : ''}<span>Every search word must match. Historical comparison cases are not included.</span></div>
    {!loading && !error && page && <>
      {!page.items.length && <p className="small-empty">No saved investigations match. Broaden the filters or try a phrase from the incident description.</p>}
      {!!page.items.length && <div className="queue-head" aria-hidden="true"><span>Priority</span><span>Incident</span><span>Amount</span><span>Status</span><span /></div>}
      <motion.ul className="queue" variants={listVariants} initial="hidden" animate="show" key={`${offset}-${JSON.stringify(query)}`}>
        {page.items.map(c => {
          const tier = c.priority_tier && typeof c.priority_score === 'number' ? c.priority_tier : null
          return <motion.li key={c.run_id} variants={itemVariants}>
            <button className="queue-row" disabled={busy} onClick={() => onOpen(c.run_id)} title={c.description}>
              <span className={cx('queue-priority', tier ? TIER_TONE[tier] : 'none')}>
                {tier ? <><b>{c.priority_score}</b><small>{label(tier)}</small><i style={{ ['--p' as string]: `${c.priority_score}%` }} /></> : <small>Not scored</small>}
              </span>
              <span className="queue-main">
                <strong>{shortTitle(c.title || c.description, 88) || `${label(c.claim_type)} claim`}</strong>
                <span>{label(c.claim_type)} · {c.state || '—'} · Filed {c.claim_filed_date || '—'} · <span className="mono">{c.run_id.slice(0, 8)}</span></span>
              </span>
              <span className="queue-amount">{money(c.claim_amount)}</span>
              <span className="queue-status"><Pill tone={STATUS_TONE[c.status]} dot>{label(c.status)}</Pill></span>
              <ChevronRight size={16} className="queue-chev" aria-hidden="true" />
            </button>
          </motion.li>
        })}
      </motion.ul>
      {page.total > 0 && <div className="pager"><span>{offset + 1}–{offset + page.items.length} of {page.total}</span><div><button className="btn" disabled={offset === 0} onClick={() => search(query, Math.max(0, offset - 20))}>Previous</button><button className="btn" disabled={offset + page.items.length >= page.total} onClick={() => search(query, offset + 20)}>Next</button></div></div>}
    </>}
  </Card>
}
