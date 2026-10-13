import type { SynaptStats } from './api'

const count = (n: number | null | undefined) => (typeof n === 'number' ? n.toLocaleString('en-US') : '—')

/** The figures shown as tiles, in reading order: what was stored, then what was learned from it. */
export function statTiles(stats: SynaptStats): { label: string; value: string; hint: string }[] {
  const episodes = stats.episodes
  return [
    { label: 'Documents', value: count(stats.documents), hint: 'Uploaded files' },
    { label: 'Passages', value: count(stats.passages), hint: 'Searchable text pieces' },
    { label: 'Graph nodes', value: count(stats.graph_nodes), hint: 'Everything in the knowledge graph' },
    { label: 'Connections', value: count(stats.connections), hint: 'Links between nodes' },
    { label: 'Procedures', value: count(stats.procedures), hint: 'Extracted step-by-step procedures' },
    { label: 'Steps', value: count(stats.steps), hint: 'Steps inside those procedures' },
    { label: 'Entities', value: count(stats.entities), hint: 'People, processes, products and goals found' },
    { label: 'Episodes', value: !episodes ? '—' : episodes.store_exists ? count(episodes.count) : '0', hint: 'Lived cases remembered from feedback' },
  ]
}

/** One line of context under the tiles; never claims more than the response says. */
export function statNote(stats: SynaptStats): string {
  const parts = [stats.kind ? `${stats.kind} provider` : null, stats.has_ticket_store ? 'ticket store present' : 'no ticket store']
  const when = stats.fetched_at ? new Date(stats.fetched_at) : null
  const time = when && !Number.isNaN(when.getTime()) ? `read ${when.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}` : null
  return [...parts, time, stats.stale ? 'last known figures — Synapt could not be reached just now' : null].filter(Boolean).join(' · ')
}
