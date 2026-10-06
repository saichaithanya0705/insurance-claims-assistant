import type { ClaimInput, Evidence, Finding, Run, SimilarCase } from './api'

export function claimSnapshot(claim: ClaimInput) {
  const { provided_documents, ...details } = claim
  return { ...details, documents_reported_available: provided_documents }
}

export function comparisonSnapshot(item: SimilarCase) {
  return { case_id: item.claim_id, claim_type: item.claim_type, state: item.state, claimed_amount: item.claim_amount, historical_outcome: item.claim_status, resolution_days: item.days_to_resolution, rank_score: item.similarity_score, score_meaning: 'Retrieval rank score; not a probability', match_reasons: item.match_reasons?.map(readable), differences: item.differences?.map(readable) }
}

export function provenanceLabel(provenance: string) {
  return provenance === 'user_input' ? 'Claimant report' : provenance.includes('synthetic') ? 'Synthetic comparison material' : 'Retrieved source'
}

export function readable(text: string) {
  if (/Optional Synapt .*lacks supported provenance/i.test(text)) return 'Some retrieved material could not be linked to a supported source and was excluded. Inspect technical detail for the affected retrieval tool.'
  return text.replace(/\bSynapt\b/gi, 'retrieved source').replace(/Same previous_claims_count: 0\b/g, 'No previous claims in either case').replace(/previous_claims_count/g, 'previous claims').replace(/policyholder_tenure_years/g, 'policyholder tenure in years').replace(/provided_documents/g, 'documents reported available').replace(/claim_filed_date/g, 'filing date').replace(/claim_amount/g, 'claim amount').replace(/claim_type/g, 'claim type').replace(/claim_status/g, 'historical outcome')
}
export function findingText(f: Finding, run: Run) {
  if (f.kind === 'fact' && /\b(?:provided|submitted|uploaded|attached|reviewed|verified)\b.{0,100}\b(?:documents?|repair estimate|incident statement|photos|police report)\b/i.test(f.text) && !/\b(?:reported|reports|names only|not|no|unverified|availability)\b/i.test(f.text))
    return `The claimant reports these documents are available: ${run.claim?.provided_documents?.join(', ') || 'none listed'}. Only names were recorded; content was not received or reviewed.`
  return readable(f.text)
}
export function sourceTitle(e: Evidence) {
  if (e.source_id === 'claim:input') return 'Submitted case details'
  if (e.source_id.startsWith('history:')) return `Historical comparison ${e.source_id.slice(8)}`
  return e.title.replace(/\.(?:json|txt|md|pdf)$/i, '').replace(/[_/]+/g, ' ').replace(/\b[0-9a-f]{8}-[0-9a-f-]{27,}\b/gi, '').trim() || 'Retrieved source passage'
}

export function sourceExcerpt(e: Evidence) {
  // Select an unchanged narrative paragraph; source headers/metadata and the
  // complete original are available separately. Never generate a quotation.
  const narrative = (paragraph: string) => {
    const text = paragraph.trim()
    return text.split(/\s+/).length >= 8 && !/^(?:#|source_id:|source_url:|provenance:|attribution:|claim_id:|policy_id:|provider_id:|Educational decision support only\.)/i.test(text)
  }
  return e.text.split(/\r?\n\s*\r?\n/).find(narrative) ?? e.text.split(/\r?\n/).find(narrative) ?? null
}
