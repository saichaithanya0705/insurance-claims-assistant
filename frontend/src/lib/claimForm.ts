import type { ClaimInput, ClaimType, SearchFilters } from './api'
import { todayLocal } from './format'
import { STATES, stateCode } from './states'

export interface FormState {
  description: string
  claim_type: '' | ClaimType
  state: string
  incident_date: string
  claim_filed_date: string
  claim_amount: string
  deductible: string
  previous_claims_count: string
  policyholder_tenure_years: string
  provided_documents: string[]
}

export interface FilterState {
  claim_type: '' | ClaimType
  state: string
  claim_status: '' | 'approved' | 'denied' | 'pending' | 'under_review'
  min_amount: string
  max_amount: string
  min_previous_claims: string
  max_previous_claims: string
}

export const EMPTY_FORM: FormState = {
  description: '',
  claim_type: '',
  state: '',
  incident_date: '',
  claim_filed_date: '',
  claim_amount: '',
  deductible: '',
  previous_claims_count: '',
  policyholder_tenure_years: '',
  provided_documents: [],
}

export const EMPTY_FILTERS: FilterState = {
  claim_type: '',
  state: '',
  claim_status: '',
  min_amount: '',
  max_amount: '',
  min_previous_claims: '',
  max_previous_claims: '',
}

export const formFromClaim = (claim: ClaimInput): FormState => ({
  description: claim.description ?? '',
  claim_type: claim.claim_type ?? '',
  state: claim.state ?? '',
  incident_date: claim.incident_date ?? '',
  claim_filed_date: claim.claim_filed_date ?? '',
  claim_amount: String(claim.claim_amount ?? ''),
  deductible: String(claim.deductible ?? ''),
  previous_claims_count: String(claim.previous_claims_count ?? ''),
  policyholder_tenure_years: String(claim.policyholder_tenure_years ?? ''),
  provided_documents: Array.isArray(claim.provided_documents) ? claim.provided_documents : [],
})

export function buildClaim(form: FormState): ClaimInput {
  const claim: ClaimInput = {
    description: form.description.trim(),
    claim_type: form.claim_type || null,
    state: stateCode(form.state),
    incident_date: form.incident_date,
    claim_filed_date: form.claim_filed_date,
    claim_amount: Number(form.claim_amount),
    deductible: Number(form.deductible),
    previous_claims_count: Number(form.previous_claims_count),
    policyholder_tenure_years: Number(form.policyholder_tenure_years),
    provided_documents: form.provided_documents.map((d) => d.trim()).filter(Boolean),
  }
  if (claim.description.length < 10) throw new Error('Describe the incident in at least 10 characters.')
  if (claim.description.length > 6000) throw new Error('Keep the incident description within 6000 characters.')
  if (!STATES.some(([code]) => code === claim.state)) throw new Error('Enter a two-letter US state code, for example CA.')
  if (!claim.incident_date || !claim.claim_filed_date) throw new Error('Enter both the incident and filing dates.')
  if (claim.claim_filed_date < claim.incident_date) throw new Error('Filing date must be on or after the incident date.')
  if (claim.incident_date > todayLocal() || claim.claim_filed_date > todayLocal()) throw new Error('Dates cannot be in the future.')
  for (const key of ['claim_amount', 'deductible', 'previous_claims_count', 'policyholder_tenure_years'] as const)
    if (form[key].trim() === '' || !Number.isFinite(claim[key]) || claim[key] < 0) throw new Error(`Enter a valid ${key.replace(/_/g, ' ')}.`)
  if (claim.claim_amount > 1_000_000_000 || claim.deductible > 1_000_000_000) throw new Error('Amounts cannot exceed one billion dollars.')
  if (!Number.isInteger(claim.previous_claims_count) || claim.previous_claims_count > 1000) throw new Error('Previous claims must be a whole number from 0 to 1000.')
  if (claim.policyholder_tenure_years > 100) throw new Error('Tenure cannot exceed 100 years.')
  if (claim.provided_documents.length > 50) throw new Error('List at most 50 available documents.')
  return claim
}

export function buildFilters(f: FilterState): SearchFilters {
  const filters: SearchFilters = {}
  if (f.claim_type) filters.claim_type = f.claim_type
  if (f.state.trim()) filters.state = f.state.trim().toUpperCase()
  if (f.claim_status) filters.claim_status = f.claim_status
  for (const key of ['min_amount', 'max_amount', 'min_previous_claims', 'max_previous_claims'] as const)
    if (f[key] !== '') filters[key] = Number(f[key])
  if (filters.min_amount !== undefined && filters.max_amount !== undefined && filters.min_amount > filters.max_amount)
    throw new Error('Minimum amount cannot exceed maximum amount.')
  if (
    filters.min_previous_claims !== undefined &&
    filters.max_previous_claims !== undefined &&
    filters.min_previous_claims > filters.max_previous_claims
  )
    throw new Error('Minimum prior claims cannot exceed maximum prior claims.')
  return filters
}
