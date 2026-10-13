import type { GraphSearch, KnowledgeGraph } from './api'

/** Why a procedure applies to this claim, in plain words. The check is ours; the procedure text is Synapt's. */
export function appliesLabel(reason: string, claimType?: string | null): string {
  if (reason === 'claim_type') return claimType ? `Written for ${claimType} claims` : 'Written for this claim type'
  const conditions: Record<string, string> = {
    theft: 'Theft claims',
    late_filing: 'Late-filed claims',
    large_loss: 'Large losses',
    repeat_claimant: 'Repeat claimants',
    new_policyholder: 'New policyholders',
    water_damage: 'Water damage',
    fraud_signal: 'Fraud-flag review signal',
  }
  return conditions[reason] ?? 'General handling, applies to every claim'
}

/** What became of one search result. A set-aside hit names its reason, so nothing looks silently dropped. */
export function hitOutcome(hit: GraphSearch['found'][number]): string {
  if (hit.used) return 'Used'
  if (hit.applies_because === null) return 'Set aside: written for another claim type, or for a condition this claim does not meet'
  return 'Not walked: already found by another search, or the limit was reached'
}

/** The read-only Synapt calls behind a graph: searches (the standard ones and any the model asked for), and one walk per procedure. */
export function callSummary(graph: KnowledgeGraph): string {
  const searches = graph.searches.length + (graph.followup?.searches.length ?? 0)
  const walks = Math.max(0, graph.calls - searches)
  return `${graph.calls} read-only call${graph.calls === 1 ? '' : 's'} to Synapt (trident_search ×${searches}, trident_traverse ×${walks}). Nothing was written.`
}

/** One sentence on what the model added after the standard searches, or null when it did nothing worth saying. */
export function followUpLine(graph: KnowledgeGraph): string | null {
  const follow = graph.followup
  if (!follow || follow.searches.length === 0) return null
  const asked = follow.searches.map((s) => `“${s.query}”`).join(' and ')
  if (follow.read.length) return `A model also searched for ${asked} and read ${follow.read.length === 1 ? 'one more procedure' : `${follow.read.length} more procedures`}: ${follow.read.join('; ')}.`
  return `A model also searched for ${asked}: nothing new fit this claim.`
}

/** Passage IDs are long; show enough to recognise one. */
export function shortChunk(id: string): string {
  return id.length > 22 ? `${id.slice(0, 18)}…` : id
}
