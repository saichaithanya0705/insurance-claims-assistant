/** Sentence case for enum-like values: "awaiting_review" -> "Awaiting review". */
export const label = (value: unknown) => {
  const text = String(value ?? 'Unavailable').replace(/_/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Shortens free text at a word boundary so titles never end mid-word. */
export const shortTitle = (value: unknown, max = 72) => {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim()
  if (text.length <= max) return text
  const cut = text.slice(0, max + 1)
  const sentence = cut.search(/[.;!?](\s|$)/)
  if (sentence >= max * 0.45) return text.slice(0, sentence)
  const space = cut.lastIndexOf(' ')
  return `${text.slice(0, space > max * 0.5 ? space : max).replace(/[\s,;:–—-]+$/, '')}…`
}

export const money = (value: unknown, digits = 0) =>
  typeof value === 'number' && Number.isFinite(value)
    ? new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        maximumFractionDigits: digits,
      }).format(value)
    : 'Unavailable'

export const num = (value: unknown, digits = 2) =>
  typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString('en-US', { maximumFractionDigits: digits })
    : '—'

export const pct = (value: unknown, digits = 1) =>
  typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(digits)}%` : '—'

export const daysBetween = (from: string, to: string) => {
  if (!from || !to) return null
  const a = Date.parse(from)
  const b = Date.parse(to)
  if (Number.isNaN(a) || Number.isNaN(b)) return null
  return Math.round((b - a) / 86_400_000)
}

export const todayLocal = () => {
  const today = new Date()
  return new Date(today.getTime() - today.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
}

export const modeLabel = (mode?: string) =>
  mode === 'live' ? 'Live Synapt' : mode === 'fixture' ? 'Fixture evidence' : label(mode)

export const humanValue = (value: unknown): string => {
  if (value === null || value === undefined) return 'Unavailable'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'number')
    return Number.isInteger(value)
      ? value.toLocaleString('en-US')
      : value.toLocaleString('en-US', { maximumFractionDigits: 5 })
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' ')

export const RECENT_KEY = 'claims.recents.'
export interface RecentRun {
  run_id: string
  title: string
  status: string
  amount: number
  at: number
}
export const loadRecent = (userId = 'local'): RecentRun[] => {
  try {
    localStorage.removeItem('synapt.recentRuns.v1')
    const parsed = JSON.parse(sessionStorage.getItem(RECENT_KEY + userId) || '[]')
    return Array.isArray(parsed) ? parsed.slice(0, 8) : []
  } catch {
    return []
  }
}
export const saveRecent = (runs: RecentRun[], userId = 'local') => {
  try {
    sessionStorage.setItem(RECENT_KEY + userId, JSON.stringify(runs.slice(0, 8)))
  } catch {
    /* storage unavailable — history is a convenience only */
  }
}

export const timeAgo = (at: number) => {
  const seconds = Math.round((Date.now() - at) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}
