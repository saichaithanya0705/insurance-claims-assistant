// Pure presentation helpers for the claim-sentence intake: how a FormState reads as a sentence,
// the margin notes beside it and the plain-English description of the comparison filters.
import type { ClaimType } from './api'
import type { FilterState, FormState } from './claimForm'
import { daysBetweenIso, parseIso, type NoteField } from './readNotes'
import { STATES } from './states'

export type Field = NoteField
export type Tone = '' | 'sky' | 'amber' | 'rose' | 'teal'
export interface Signals { theft: boolean; missingDocs: string[] }

export const FIELDS: Record<Field, { label: string; ph: string; optional?: boolean }> = {
  claim_type: { label: 'Claim type', ph: 'a claim', optional: true },
  state: { label: 'State', ph: 'which state' },
  claim_amount: { label: 'Claim amount', ph: 'how much' },
  deductible: { label: 'Deductible', ph: '$ —' },
  incident_date: { label: 'Incident date', ph: 'which day' },
  claim_filed_date: { label: 'Filing date', ph: 'when' },
  policyholder_tenure_years: { label: 'Policyholder tenure', ph: 'how long' },
  previous_claims_count: { label: 'Earlier claims', ph: 'how many earlier claims' },
  provided_documents: { label: 'Documents received', ph: 'nothing yet', optional: true },
}
export const ORDER = Object.keys(FIELDS) as Field[]
export const REQUIRED = ORDER.filter((f) => !FIELDS[f].optional)

export const TYPES: ['' | ClaimType, string][] = [['', 'Auto-detect'], ['auto', 'Auto'], ['home', 'Home'], ['renters', 'Renters'], ['property', 'Property'], ['business', 'Business']]
const TYPE_TEXT: Record<string, string> = { '': 'A claim', auto: 'An auto claim', home: 'A home claim', renters: 'A renters claim', property: 'A property claim', business: 'A business claim' }
export const OUTCOMES: [FilterState['claim_status'], string][] = [['', 'Settled'], ['approved', 'Approved'], ['denied', 'Denied'], ['pending', 'Pending'], ['under_review', 'Under review']]
/** "police report, photos" -> ['police report', 'photos']; blanks and repeats are dropped. */
export const parseDocuments = (text: string): string[] => [...new Set(text.split(/[,;\n]/).map((d) => d.trim()).filter(Boolean))]
export const DOCS = ['incident statement', 'police report', 'repair estimate', 'photos', 'invoice', 'medical report', 'inspection report']
const DOC_ARTICLE: Record<string, string> = { 'incident statement': 'an incident statement', 'police report': 'a police report', 'repair estimate': 'a repair estimate', photos: 'photos', invoice: 'an invoice', 'medical report': 'a medical report', 'inspection report': 'an inspection report' }

export const stateName = (code: string) => STATES.find(([c]) => c === code)?.[1] ?? ''
export const fmtDate = (s: string) => parseIso(s).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
export const fmtMoney = (v: number | string) => '$' + Number(v).toLocaleString('en-US', { maximumFractionDigits: 2 })
const listJoin = (a: string[]) => (a.length < 2 ? a.join('') : a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1])
const num = (s: string) => (s.trim() === '' || !Number.isFinite(Number(s)) ? null : Number(s))
const validDate = (s: string) => /^\d{4}-\d{2}-\d{2}$/.test(s)

export const isEmpty = (form: FormState, f: Field) => (f === 'provided_documents' ? form[f].length === 0 : form[f] === '')

/** The phrase that fills a blank in the sentence, or null while it is still empty. */
export function display(f: Field, form: FormState): string | null {
  switch (f) {
    case 'claim_type':
      return TYPE_TEXT[form.claim_type] ?? TYPE_TEXT['']
    case 'state':
      return form.state ? stateName(form.state) || form.state : null
    case 'claim_amount':
    case 'deductible':
      return num(form[f]) === null ? null : fmtMoney(form[f])
    case 'incident_date':
      return validDate(form.incident_date) ? fmtDate(form.incident_date) : null
    case 'claim_filed_date': {
      const v = form.claim_filed_date
      if (!validDate(v)) return null
      if (validDate(form.incident_date)) {
        const d = daysBetweenIso(form.incident_date, v)
        if (d === 0) return 'the same day'
        if (d === 1) return 'the next day'
        if (d > 1) return `${d} days later`
      }
      return 'on ' + fmtDate(v)
    }
    case 'policyholder_tenure_years': {
      const n = num(form.policyholder_tenure_years)
      if (n === null) return null
      return n < 1 ? 'for under a year' : `for ${n} year${n === 1 ? '' : 's'}`
    }
    case 'previous_claims_count': {
      const n = num(form.previous_claims_count)
      if (n === null) return null
      return n === 0 ? 'no earlier claims' : `${n} earlier claim${n === 1 ? '' : 's'}`
    }
    case 'provided_documents':
      return form.provided_documents.length ? listJoin(form.provided_documents.map((d) => DOC_ARTICLE[d] || d)) : 'nothing yet'
  }
}

/** What still blocks submission, in the order the handler should fix it. */
export function missingList(form: FormState): [Field | 'description', string][] {
  const m: [Field | 'description', string][] = []
  if (form.description.trim().length < 10) m.push(['description', 'what happened'])
  for (const f of REQUIRED) if (isEmpty(form, f)) m.push([f, FIELDS[f].label.toLowerCase()])
  return m
}

export function marginNotes(form: FormState, signals: Signals, readCount: number): [Tone, string, string][] {
  const n: [Tone, string, string][] = []
  if (readCount) n.push(['sky', `${readCount} detail${readCount === 1 ? '' : 's'} read from your notes`, 'Underlined in blue. Click one to see the words it came from.'])
  const amt = num(form.claim_amount)
  const ded = num(form.deductible)
  if (signals.theft && !form.provided_documents.includes('police report')) n.push(['rose', 'Theft, but no police report', 'The brief will list the report as missing evidence.'])
  for (const d of signals.missingDocs)
    if (!(signals.theft && d === 'police report') && !form.provided_documents.includes(d)) n.push(['amber', `Notes say the ${d} is still missing`, 'Left out of “documents received”.'])
  if (validDate(form.incident_date) && validDate(form.claim_filed_date)) {
    const d = daysBetweenIso(form.incident_date, form.claim_filed_date)
    if (d < 0) n.push(['rose', 'Filed before the incident', 'Check the two dates. The filing date must come on or after the incident.'])
    else if (d > 30) n.push(['amber', `Reported ${d} days after the incident`, 'Late reporting is one of the things the investigation looks at.'])
    else n.push(['', `Reported ${d === 0 ? 'the same day' : d === 1 ? 'the next day' : d + ' days after the incident'}`, 'Within the usual reporting window.'])
  }
  if (amt !== null && ded !== null) {
    if (ded > amt) n.push(['rose', 'Deductible is larger than the claim', 'There would be nothing to pay out.'])
    else n.push(['teal', `Net exposure ${fmtMoney(amt - ded)}`, 'Claim amount minus the deductible.'])
  }
  if (amt !== null && amt >= 50000) n.push(['amber', 'Large loss', 'Above $50,000.'])
  const prior = num(form.previous_claims_count)
  if (prior !== null && prior >= 3) n.push(['amber', `${prior} earlier claims`, 'A frequent claimant history is weighed in the brief.'])
  const tenure = num(form.policyholder_tenure_years)
  if (tenure !== null && tenure < 1) n.push(['amber', 'New policyholder', 'Less than a year on the policy.'])
  return n
}

// ---------- "Compare it against" ----------
export type MatchKey = 'type' | 'state' | 'amount' | 'history'
export type Match = Record<MatchKey, boolean>
export const NO_MATCH: Match = { type: false, state: false, amount: false, history: false }

const STATE_CODES = new Set(STATES.map(([c]) => c))

/** The filter values one "Same …" chip stands for, given the claim as it reads now. */
export function matchFilters(key: MatchKey, form: FormState): Partial<FilterState> {
  switch (key) {
    case 'type':
      return { claim_type: form.claim_type }
    case 'state':
      return { state: STATE_CODES.has(form.state) ? form.state : '' }
    case 'amount': {
      const a = num(form.claim_amount)
      return a === null ? { min_amount: '', max_amount: '' } : { min_amount: String(Math.round(a * 0.5)), max_amount: String(Math.round(a * 1.5)) }
    }
    case 'history': {
      const p = num(form.previous_claims_count)
      return p === null ? { min_previous_claims: '', max_previous_claims: '' } : { min_previous_claims: String(Math.max(0, p - 1)), max_previous_claims: String(p + 1) }
    }
  }
}
export const clearedFilters = (key: MatchKey): Partial<FilterState> =>
  key === 'type' ? { claim_type: '' } : key === 'state' ? { state: '' } : key === 'amount' ? { min_amount: '', max_amount: '' } : { min_previous_claims: '', max_previous_claims: '' }

/** Which chips are lit for filters that already exist (a remount, or edits made in the full form). */
export function matchFromFilters(filters: FilterState, form: FormState): Match {
  const same = (key: MatchKey) => Object.entries(matchFilters(key, form)).every(([k, v]) => v !== '' && filters[k as keyof FilterState] === v)
  return { type: same('type'), state: same('state'), amount: same('amount'), history: same('history') }
}

/** Apply chip changes to the filters; keys no chip owns are left alone. */
export function applyMatch(filters: FilterState, form: FormState, next: Match, prev: Match): FilterState {
  let out = filters
  for (const key of Object.keys(next) as MatchKey[]) {
    if (next[key]) out = { ...out, ...matchFilters(key, form) }
    else if (prev[key]) out = { ...out, ...clearedFilters(key) }
  }
  return out
}

export function compareCaption(filters: FilterState): string {
  // With no outcome chosen the search compares settled (approved or denied) claims only.
  // With no type chosen the search still compares the claim's own type, never every type.
  const kind = filters.claim_type ? `${filters.claim_type} claims` : 'claims of the same type'
  const outcome = { '': 'settled', approved: 'approved', denied: 'denied', pending: 'pending' }[filters.claim_status as string]
  let head = outcome ? `${outcome} ${kind}` : `${kind} under review`
  if (filters.state) head += ` from ${stateName(filters.state) || filters.state}`
  const parts: string[] = [head]
  if (filters.min_amount !== '' || filters.max_amount !== '') {
    const lo = filters.min_amount !== '' ? fmtMoney(filters.min_amount) : null
    const hi = filters.max_amount !== '' ? fmtMoney(filters.max_amount) : null
    parts.push(lo && hi ? `between ${lo} and ${hi}` : lo ? `of at least ${lo}` : `of at most ${hi}`)
  }
  if (filters.min_previous_claims !== '' || filters.max_previous_claims !== '') {
    const lo = filters.min_previous_claims
    const hi = filters.max_previous_claims
    parts.push(lo !== '' && hi !== '' ? `with ${lo}–${hi} earlier claims` : lo !== '' ? `with at least ${lo} earlier claims` : `with at most ${hi} earlier claims`)
  }
  return 'Comparing against ' + parts.join(', ') + '.'
}

