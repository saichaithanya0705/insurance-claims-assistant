import type { RunPreview } from './api'

// Which parts of a running investigation can be shown yet, and the words for them. Plain functions, so they can be tested
// without a browser.

export interface PreviewPart {
  key: 'search' | 'findings' | 'priority' | 'recommendations'
  title: string
  summary: string
}

const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString('en-US')} ${n === 1 ? one : many}`

/** The sections that have landed, in the order the stages finish. Empty until retrieval has finished. */
export function previewParts(preview: RunPreview | null): PreviewPart[] {
  if (!preview) return []
  const parts: PreviewPart[] = []
  const r = preview.retrieval
  if (r) {
    const found = [plural(r.passages, 'passage'), plural(r.procedures.length, 'procedure'), `${plural(r.similar_total, 'closest past claim')}`]
    parts.push({ key: 'search', title: 'What the search found', summary: `Found ${found.join(', ')}.` })
  }
  if (preview.findings) parts.push({ key: 'findings', title: 'Findings so far', summary: plural(preview.findings.length, 'finding') })
  if (preview.priority) {
    parts.push({ key: 'priority', title: 'Handling priority', summary: `${preview.priority.tier ? preview.priority.tier[0].toUpperCase() + preview.priority.tier.slice(1) : 'Priority'} (${preview.priority.score ?? '—'}/100). It only orders handler attention; it says nothing about coverage or fraud.` })
  }
  if (preview.recommendations) parts.push({ key: 'recommendations', title: 'Recommended actions', summary: plural(preview.recommendations.length, 'action') })
  return parts
}

/** One line about the knowledge base's own written answer. Only an administrator sees the vendor's name. */
export function queryLine(state: NonNullable<NonNullable<RunPreview['retrieval']>['query_agent']>, admin: boolean): string {
  const who = admin ? 'Synapt’s query agent' : 'The knowledge base'
  if (state.state === 'pending') return `${who} is still writing its answer; it will appear in the brief.`
  if (state.state === 'answered') return `${who} has answered; its answer will be shown beside the brief.`
  return `${who} did not answer for this run; the brief does not depend on it.`
}
