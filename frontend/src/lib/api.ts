// Typed client for the FastAPI backend in src/claims/api.py.

export type ClaimType = 'auto' | 'home' | 'renters' | 'property' | 'business'
export type FindingKind = 'fact' | 'gap' | 'risk_indicator' | 'limitation' | 'contradiction'

export interface ClaimInput {
  description: string
  claim_type: ClaimType | null
  state: string
  incident_date: string
  claim_filed_date: string
  claim_amount: number
  deductible: number
  previous_claims_count: number
  policyholder_tenure_years: number
  provided_documents: string[]
}

export interface SearchFilters {
  claim_type?: ClaimType
  state?: string
  claim_status?: 'approved' | 'denied'
  min_amount?: number
  max_amount?: number
  min_previous_claims?: number
  max_previous_claims?: number
}

export interface Finding {
  kind: FindingKind
  text: string
  source_ids: string[]
}

export interface Recommendation {
  action: string
  reason: string
  source_ids: string[]
}

export interface Evidence {
  source_id: string
  title: string
  text: string
  provenance: 'synthetic_fixture' | 'published_synthetic' | 'synapt' | 'user_input' | string
  provider_id?: string | null
}

export interface SimilarCase {
  claim_id: string
  claim_type: string
  state: string
  claim_amount: number
  claim_status: string
  days_to_resolution: number | null
  similarity_score: number
  score_kind?: string
  semantic_match?: boolean
  match_reasons: string[]
  differences: string[]
  provenance: string
}

export interface FeatureImportance {
  feature: string
  score_drop: number
}

export interface GlobalExplanation {
  scope?: string
  interpretation?: string
  scoring?: string
  features?: FeatureImportance[]
}

export interface EstimatePrediction {
  available: boolean
  reason?: string
  estimate?: number
  unit?: string
  interval?: [number, number]
  interval_label?: string
  global_explanation?: GlobalExplanation
}

export interface FraudPrediction {
  available: boolean
  reason?: string
  score?: number
  review_threshold?: number
  review_signal?: boolean
  meaning?: string
  global_explanation?: GlobalExplanation
}

export interface Predictions {
  available: boolean
  reason?: string
  origin?: unknown
  limitations?: string[]
  warnings?: string[]
  confidence_distinction?: string
  amount?: EstimatePrediction
  resolution?: EstimatePrediction
  fraud?: FraudPrediction
}

export interface TraceItem {
  stage: string
  status: string
  detail: string | Record<string, unknown>
}

export interface Run {
  run_id: string
  status: 'running' | 'awaiting_review' | 'needs_manual_review' | 'reviewed' | 'revision_requested' | 'failed' | string
  mode: 'fixture' | 'live' | string
  agent_mode: string
  claim: ClaimInput
  filters?: SearchFilters
  classification?: { claim_type: ClaimType | null; method?: string; needs_review: boolean }
  similar_cases?: SimilarCase[]
  evidence?: Evidence[]
  findings?: Finding[]
  recommendations?: Recommendation[]
  priority?: {
    service_urgency: string
    investigation_priority: string
    reasons: string[]
    policy?: string
  }
  predictions?: Predictions
  validation?: { passed: boolean; issues: string[]; scope?: string }
  review?: { decision: 'accept_brief' | 'request_revision'; note: string } | null
  trace?: TraceItem[]
  error?: string
}

export interface Health {
  status: string
  synapt_mode: string
  agent_mode: string
  synapt_live_verified: boolean
  notice: string
}

export interface DemoCase {
  id: string
  title: string
  claim: ClaimInput
}

export interface IntegrationStatus {
  mode: string
  provider_configured: boolean
  credentials_configured: boolean
  live_verified: boolean
  mcp_url: string
  auth_contract: string
  local_history_origin: string
}

export interface TaskMetric {
  available: boolean
  reason?: string
  counts?: Record<string, number>
  positive_counts?: number[]
  // regression
  selected_model?: string
  selection?: string
  mae?: number
  baseline_mae?: number
  candidate_calibration_mae?: number
  baseline_calibration_mae?: number
  empirical_interval_radius?: number
  heldout_interval_coverage?: number
  interval_label?: string
  // classification
  precision?: number
  recall?: number
  pr_auc_average_precision?: number
  baseline_pr_auc?: number
  brier_score?: number
  baseline_brier_score?: number
  review_threshold?: number
  calibration?: string
  global_explanation?: GlobalExplanation
}

export interface ModelStatus {
  available: boolean
  reason?: string
  data_present?: boolean
  limitations?: string[]
  trained_at?: string
  origin?: unknown
  valid_rows?: number
  excluded_rows?: number
  split?: Record<string, unknown>
  metrics?: Partial<Record<'amount' | 'resolution' | 'fraud', TaskMetric>>
  feature_contracts?: Record<string, string[]>
}

export interface EvaluationCase {
  case: string
  checks: Record<string, boolean>
  passed: boolean
  run_id: string
}

export interface JudgeResult {
  run_id: string
  metric: string
  judge_model?: string
  status: string
  score: number | null
  reason?: string
  threshold?: number
  passed?: boolean
  error_type?: string
}

export interface EvaluationStatus {
  status: string
  judge_status: string
  deepeval_installed?: boolean
  judge_configured?: boolean
  mode?: string
  agent_mode?: string
  cases?: EvaluationCase[]
  passed?: number
  total?: number
  scope?: string
  judge_results?: JudgeResult[]
  judge_expected_metrics?: number
  judge_completed_metrics?: number
}

export interface Lessons {
  candidate_lessons: { id: number; run_id: string; rating: number; note: string }[]
  promotion: string
}

let apiKey = ''
let csrf = ''
export const setCsrfToken = (token: string) => { csrf = token }
export const setApiKey = (key: string) => {
  apiKey = key
}
export const hasApiKey = () => apiKey.length > 0

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const abort = new AbortController()
  const cancel = () => abort.abort(options.signal?.reason)
  if (options.signal?.aborted) cancel()
  else options.signal?.addEventListener('abort', cancel, { once: true })
  const timeout = setTimeout(() => abort.abort(), 180_000)
  try {
    const response = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(apiKey ? { 'X-Claims-Api-Key': apiKey } : {}),
        ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
        ...(options.headers || {}),
      },
      signal: abort.signal,
    })
    const body = await response.json().catch(() => null)
    if (!response.ok) {
      const detail = body?.detail ?? body?.error ?? `Request failed (${response.status})`
      let message: string
      if (typeof detail === 'string') message = detail
      else if (Array.isArray(detail))
        message = detail
          .map(
            (item: { loc?: unknown[]; msg?: string }) =>
              `${(Array.isArray(item.loc) ? item.loc : []).filter((x) => x !== 'body').join(' / ')}: ${item.msg || 'Invalid value'}`,
          )
          .join('; ')
      else message = JSON.stringify(detail)
      if (response.status === 401 && !path.startsWith('/api/auth/')) {
        window.dispatchEvent(new Event('claims-session-expired'))
        message = 'Please sign in again to continue.'
      }
      throw new ApiError(message, response.status)
    }
    if (body === null) throw new ApiError('The server returned an unreadable response.', response.status)
    return body as T
  } catch (error) {
    if (options.signal?.aborted) throw error
    if (error instanceof DOMException && error.name === 'AbortError')
      throw new ApiError('The request timed out. The server may still be processing it; search Saved cases before submitting another investigation.', 0)
    throw error
  } finally {
    clearTimeout(timeout)
    options.signal?.removeEventListener('abort', cancel)
  }
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, { method: 'POST', ...(body !== undefined ? { body: JSON.stringify(body) } : {}) })
