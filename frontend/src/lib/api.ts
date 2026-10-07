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
  claim_status?: 'approved' | 'denied' | 'pending' | 'under_review'
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
  deductible?: number | null
  previous_claims_count?: number | null
  policyholder_tenure_years?: number | null
  claim_status: string
  days_to_resolution: number | null
  /** Dataset label on the historical claim (synthetic; not proof of fraud). */
  dataset_fraud_flag?: boolean | null
  /** Pending / under review: on file before this claim, no final outcome. */
  open_case?: boolean
  similarity_score: number
  score_kind?: string
  semantic_match?: boolean
  /** Position in Synapt's own ranking of ingested claim cards (1 = best). */
  semantic_rank?: number | null
  /** 'fusion': among the closest claims; 'semantic': added because Synapt ranks it related in meaning. */
  surfaced_by?: 'fusion' | 'semantic'
  match_reasons: string[]
  differences: string[]
  provenance: string
}

export interface FeatureImportance {
  feature: string
  score_drop: number
}

export interface EffectPoint {
  value: string | number
  mean_prediction: number
}

/** Direction of one feature's effect (partial dependence): associations, not causes. */
export interface FeatureEffect {
  feature: string
  kind: 'numeric' | 'categorical'
  direction: 'higher_values_increase' | 'higher_values_decrease' | 'non_monotonic' | 'varies_by_category' | 'little_effect'
  spread: number
  points: EffectPoint[]
  highest?: EffectPoint
  lowest?: EffectPoint
}

export interface GlobalExplanation {
  scope?: string
  interpretation?: string
  scoring?: string
  features?: FeatureImportance[]
  effects?: FeatureEffect[]
  effects_method?: string
  summary?: string[]
}

export interface LocalExplanation {
  method: string
  unit: string
  contributions: { feature: string; value: string | number; typical_value: string | number; effect: number }[]
}

export interface EstimatePrediction {
  available: boolean
  reason?: string
  estimate?: number
  unit?: string
  interval?: [number, number]
  interval_label?: string
  global_explanation?: GlobalExplanation
  local_explanation?: LocalExplanation | null
}

export interface FraudPrediction {
  available: boolean
  reason?: string
  score?: number
  review_threshold?: number
  review_signal?: boolean
  meaning?: string
  global_explanation?: GlobalExplanation
  local_explanation?: LocalExplanation | null
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

export interface JudgeVerdict {
  status: 'pending' | 'completed' | 'skipped' | 'failed'
  reason?: string
  model?: string
  independent?: boolean
  passed?: boolean
  grounded?: boolean
  boundary_respected?: boolean
  recommendations_supported?: boolean
  score?: number
  issues?: string[]
  summary?: string
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
    /** 0-100 queue priority; every point is attributed in `components`. */
    score?: number
    tier?: 'critical' | 'high' | 'medium' | 'low'
    components?: { points: number; reason: string }[]
    similar_flagged?: number
  }
  predictions?: Predictions
  validation?: { passed: boolean; issues: string[]; scope?: string }
  /** Independent LLM judge verdict (advisory). `model` / `independent` are admin-only. */
  judge?: JudgeVerdict
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
  /** Rows in the Parquet file queried in place; null when only a sample/fixtures are loaded. */
  history_rows?: number | null
  judge_mode?: string
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
  judge_passed_metrics?: number
  judge_quality_passed?: boolean | null
  overall_passed?: boolean
  judge_requested?: boolean
  judge_independent?: boolean
}

export interface Lesson {
  id: number
  run_id: string
  rating: number
  note: string
  promoted: boolean
  promoted_at?: string | null
  promotion_ref?: string | null
  claim_type?: string | null
  state?: string | null
}

export interface Lessons {
  candidate_lessons: Lesson[]
  promotion: string
}

/* ---------- Traces, explanations and system metrics ---------- */

export type SpanKind = 'run' | 'stage' | 'llm' | 'tool' | 'retrieval' | 'compute' | 'evaluation' | string

export interface TraceSpan {
  span_id: string
  parent_id: string | null
  name: string
  kind: SpanKind
  status: 'ok' | 'error' | 'waiting' | string
  started_at: string
  /** Position on the trace's shared time axis. */
  offset_ms: number
  duration_ms: number
  depth: number
  attributes: Record<string, unknown>
}

export interface TraceSummary {
  started_at: string
  duration_ms: number
  stages: { stage: string; duration_ms: number; status: string }[]
  llm: {
    calls: number
    total_ms: number
    retries: number
    failures: number
    tokens: { prompt: number; completion: number; total: number }
    by_purpose: Record<string, { calls: number; ms: number; tokens: number; model?: string | null }>
  }
  errors: { span: string; error_type: string | null }[]
  origin?: string | null
  outcome?: string | null
}

export interface Trace {
  run_id: string
  /** 'recorded' spans were measured while the run executed; 'reconstructed' ones are rebuilt from the audit log. */
  source: 'recorded' | 'reconstructed'
  started_at: string | null
  total_ms: number
  spans: TraceSpan[]
  summary: TraceSummary | null
  note?: string
}

export interface TraceListItem {
  run_id: string
  title: string
  description: string
  status: string
  claim_type?: string | null
  state?: string
  claim_amount?: number
  priority_tier?: string | null
  trace_source: 'recorded' | 'reconstructed' | null
  started_at: string | null
  duration_ms: number | null
  llm_calls: number | null
  tokens: number | null
  errors: number
  origin: string | null
  mode: string | null
  agent_mode: string | null
  validation_passed: boolean | null
  judge_status: string | null
  judge_passed: boolean | null
  judge_score: number | null
}

export interface TraceList {
  items: TraceListItem[]
  total: number
  offset: number
  limit: number
}

export interface AuditEvent {
  id: number
  time: string
  kind: string
  body: Record<string, unknown>
}

export interface Stats {
  count: number
  p50: number | null
  p95: number | null
  max: number | null
  mean: number | null
}

export interface ObservabilitySummary {
  window: string
  origin: string
  generated_at: string
  queries: {
    total: number
    by_status: Record<string, number>
    failed: number
    success_rate: number | null
    by_origin: Record<string, number>
    by_mode: Record<string, number>
  }
  latency_ms: Stats
  stages: (Stats & { stage: string; errors: number })[]
  operations: (Stats & { name: string; kind: string; errors: number })[]
  llm: {
    calls: number
    failures: number
    retries: number
    tokens: { prompt: number; completion: number; total: number }
    tokens_per_query: number | null
    by_purpose: {
      purpose: string
      model: string | null
      calls: number
      tokens: number
      prompt_tokens: number
      completion_tokens: number
      failures: number
      retries: number
      latency_ms: Stats
    }[]
  }
  quality: {
    validated: number
    validation_passed: number
    validation_pass_rate: number | null
    judge: { completed: number; passed: number; failed: number; pending: number; skipped: number; pass_rate: number | null; mean_score: number | null }
    handler: { accepted: number; revision_requested: number; awaiting: number }
  }
  errors: { run_id: string; time: string; span: string; kind: string; error_type: string | null }[]
  series: { bucket: string; queries: number; failed: number; p50_ms: number | null }[]
  api: {
    requests: number
    server_errors: number
    client_errors: number
    latency_ms: Stats
    routes: (Stats & { method: string; route: string; client_errors: number; server_errors: number })[]
  }
  coverage: { recorded: number; reconstructed: number; note: string }
}

export interface ExplainSource {
  source_id: string
  label: string
  category: 'claim' | 'procedure' | 'history' | 'lesson' | 'unknown' | string
  provenance?: string | null
  excerpt?: string | null
}

export interface ExplainStage {
  stage: string
  title: string
  kind: 'ai' | 'rules' | 'search' | 'statistics' | 'human' | 'off' | string
  what: string
  how: string
  inputs: string[]
  outputs: string[]
  duration_ms: number | null
  status: 'complete' | 'waiting' | 'pending' | 'skipped' | string
}

export interface ExplainLineage {
  type: 'finding' | 'recommendation'
  index: number
  kind: string
  text: string
  stage: string
  method: 'ai' | 'rules'
  sources: ExplainSource[]
  unsupported: boolean
}

export interface ExplainRankedCase {
  rank: number
  claim_id: string
  claim_type?: string | null
  state?: string | null
  claim_amount?: number | null
  outcome?: string | null
  surfaced_by?: 'fusion' | 'semantic' | null
  total: number | null
  keyword_rank: number | null
  feature_rank: number | null
  semantic_rank: number | null
  points: { keyword: number; feature: number; semantic: number } | null
  reasons: string[]
  differences: string[]
}

export interface ExplainRetrieval {
  recorded: boolean
  pool: string
  filters: Record<string, unknown>
  methods: { id: 'keyword' | 'feature' | 'semantic'; name: string; weight: number | null; how: string }[]
  formula: string
  candidates: { sql_candidates: number | null; semantic_added: number | null; pool_size: number | null; top_k: number | null } | null
  semantic: Record<string, number> | null
  ranked: ExplainRankedCase[]
  evidence_by_category: Record<string, number>
  note: string | null
  knowledge_queries?: { purpose: string | null; tool: string | null; query: string | null; top_k: number | null; duration_ms: number }[]
}

export interface ExplainPriority {
  score: number | null
  tier: string | null
  service_urgency?: string | null
  investigation_priority?: string | null
  tiers: { tier: string; from: number }[]
  next_tier: { tier: string; points_needed: number } | null
  factors: { id: string; label: string; max_points: number; rule: string; points: number; applied: boolean }[]
  components: { points: number; reason: string }[]
  unmatched_components: { points: number; reason: string }[]
  policy?: string | null
}

export interface ExplainEstimateTask {
  id: 'amount' | 'resolution' | 'fraud'
  title: string
  available: boolean
  reason?: string | null
  unit: string
  estimate?: number | null
  interval?: [number, number] | null
  score?: number | null
  review_threshold?: number | null
  review_signal?: boolean | null
  drivers: { feature: string; value: string | number; typical_value: string | number; effect: number }[]
  driver_method?: string | null
  learned: string[]
  learned_method?: string | null
  important_features: { feature: string; score_drop: number }[]
}

export interface ExplainValidationCheck {
  id: string
  label: string
  description: string
  passed: boolean
  inspected: number
  failed: number
}

export interface ExplainGrounding {
  findings: number
  substantive_findings: number
  substantive_cited: number
  recommendations: number
  recommendations_cited: number
  citations: number
  citations_resolved: number
  sources_available: number
  sources_cited: number
  external_sources_available: number
  external_sources_cited: number
  uncited_sources: string[]
}

export interface ExplainLayer {
  id: 'validation' | 'grounding' | 'judge' | 'human' | 'suite' | string
  title: string
  kind: 'rules' | 'ai' | 'human' | string
  gate: boolean
  summary: string
  state?: string
  checks?: ExplainValidationCheck[]
  checks_source?: string
  issues?: string[]
  scope?: string | null
  rechecked?: { matches_saved: boolean; source: string } | null
  metrics?: ExplainGrounding
  /** A boolean for the AI review; the number of golden claims that passed for the evaluation suite. */
  passed?: boolean | number | null
  total?: number | null
  grounded?: boolean | null
  boundary_respected?: boolean | null
  recommendations_supported?: boolean | null
  score?: number | null
  verdict?: string | null
  reason?: string | null
  criteria?: string
  model?: string | null
  independent?: boolean | null
  decision?: string | null
  note?: string | null
  judge_status?: string | null
  judge_passed_metrics?: number | null
  judge_expected_metrics?: number | null
}

export interface Explanation {
  run_id: string
  status: string
  generation: 'ai' | 'rules'
  headline: string
  pipeline: ExplainStage[]
  lineage: ExplainLineage[]
  retrieval: ExplainRetrieval
  priority: ExplainPriority
  estimates: { available: boolean; reason?: string; tasks: ExplainEstimateTask[]; warnings?: string[]; limitations?: string[]; note?: string | null }
  evaluation: { layers: ExplainLayer[] }
  boundaries: string[]
  timeline: { source: string; total_ms: number; stages: { stage: string; duration_ms: number; status: string }[] } | null
  limitations: string[]
  technical?: {
    mode?: string
    agent_mode?: string
    trace_source?: string
    llm: TraceSummary['llm'] | null
    classification_method?: string
  }
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

// Default request budget. Long-running server jobs (an evaluation with the LLM judge takes several
// minutes) pass their own larger `timeoutMs`.
const DEFAULT_TIMEOUT_MS = 180_000

export async function api<T>(path: string, options: RequestInit & { timeoutMs?: number } = {}): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, ...init } = options
  const abort = new AbortController()
  const cancel = () => abort.abort(init.signal?.reason)
  if (init.signal?.aborted) cancel()
  else init.signal?.addEventListener('abort', cancel, { once: true })
  const timeout = setTimeout(() => abort.abort(), timeoutMs)
  try {
    const response = await fetch(path, {
      ...init,
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
    if (init.signal?.aborted) throw error
    if (error instanceof DOMException && error.name === 'AbortError')
      throw new ApiError('The request timed out. The server may still be processing it; search Saved cases before submitting another investigation.', 0)
    throw error
  } finally {
    clearTimeout(timeout)
    init.signal?.removeEventListener('abort', cancel)
  }
}

export const post = <T>(path: string, body?: unknown, options: { timeoutMs?: number } = {}) =>
  api<T>(path, { method: 'POST', ...(body !== undefined ? { body: JSON.stringify(body) } : {}), ...options })
