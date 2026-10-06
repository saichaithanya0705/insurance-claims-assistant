import { AnimatePresence, motion } from 'motion/react'
import { useState, type FormEvent, type KeyboardEvent } from 'react'
import {
  ArrowRight,
  Car,
  ChevronDown,
  CircleHelp,
  FileText,
  House,
  KeyRound,
  Loader2,
  Plus,
  RotateCcw,
  SlidersHorizontal,
  X,
} from 'lucide-react'
import type { ClaimInput, ClaimType, DemoCase, SearchFilters } from '../lib/api'
import { cx, daysBetween, money, todayLocal } from '../lib/format'
import { STATES, stateCode } from '../lib/states'
import { Card, DataView, ErrorBox } from './ui'

export interface FormState {
  description: string
  claim_type: '' | ClaimType
  state: string
  incident_date: string
  claim_filed_date: string
  claim_amount: string
  deductible: string
  previous_claims_count: string
  policyholder_tenure_years: string
  provided_documents: string[]
}

export interface FilterState {
  claim_type: '' | ClaimType
  state: string
  claim_status: '' | 'approved' | 'denied'
  min_amount: string
  max_amount: string
  min_previous_claims: string
  max_previous_claims: string
}

export const EMPTY_FORM: FormState = {
  description: '',
  claim_type: '',
  state: '',
  incident_date: '',
  claim_filed_date: '',
  claim_amount: '',
  deductible: '',
  previous_claims_count: '',
  policyholder_tenure_years: '',
  provided_documents: [],
}

export const EMPTY_FILTERS: FilterState = {
  claim_type: '',
  state: '',
  claim_status: '',
  min_amount: '',
  max_amount: '',
  min_previous_claims: '',
  max_previous_claims: '',
}

export const formFromClaim = (claim: ClaimInput): FormState => ({
  description: claim.description ?? '',
  claim_type: claim.claim_type ?? '',
  state: claim.state ?? '',
  incident_date: claim.incident_date ?? '',
  claim_filed_date: claim.claim_filed_date ?? '',
  claim_amount: String(claim.claim_amount ?? ''),
  deductible: String(claim.deductible ?? ''),
  previous_claims_count: String(claim.previous_claims_count ?? ''),
  policyholder_tenure_years: String(claim.policyholder_tenure_years ?? ''),
  provided_documents: Array.isArray(claim.provided_documents) ? claim.provided_documents : [],
})

export function buildClaim(form: FormState): ClaimInput {
  const claim: ClaimInput = {
    description: form.description.trim(),
    claim_type: form.claim_type || null,
    state: stateCode(form.state),
    incident_date: form.incident_date,
    claim_filed_date: form.claim_filed_date,
    claim_amount: Number(form.claim_amount),
    deductible: Number(form.deductible),
    previous_claims_count: Number(form.previous_claims_count),
    policyholder_tenure_years: Number(form.policyholder_tenure_years),
    provided_documents: form.provided_documents.map((d) => d.trim()).filter(Boolean),
  }
  if (claim.description.length < 10) throw new Error('Describe the incident in at least 10 characters.')
  if (claim.description.length > 6000) throw new Error('Keep the incident description within 6000 characters.')
  if (!STATES.some(([code]) => code === claim.state)) throw new Error('Enter a two-letter US state code, for example CA.')
  if (!claim.incident_date || !claim.claim_filed_date) throw new Error('Enter both the incident and filing dates.')
  if (claim.claim_filed_date < claim.incident_date) throw new Error('Filing date must be on or after the incident date.')
  if (claim.incident_date > todayLocal() || claim.claim_filed_date > todayLocal()) throw new Error('Dates cannot be in the future.')
  for (const key of ['claim_amount', 'deductible', 'previous_claims_count', 'policyholder_tenure_years'] as const)
    if (form[key].trim() === '' || !Number.isFinite(claim[key]) || claim[key] < 0) throw new Error(`Enter a valid ${key.replace(/_/g, ' ')}.`)
  if (claim.claim_amount > 1_000_000_000 || claim.deductible > 1_000_000_000) throw new Error('Amounts cannot exceed one billion dollars.')
  if (!Number.isInteger(claim.previous_claims_count) || claim.previous_claims_count > 1000) throw new Error('Previous claims must be a whole number from 0 to 1000.')
  if (claim.policyholder_tenure_years > 100) throw new Error('Tenure cannot exceed 100 years.')
  if (claim.provided_documents.length > 50) throw new Error('List at most 50 available documents.')
  return claim
}

export function buildFilters(f: FilterState): SearchFilters {
  const filters: SearchFilters = {}
  if (f.claim_type) filters.claim_type = f.claim_type
  if (f.state.trim()) filters.state = f.state.trim().toUpperCase()
  if (f.claim_status) filters.claim_status = f.claim_status
  for (const key of ['min_amount', 'max_amount', 'min_previous_claims', 'max_previous_claims'] as const)
    if (f[key] !== '') filters[key] = Number(f[key])
  if (filters.min_amount !== undefined && filters.max_amount !== undefined && filters.min_amount > filters.max_amount)
    throw new Error('Minimum amount cannot exceed maximum amount.')
  if (
    filters.min_previous_claims !== undefined &&
    filters.max_previous_claims !== undefined &&
    filters.min_previous_claims > filters.max_previous_claims
  )
    throw new Error('Minimum prior claims cannot exceed maximum prior claims.')
  return filters
}

const TYPES: { value: '' | ClaimType; label: string }[] = [
  { value: '', label: 'Auto-detect' },
  { value: 'auto', label: 'Auto' },
  { value: 'home', label: 'Home' },
  { value: 'renters', label: 'Renters' },
  { value: 'property', label: 'Property' },
  { value: 'business', label: 'Business' },
]

const DOC_SUGGESTIONS = ['incident statement', 'police report', 'repair estimate', 'photos', 'invoice', 'medical report', 'inspection report']

const demoVisual = (id: string) => {
  switch (id) {
    case 'auto-ready':
      return { Icon: Car, color: 'var(--teal)', bg: 'var(--teal-dim)' }
    case 'theft-gap':
      return { Icon: KeyRound, color: 'var(--amber)', bg: 'var(--amber-dim)' }
    case 'home-conflict':
      return { Icon: House, color: 'var(--rose)', bg: 'var(--rose-dim)' }
    case 'unknown':
      return { Icon: CircleHelp, color: 'var(--violet)', bg: 'var(--violet-dim)' }
    default:
      return { Icon: FileText, color: 'var(--sky)', bg: 'var(--sky-dim)' }
  }
}

export function IntakeForm({
  form,
  setForm,
  filters,
  setFilters,
  demoCases,
  demoLoading,
  demoError,
  onRetryDemos,
  selectedDemo,
  onDemo,
  busy,
  error,
  onSubmit,
  onReset,
}: {
  form: FormState
  setForm: (f: FormState) => void
  filters: FilterState
  setFilters: (f: FilterState) => void
  demoCases: DemoCase[]
  demoLoading: boolean
  demoError: string | null
  onRetryDemos: () => void
  selectedDemo: string | null
  onDemo: (index: number) => void
  busy: boolean
  error: string | null
  onSubmit: (nextForm: FormState) => void
  onReset: () => void
}) {
  const [step, setStep] = useState(0)
  const [expert, setExpert] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const [docDraft, setDocDraft] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const today = todayLocal()
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setFieldErrors({})
    setForm({ ...form, [key]: value })
  }
  const setF = <K extends keyof FilterState>(key: K, value: FilterState[K]) => {
    setFieldErrors({})
    setFilters({ ...filters, [key]: value })
  }
  const errorProps = (id: string) => ({
    'aria-invalid': !!fieldErrors[id],
    'aria-describedby': fieldErrors[id] ? `${id}-error` : undefined,
  })
  const fieldError = (id: string) => fieldErrors[id] ? <small id={`${id}-error`} className="field-error" role="alert">{fieldErrors[id]}</small> : null

  const delay = daysBetween(form.incident_date, form.claim_filed_date)
  const net = form.claim_amount !== '' && form.deductible !== '' ? Number(form.claim_amount) - Number(form.deductible) : null
  const prior = form.previous_claims_count === '' ? null : Number(form.previous_claims_count)
  const activeFilters = Object.values(filters).filter((v) => v !== '').length

  const addDoc = (value: string) => {
    const v = value.trim()
    if (!v || form.provided_documents.includes(v) || form.provided_documents.length >= 50) return
    set('provided_documents', [...form.provided_documents, v])
    setDocDraft('')
  }
  const onDocKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addDoc(docDraft)
    } else if (e.key === 'Backspace' && !docDraft && form.provided_documents.length)
      set('provided_documents', form.provided_documents.slice(0, -1))
  }

  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (busy) return
    const formElement = e.currentTarget
    const controls = Array.from(formElement.elements).filter(
      (control): control is HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement =>
        control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement,
    )
    controls.forEach((control) => control.setCustomValidity(''))
    const custom = (id: string, message: string) => controls.find((control) => control.id === id)?.setCustomValidity(message)
    if (form.description.trim().length < 10) custom('description', 'Describe the incident in at least 10 non-whitespace characters.')
    if (!STATES.some(([code]) => code === stateCode(form.state))) custom('state', 'Enter a two-letter US state code, for example CA.')
    if (form.claim_filed_date && form.incident_date && form.claim_filed_date < form.incident_date) custom('claim_filed_date', 'Filing date must be on or after the incident date.')
    if (form.incident_date > today) custom('incident_date', 'Incident date cannot be in the future.')
    if (form.claim_filed_date > today) custom('claim_filed_date', 'Filing date cannot be in the future.')
    if (filters.state && !/^[A-Z]{2}$/.test(filters.state)) custom('f-state', 'Enter a two-letter state code or leave this filter empty.')
    if (filters.min_amount !== '' && filters.max_amount !== '' && Number(filters.min_amount) > Number(filters.max_amount)) custom('f-max-amt', 'Maximum amount must be at least the minimum amount.')
    if (filters.min_previous_claims !== '' && filters.max_previous_claims !== '' && Number(filters.min_previous_claims) > Number(filters.max_previous_claims)) custom('f-max-h', 'Maximum prior claims must be at least the minimum.')
    const invalid = controls.filter((control) => (!expert && step === 0 ? control.id === 'description' : true) && !control.checkValidity())
    if (invalid.length) {
      setFieldErrors(Object.fromEntries(invalid.map((control) => [control.id, control.validationMessage])))
      if (!expert) setStep(invalid[0].id === 'description' ? 0 : 1)
      requestAnimationFrame(() => invalid[0].focus())
      if (invalid[0].id.startsWith('f-') && !showFilters) {
        setShowFilters(true)
        requestAnimationFrame(() => invalid[0].focus())
      } else invalid[0].focus()
      return
    }
    if (!expert && step === 0) { setStep(1); requestAnimationFrame(() => document.getElementById('state')?.focus()); return }
    const documentName = docDraft.trim()
    if (documentName && !form.provided_documents.includes(documentName) && form.provided_documents.length >= 50) {
      setFieldErrors({ 'doc-input': 'List at most 50 available documents. Remove one before adding another.' })
      controls.find((control) => control.id === 'doc-input')?.focus()
      return
    }
    const nextForm = documentName && !form.provided_documents.includes(documentName)
      ? { ...form, provided_documents: [...form.provided_documents, documentName] }
      : form
    setFieldErrors({})
    setForm(nextForm)
    setDocDraft('')
    if (!expert && step < 2) { setStep(2); requestAnimationFrame(() => document.getElementById('draft-review')?.focus()); return }
    onSubmit(nextForm)
  }

  return (
    <Card className="intake" aria-labelledby="intake-title">
      <div className="card-head">
        <h2 id="intake-title">
          <span className="head-icon">
            <FileText size={15} />
          </span>
          New investigation
        </h2>
        <button type="button" className="btn sm" aria-pressed={expert} onClick={() => { setExpert(v => !v) }}>{expert ? 'Guided entry' : 'All fields'}</button>
      </div>
      <div className="card-body" id="intake-body">
        <p className="section-desc">Describe the incident, confirm details, then review before building a brief.</p>
        {!expert && <nav className="composer-steps" aria-label="Intake steps">{['Incident', 'Details', 'Review'].map((name, i) => <span key={name} aria-current={step === i ? 'step' : undefined}>{i + 1}. {name}</span>)}</nav>}
        <details className="form-section"><summary>Try an example · Optional</summary>
          <div className="demo-grid">
            {demoLoading && <p role="status" style={{ gridColumn: '1 / -1' }}>Loading demo cases…</p>}
            {!demoLoading && demoError && <div style={{ gridColumn: '1 / -1' }}><ErrorBox message={demoError} /><button type="button" className="btn sm" onClick={onRetryDemos}>Retry demo cases</button></div>}
            {!demoLoading && !demoError && demoCases.length === 0 && <p style={{ gridColumn: '1 / -1' }}>No demo cases are available. Enter a claim below.</p>}
            {demoCases.map((demo, index) => {
              const { Icon, color, bg } = demoVisual(demo.id)
              return (
                <button
                  key={demo.id}
                  type="button"
                  className={cx('demo-card', selectedDemo === demo.id && 'selected')}
                  onClick={() => { setDocDraft(''); setFieldErrors({}); onDemo(index) }}
                  disabled={busy}
                >
                  <span className="ic" style={{ color, background: bg }}>
                    <Icon size={15} />
                  </span>
                  <span className="tt">{demo.title}</span>
                  <span className="mm">
                    {demo.claim.state} · {money(demo.claim.claim_amount)}
                  </span>
                </button>
              )
            })}
          </div>
        </details>

        <form onSubmit={submit} noValidate onInput={(event) => {
          const control = event.target
          if (control instanceof HTMLInputElement || control instanceof HTMLTextAreaElement || control instanceof HTMLSelectElement) control.setCustomValidity('')
        }}>
          <fieldset disabled={busy} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
            <div hidden={!expert && step !== 0}>
            <div className="field">
              <label htmlFor="description">
                Incident description <span className="counter">{form.description.length}/6000</span>
              </label>
              <textarea
                id="description"
                {...errorProps('description')}
                required
                minLength={10}
                maxLength={6000}
                value={form.description}
                onChange={(e) => set('description', e.target.value)}
                placeholder="Describe the incident, available evidence and any open questions."
              />
              {fieldError('description')}
            </div>

            <div className="field" role="radiogroup" aria-labelledby="type-label">
              <span className="field-label" id="type-label">
                Claim type
              </span>
              <div className="seg">
                {TYPES.map((t) => (
                  <label key={t.value || 'auto-detect'} className="seg-opt">
                    <input type="radio" name="claim_type" value={t.value} checked={form.claim_type === t.value} onChange={() => set('claim_type', t.value)} />
                    <span>{t.label}</span>
                  </label>
                ))}
              </div>
            </div>

            </div><div hidden={!expert && step !== 1}>
            <div className="field-row">
              <div className="field">
                <label htmlFor="state">US state</label>
                <input
                  id="state"
                  {...errorProps('state')}
                  required
                  list="us-states"
                  value={form.state}
                  onChange={(e) => set('state', e.target.value)}
                  onBlur={() => set('state', stateCode(form.state))}
                  placeholder="State name or code, e.g. Texas"
                  autoCapitalize="characters"
                  autoComplete="address-level1"
                />
                <datalist id="us-states">{STATES.map(([code, name]) => <option key={code} value={name}>{code}</option>)}</datalist>
                {fieldError('state')}
              </div>
              <div className="field">
                <label htmlFor="tenure">Policyholder tenure · years</label>
                <input id="tenure" {...errorProps('tenure')} type="number" min={0} max={100} step="any" required value={form.policyholder_tenure_years} onChange={(e) => set('policyholder_tenure_years', e.target.value)} placeholder="0.0" />
                {fieldError('tenure')}
              </div>
            </div>

            <div className="field-row">
              <div className="field">
                <label htmlFor="incident_date">Incident date</label>
                <input id="incident_date" {...errorProps('incident_date')} type="date" max={today} required value={form.incident_date} onChange={(e) => set('incident_date', e.target.value)} />
                {fieldError('incident_date')}
              </div>
              <div className="field">
                <label htmlFor="claim_filed_date">Filing date</label>
                <input id="claim_filed_date" {...errorProps('claim_filed_date')} type="date" max={today} min={form.incident_date || undefined} required value={form.claim_filed_date} onChange={(e) => set('claim_filed_date', e.target.value)} />
                {fieldError('claim_filed_date')}
              </div>
            </div>

            <div className="field-row">
              <div className="field">
                <label htmlFor="claim_amount">Claim amount</label>
                <div className="affix">
                  <span>$</span>
                  <input id="claim_amount" {...errorProps('claim_amount')} type="number" min={0} max={1_000_000_000} step={0.01} required value={form.claim_amount} onChange={(e) => set('claim_amount', e.target.value)} placeholder="0.00" />
                </div>
                {fieldError('claim_amount')}
              </div>
              <div className="field">
                <label htmlFor="deductible">Deductible</label>
                <div className="affix">
                  <span>$</span>
                  <input id="deductible" {...errorProps('deductible')} type="number" min={0} max={1_000_000_000} step={0.01} required value={form.deductible} onChange={(e) => set('deductible', e.target.value)} placeholder="0.00" />
                </div>
                {fieldError('deductible')}
              </div>
            </div>

            <div className="field">
              <label htmlFor="prior">Previous claims</label>
              <input id="prior" {...errorProps('prior')} type="number" min={0} max={1000} step={1} required value={form.previous_claims_count} onChange={(e) => set('previous_claims_count', e.target.value)} placeholder="0" />
              {fieldError('prior')}
            </div>

            <div className="signals" aria-label="Live queue policy signals">
              <div className={cx('signal', delay !== null && delay > 14 && 'warn')}>
                <small>Filing delay</small>
                <strong>{delay === null ? '—' : `${delay}d`}</strong>
              </div>
              <div className="signal">
                <small>Net exposure</small>
                <strong>{net === null || !Number.isFinite(net) ? '—' : money(net)}</strong>
              </div>
              <div className={cx('signal', prior !== null && prior >= 3 && 'warn')}>
                <small>Prior claims</small>
                <strong>{prior === null ? '—' : prior}</strong>
              </div>
            </div>

            <div className="field">
              <span className="field-label">
                <span>
                  Documents reported available <span className="opt">/ optional</span>
                </span>
                <span className="counter">{form.provided_documents.length}/50</span>
              </span>
              <div className="tag-input" onClick={() => document.getElementById('doc-input')?.focus()}>
                <AnimatePresence initial={false}>
                  {form.provided_documents.map((doc) => (
                    <motion.span key={doc} className="tag" layout initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} exit={{ opacity: 0, scale: 0.8 }}>
                      {doc}
                      <button type="button" aria-label={`Remove ${doc}`} onClick={() => set('provided_documents', form.provided_documents.filter((d) => d !== doc))}>
                        <X size={11} />
                      </button>
                    </motion.span>
                  ))}
                </AnimatePresence>
                <input id="doc-input" {...errorProps('doc-input')} value={docDraft} onChange={(e) => { setFieldErrors({}); setDocDraft(e.target.value) }} onKeyDown={onDocKey} placeholder={form.provided_documents.length ? 'Add another…' : 'Type a document name, press Enter'} aria-label="Add document name" maxLength={200} />
              </div>
              {fieldError('doc-input')}
              <div className="suggest">
                {DOC_SUGGESTIONS.filter((s) => !form.provided_documents.includes(s)).map((s) => (
                  <button key={s} type="button" onClick={() => addDoc(s)}>
                    <Plus size={10} style={{ verticalAlign: -1 }} /> {s}
                  </button>
                ))}
              </div>
              <small>Names only. This form does not upload document content.</small>
            </div>

            <button type="button" className="collapse-btn" aria-expanded={showFilters} aria-controls="filters-panel" onClick={() => setShowFilters((s) => !s)}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <SlidersHorizontal size={15} /> Historical case filters
                {activeFilters > 0 && <span className="pill sky">{activeFilters} active</span>}
              </span>
              <motion.span animate={{ rotate: showFilters ? 180 : 0 }}>
                <ChevronDown size={16} />
              </motion.span>
            </button>
                <div
                  id="filters-panel"
                  hidden={!showFilters}
                  style={{ display: showFilters ? undefined : 'none' }}
                >
                  <p className="field" style={{ fontSize: 12, color: 'var(--text-3)' }}>
                    Narrow the comparison set independently of the submitted claim.
                  </p>
                  <div className="field-row">
                    <div className="field">
                      <label htmlFor="f-type">Claim type</label>
                      <select id="f-type" value={filters.claim_type} onChange={(e) => setF('claim_type', e.target.value as FilterState['claim_type'])}>
                        <option value="">All types</option>
                        {TYPES.slice(1).map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div className="field">
                      <label htmlFor="f-state">State</label>
                      <input id="f-state" {...errorProps('f-state')} pattern="[A-Z]{2}" maxLength={2} value={filters.state} onChange={(e) => setF('state', e.target.value.toUpperCase().replace(/[^A-Z]/g, ''))} placeholder="All states" />
                      {fieldError('f-state')}
                    </div>
                  </div>
                  <div className="field">
                    <label htmlFor="f-status">Historical outcome</label>
                    <select id="f-status" value={filters.claim_status} onChange={(e) => setF('claim_status', e.target.value as FilterState['claim_status'])}>
                      <option value="">All outcomes</option>
                      <option value="approved">Approved</option>
                      <option value="denied">Denied</option>
                    </select>
                  </div>
                  <div className="field-row">
                    <div className="field">
                      <label htmlFor="f-min-amt">Min amount</label>
                      <input id="f-min-amt" {...errorProps('f-min-amt')} type="number" min={0} step={0.01} value={filters.min_amount} onChange={(e) => setF('min_amount', e.target.value)} placeholder="No minimum" />
                      {fieldError('f-min-amt')}
                    </div>
                    <div className="field">
                      <label htmlFor="f-max-amt">Max amount</label>
                      <input id="f-max-amt" {...errorProps('f-max-amt')} type="number" min={0} step={0.01} value={filters.max_amount} onChange={(e) => setF('max_amount', e.target.value)} placeholder="No maximum" />
                      {fieldError('f-max-amt')}
                    </div>
                  </div>
                  <div className="field-row">
                    <div className="field">
                      <label htmlFor="f-min-h">Min prior claims</label>
                      <input id="f-min-h" {...errorProps('f-min-h')} type="number" min={0} step={1} value={filters.min_previous_claims} onChange={(e) => setF('min_previous_claims', e.target.value)} placeholder="No minimum" />
                      {fieldError('f-min-h')}
                    </div>
                    <div className="field">
                      <label htmlFor="f-max-h">Max prior claims</label>
                      <input id="f-max-h" {...errorProps('f-max-h')} type="number" min={0} step={1} value={filters.max_previous_claims} onChange={(e) => setF('max_previous_claims', e.target.value)} placeholder="No maximum" />
                      {fieldError('f-max-h')}
                    </div>
                  </div>
                </div>

            </div>
            {!expert && step === 2 && <section id="draft-review" tabIndex={-1}><h3>Review the draft</h3><p className="section-desc">Check these inputs before submission. Document names mean reported available; content has not been attached, extracted or reviewed.</p><DataView value={{ incident: form.description, type: form.claim_type || 'Auto-detect', state: stateCode(form.state), incident_date: form.incident_date, filing_date: form.claim_filed_date, claim_amount: form.claim_amount, deductible: form.deductible, previous_claims: form.previous_claims_count, policyholder_tenure_years: form.policyholder_tenure_years, documents_reported_available: form.provided_documents, historical_comparison_filters: filters }} /></section>}
            <div style={{ marginTop: 10, display: 'grid', gap: 10 }}>
              <ErrorBox message={error} />
              {!expert && step > 0 && <button type="button" className="btn" onClick={() => { setStep(n => n - 1); requestAnimationFrame(() => document.getElementById(step === 1 ? 'description' : 'state')?.focus()) }}>Back</button>}
              <button className="btn primary lg" type="submit" id="investigate-button">
                {busy ? (
                  <>
                    <Loader2 size={17} className="spin" /> Building investigation…
                  </>
                ) : (
                  <>
                    {!expert && step < 2 ? 'Continue' : 'Build investigation brief'} <ArrowRight size={17} />
                  </>
                )}
              </button>
              <button type="button" className="btn ghost sm" onClick={() => { setDocDraft(''); setFieldErrors({}); onReset() }} style={{ justifySelf: 'center' }}>
                <RotateCcw size={13} /> Clear form
              </button>
            </div>
            <p className="form-foot">Recommendations require handler review. Nothing here approves, denies or pays a claim.</p>
          </fieldset>
        </form>
      </div>
    </Card>
  )
}
