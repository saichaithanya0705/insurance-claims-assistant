import type { Evidence, SideAnswer, SidePart, SideSource } from './api'

// Wording and small rules for the side chat. Plain functions so they can be tested without a browser.

export const MIN_QUESTION = 3

/** Each source a part can come from: its name for the reader, and a colour tone. An administrator sees the vendor's name. */
export function sourceLabel(source: SideSource, admin: boolean): string {
  switch (source) {
    case 'claim': return 'Submitted claim'
    case 'brief': return 'This brief'
    case 'history': return 'Past claims · exact figures'
    case 'estimates': return 'Model estimates'
    case 'evidence': return 'Retrieved evidence'
    case 'synapt': return admin ? 'Synapt knowledge base' : 'Knowledge base'
    case 'boundary': return 'Decision boundary'
    case 'outside': return 'Outside this tool'
    default: return 'Not understood'
  }
}

export const sourceTone = (source: SideSource): string =>
  ({ claim: 'sky', brief: 'teal', history: 'amber', estimates: 'violet', evidence: 'teal', synapt: 'teal', boundary: 'rose', outside: 'neutral', unknown: 'neutral' } as Record<string, string>)[source] ?? 'neutral'

/** What a source is made of, one line, shown under the badge so a reader knows what kind of answer this is. */
export function sourceNote(source: SideSource, admin: boolean): string {
  switch (source) {
    case 'claim': return 'Read from the saved claim. No model was used.'
    case 'brief': return 'Read from the findings, priority and checks saved with this brief. No model was used.'
    case 'history': return 'Exact statistics from the full dataset, computed by DuckDB. No model was used.'
    case 'estimates': return 'From the trained models saved with this run: patterns in synthetic claims, not a decision.'
    case 'evidence': return 'Read from the evidence saved with this brief.'
    case 'synapt': return admin ? "Written by Synapt's query agent from its own knowledge, with the passages and procedures it used. This is not checked by the brief's validation." : 'Written by the knowledge base from its own passages and procedures. It is not checked by the brief’s validation.'
    case 'boundary': return 'This tool prepares a brief; a handler decides.'
    case 'outside': return 'Not held here: nothing was looked up and nothing was guessed.'
    default: return ''
  }
}

/** A short name for an evidence ID, using the evidence list when it holds the item. */
export function citeLabel(id: string, evidence: Evidence[] = []): string {
  const known = evidence.find((e) => e.source_id === id)
  if (id === 'claim:input') return 'Submitted claim'
  if (id.startsWith('history:')) return `Past case ${id.slice(8)}`
  if (known?.title) return known.title.replace(/^Knowledge graph procedure:\s*/i, 'Procedure: ').replace(/\.(?:json|txt|md|pdf)$/i, '')
  if (id.startsWith('graph:procedure:')) return 'Graph procedure'
  if (id.startsWith('chunk_')) return 'Source passage'
  return id.length > 28 ? `${id.slice(0, 26)}…` : id
}

/** null when the question can be sent; otherwise what to tell the person. */
export function questionProblem(text: string, max: number): string | null {
  const trimmed = text.trim()
  if (trimmed.length < MIN_QUESTION) return 'Write a question first.'
  if (trimmed.length > max) return `Keep it under ${max} characters.`
  return null
}

export function confidenceTone(label: string): string {
  return label === 'High' ? 'teal' : label === 'Medium' ? 'amber' : 'rose'
}

/** What was consulted, in words, for the line under an answer. */
export function consultedLine(answer: SideAnswer, admin: boolean): string {
  const names = answer.parts.map((p) => sourceLabel(p.source, admin))
  const unique = [...new Set(names)]
  const fallback = answer.route.fallback ? ' (no specific pattern matched, so the knowledge base was asked)' : ''
  return unique.length ? `Answered from: ${unique.join(' + ')}${fallback}` : ''
}

/** A plain-text copy of an answer for pasting into a note. */
export function answerAsText(answer: SideAnswer, admin: boolean): string {
  const lines = [`Q: ${answer.question}`]
  for (const part of answer.parts) {
    lines.push('', `[${sourceLabel(part.source, admin)}]`)
    if (part.text) lines.push(part.text)
    for (const fact of part.facts) lines.push(`- ${fact.label}: ${fact.value}`)
    for (const item of part.items) lines.push(`- ${item.text}`)
    if (part.table) {
      lines.push(part.table.columns.join(' | '))
      for (const row of part.table.rows) lines.push(row.join(' | '))
    }
    for (const note of part.notes) lines.push(`Note: ${note}`)
  }
  lines.push('', 'Side chat answer: not part of the investigation brief.')
  return lines.join('\n')
}

/** The citations of a part that the brief also holds, so they can be opened as evidence. */
export function openableCites(part: SidePart, evidence: Evidence[]): string[] {
  const held = new Set(evidence.map((e) => e.source_id))
  const all = [...part.cites, ...part.items.flatMap((i) => i.cites)]
  return [...new Set(all)].filter((id) => held.has(id))
}

/** A message for a failed request that tells the person what to do. */
export function askErrorMessage(error: unknown): string {
  const status = (error as { status?: number })?.status
  const message = (error as Error)?.message
  if (status === 429) return message || 'Too many side questions just now. Try again in a moment.'
  if (status === 404) return 'This investigation could not be found. Refresh the page and try again.'
  if (status === 401 || status === 403) return 'You need to sign in again to ask on the side.'
  if (status === 422) return message || 'That question could not be sent. Check its length.'
  return message || 'The side question could not be answered. Try again in a moment.'
}

export const FEEDBACK_NOTE_MAX = 300

/** The three choices a handler can make about a knowledge-base answer; the server maps them to Synapt's own verdicts. */
export const FEEDBACK_CHOICES = [
  { key: 'helpful', label: 'Yes' },
  { key: 'partly', label: 'Partly' },
  { key: 'not_helpful', label: 'No' },
] as const

export function feedbackThanks(choice: string, admin: boolean): string {
  const word = choice === 'helpful' ? 'Yes' : choice === 'partly' ? 'Partly' : choice === 'not_helpful' ? 'No' : 'Your verdict'
  return `Thanks. “${word}” was sent ${admin ? 'to Synapt' : 'to the knowledge base'}.`
}

export function feedbackErrorMessage(error: unknown): string {
  const status = (error as { status?: number })?.status
  const message = (error as Error)?.message
  if (status === 401 || status === 403) return 'You need to sign in again to send feedback.'
  if (status === 404) return 'There is no knowledge-base answer here to rate.'
  if (status === 422) return message || 'That could not be sent. Check the note’s length.'
  return message || 'The feedback could not be sent. Try again in a moment.'
}
