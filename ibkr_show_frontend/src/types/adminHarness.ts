export interface HarnessListResponse<T> {
  items: T[]
  summary?: Record<string, unknown>
}

export interface LLMCallMetric {
  call_id: string
  run_id?: string | null
  session_id?: string | null
  agent_name?: string | null
  node_name?: string | null
  provider_id?: string | null
  provider_name?: string | null
  provider_type?: string | null
  model?: string | null
  call_type?: string | null
  prompt_key?: string | null
  prompt_version?: string | null
  prompt_hash?: string | null
  prompt_source?: string | null
  response_format_type?: string | null
  tool_calling?: boolean
  tool_count?: number
  temperature?: number | null
  max_tokens?: number | null
  prompt_tokens?: number
  completion_tokens?: number
  total_tokens?: number
  reasoning_tokens?: number
  cached_tokens?: number
  latency_ms?: number
  estimated_cost?: number | null
  ok?: boolean
  error_code?: string | null
  error_message?: string | null
  created_at?: string
}

export interface AgentRunTraceListItem {
  run_id: string
  agent_name?: string | null
  agent_version?: string | null
  agent_mode?: string | null
  session_id?: string | null
  user_id?: string | null
  request_id?: string | null
  final_status?: string | null
  error_code?: string | null
  error_message?: string | null
  latency_ms?: number
  started_at?: string
  finished_at?: string | null
  prompt_keys?: string[]
  prompt_versions?: string[]
  prompt_hashes?: string[]
  llm_call_count?: number
  tool_call_count?: number
  total_tokens?: number
  estimated_cost?: number | null
}

export interface AgentRunTraceDetail extends AgentRunTraceListItem {
  prompt_metadata?: Record<string, unknown>
  context_manifest?: Record<string, unknown>
  llm_calls?: Record<string, unknown>[]
  tool_calls?: Record<string, unknown>[]
  validation?: Record<string, unknown>
  repair_attempts?: Record<string, unknown>[]
  fallback?: Record<string, unknown>
  quality_score?: Record<string, unknown>
  node_traces?: Record<string, unknown>[]
  metadata?: Record<string, unknown>
}

export interface AgentReplaySnapshot {
  replay_id: string
  run_id?: string | null
  agent_name?: string | null
  agent_version?: string | null
  agent_mode?: string | null
  created_at?: string
  source?: string
  replay_schema_version?: string
  request?: Record<string, unknown>
  prompt_refs?: Record<string, unknown>[]
  model_config?: Record<string, unknown>
  context_snapshot?: Record<string, unknown>
  tool_snapshots?: Record<string, unknown>[]
  llm_snapshots?: Record<string, unknown>[]
  final_output?: Record<string, unknown>
  persisted_document_id?: string | null
  final_status?: string | null
  data_limitations?: string[]
  trace_ref?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export interface EvalCase {
  case_id: string
  agent_name?: string | null
  title?: string
  description?: string
  tags?: string[]
  source?: string
  input?: Record<string, unknown>
  mock_context?: Record<string, unknown>
  mock_tool_outputs?: Record<string, unknown>
  expected_behavior?: Record<string, unknown>
  expected_output_fields?: string[]
  forbidden_behavior?: string[]
  scoring_rubric?: Record<string, unknown>
  created_at?: string
  metadata?: Record<string, unknown>
  enabled?: boolean
  severity?: string
  category?: string
  source_replay_id?: string | null
  expected_tools?: string[]
  expected_data_limitations?: string[]
  notes?: string
  updated_at?: string
  version?: number
  judge_enabled?: boolean
  judge_rubric?: Record<string, unknown>
  judge_model_config?: Record<string, unknown>
  eval_scope?: 'agent' | 'node' | string
  node_name?: string | null
  source_run_id?: string | null
  source_llm_call_id?: string | null
  source_node_trace_id?: string | null
  prompt_key?: string | null
  prompt_version?: string | null
  prompt_hash?: string | null
  model?: string | null
  archived?: boolean
  archived_at?: string | null
  archived_reason?: string | null
}

export interface EvalCheckResult {
  check_name?: string
  passed?: boolean
  severity?: string
  score?: number
  max_score?: number
  message?: string
  details?: Record<string, unknown>
}

export interface EvalCaseResult {
  case_id?: string
  agent_name?: string | null
  status?: string
  score?: number
  max_score?: number
  checks?: EvalCheckResult[]
  output_summary?: Record<string, unknown>
  error_code?: string | null
  error_message?: string | null
  latency_ms?: number
  replay_id?: string | null
  run_id?: string | null
  metadata?: Record<string, unknown>
}

export interface EvalRun {
  eval_run_id: string
  name?: string
  agent_name?: string | null
  case_ids?: string[]
  config?: Record<string, unknown>
  started_at?: string
  finished_at?: string | null
  status?: string
  summary?: Record<string, unknown>
  results?: EvalCaseResult[]
}

export interface LlmCallListParams {
  hours?: number
  agent_name?: string
  prompt_key?: string
  model?: string
  ok?: boolean | null
  limit?: number
}

export interface AgentRunsListParams {
  hours?: number
  agent_name?: string
  final_status?: string
  limit?: number
}

export interface AgentReplaysListParams {
  hours?: number
  agent_name?: string
  final_status?: string
  limit?: number
}

export interface EvalCasesListParams {
  agent_name?: string
  source?: string
  enabled?: boolean | null
  severity?: string
  category?: string
  tag?: string
  source_replay_id?: string
  query?: string
  limit?: number
  eval_scope?: string
  node_name?: string
  source_run_id?: string
  source_llm_call_id?: string
  prompt_key?: string
  model?: string
  include_archived?: boolean
}

export interface EvalRunsListParams {
  hours?: number
  agent_name?: string
  limit?: number
}

export interface EvalRunPayload {
  case_ids?: string[]
  agent_name?: string | null
  replay_ids?: string[]
  mode?: string
  name?: string | null
}

export interface EvalCaseUpdatePayload {
  title?: string
  description?: string
  tags?: string[]
  enabled?: boolean
  severity?: string
  category?: string
  input?: Record<string, unknown>
  mock_context?: Record<string, unknown>
  mock_tool_outputs?: Record<string, unknown>
  expected_behavior?: Record<string, unknown>
  expected_output_fields?: string[]
  expected_tools?: string[]
  expected_data_limitations?: string[]
  forbidden_behavior?: string[]
  scoring_rubric?: Record<string, unknown>
  notes?: string
  metadata?: Record<string, unknown>
  eval_scope?: 'agent' | 'node' | string
  node_name?: string | null
  source_run_id?: string | null
  source_llm_call_id?: string | null
  source_node_trace_id?: string | null
  prompt_key?: string | null
  prompt_version?: string | null
  prompt_hash?: string | null
  model?: string | null
}

export interface EvalCaseBulkUpdatePayload {
  case_ids: string[]
  updates: {
    enabled?: boolean
    severity?: string
    category?: string
    tags_add?: string[]
    tags_remove?: string[]
    notes_append?: string
  }
}

export interface EvalCaseBulkUpdateResponse {
  updated_count: number
  failed_count: number
  items: Array<{
    case_id: string
    status: string
    error_code?: string
    error_message?: string
  }>
}

export interface EvalCaseClonePayload {
  title?: string
  enabled?: boolean
}

export interface BadCaseFeedback {
  feedback_id: string
  source_type: string
  source_id: string
  agent_name?: string
  title: string
  description?: string
  issue_type?: string
  severity?: string
  category?: string
  tags?: string[]
  status?: string
  notes?: string
  replay_id?: string | null
  run_id?: string | null
  eval_run_id?: string | null
  case_id?: string | null
  result_case_id?: string | null
  converted_case_id?: string | null
  evidence?: Record<string, unknown>
  metadata?: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

export interface BadCaseFeedbackListParams {
  status?: string
  source_type?: string
  agent_name?: string
  severity?: string
  category?: string
  issue_type?: string
  tag?: string
  eval_run_id?: string
  query?: string
  limit?: number
}

export interface BadCaseFeedbackListResponse {
  items: BadCaseFeedback[]
  summary: {
    count: number
    by_status: Record<string, number>
    by_severity: Record<string, number>
    by_issue_type: Record<string, number>
  }
}

export interface BadCaseFeedbackCreatePayload {
  source_type: string
  source_id: string
  title: string
  agent_name?: string
  description?: string
  issue_type?: string
  severity?: string
  category?: string
  tags?: string[]
  notes?: string
  replay_id?: string | null
  run_id?: string | null
  eval_run_id?: string | null
  case_id?: string | null
  result_case_id?: string | null
  evidence?: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export interface BadCaseFeedbackUpdatePayload {
  title?: string
  description?: string
  issue_type?: string
  severity?: string
  category?: string
  tags?: string[]
  status?: string
  notes?: string
  metadata?: Record<string, unknown>
}

export interface AgentRegressionGatePayload {
  fail_on_critical?: boolean
  fail_on_high?: boolean
  min_pass_rate?: number | null
  max_failed?: number | null
}

export interface AgentRegressionRunPayload {
  agent_name: string
  mode?: 'static' | 'live_mock' | string
  case_tag?: string | null
  severity?: string | null
  category?: string | null
  include_disabled?: boolean
  include_judge?: boolean
  limit?: number
  gate?: AgentRegressionGatePayload
  trigger?: string
  prompt?: Record<string, unknown>
  model?: Record<string, unknown>
  git?: Record<string, unknown>
  baseline_eval_run_id?: string | null
  name?: string | null
  include_node_eval?: boolean
  node_name?: string | null
}

export interface AgentRegressionGateResult {
  passed: boolean
  reasons?: string[]
  critical_failure_count?: number
  high_priority_failure_count?: number
  failed_count?: number
  error_count?: number
  pass_rate?: number
  min_pass_rate?: number | null
  agent_case_count?: number
  agent_failed_count?: number
  agent_pass_rate?: number | null
  node_case_count?: number
  node_failed_count?: number
  node_pass_rate?: number | null
}

export interface AgentRegressionRunResponse {
  eval_run: EvalRun
  gate_result: AgentRegressionGateResult
  baseline_compare_result?: Record<string, unknown> | null
  selected_case_count?: number
  selected_agent_case_count?: number
  selected_node_case_count?: number
  skipped_judge_case_count?: number
  skipped_disabled_case_count?: number
  scope_breakdown?: Record<string, unknown>
}

export interface EvalCoverageSummary {
  case_count?: number
  enabled_case_count?: number
  disabled_case_count?: number
  agent_count?: number
  judge_case_count?: number
  bad_case_source_count?: number
  replay_source_count?: number
  manual_source_count?: number
  recent_eval_run_count?: number
  recent_evaluated_case_count?: number
  never_evaluated_case_count?: number
}

export interface EvalCoverageAgentRow {
  agent_name: string
  case_count?: number
  enabled_case_count?: number
  disabled_case_count?: number
  judge_case_count?: number
  recent_eval_run_count?: number
  recent_pass_rate?: number | null
  recent_failed_count?: number
  recent_error_count?: number
  high_case_count?: number
  critical_case_count?: number
  high_critical_failure_count?: number
  never_evaluated_case_count?: number
}

export interface EvalCoverageCategoryRow {
  agent_name: string
  category: string
  case_count?: number
  enabled_case_count?: number
  recent_pass_rate?: number | null
  recent_failed_count?: number
  high_case_count?: number
  critical_case_count?: number
}

export interface EvalCoverageSeverityRow {
  agent_name: string
  severity: string
  case_count?: number
  enabled_case_count?: number
  recent_pass_rate?: number | null
  recent_failed_count?: number
}

export interface EvalCoverageTagRow {
  agent_name: string
  tag: string
  case_count?: number
  enabled_case_count?: number
  recent_pass_rate?: number | null
}

export interface EvalCoverageSourceRow {
  source: string
  case_count?: number
  enabled_case_count?: number
}

export interface EvalCaseCoverageRow {
  case_id: string
  agent_name?: string
  title?: string
  enabled?: boolean
  severity?: string
  category?: string
  tags?: string[]
  source?: string
  judge_enabled?: boolean
  eval_scope?: string
  node_name?: string | null
  prompt_key?: string | null
  model?: string | null
  last_eval_run_id?: string | null
  last_status?: string | null
  last_score?: number | null
  last_max_score?: number | null
  last_evaluated_at?: string | null
  recent_run_count?: number
  recent_pass_count?: number
  recent_failed_count?: number
  never_evaluated?: boolean
}

export interface EvalCoverageGap {
  gap_id: string
  agent_name: string
  gap_type: string
  severity: string
  category: string
  title: string
  description: string
  evidence: Record<string, unknown>
  suggested_action: string
}

export interface EvalCoverageRecommendation {
  recommendation_id: string
  agent_name: string
  priority: string
  title: string
  description: string
  action_type: string
  related_gap_ids: string[]
  metadata: Record<string, unknown>
}

export interface EvalCoverageResponse {
  summary: EvalCoverageSummary
  by_agent: EvalCoverageAgentRow[]
  by_agent_category: EvalCoverageCategoryRow[]
  by_agent_severity: EvalCoverageSeverityRow[]
  by_agent_tag: EvalCoverageTagRow[]
  by_source: EvalCoverageSourceRow[]
  case_coverage: EvalCaseCoverageRow[]
  gaps: EvalCoverageGap[]
  recommendations: EvalCoverageRecommendation[]
}

export interface EvalCoverageParams {
  agent_name?: string
  hours?: number
  limit?: number
  include_disabled?: boolean
}

export interface RegressionProfileGate {
  fail_on_critical: boolean
  fail_on_high: boolean
  min_pass_rate: number | null
  max_failed: number | null
}

export interface RegressionProfileTriggerPolicy {
  on_prompt_save: boolean
  on_code_change: boolean
  on_deploy: boolean
}

export interface RegressionProfile {
  profile_id: string
  agent_name: string
  enabled: boolean
  mode: string
  case_tag: string | null
  severity: string | null
  category: string | null
  include_disabled: boolean
  include_judge: boolean
  include_node_eval: boolean
  node_name: string | null
  limit: number
  gate: RegressionProfileGate
  trigger_policy: RegressionProfileTriggerPolicy
  notes: string
  created_at: string
  updated_at: string
  version: number
}

export interface RegressionProfileListResponse {
  items: RegressionProfile[]
  summary: {
    profile_count: number
    enabled_count: number
  }
}

export interface RegressionProfileUpsertPayload {
  enabled?: boolean
  mode?: string
  case_tag?: string | null
  severity?: string | null
  category?: string | null
  include_disabled?: boolean
  include_judge?: boolean
  include_node_eval?: boolean
  node_name?: string | null
  limit?: number
  gate?: Partial<RegressionProfileGate>
  trigger_policy?: Partial<RegressionProfileTriggerPolicy>
  notes?: string
}

export interface ImpactedAgent {
  agent_name: string
  confidence: string
  matched_files: string[]
  impacted_nodes: string[]
  profile_exists: boolean
  profile_enabled: boolean
  trigger_policy_on_code_change: boolean
  recommended: boolean
  reason: string
  recommended_node_names?: string[]
  regression_payload: Record<string, unknown> | null
}

export interface ImpactAnalysisResult {
  impacted_agents: ImpactedAgent[]
  unmatched_files: string[]
  summary: {
    changed_file_count: number
    impacted_agent_count: number
    recommended_run_count: number
  }
  base_ref?: string | null
  head_ref?: string | null
}

export interface ImpactAnalysisChangedFilesPayload {
  changed_files: string[]
  base_ref?: string
  head_ref?: string
  include_payload?: boolean
}

export interface ImpactAnalysisGitDiffPayload {
  base_ref: string
  head_ref: string
  include_payload?: boolean
}

// ---------------------------------------------------------------------------
// Eval P3 Stage 06: Correctness Summary
// ---------------------------------------------------------------------------

export interface CorrectnessSummary {
  eval_run_count: number
  judged_case_count: number
  avg_overall_score: number
  failed_dimension_count: number
  high_risk_failure_count: number
}

export interface CorrectnessByAgent {
  agent_name: string
  judged_case_count: number
  avg_overall_score: number
  weakest_dimensions: string[]
  failed_count: number
}

export interface CorrectnessByDimension {
  dimension: string
  avg_score: number
  failed_count: number
  warning_count: number
  affected_agents: string[]
}

export interface CorrectnessRecentFailure {
  eval_run_id: string
  case_id: string
  agent_name: string
  failed_dimensions: string[]
  failure_reasons: string[]
}

export interface CorrectnessSummaryResponse {
  summary: CorrectnessSummary
  by_agent: CorrectnessByAgent[]
  by_dimension: CorrectnessByDimension[]
  recent_failures: CorrectnessRecentFailure[]
}

export interface CorrectnessSummaryParams {
  agent_name?: string
  hours?: number
  limit?: number
}
