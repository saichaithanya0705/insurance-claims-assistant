// Typed client for the FastAPI backend in src/claims/api/main.py.

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
  /** Position in Synapt's ticket-store ranking of similar past claims (1 = best). */
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

/** One comparison group, computed by DuckDB over the full dataset. Display only: never evidence. */
export interface CohortFigures {
  key: 'exact' | 'type_amount_history' | 'type' | string
  definition: string
  claims: number
  approved_share: number | null
  denied_share: number | null
  median_days: number | null
  p25_days: number | null
  p75_days: number | null
  /** Share carrying the dataset's synthetic fraud flag: a synthetic label, not proof of fraud. */
  flag_rate: number | null
  sufficient: boolean
}

export interface CohortStats {
  available: boolean
  reason?: string
  source?: 'duckdb_parquet' | string
  cutoff?: string
  eligibility?: string
  dataset_claims?: number | null
  cohorts?: CohortFigures[]
  /** Only the cards retrieval already had. `source` says whether they came from Synapt or the local copy. */
  synapt_cross_check?: {
    source: 'synapt' | 'local_fallback' | string
    cards_returned: number
    in_exact_cohort: number
    in_type_amount_history_cohort: number
  } | null
  notes?: string[]
  elapsed_seconds?: number
}

/** Side chat: a question asked beside an investigation. Answered from the saved run or Synapt's knowledge base, whichever
 *  can answer it, and never part of the brief. */
export type SideSource = 'claim' | 'brief' | 'history' | 'estimates' | 'evidence' | 'synapt' | 'boundary' | 'outside' | 'unknown'

export interface SideFact { label: string; value: string }
export interface SideItem { text: string; cites: string[]; tag: string | null }

export interface SideSynapt {
  /** Everyone sees the label; the numbers are administrators only. */
  confidence: { label: 'High' | 'Medium' | 'Low' | string; overall?: number | null; passages?: number | null; procedures?: number | null; graph?: number | null }
  trust?: { degraded: boolean; reasons: string[] }
  passages: { chunk_id: string; title: string; source: string | null; score?: number | null; in_evidence: boolean }[]
  procedures: string[]
  graph: { nodes: number; edges: number; by_label: Record<string, number>; top: { label: string; name: string; relevance?: number | null }[] }
  query_id?: string | null
  stores?: string[]
  latency_ms?: number | null
  warnings: string[]
}

export interface SidePart {
  source: SideSource
  title: string
  status: 'ok' | 'unavailable' | 'declined' | string
  text: string
  facts: SideFact[]
  items: SideItem[]
  table: { columns: string[]; rows: string[][] } | null
  notes: string[]
  /** Evidence IDs this part rests on; the ones the brief holds can be opened as evidence. */
  cites: string[]
  synapt: SideSynapt | null
}

export interface SideAnswer {
  /** null when the answer was not saved (a failed Synapt call), so the question can be asked again. */
  id: number | null
  asked_at: string | null
  question: string
  route: { intents: string[]; fallback: boolean; matched?: Record<string, string[]> }
  parts: SidePart[]
  elapsed_ms?: number
  notice: string
  /** The same question was asked before; this is the saved answer. */
  repeat: boolean
}

export interface SideChatState {
  items: SideAnswer[]
  suggestions: { kind: string; text: string }[]
  limits: { max_question: number; max_per_run: number }
}

/** One knowledge-base answer a handler has rated. The query ID and Synapt's verdict wording never reach the page. */
export interface QueryFeedbackItem {
  /** `investigation` for the answer every run asks for, or `side:<id>` for a side-chat answer. */
  target: string
  choice: 'helpful' | 'partly' | 'not_helpful' | string
  sent_at: string
}

/** Synapt's query agent's answer to the one fixed handling question every investigation asks (display only: never evidence,
 *  never cited, never checked by the brief's validation). `task_id` is the run's own ID, administrators only. */
export interface QueryAgent {
  available: boolean
  /** True while the answer is still on its way; the brief did not wait for it and the page picks it up when it arrives. */
  pending?: boolean
  reason?: string
  question: string | null
  part: SidePart | null
  task_id?: string | null
}

/** What an investigation that is still running has produced so far (GET /api/investigations/{id}/preview). A part that has
 *  not landed is null. It is not the brief: it is not complete, validated or reviewed. */
export interface RunPreview {
  run_id: string | null
  status: string | null
  stages: string[]
  claim_type: string | null
  retrieval: {
    passages: number
    procedures: string[]
    similar_cases: { claim_type?: string | null; state?: string | null; claim_amount?: number | null; claim_status?: string | null; days_to_resolution?: number | null }[]
    similar_total: number
    cohort: string | null
    query_agent: { state: 'pending' | 'answered' | 'unavailable'; question?: string | null; answer?: string } | null
  } | null
  findings: { kind: string; text: string }[] | null
  priority: { tier: string | null; score: number | null; reasons: string[] } | null
  recommendations: { action: string; reason: string }[] | null
}

/** One span of an investigation in progress, as GET /api/investigations/{id}/progress serves it.
 *  `detail` (tool, query, model) is administrators only; everyone else gets `label` and `result`. */
export interface LiveSpan {
  id: string
  parent: string | null
  kind: 'run' | 'stage' | 'tool' | 'llm' | 'retrieval' | 'compute' | 'evaluation' | string
  /** The stage key (classify, retrieve, ...) for a stage span; null for every other span. */
  name: string | null
  label: string
  detail: string | null
  result: string | null
  status: 'running' | 'ok' | 'error' | 'waiting' | string
  /** Milliseconds after the run was registered, on the server's clock. */
  started_ms: number
  duration_ms: number | null
  /** Work nobody waits for (the independent review). */
  background: boolean
  /** The agent that did this work (an agent span carries its own ID too); null for the run and its stages. */
  agent: string | null
  seq: number
}

/** One actor of an investigation, as `GET /api/agents` describes it. Tool IDs, the identity and the prompt are administrators only. */
export interface AgentInfo {
  id: string
  name: string
  /** `agent` takes part in an investigation; `system` and `human` are the other actors that can reach the knowledge base. */
  kind: 'agent' | 'system' | 'human' | string
  method: 'model' | 'rules' | 'none' | string
  stage: string
  purpose: string
  cannot: string
  /** What it can use, in plain words. */
  can_use: string[]
  tools?: string[]
  identity?: string
  /** Whether an Agent Connector client ID is set for this agent (the ID itself is never sent). */
  client_id_set?: boolean
  model_purpose?: string
  prompt?: string
}

export interface ToolInfo {
  id: string
  system: 'synapt' | 'local' | string
  plain: string
  summary: string
  writes: boolean
  held_by: string[]
}

export interface AgentRoster {
  agents: AgentInfo[]
  /** Administrators only. */
  tools?: ToolInfo[]
}

/** A compiled LangGraph graph as `GET /api/agents/graph` describes it. */
export interface GraphView {
  nodes: { id: string; agents: string[] }[]
  edges: { from: string; to: string; conditional?: boolean }[]
  mermaid: string
}

export interface AgentGraphs {
  investigation: GraphView
  retrieve: GraphView
  supervise?: GraphView
}

/** One agent's part in a finished investigation (`GET /api/investigations/{id}/agents`). */
export interface RunAgent {
  id: string
  name: string
  method: string
  stage: string
  purpose: string
  ran: boolean
  status?: 'ok' | 'error' | 'waiting' | string
  background?: boolean
  started_ms?: number | null
  duration_ms?: number
  tool_calls?: number
  refused?: number
  model_calls?: number
  tokens?: number
  /** Administrators only. */
  tools_used?: Record<string, number>
  tools_refused?: string[]
  models?: string[]
}

export interface LiveProgress {
  run_id: string
  /** `queued`: waiting for another investigation to finish; investigations run one at a time. */
  state: 'queued' | 'running' | 'done' | 'failed'
  outcome: string | null
  now_ms: number
  running_ms: number | null
  /** Pass back as `after` to receive only what changed. */
  next: number
  truncated: boolean
  spans: LiveSpan[]
  counts: { knowledge_calls: number; model_calls: number; open: number }
}

/** One step of a procedure as the Synapt knowledge graph holds it (Procedure -HAS_STEP-> Step). */
export interface GraphStep {
  number: number
  text: string
  needs: string | null
  who: string | null
}

/** A rule, control or task a step references in the graph (Step -REFERENCES-> Entity). */
export interface GraphEntity {
  label: string
  kind: string
  description: string
  confidence: number | null
}

export interface GraphProcedure {
  /** Cited evidence ID, `graph:procedure:<id>`. */
  source_id: string
  node_id: string
  name: string
  intent: string
  score: number | null
  /** Why it applies to this claim: its claim type, a theft claim, or general handling. */
  applies_because: 'claim_type' | 'theft' | 'general' | 'late_filing' | 'large_loss' | 'repeat_claimant' | 'new_policyholder' | 'water_damage' | string
  steps: GraphStep[]
  entities: GraphEntity[]
  /** The passages Synapt extracted this procedure from (the chunk IDs passage evidence is cited by). */
  source_chunk_ids: string[]
  edge_counts?: Record<string, number>
  /** `model` when the Procedure Graph Navigator's model found and read it beyond the standard searches. */
  found_by?: 'model' | string
}

export interface GraphSearch {
  scope: 'claim_type' | 'theft' | 'general' | string
  query: string
  found: { name: string; score: number | null; used: boolean; applies_because: string | null }[]
}

/** What the Procedure Graph Navigator's model did after the standard searches. */
export interface GraphFollowUp {
  searches: { query: string; found: number; fitting: number }[]
  read: string[]
  rounds: number
}

/** Handling procedures read from the Synapt knowledge graph for one run; absent when Synapt was not used. */
export interface KnowledgeGraph {
  available: boolean
  reason?: string
  provider_id?: string | null
  procedures: GraphProcedure[]
  searches: GraphSearch[]
  calls: number
  /** The conditions this claim meets (filed late, a large loss, ...), which decide the conditional procedures. */
  cues?: { key: string; label: string }[]
  tools?: string[]
  edge_types?: string[]
  followup?: GraphFollowUp
}

/** What the Supervisor Agent did with a finished brief. */
export interface SupervisorRecord {
  status: 'done' | 'skipped' | 'unavailable' | string
  /** A short plain-language summary for the handler; null when there is none (the model's did not pass the text checks, or it was not run). */
  summary: string | null
  summary_rejected?: string | null
  /** The findings were sent back once and the brief was checked again. */
  revised: boolean
  revision?: { issues: string[]; instructions?: string; applied: boolean; passed_after?: boolean; issues_after?: string[]; failure?: string } | null
  reason?: string | null
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
  supervisor?: SupervisorRecord
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
  /** Cohort statistics from DuckDB; absent on runs saved before the feature existed. */
  cohort?: CohortStats
  /** Procedures read from the Synapt knowledge graph; absent on runs saved before the feature existed. */
  graph?: KnowledgeGraph | null
  /** Synapt's query agent's answer; absent on runs saved before the feature, or when no call was made. */
  query_agent?: QueryAgent | null
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

/** What the Synapt provider holds right now (administrators only); `available: false` carries a plain reason. */
export interface SynaptStats {
  available: boolean
  reason?: string
  stale?: boolean
  provider_id?: string
  kind?: string
  has_ticket_store?: boolean
  documents?: number | null
  passages?: number | null
  graph_nodes?: number | null
  connections?: number | null
  procedures?: number | null
  steps?: number | null
  entities?: number | null
  concepts?: number | null
  knowledge_by_kind?: { kind: string; count: number }[]
  episodes?: { store_exists: boolean; count: number | null } | null
  fetched_at?: string
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
  // candidates compared on the selection cohort (lower MAE is better; for fraud, PR-AUC higher is better)
  candidate_selection_maes?: Record<string, number>
  candidate_selection_scores?: Record<string, { pr_auc?: number; brier?: number; recall_at_50pct_precision?: number }>
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

export interface EvaluationStep {
  id: string
  label: string
  state: 'pending' | 'running' | 'done' | 'failed' | 'skipped'
  started_at: string | null
  ended_at: string | null
  detail: string | null
}

export interface EvaluationProgress {
  state: 'idle' | 'running' | 'done' | 'failed'
  judge_requested: boolean
  started_at: string | null
  finished_at: string | null
  phase: string | null
  current: string | null
  total_steps: number
  done_steps: number
  steps: EvaluationStep[]
  events: { at: string; text: string }[]
}

export interface EvaluationStatus {
  status: string
  judge_status: string
  progress?: EvaluationProgress
  judge_model?: string | null
  judge_threshold?: number
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

export interface EvaluationRunItem {
  id: number
  time: string
  started_at: string | null
  finished_at: string | null
  duration_seconds: number | null
  mode: string | null
  agent_mode: string | null
  overall_passed: boolean | null
  cases: { passed: number | null; total: number | null; items: { case: string; passed: boolean; run_id: string | null }[] }
  judge: {
    requested: boolean
    status: string | null
    model: string | null
    independent: boolean | null
    threshold: number | null
    expected_metrics: number | null
    completed_metrics: number | null
    passed_metrics: number | null
    mean_score: number | null
    metrics: { metric: string; completed: number; passed: number; failed: number; skipped: number; mean_score: number | null }[]
    model_calls: { traced: boolean; calls: number; tokens: number; total_ms: number }
  }
}

export interface EvaluationRuns {
  generated_at: string
  items: EvaluationRunItem[]
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

// ---------- Intake: model pass over the handler's free-text notes ----------
export interface IntakeExtraction {
  /** Field name -> value plus the words from the notes that support it. The server only returns
   *  values whose quote appears word for word in the notes. */
  fields: Record<string, { value: unknown; quote: string }>
  model: string
}

/** Advisory: rejects with an ApiError (503 when no model is available) and the caller keeps its own reading. */
export const extractIntake = (description: string, signal?: AbortSignal) =>
  api<IntakeExtraction>('/api/intake/extract', { method: 'POST', body: JSON.stringify({ description }), signal, timeoutMs: 45_000 })
