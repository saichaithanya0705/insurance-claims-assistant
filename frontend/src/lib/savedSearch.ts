export interface CaseSuggestion {
  run_id: string
  title: string
  description: string
  status: string
  claim_type: string | null
  state: string
  claim_amount: number
  claim_filed_date: string
  match_kind: string
}
export interface CaseSuggestions {
  items: CaseSuggestion[]
  total: number
  semantic_status: 'ready' | 'unavailable' | 'disabled' | 'not_needed'
}
export function validateSuggestions(value: unknown): CaseSuggestions {
  const page = value as CaseSuggestions
  if (!page || !Array.isArray(page.items) || !Number.isInteger(page.total) || page.total < page.items.length || !['ready', 'unavailable', 'disabled', 'not_needed'].includes(page.semantic_status)) throw new Error('The saved-case search response is invalid.')
  const ids = new Set<string>()
  for (const item of page.items) {
    if (!item || typeof item.run_id !== 'string' || !item.run_id || ids.has(item.run_id) || typeof item.title !== 'string' || typeof item.description !== 'string' || typeof item.state !== 'string' || typeof item.status !== 'string' || typeof item.match_kind !== 'string' || !Number.isFinite(item.claim_amount) || (item.claim_type !== null && typeof item.claim_type !== 'string')) throw new Error('The saved-case search returned an invalid claim.')
    ids.add(item.run_id)
  }
  return page
}
