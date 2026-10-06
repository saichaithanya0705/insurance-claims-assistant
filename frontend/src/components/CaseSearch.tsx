import { useEffect, useId, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { api } from '../lib/api'
import { label, money } from '../lib/format'
import { validateSuggestions, type CaseSuggestion, type CaseSuggestions } from '../lib/savedSearch'

export function CaseSearch({ onOpen, disabled, onQueryChange }: { onOpen: (id: string) => void; disabled: boolean; onQueryChange: () => void }) {
  const listId = useId()
  const root = useRef<HTMLDivElement>(null)
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [response, setResponse] = useState<{ query: string; page?: CaseSuggestions; error?: string } | null>(null)
  const expanded = open && !disabled
  const current = response?.query === query ? response : null
  const items = current?.page?.items ?? []
  const loading = expanded && !current

  useEffect(() => {
    if (!expanded) return
    const controller = new AbortController()
    let live = true
    const timer = setTimeout(() => {
      api<unknown>(`/api/case-suggestions?${new URLSearchParams({ q: query, limit: '8' })}`, { signal: controller.signal })
        .then(validateSuggestions)
        .then(page => { if (live) setResponse({ query, page }) })
        .catch(e => { if (live && !controller.signal.aborted) setResponse({ query, error: (e as Error).message }) })
    }, 220)
    return () => { live = false; clearTimeout(timer); controller.abort() }
  }, [query, expanded])

  useEffect(() => {
    if (!expanded) return
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    document.addEventListener('pointerdown', outside)
    return () => document.removeEventListener('pointerdown', outside)
  }, [expanded])

  useEffect(() => {
    if (expanded && active >= 0) document.getElementById(`${listId}-${active}`)?.scrollIntoView({ block: 'nearest' })
  }, [active, expanded, listId])

  const choose = (item: CaseSuggestion) => {
    if (disabled) return
    setOpen(false)
    setActive(-1)
    setQuery('')
    setResponse(null)
    onOpen(item.run_id)
  }
  const status = loading ? 'Searching saved claims…' : current?.error ? current.error : current?.page ? items.length ? `${current.page.total} matching claims. ${current.page.total > items.length ? 'Showing the first eight. ' : ''}Use arrow keys and Enter to open a claim.` : query.trim() ? 'No matching claims. Try different words or part of an ID.' : 'No saved claims yet.' : ''

  return <div className="case-search" ref={root} onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) { setOpen(false); setActive(-1) } }}>
    <label className="sr-only" htmlFor="claim-search">Search claims by ID or title</label>
    <div className="case-search-field"><Search size={17} aria-hidden="true" /><input id="claim-search" className="input" type="text" role="combobox" aria-autocomplete="list" aria-expanded={expanded} aria-controls={expanded ? listId : undefined} aria-activedescendant={expanded && items[active] ? `${listId}-${active}` : undefined} aria-describedby={`${listId}-status`} autoComplete="off" spellCheck={false} placeholder="Search claims by ID or title…" maxLength={300} value={query} disabled={disabled}
      onFocus={() => { setOpen(true); setActive(-1) }}
      onClick={() => setOpen(true)}
      onChange={e => { setQuery(e.target.value); setResponse(null); setActive(-1); setOpen(true); onQueryChange() }}
      onKeyDown={e => {
        if (e.nativeEvent.isComposing) return
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setOpen(false); setActive(-1) }
        else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault()
          setOpen(true)
          if (items.length) setActive(i => e.key === 'ArrowDown' ? Math.min(i + 1, items.length - 1) : i < 0 ? items.length - 1 : Math.max(0, i - 1))
        } else if (e.key === 'Enter' && expanded && items[active]) { e.preventDefault(); choose(items[active]) }
      }} /></div>
    <span id={`${listId}-status`} className="sr-only" role="status">{expanded ? status : ''}</span>
    {expanded && <div className="case-search-popup">
      <div className="case-search-caption">{query.trim() ? 'Matching claims' : 'Recently saved claims'}<span>{loading ? 'Searching…' : current?.page ? `${current.page.total} found` : ''}</span></div>
      <div id={listId} role="listbox" aria-label="Available claims" aria-busy={loading} className="case-search-list">
        {items.map((item, i) => <div key={item.run_id} id={`${listId}-${i}`} role="option" aria-selected={active === i} className={`case-search-option${active === i ? ' active' : ''}`} onMouseDown={e => e.preventDefault()} onPointerMove={() => setActive(i)} onClick={() => choose(item)}>
          <span className="case-search-title">{item.title}</span>
          <span className="case-search-meta">{label(item.claim_type)} · {item.state || 'State unspecified'} · {money(item.claim_amount)} · {label(item.status)}</span>
          <span className="case-search-id">{item.run_id}<span>{item.match_kind}</span></span>
        </div>)}
      </div>
      {!items.length && <p className="case-search-message">{status}</p>}
      {items.length > 0 && <p className="case-search-hint">↑ ↓ to navigate · Enter to open · Esc to close{current?.page?.semantic_status === 'unavailable' ? ' · ID and text matches only; related-meaning search is unavailable.' : ''}</p>}
    </div>}
  </div>
}
