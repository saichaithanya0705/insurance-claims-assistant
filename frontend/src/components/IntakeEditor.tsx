import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { X } from 'lucide-react'
import type { FormState } from '../lib/claimForm'
import { cx } from '../lib/format'
import { DOCS, FIELDS, TYPES, stateName, type Field } from '../lib/intakeView'
import { addDays } from '../lib/readNotes'
import { STATES } from '../lib/states'

export interface Prov {
  src: 'notes' | 'you'
  /** The words the value was read from (notes only). */
  snip?: string
  via?: 'model'
}

const DEDUCTIBLES: [string, string][] = [['250', '$250'], ['500', '$500'], ['1000', '$1,000'], ['2500', '$2,500']]
const TENURES: [string, string][] = [['0.5', 'Under a year'], ['1', '1 year'], ['3', '3 years'], ['5', '5 years'], ['10', '10 years']]
const PRIORS: [string, string][] = [['0', 'None'], ['1', '1'], ['2', '2'], ['3', '3'], ['5', '5']]

const matchStates = (query: string) => {
  const q = query.trim().toLowerCase()
  if (!q) return STATES
  const starts = STATES.filter(([c, n]) => n.toLowerCase().startsWith(q) || c.toLowerCase() === q)
  return starts.concat(STATES.filter(([c, n]) => !n.toLowerCase().startsWith(q) && c.toLowerCase() !== q && n.toLowerCase().includes(q)))
}

function Chips({ items, current, onPick }: { items: [string, string][]; current: string; onPick: (value: string) => void }) {
  return (
    <div className="si-chips">
      {items.map(([v, l]) => (
        <button key={v || 'none'} type="button" className={cx('si-chip', current === v && 'on')} aria-pressed={current === v} onClick={() => onPick(v)}>{l}</button>
      ))}
    </div>
  )
}

export function IntakeEditor({ field, form, prov, today, onCommit, onDocs, onClose }: {
  field: Field
  form: FormState
  prov?: Prov
  today: string
  /** Set a value, close the editor and move on to the next blank. */
  onCommit: (field: Field, value: string) => void
  /** Change the document list while the editor stays open. */
  onDocs: (docs: string[]) => void
  onClose: () => void
}) {
  const value = form[field]
  const [draft, setDraft] = useState(() => (field === 'state' ? stateName(form.state) : field === 'provided_documents' ? '' : String(value)))
  const [err, setErr] = useState('')
  const root = useRef<HTMLDivElement>(null)

  // Focus the first useful control when the editor opens.
  useEffect(() => {
    const el = root.current?.querySelector<HTMLElement>('[data-first]') ?? root.current?.querySelector<HTMLElement>('.si-chip.on, .si-chip')
    el?.focus()
    if (el instanceof HTMLInputElement && el.type !== 'date') el.select()
  }, [])

  const fail = (message: string) => {
    setErr(message)
    root.current?.querySelector<HTMLElement>('[data-first]')?.focus()
  }

  const submit = () => {
    const raw = draft.trim()
    switch (field) {
      case 'claim_amount':
      case 'deductible': {
        const n = Number(raw.replace(/[$,\s]/g, ''))
        if (raw === '' || !Number.isFinite(n) || n < 0) return fail('Enter an amount, for example 12,400.')
        if (n > 1e9) return fail('Amounts cannot exceed one billion dollars.')
        return onCommit(field, String(n))
      }
      case 'incident_date':
      case 'claim_filed_date': {
        if (!raw) return fail('Pick a date.')
        if (raw > today) return fail('Dates cannot be in the future.')
        if (field === 'claim_filed_date' && form.incident_date && raw < form.incident_date) return fail('Filing must be on or after the incident.')
        return onCommit(field, raw)
      }
      case 'policyholder_tenure_years': {
        const n = Number(raw)
        if (raw === '' || !Number.isFinite(n) || n < 0 || n > 100) return fail('Enter years between 0 and 100.')
        return onCommit(field, String(n))
      }
      case 'previous_claims_count': {
        const n = Number(raw)
        if (raw === '' || !Number.isInteger(n) || n < 0 || n > 1000) return fail('Enter a whole number from 0 to 1000.')
        return onCommit(field, String(n))
      }
      case 'state': {
        const q = raw.toLowerCase()
        const hit = STATES.find(([c, n]) => c.toLowerCase() === q || n.toLowerCase() === q) || (q ? STATES.find(([, n]) => n.toLowerCase().startsWith(q)) : undefined)
        return hit ? onCommit(field, hit[0]) : fail('Pick a US state.')
      }
      case 'provided_documents': {
        if (raw) return addDoc(raw)
        return onCommit(field, '')
      }
      default:
        return undefined
    }
  }

  const addDoc = (name: string) => {
    const docs = form.provided_documents
    if (!docs.includes(name)) {
      if (docs.length >= 50) return fail('List at most 50 documents.')
      onDocs([...docs, name])
    }
    setDraft('')
    setErr('')
  }

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      submit()
    }
  }
  const type = (next: string) => {
    setDraft(next)
    setErr('')
  }
  const done = (
    <div className="si-pop-foot">
      <span className="si-perr" role="alert">{err}</span>
      <button type="button" className="si-done" onClick={submit}>Done <kbd>↵</kbd></button>
    </div>
  )

  let body
  switch (field) {
    case 'claim_type':
      body = (
        <>
          <Chips items={TYPES.map(([v, l]) => [v, l])} current={form.claim_type} onPick={(v) => onCommit(field, v)} />
          <p className="si-hint">Auto-detect lets the system classify it from the description.</p>
        </>
      )
      break
    case 'state': {
      const hits = matchStates(draft).slice(0, 7)
      body = (
        <>
          <input className="si-input" data-first aria-label="State" placeholder="Type a state or code…" autoComplete="off" value={draft} onChange={(e) => type(e.target.value)} onKeyDown={onKey} />
          <ul className="si-opts">
            {hits.map(([c, n]) => <li key={c}><button type="button" onClick={() => onCommit(field, c)}>{n}<small>{c}</small></button></li>)}
            {!hits.length && <li className="si-hint" style={{ padding: '6px 9px' }}>No US state matches.</li>}
          </ul>
          <div className="si-pop-foot"><span className="si-perr" role="alert">{err}</span></div>
        </>
      )
      break
    }
    case 'claim_amount':
    case 'deductible':
      body = (
        <>
          <div className="si-affix"><span>$</span><input className="si-input" data-first aria-label={FIELDS[field].label} inputMode="decimal" autoComplete="off" placeholder="0" value={draft} onChange={(e) => type(e.target.value)} onKeyDown={onKey} /></div>
          {field === 'deductible' && <Chips items={DEDUCTIBLES} current={value as string} onPick={(v) => onCommit(field, v)} />}
          {done}
        </>
      )
      break
    case 'incident_date': {
      const opts: [string, string][] = [[today, 'Today'], [addDays(today, -1), 'Yesterday'], [addDays(today, -3), '3 days ago'], [addDays(today, -7), 'A week ago']]
      body = (
        <>
          <input className="si-input" data-first aria-label="Incident date" type="date" max={today} value={draft} onChange={(e) => type(e.target.value)} onKeyDown={onKey} />
          <Chips items={opts} current={value as string} onPick={(v) => onCommit(field, v)} />
          {done}
        </>
      )
      break
    }
    case 'claim_filed_date': {
      const base = form.incident_date
      const opts: [string, string][] = base
        ? ([[0, 'Same day'], [1, 'Next day'], [3, '3 days later'], [7, 'A week later']] as [number, string][]).map(([n, l]): [string, string] => [addDays(base, n), l]).filter(([d]) => d <= today)
        : [[today, 'Today'], [addDays(today, -1), 'Yesterday']]
      body = (
        <>
          <input className="si-input" data-first aria-label="Filing date" type="date" max={today} min={base || undefined} value={draft} onChange={(e) => type(e.target.value)} onKeyDown={onKey} />
          <Chips items={opts} current={value as string} onPick={(v) => onCommit(field, v)} />
          {done}
        </>
      )
      break
    }
    case 'policyholder_tenure_years':
      body = (
        <>
          <div className="si-affix"><input className="si-input" data-first aria-label="Years as a policyholder" inputMode="decimal" autoComplete="off" placeholder="0" value={draft} onChange={(e) => type(e.target.value)} onKeyDown={onKey} /><span className="si-suffix">years</span></div>
          <Chips items={TENURES} current={value as string} onPick={(v) => onCommit(field, v)} />
          {done}
        </>
      )
      break
    case 'previous_claims_count':
      body = (
        <>
          <div className="si-stepper">
            <button type="button" aria-label="One fewer" onClick={() => type(String(Math.max(0, (Number(draft) || 0) - 1)))}>−</button>
            <input className="si-input" data-first aria-label="Earlier claims" inputMode="numeric" autoComplete="off" placeholder="0" value={draft} onChange={(e) => type(e.target.value)} onKeyDown={onKey} />
            <button type="button" aria-label="One more" onClick={() => type(String((Number(draft) || 0) + 1))}>+</button>
          </div>
          <Chips items={PRIORS} current={value as string} onPick={(v) => onCommit(field, v)} />
          {done}
        </>
      )
      break
    case 'provided_documents': {
      const docs = form.provided_documents
      const all = [...DOCS, ...docs.filter((d) => !DOCS.includes(d))]
      body = (
        <>
          <div className="si-chips">
            {all.map((d) => (
              <button key={d} type="button" className={cx('si-chip', docs.includes(d) && 'on')} aria-pressed={docs.includes(d)} onClick={() => onDocs(docs.includes(d) ? docs.filter((x) => x !== d) : [...docs, d])}>{d}</button>
            ))}
          </div>
          <input className="si-input" data-first style={{ marginTop: 10 }} aria-label="Add another document" maxLength={200} placeholder="Add another, press Enter" autoComplete="off" value={draft} onChange={(e) => type(e.target.value)} onKeyDown={onKey} />
          <p className="si-hint">Names only. Nothing is uploaded.</p>
          {done}
        </>
      )
      break
    }
  }

  return (
    <div ref={root}>
      <div className="si-pop-head">
        <span className="si-pop-title">{FIELDS[field].label}</span>
        {prov?.src === 'notes' && <span className="si-pill">{prov.via === 'model' ? 'read by the model' : 'from your notes'}</span>}
        <button type="button" className="si-x" aria-label="Close" onClick={onClose}><X size={15} /></button>
      </div>
      {prov?.src === 'notes' && prov.snip && <blockquote className="si-quote">{prov.snip}</blockquote>}
      {body}
    </div>
  )
}
