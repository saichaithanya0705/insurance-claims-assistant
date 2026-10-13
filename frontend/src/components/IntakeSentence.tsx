import { useEffect, useLayoutEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { ArrowRight, Loader2 } from 'lucide-react'
import { extractIntake, type DemoCase, type IntakeExtraction } from '../lib/api'
import { buildClaim, buildFilters, type FilterState, type FormState } from '../lib/claimForm'
import { cx, todayLocal } from '../lib/format'
import {
  FIELDS, ORDER, OUTCOMES, REQUIRED, applyMatch, compareCaption, display, isEmpty, marginNotes, matchFromFilters, missingList,
  type Field, type Match, type MatchKey, type Signals,
} from '../lib/intakeView'
import { quoteIn, readNotes } from '../lib/readNotes'
import { ErrorBox } from './ui'
import { IntakeEditor, type Prov } from './IntakeEditor'
import { IntakeReview } from './IntakeReview'

type ProvMap = Partial<Record<Field, Prov>>
type Reader = { kind: 'idle' } | { kind: 'busy' } | { kind: 'done'; model: string; count: number } | { kind: 'local' }

const MAX_NOTES = 6000
const NO_SIGNALS: Signals = { theft: false, missingDocs: [] }
const MATCH_CHIPS: [MatchKey, string, (f: FormState) => boolean, string][] = [
  ['type', 'Same type', (f) => !f.claim_type, 'Set the claim type first'],
  ['state', 'Same state', (f) => !f.state, 'Set the state first'],
  ['amount', 'Similar amount', (f) => f.claim_amount === '', 'Set the claim amount first'],
  ['history', 'Similar history', (f) => f.previous_claims_count === '', 'Set the earlier claims first'],
]
const SENTENCE_LABEL: Record<Field, string> = Object.fromEntries(ORDER.map((f) => [f, FIELDS[f].label])) as Record<Field, string>

const reduceMotion = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
const sameValue = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)
const emptyValue = (f: Field): FormState[Field] => (f === 'provided_documents' ? [] : '')

/** A model value as the string (or list) the form holds, or null when it is not usable. */
function formValue(f: Field, raw: unknown): FormState[Field] | null {
  if (f === 'provided_documents') return Array.isArray(raw) && raw.every((d) => typeof d === 'string') && raw.length ? (raw as string[]) : null
  if (typeof raw === 'number' && Number.isFinite(raw)) return String(raw)
  return typeof raw === 'string' && raw.trim() ? raw.trim() : null
}

export function IntakeSentence({
  form, setForm, filters, setFilters, demoCases, demoLoading, demoError, onRetryDemos, selectedDemo, onDemo, busy, error, onSubmit, onReset, onClassic,
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
  onClassic: () => void
}) {
  const today = todayLocal()

  // The latest values, readable from timers and async callbacks without going stale.
  const props = useRef({ setForm, setFilters })
  const formRef = useRef(form)
  const filtersRef = useRef(filters)
  useLayoutEffect(() => {
    props.current = { setForm, setFilters }
    formRef.current = form
    filtersRef.current = filters
  })
  const [prov, setProvState] = useState<ProvMap>(() => {
    // Anything already filled in (a loaded example, a revised case, edits in the full form) is the handler's.
    const start: ProvMap = {}
    for (const f of ORDER) if (!isEmpty(form, f)) start[f] = { src: 'you' }
    return start
  })
  const provRef = useRef(prov)
  const [match, setMatchState] = useState<Match>(() => matchFromFilters(filters, form))
  const matchRef = useRef(match)
  const [localSignals, setLocalSignals] = useState<Signals>(NO_SIGNALS)
  const [modelSignals, setModelSignals] = useState<Signals>(NO_SIGNALS)
  const [reader, setReader] = useState<Reader>({ kind: 'idle' })
  const [flash, setFlash] = useState<Field[]>([])
  const [popField, setPopField] = useState<Field | null>(null)
  const [, setTick] = useState(0)
  const [dlgOpen, setDlgOpen] = useState(false)
  const [note, setNote] = useState('')

  const storyRef = useRef<HTMLTextAreaElement>(null)
  const popRef = useRef<HTMLDivElement>(null)
  const dlgRef = useRef<HTMLDialogElement>(null)
  const tokRefs = useRef<Partial<Record<Field, HTMLButtonElement | null>>>({})
  const localTimer = useRef<number>(0)
  const modelTimer = useRef<number>(0)
  const flashTimer = useRef<number>(0)
  const noteTimer = useRef<number>(0)
  const run = useRef(0)
  const abort = useRef<AbortController | null>(null)
  const pasted = useRef(false)

  const setProvs = (next: ProvMap) => {
    provRef.current = next
    setProvState(next)
  }
  const setFiltersNow = (next: FilterState) => {
    if (sameValue(next, filtersRef.current)) return
    filtersRef.current = next
    props.current.setFilters(next)
  }
  /** Change claim values. Any comparison chip that is switched on follows the new value. */
  const update = (patch: Partial<FormState>) => {
    const next = { ...formRef.current, ...patch }
    formRef.current = next
    props.current.setForm(next)
    setFiltersNow(applyMatch(filtersRef.current, next, matchRef.current, matchRef.current))
  }
  const say = (text: string) => {
    setNote(text)
    window.clearTimeout(noteTimer.current)
    noteTimer.current = window.setTimeout(() => setNote(''), 5000)
  }

  // ---------- reading the notes ----------
  /** Fill blanks from what the notes say. Values the handler set are never touched, and values the
   *  notes (or the model) no longer support are taken back out. */
  const applyLocal = (text: string) => {
    const r = readNotes(text, todayLocal())
    const provs = { ...provRef.current }
    const patch: Record<string, FormState[Field]> = {}
    const changed: Field[] = []
    for (const f of ORDER) {
      const p = provs[f]
      if (p?.src === 'you' || (!p && !isEmpty(formRef.current, f))) continue
      if (p?.via === 'model' && quoteIn(text, p.snip ?? '')) continue
      const hit = r.fields[f]
      if (hit) {
        const v = f === 'provided_documents' ? (hit.value as string[]) : String(hit.value)
        if (!sameValue(v, formRef.current[f])) changed.push(f)
        patch[f] = v
        provs[f] = { src: 'notes', snip: hit.snip }
      } else if (p?.src === 'notes') {
        patch[f] = emptyValue(f)
        delete provs[f]
      }
    }
    setProvs(provs)
    setLocalSignals({ theft: r.theft, missingDocs: r.missingDocs })
    if (Object.keys(patch).length) update(patch)
    flashFields(changed)
  }

  const flashFields = (fields: Field[]) => {
    if (!fields.length) return
    setFlash(fields)
    window.clearTimeout(flashTimer.current)
    flashTimer.current = window.setTimeout(() => setFlash([]), 1200)
  }

  /** The model's reading replaces what the local reader found, but never what the handler set. */
  const applyModel = (res: IntakeExtraction, text: string) => {
    const provs = { ...provRef.current }
    const patch: Record<string, FormState[Field]> = {}
    const changed: Field[] = []
    let count = 0
    for (const f of ORDER) {
      const p = provs[f]
      if (p?.src === 'you' || (!p && !isEmpty(formRef.current, f))) continue
      const hit = res.fields[f]
      const v = hit && quoteIn(text, hit.quote) ? formValue(f, hit.value) : null
      if (hit && v !== null) {
        if (!sameValue(v, formRef.current[f])) changed.push(f)
        patch[f] = v
        provs[f] = { src: 'notes', via: 'model', snip: hit.quote }
        count++
      } else if (p?.via === 'model') {
        patch[f] = emptyValue(f)
        delete provs[f]
      }
    }
    const missing = res.fields.missing_documents?.value
    setModelSignals({
      theft: res.fields.theft?.value === true && quoteIn(text, res.fields.theft.quote),
      missingDocs: Array.isArray(missing) && quoteIn(text, res.fields.missing_documents.quote) ? missing.filter((d): d is string => typeof d === 'string') : [],
    })
    setProvs(provs)
    if (Object.keys(patch).length) update(patch)
    applyLocal(text) // anything the model left blank can still come from the local reader
    flashFields(changed)
    setReader({ kind: 'done', model: res.model, count })
  }

  const scheduleModel = (text: string, wait: number) => {
    window.clearTimeout(modelTimer.current)
    abort.current?.abort()
    const mine = ++run.current
    if (text.trim().length < 10) return setReader({ kind: 'idle' })
    modelTimer.current = window.setTimeout(async () => {
      setReader({ kind: 'busy' })
      const controller = new AbortController()
      abort.current = controller
      try {
        const res = await extractIntake(text, controller.signal)
        if (mine !== run.current || formRef.current.description !== text) return
        applyModel(res, text)
      } catch {
        // No model, a timeout or a refusal: the instant local reading stands, quietly.
        if (mine === run.current) setReader({ kind: 'local' })
      }
    }, wait)
  }

  const onStory = (e: ChangeEvent<HTMLTextAreaElement>) => {
    const text = e.target.value
    update({ description: text })
    window.clearTimeout(localTimer.current)
    localTimer.current = window.setTimeout(() => applyLocal(text), 220)
    scheduleModel(text, pasted.current ? 0 : 1200)
    pasted.current = false
  }

  useEffect(() => {
    const el = storyRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = el.scrollHeight + 'px'
  }, [form.description])

  useEffect(() => () => {
    for (const t of [localTimer, modelTimer, flashTimer, noteTimer]) window.clearTimeout(t.current)
    run.current++
    abort.current?.abort()
  }, [])

  // ---------- the popover editor ----------
  const focusToken = (f: Field) => requestAnimationFrame(() => tokRefs.current[f]?.focus())
  const closePop = (restore = true) => {
    if (!popField) return
    const f = popField
    setPopField(null)
    if (restore) focusToken(f)
  }

  const commit = (f: Field, value: string) => {
    setProvs({ ...provRef.current, [f]: { src: 'you' } })
    if (f !== 'provided_documents') update({ [f]: value })
    const start = ORDER.indexOf(f)
    const next = [...ORDER.slice(start + 1), ...ORDER.slice(0, start)].find((x) => REQUIRED.includes(x) && isEmpty(formRef.current, x))
    if (next) setPopField(next)
    else {
      setPopField(null)
      focusToken(f)
    }
  }
  const setDocs = (docs: string[]) => {
    setProvs({ ...provRef.current, provided_documents: { src: 'you' } })
    update({ provided_documents: docs })
  }

  // ---------- the last look: every value is a box that can still be changed ----------
  const editField = (f: Exclude<Field, 'provided_documents'>, value: string) => {
    setProvs({ ...provRef.current, [f]: { src: 'you' } })
    update({ [f]: value })
  }
  // Editing a comparison value by hand also relights or dims the "Same …" chips to match.
  const editFilter = (patch: Partial<FilterState>) => {
    const nextFilters = { ...filtersRef.current, ...patch }
    setFiltersNow(nextFilters)
    const lit = matchFromFilters(nextFilters, formRef.current)
    matchRef.current = lit
    setMatchState(lit)
  }

  useEffect(() => {
    if (!popField) return
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Escape') return
      e.preventDefault()
      closePop()
    }
    const onDown = (e: PointerEvent) => {
      const t = e.target as Element
      if (!popRef.current?.contains(t) && !t.closest('.si-tok')) closePop(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onDown)
    }
  })

  useEffect(() => {
    const onResize = () => setTick((n) => n + 1)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // Sit the popover under its blank; at phone width CSS turns it into a bottom sheet.
  useLayoutEffect(() => {
    const pop = popRef.current
    if (!popField || !pop) return
    // Read the width now rather than from state, so the sheet can never go stale.
    if (window.matchMedia('(max-width: 640px)').matches) {
      pop.style.left = pop.style.top = ''
      return
    }
    const tok = tokRefs.current[popField]
    if (!tok) return
    const r = tok.getClientRects()[0] ?? tok.getBoundingClientRect()
    const left = Math.max(window.scrollX + 16, Math.min(r.left + window.scrollX, window.scrollX + window.innerWidth - pop.offsetWidth - 16))
    pop.style.left = left + 'px'
    pop.style.top = r.bottom + window.scrollY + 10 + 'px'
  })

  const trapTab = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== 'Tab' || !popRef.current) return
    const items = Array.from(popRef.current.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled])'))
    if (!items.length) return
    const first = items[0]
    const last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }

  // ---------- comparison ----------
  const toggleMatch = (key: MatchKey) => {
    const prev = matchRef.current
    const next = { ...prev, [key]: !prev[key] }
    matchRef.current = next
    setMatchState(next)
    setFiltersNow(applyMatch(filtersRef.current, formRef.current, next, prev))
  }
  const setOutcome = (status: FilterState['claim_status']) => setFiltersNow({ ...filtersRef.current, claim_status: status })

  // ---------- footer: status, dialog, submit ----------
  const jump = (f: Field | 'description') => {
    const behavior = reduceMotion() ? 'auto' : 'smooth'
    if (f === 'description') {
      storyRef.current?.focus()
      storyRef.current?.scrollIntoView({ block: 'center', behavior })
      return
    }
    tokRefs.current[f]?.scrollIntoView({ block: 'center', behavior })
    setPopField(f)
  }
  const missing = missingList(form)
  const total = REQUIRED.length + 1
  const readCount = ORDER.filter((f) => prov[f]?.src === 'notes').length
  const signals: Signals = {
    theft: localSignals.theft || modelSignals.theft,
    missingDocs: [...new Set([...localSignals.missingDocs, ...modelSignals.missingDocs])],
  }
  const next = REQUIRED.find((f) => isEmpty(form, f))

  const go = () => {
    if (busy) return
    if (missing.length) {
      say(`${missing.length} still to fill. Taking you to ${missing[0][1]}.`)
      return jump(missing[0][0])
    }
    try {
      buildClaim(form)
      buildFilters(filters)
    } catch (e) {
      const message = (e as Error).message
      say(message)
      if (/filing date/i.test(message)) jump('claim_filed_date')
      return
    }
    setDlgOpen(true)
  }

  useEffect(() => {
    const d = dlgRef.current
    if (!d) return
    if (dlgOpen && !d.open) d.showModal()
    else if (!dlgOpen && d.open) d.close()
  }, [dlgOpen])

  const preview = (() => {
    if (!dlgOpen) return { json: '', problem: '' }
    let claim: unknown
    let problem = ''
    try {
      claim = buildClaim(form)
    } catch (e) {
      problem = (e as Error).message
      claim = form
    }
    let f: unknown = {}
    try {
      f = buildFilters(filters)
    } catch (e) {
      problem ||= (e as Error).message
    }
    return { json: JSON.stringify({ claim, filters: f }, null, 2), problem }
  })()
  const startInvestigation = () => {
    setDlgOpen(false)
    onSubmit(formRef.current)
  }

  // ---------- rendering ----------
  const tok = (f: Field) => {
    const text = display(f, form)
    const p = prov[f]
    const optEmpty = !!FIELDS[f].optional && isEmpty(form, f)
    const state = !text ? 'empty' : p?.src === 'notes' ? 'read' : optEmpty ? 'opt' : 'you'
    const how = !text ? 'not set yet' : p?.src === 'notes' ? (p.via === 'model' ? 'read by the model from your notes' : 'read from your notes') : optEmpty ? 'optional' : 'set by you'
    const shown = f === 'claim_type' && optEmpty ? 'auto-detect' : text || ''
    return (
      <button
        key={f}
        ref={(el) => { tokRefs.current[f] = el }}
        type="button"
        className={cx('si-tok', state, popField === f && 'active', next === f && form.description.trim().length >= 10 && !popField && 'next', flash.includes(f) && p?.src === 'notes' && 'flash')}
        aria-haspopup="dialog"
        aria-expanded={popField === f}
        aria-label={`${SENTENCE_LABEL[f]}: ${shown} (${how}). Change`}
        onClick={() => (popField === f ? closePop() : setPopField(f))}
      >
        {text || FIELDS[f].ph}
      </button>
    )
  }

  const caption = compareCaption(filters)
  const marginList = marginNotes(form, signals, readCount)
  const readerLine = reader.kind === 'busy'
    ? <><i className="si-dot" aria-hidden="true" /><span>Reading your notes with the model…</span></>
    : reader.kind === 'done'
      ? <><i className="si-dot" aria-hidden="true" /><span>Read by <code>{reader.model}</code>: {reader.count} field{reader.count === 1 ? '' : 's'}, each tied to a quote from your notes.</span></>
      : reader.kind === 'local' && readCount
        ? <><i className="si-dot" aria-hidden="true" /><span>Filled from your notes.</span></>
        : null

  return (
    <div className="si-page">
      <header className="si-head">
        <p className="si-eyebrow">New investigation</p>
        <h2 className="si-title" id="intake-title">Tell us about the claim.</h2>
        <p className="si-lede">Write it the way you'd brief a colleague. Whatever we can read from your words fills into the sentence below. Click any underlined phrase to check or change it.</p>
      </header>

      <div className="si-layout">
        <article className="si-sheet" aria-labelledby="intake-title">
          <section className="si-story">
            <label className="si-kicker" htmlFor="si-story">What happened <span className="si-counter">{form.description.length} / {MAX_NOTES}</span></label>
            <textarea
              id="si-story"
              ref={storyRef}
              className="si-textarea"
              maxLength={MAX_NOTES}
              rows={4}
              spellCheck
              disabled={busy}
              value={form.description}
              onChange={onStory}
              onPaste={() => { pasted.current = true }}
              placeholder="Rear-ended at a red light in Austin, TX on March 3. Repair estimate came to $12,400, $500 deductible…"
            />
            <div className={cx('si-reader', reader.kind === 'busy' && 'busy')} aria-live="polite">{readerLine}</div>
            <div className="si-examples">
              <span>Or start from an example:</span>
              {demoLoading && <span role="status">Loading examples…</span>}
              {demoCases.map((demo, index) => (
                <button key={demo.id} type="button" className="si-ex" aria-pressed={selectedDemo === demo.id} disabled={busy} onClick={() => onDemo(index)}>{demo.title}</button>
              ))}
              {!demoLoading && !demoError && demoCases.length === 0 && <span>none available</span>}
              <button type="button" className="si-link" onClick={() => { onReset(); requestAnimationFrame(() => storyRef.current?.focus()) }}>Clear</button>
            </div>
            {!demoLoading && demoError && (
              <div className="si-demo-error"><ErrorBox message={demoError} /><button type="button" className="si-link" onClick={onRetryDemos}>Retry examples</button></div>
            )}
          </section>

          <section className="si-summary" aria-labelledby="si-sum">
            <p className="si-kicker" id="si-sum">The claim, in one sentence</p>
            <p className="si-sentence">
              {tok('claim_type')} from {tok('state')}, for {tok('claim_amount')} against a {tok('deductible')} deductible.{' '}
              It happened on {tok('incident_date')} and was reported {tok('claim_filed_date')}.{' '}
              The policyholder has been with us {tok('policyholder_tenure_years')} and has {tok('previous_claims_count')}.{' '}
              They have sent {tok('provided_documents')}.
            </p>
            <div className="si-legend" aria-hidden="true">
              <span><i className="l-read" />read from your notes</span>
              <span><i className="l-you" />set by you</span>
              <span><i className="l-need" />still needed</span>
              <span><i className="l-opt" />optional</span>
            </div>
          </section>

          <section className="si-compare" aria-labelledby="si-cmp">
            <p className="si-kicker" id="si-cmp">Compare it against</p>
            <div className="si-match" role="group" aria-labelledby="si-cmp">
              {MATCH_CHIPS.map(([key, label, off, why]) => (
                <button key={key} type="button" className="si-mchip" aria-pressed={match[key] && !off(form)} disabled={off(form)} title={off(form) ? why : undefined} onClick={() => toggleMatch(key)}>{label}</button>
              ))}
              <span className="si-outcome" role="group" aria-label="Outcome">
                {OUTCOMES.map(([v, l]) => <button key={v || 'settled'} type="button" aria-pressed={filters.claim_status === v} onClick={() => setOutcome(v)}>{l}</button>)}
              </span>
            </div>
            <p className="si-caption" aria-live="polite">{caption}</p>
          </section>

          {error && <div className="si-error"><ErrorBox message={error} /></div>}

          <footer className="si-send">
            <div className="si-progress" aria-hidden="true">{Array.from({ length: total }, (_, i) => <i key={i} className={i < total - missing.length ? 'on' : ''} />)}</div>
            <div className="si-status" aria-live="polite">
              {missing.length ? (
                <><strong>{missing.length} to go.</strong> Next: <button type="button" onClick={() => jump(missing[0][0])}>{missing[0][1]}</button></>
              ) : (
                <><strong>Ready.</strong> {readCount ? `${readCount} detail${readCount === 1 ? ' was' : 's were'} read from your notes. Give the blue ones a glance.` : 'Everything was set by you.'}</>
              )}
              {note && <span className="si-note-line" role="status">{note}</span>}
            </div>
            <button type="button" className="si-link" onClick={() => setDlgOpen(true)}>What gets sent</button>
            <button type="button" className={cx('si-primary', missing.length > 0 && 'waiting')} id="investigate-button" disabled={busy} onClick={go}>
              {busy ? <><Loader2 size={16} className="spin" /> Building investigation…</> : <>Investigate <ArrowRight size={16} /></>}
            </button>
          </footer>
        </article>

        <aside className="si-margin" aria-labelledby="si-m">
          <h3 id="si-m">In the margin</h3>
          <div aria-live="polite">
            {marginList.length ? marginList.map(([tone, b, s]) => <div key={b} className={cx('si-note', tone)}><b>{b}</b><span>{s}</span></div>) : (
              <div className="si-note empty">Notes appear here as the claim takes shape: reporting delay, net exposure, missing evidence.</div>
            )}
          </div>
          <div className="si-escape">Prefer separate boxes? <button type="button" className="si-link" onClick={onClassic}>Use the full form</button></div>
          <p className="si-foot">Recommendations require handler review. Nothing here approves, denies or pays a claim.</p>
        </aside>
      </div>

      {popField && createPortal(
        <div ref={popRef} className="si-pop" role="dialog" aria-label={FIELDS[popField].label} onKeyDown={trapTab}>
          <IntakeEditor key={popField} field={popField} form={form} prov={prov[popField]} today={today} onCommit={commit} onDocs={setDocs} onClose={() => closePop()} />
        </div>,
        document.body,
      )}

      <dialog ref={dlgRef} className="si-dlg" aria-labelledby="si-dlg-h" onCancel={() => setDlgOpen(false)} onClose={() => setDlgOpen(false)}>
        <div className="si-dlg-body">
          <h3 id="si-dlg-h">{missing.length ? 'A few details are still needed' : 'Check the claim one last time'}</h3>
          <p>Change anything here before you start. This is exactly what is sent to <code>POST /api/investigations</code>; nothing is sent until you press Start investigation.</p>
          {(missing.length > 0 || preview.problem) && <p className="si-dlg-warn" role="status">{preview.problem || `Not ready yet: ${missing.length} detail${missing.length === 1 ? '' : 's'} still needed.`}</p>}
          {dlgOpen && (
            <IntakeReview
              form={form}
              filters={filters}
              hints={Object.fromEntries(ORDER.filter((f) => prov[f]?.src === 'notes' && !isEmpty(form, f)).map((f) => [f, 'Read from your notes. Please check it.']))}
              today={today}
              json={preview.json}
              onField={editField}
              onDescription={(value) => update({ description: value })}
              onDocs={setDocs}
              onFilter={editFilter}
            />
          )}
        </div>
        <div className="si-dlg-foot">
          <button type="button" className="si-ghost" onClick={() => setDlgOpen(false)}>Back to editing</button>
          <button type="button" className="si-primary" disabled={busy || missing.length > 0 || !!preview.problem} onClick={startInvestigation}>Start investigation</button>
        </div>
      </dialog>
    </div>
  )
}
