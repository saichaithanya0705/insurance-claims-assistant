import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { label, money } from '../lib/format'
import { Card, ErrorBox } from './ui'
import { STATES } from '../lib/states'

interface SavedCase { run_id: string; title: string; description: string; status: string; claim_type: string; state: string; claim_amount: number; claim_filed_date: string }
interface Page { items: SavedCase[]; total: number; offset: number; limit: number }
const empty = { q: '', status: '', claim_type: '', state: '', date_from: '', date_to: '', min_amount: '', max_amount: '' }

export function CaseLibrary({ onOpen, busy }: { onOpen: (id: string) => void; busy: boolean }) {
  const [filters, setFilters] = useState(empty)
  const [query, setQuery] = useState(empty)
  const [offset, setOffset] = useState(0)
  const [page, setPage] = useState<Page | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
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
  return <Card className="case-library"><div className="card-body">
    <h2>Saved cases</h2><p className="section-desc">Search the investigations available to your account by incident words, claim type, state name/code or ID. Every search word must match. Empty search shows newest cases first. Recent runs are only shortcuts.</p>
    <form onSubmit={e => { e.preventDefault(); search(filters) }}>
      {field('q', 'Search saved cases')}
      <div className="library-filters">
        <div className="field"><label htmlFor="cases-status">Review status</label><select id="cases-status" value={filters.status} onChange={e => setFilters({ ...filters, status: e.target.value })}><option value="">All statuses</option>{['awaiting_review', 'needs_manual_review', 'reviewed', 'revision_requested', 'failed'].map(s => <option key={s} value={s}>{label(s)}</option>)}</select></div>
        <div className="field"><label htmlFor="cases-type">Claim type</label><select id="cases-type" value={filters.claim_type} onChange={e => setFilters({ ...filters, claim_type: e.target.value })}><option value="">All types</option>{['auto', 'home', 'renters', 'property', 'business'].map(s => <option key={s} value={s}>{label(s)}</option>)}</select></div>
        <div className="field"><label htmlFor="cases-state">State</label><select id="cases-state" value={filters.state} onChange={e => setFilters({ ...filters, state: e.target.value })}><option value="">All states</option>{STATES.map(([code, name]) => <option key={code} value={code}>{name} ({code})</option>)}</select></div>
        {field('date_from', 'Filed from', 'date')}{field('date_to', 'Filed through', 'date')}{field('min_amount', 'Minimum amount ($)', 'number')}{field('max_amount', 'Maximum amount ($)', 'number')}
      </div>
      <div className="case-tools"><button className="btn primary" type="submit">Search cases</button><button className="btn" type="button" onClick={() => { setFilters(empty); search(empty) }}>Clear filters</button></div>
    </form>
    <ErrorBox message={error} />{error && <button className="btn" onClick={() => search(query, offset)}>Retry search</button>}
    <div role="status">{loading ? 'Searching saved cases…' : !error ? `${page?.total ?? 0} saved cases found` : ''}</div>
    {!loading && !error && page && <>
      {!page.items.length && <p className="small-empty">No saved investigations match. Broaden the filters or try a phrase from the incident description. This does not search historical comparison cases.</p>}
      <div className="case-list">{page.items.map(c => <article key={c.run_id}><button className="case-open" disabled={busy} onClick={() => onOpen(c.run_id)}><strong>{c.title || `${label(c.claim_type)} claim · ${c.state}`}</strong><span>{label(c.claim_type)} · {c.state} · {money(c.claim_amount)} · Filed {c.claim_filed_date} · {label(c.status)}</span><p>{c.description}</p><small>ID {c.run_id}</small></button></article>)}</div>
      <div className="case-tools"><button className="btn" disabled={offset === 0} onClick={() => search(query, Math.max(0, offset - 20))}>Previous</button><span>{page.total ? offset + 1 : 0}–{offset + page.items.length} of {page.total}</span><button className="btn" disabled={offset + page.items.length >= page.total} onClick={() => search(query, offset + 20)}>Next</button></div>
    </>}
  </div></Card>
}
