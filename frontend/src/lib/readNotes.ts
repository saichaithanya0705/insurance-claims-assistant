// Deterministic, local reader for the intake notes. The same words always give the same values and
// nothing is sent anywhere. The model pass (POST /api/intake/extract) refines these results.
import { todayLocal } from './format'
import { STATES } from './states'

export type NoteField =
  | 'claim_type'
  | 'state'
  | 'claim_amount'
  | 'deductible'
  | 'incident_date'
  | 'claim_filed_date'
  | 'policyholder_tenure_years'
  | 'previous_claims_count'
  | 'provided_documents'

export interface NoteHit {
  value: string | number | string[]
  /** The words the value came from, with a little surrounding context. */
  snip: string
}

export interface NotesReading {
  fields: Partial<Record<NoteField, NoteHit>>
  theft: boolean
  /** Documents the notes say are missing (and never also reported as received). */
  missingDocs: string[]
}

// ---------- dates (all local calendar days, as ISO yyyy-mm-dd) ----------
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
export const parseIso = (s: string) => {
  const [y, m, d] = s.split('-').map(Number)
  return new Date(y, m - 1, d)
}
export const addDays = (s: string, n: number) => {
  const d = parseIso(s)
  d.setDate(d.getDate() + n)
  return iso(d)
}
export const daysBetweenIso = (a: string, b: string) => Math.round((parseIso(b).getTime() - parseIso(a).getTime()) / 864e5)
const mkDate = (y: number, m: number, d: number) => {
  const dt = new Date(y, m - 1, d)
  return dt.getMonth() === m - 1 && dt.getDate() === d && dt.getFullYear() === y ? iso(dt) : null
}

/** Whitespace-normalised, case-insensitive containment: how the server checks a model's quote. */
export const normalise = (s: string) => s.replace(/\s+/g, ' ').trim().toLowerCase()
export const quoteIn = (text: string, quote: string) => !!quote && normalise(text).includes(normalise(quote))

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const WORDNUM: Record<string, number> = { no: 0, zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10 }
const MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
const TYPE_WORDS: Record<string, RegExp> = {
  auto: /\b(car|cars|vehicle|truck|sedan|suv|driver|driving|collision|rear-ended|rear ended|windshield|bumper|honda|toyota|ford|tesla|motorcycle|fender)\b/gi,
  home: /\b(house|home|roof|basement|kitchen|pipe|burst|flood|flooded|flooding|homeowner|attic|bathroom)\b/gi,
  renters: /\b(apartment|renter|renters|tenant|landlord|lease)\b/gi,
  property: /\b(fence|shed|barn|outbuilding|rental property|vacant lot)\b/gi,
  business: /\b(business|store|shop|office|restaurant|inventory|warehouse|employee|commercial|storefront)\b/gi,
}
const DOC_WORDS: [string, RegExp][] = [
  ['police report', /\bpolice report\b/gi],
  ['photos', /\b(photos?|pictures?)\b/gi],
  ['repair estimate', /\b(?:repair |body shop |contractor )?estimate\b/gi],
  ['invoice', /\binvoices?\b/gi],
  ['medical report', /\bmedical (?:report|records?)\b/gi],
  ['inspection report', /\binspection report\b/gi],
  ['incident statement', /\b(?:incident|written|signed) statement\b/gi],
]
const NEGATED = /\b(no|without|missing|not|hasn't|hasnt|haven't|lacks?|waiting (?:on|for))\b[^.;]*$/i
const FILED_CTX = /\b(report\w*|filed|files?|submit\w*|called|notif\w*|lodged|contacted|phoned|opened)\b[^.;]*$/i
const STATES_LONGEST_FIRST = [...STATES].sort((a, b) => b[1].length - a[1].length)
const STATE_CODES = new Set(STATES.map(([code]) => code))

function snip(t: string, i: number, j: number) {
  const a = Math.max(0, i - 30)
  const b = Math.min(t.length, j + 30)
  return (a > 0 ? '…' : '') + t.slice(a, b).replace(/\s+/g, ' ').trim() + (b < t.length ? '…' : '')
}

interface Span { v: string | number; i: number; j: number }
interface DateSpan { v: string; i: number; j: number; filed?: boolean }

export function readNotes(t: string, today: string = todayLocal()): NotesReading {
  const out: NotesReading['fields'] = {}
  const put = (f: NoteField, value: NoteHit['value'], i: number, j: number) => {
    if (!(f in out)) out[f] = { value, snip: snip(t, i, j) }
  }
  const thisYear = parseIso(today).getFullYear()

  // money: the figure closest to the word "deductible" is the deductible; the largest other is the claim
  const money: { v: number; i: number; j: number }[] = []
  for (const m of t.matchAll(/\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?(\s?k\b)?/gi)) {
    let v = Number(m[1].replace(/,/g, '') + (m[2] ? '.' + m[2] : ''))
    if (m[3]) v *= 1000
    money.push({ v, i: m.index, j: m.index + m[0].length })
  }
  let ded: (typeof money)[number] | null = null
  let best = 41
  for (const w of t.matchAll(/deductible/gi))
    for (const mm of money) {
      const d = mm.j <= w.index ? w.index - mm.j : mm.i >= w.index + 10 ? mm.i - w.index - 10 : 0
      if (d < best) {
        best = d
        ded = mm
      }
    }
  if (ded) put('deductible', ded.v, ded.i, ded.j)
  const rest = money.filter((m) => m !== ded)
  if (rest.length) {
    const c = rest.reduce((a, b) => (b.v > a.v ? b : a))
    put('claim_amount', c.v, c.i, c.j)
  }

  // dates
  const dates: DateSpan[] = []
  const addDate = (v: string | null, m: RegExpMatchArray) => {
    if (v && v <= today) dates.push({ v, i: m.index ?? 0, j: (m.index ?? 0) + m[0].length })
  }
  for (const m of t.matchAll(/\b(\d{4})-(\d{2})-(\d{2})\b/g)) addDate(mkDate(+m[1], +m[2], +m[3]), m)
  for (const m of t.matchAll(/\b(\d{1,2})\/(\d{1,2})\/(\d{4}|\d{2})\b/g)) addDate(mkDate(+m[3] < 100 ? +m[3] + 2000 : +m[3], +m[1], +m[2]), m)
  for (const m of t.matchAll(/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b/gi)) {
    const mo = MONTHS.indexOf(m[1].toLowerCase()) + 1
    const y = m[3] ? +m[3] : thisYear
    let v = mkDate(y, mo, +m[2])
    if (v && !m[3] && v > today) v = mkDate(y - 1, mo, +m[2])
    addDate(v, m)
  }
  for (const m of t.matchAll(/\b(today|this morning|yesterday|last night)\b/gi)) addDate(/today|morning/i.test(m[1]) ? today : addDays(today, -1), m)
  for (const m of t.matchAll(/\b(\d+|two|three|four|five|six|seven|eight|nine|ten) days ago\b/gi)) addDate(addDays(today, -(WORDNUM[m[1].toLowerCase()] ?? +m[1])), m)
  dates.sort((a, b) => a.i - b.i)
  dates.forEach((d) => (d.filed = FILED_CTX.test(t.slice(Math.max(0, d.i - 40), d.i))))
  const incident = dates.find((d) => !d.filed)
  const filed = dates.find((d) => d.filed) || (incident && dates.find((d) => d !== incident && d.v >= incident.v))
  if (incident) put('incident_date', incident.v, incident.i, incident.j)
  if (filed) put('claim_filed_date', filed.v, filed.i, filed.j)

  // state: full names (longest first so "West Virginia" beats "Virginia") or ", TX" / "in TX"
  let st: Span | null = null
  for (const [code, name] of STATES_LONGEST_FIRST) {
    const m = new RegExp('\\b' + escapeRegExp(name) + '\\b', 'i').exec(t)
    if (m && (!st || m.index < st.i)) st = { v: code, i: m.index, j: m.index + m[0].length }
  }
  for (const m of t.matchAll(/(?:,\s*|\bin\s+)([A-Z]{2})\b/g))
    if (STATE_CODES.has(m[1]) && (!st || m.index < st.i)) st = { v: m[1], i: m.index, j: m.index + m[0].length }
  if (st) put('state', st.v, st.i, st.j)

  // claim type: whichever vocabulary shows up most, ties left to the backend's auto-detect
  const scores = Object.entries(TYPE_WORDS).map(([k, re]) => [k, [...t.matchAll(re)]] as const).sort((a, b) => b[1].length - a[1].length)
  if (scores[0][1].length && scores[0][1].length > scores[1][1].length) {
    const m = scores[0][1][0]
    put('claim_type', scores[0][0], m.index, m.index + m[0].length)
  }

  // earlier claims
  let pm = /\b(\d+|no|zero|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:prior|previous|earlier|past|other)\s+claims?\b/i.exec(t)
  if (pm) put('previous_claims_count', WORDNUM[pm[1].toLowerCase()] ?? +pm[1], pm.index, pm.index + pm[0].length)
  else if ((pm = /\b(first claim|never (?:filed|made|had) a claim)\b/i.exec(t))) put('previous_claims_count', 0, pm.index, pm.index + pm[0].length)

  // tenure
  let tm =
    /\b(?:customer|policyholder|insured|client|member|with us)\b[^.\d]{0,20}?(\d+(?:\.\d+)?)\s*(years?|yrs?|months?)\b/i.exec(t) ||
    /\b(\d+(?:\.\d+)?)\s*(years?|yrs?|months?)\s+(?:as (?:a )?(?:customer|policyholder)|with us|on the policy)/i.exec(t)
  if (tm) put('policyholder_tenure_years', /^m/i.test(tm[2]) ? Math.round((Number(tm[1]) / 12) * 100) / 100 : Number(tm[1]), tm.index, tm.index + tm[0].length)
  else if ((tm = /\b(?:customer|policyholder|insured|with us)\s+since\s+((?:19|20)\d{2})\b/i.exec(t)))
    put('policyholder_tenure_years', Math.max(0, thisYear - +tm[1]), tm.index, tm.index + tm[0].length)

  // documents: mentioned and received vs mentioned as missing
  const docs: string[] = []
  const missing: string[] = []
  let firstDoc: { i: number; j: number } | null = null
  for (const [name, re] of DOC_WORDS)
    for (const m of t.matchAll(re)) {
      const before = t.slice(Math.max(0, m.index - 40), m.index)
      if (NEGATED.test(before)) {
        if (!missing.includes(name)) missing.push(name)
      } else if (!docs.includes(name)) {
        docs.push(name)
        if (!firstDoc || m.index < firstDoc.i) firstDoc = { i: m.index, j: m.index + m[0].length }
      }
    }
  const realMissing = missing.filter((d) => !docs.includes(d))
  if (docs.length && firstDoc) put('provided_documents', docs, firstDoc.i, firstDoc.j)

  return { fields: out, theft: /\b(stolen|theft|stole|burglar\w*|broke into|break-in)\b/i.test(t), missingDocs: realMissing }
}
