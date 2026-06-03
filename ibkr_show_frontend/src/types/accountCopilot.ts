export interface CopilotSession {
  id: string
  title: string
  status: 'active' | 'archived'
  created_at: string
  updated_at: string
  last_message_at: string | null
  message_count: number
  rolling_summary: string
  compressed_until_message_id: string | null
  pinned_facts: Record<string, unknown>
  metadata: Record<string, unknown>
}

export interface CopilotSessionListResponse {
  items: CopilotSession[]
}

export interface CopilotMessage {
  id: string
  session_id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  created_at: string
  run_id: string | null
  metadata: Record<string, unknown>
}

export interface CopilotMessageListResponse {
  items: CopilotMessage[]
}

export interface CopilotRun {
  id: string
  session_id: string
  user_message_id: string
  assistant_message_id: string | null
  status: 'queued' | 'running' | 'awaiting_approval' | 'completed' | 'failed' | 'cancelled'
  created_at: string
  updated_at: string
  started_at: string | null
  completed_at: string | null
  user_input: string
  planner_output: Record<string, any>
  actions: Record<string, any>[]
  observations: Record<string, any>[]
  tool_calls: Record<string, any>[]
  skill_requests: Record<string, any>[]
  pending_approval: CopilotApproval | null
  memory_snapshot: Record<string, any>
  final_answer: string | null
  error_code: string | null
  error_message: string | null
  metadata: Record<string, any>
  _live_events?: CopilotEvent[]
  _live_final_answer?: string
  _streaming?: boolean
}

export interface CopilotSendMessageResponse {
  user_message: CopilotMessage
  assistant_message: CopilotMessage
  run: CopilotRun
}

export interface CopilotSendMessageStreamResponse {
  user_message: CopilotMessage
  run: CopilotRun
  events_url: string
}

export interface CopilotEvent {
  id: string
  run_id: string
  session_id: string
  event_type:
    | 'run_started'
    | 'planner_started'
    | 'planner_finished'
    | 'planner_repair_started'
    | 'planner_repair_finished'
    | 'action_selected'
    | 'tool_started'
    | 'tool_finished'
    | 'tool_failed'
    | 'observation_created'
    | 'skill_approval_requested'
    | 'skill_approval_approved'
    | 'skill_approval_rejected'
    | 'skill_started'
    | 'skill_finished'
    | 'skill_failed'
    | 'final_answer'
    | 'memory_update_started'
    | 'memory_update_finished'
    | 'memory_update_failed'
    | 'run_completed'
    | 'run_failed'
    | 'run_cancelled'
    | 'subagent_started'
    | 'subagent_finished'
    | 'subagent_failed'
    | 'heartbeat'
    | string
  seq: number
  created_at: string
  payload: Record<string, any>
}

export interface CopilotApproval {
  approval_id: string
  run_id?: string
  session_id?: string
  skill_name: string
  skill_display_name?: string
  skill_arguments: Record<string, any>
  approval_message: string
  plan_hash: string
  status: 'pending' | 'awaiting_approval' | 'approved' | 'rejected' | 'expired' | 'executed' | 'failed'
  created_at?: string
  updated_at?: string
  expires_at?: string
  approved_at?: string | null
  rejected_at?: string | null
  executed_at?: string | null
  result_observation_id?: string | null
  data_access?: string[]
}

export interface CopilotApprovalRequest {
  approval_id: string
  approved: boolean
  plan_hash: string
  comment?: string
}

export interface CopilotApprovalResponse {
  run: CopilotRun
  assistant_message: CopilotMessage | null
}

export interface CopilotMemory {
  id: string
  session_id: string
  memory_type: 'conversation_segment' | 'pinned_fact' | 'tool_fact' | 'skill_fact' | 'constraint'
  status: 'active' | 'superseded' | 'deleted'
  created_at: string
  updated_at: string
  message_start_id?: string | null
  message_end_id?: string | null
  message_count: number
  message_range_created_at: Record<string, string | null>
  summary: string
  symbols: string[]
  topics: string[]
  user_intent: string
  important_facts: string[]
  user_preferences: string[]
  open_questions: string[]
  tool_facts: Record<string, any>[]
  skill_facts: Record<string, any>[]
  non_compressible_constraints: string[]
  source_run_ids: string[]
  source_message_ids: string[]
  metadata: Record<string, any>
}

export interface CopilotMemoryListResponse {
  items: CopilotMemory[]
}

export interface CopilotToolSpec {
  name: string
  description: string
  category: string
  data_sensitivity: string
  read_only: boolean
  approval_required: boolean
  output_budget_chars?: number | null
  schema: Record<string, any>
}

export interface CopilotToolListResponse {
  items: CopilotToolSpec[]
}

export interface CopilotEventListResponse {
  items: CopilotEvent[]
}

export interface CopilotTraceTimelineNode {
  node_type: 'planner' | 'action' | 'tool' | 'subagent' | 'observation' | 'final_answer' | 'error'
  round?: number | null
  status: string
  label: string
  created_at: string
  payload: Record<string, any>
}

export interface CopilotRunTraceResponse {
  run_id: string
  status: string
  timeline: CopilotTraceTimelineNode[]
  events: CopilotEvent[]
}

export interface CopilotHealthCheck {
  ok: boolean
  message?: string
  count?: number
}

export interface CopilotHealthResponse {
  ok: boolean
  checks: Record<string, CopilotHealthCheck>
  settings: {
    max_react_rounds: number
    run_timeout_seconds: number
    max_event_payload_chars: number
    demo_mode: boolean
  }
}

export interface CopilotDemoSeedResponse {
  session: CopilotSession
  messages: CopilotMessage[]
  runs: CopilotRun[]
  memories: CopilotMemory[]
}

export interface CopilotToolProbeResult {
  id: string
  probe_run_id: string
  tool_name: string
  tool_domain: 'ibkr' | 'longbridge' | 'skill' | 'agent' | string
  category: string
  probe_type: 'catalog' | 'schema' | 'invoke' | 'agent_eval' | string
  status: 'pass' | 'fail' | 'partial' | 'skipped'
  ok: boolean
  latency_ms: number
  error_code?: string | null
  error_message?: string | null
  arguments_preview: Record<string, any>
  data_empty: boolean
  data_size: number
  data_limitations: string[]
  created_at: string
  metadata: Record<string, any>
}

export interface CopilotToolReliabilityLatestResponse {
  probe_run_id: string | null
  total: number
  pass: number
  fail: number
  partial: number
  skipped: number
  success_rate: number
  p95_latency_ms: number
  last_run_at: string
  domain_stats: Record<string, {
    total: number
    pass: number
    fail: number
    partial: number
    skipped: number
    success_rate: number
    avg_latency_ms: number
  }>
  results: CopilotToolProbeResult[]
}

export interface CopilotToolReliabilityResultsResponse {
  items: CopilotToolProbeResult[]
}

export interface CopilotToolReliabilityProbeRequest {
  include_live: boolean
  include_longbridge: boolean
  include_ibkr: boolean
  include_agent_eval: boolean
  symbol: string
  keyword: string
  max_tools: number
}

export interface CopilotToolReliabilityProbeResponse {
  probe_run_id: string
  total: number
  pass: number
  fail: number
  partial: number
  skipped: number
  success_rate: number
  p95_latency_ms: number
  last_run_at: string
  domain_stats: Record<string, {
    total: number
    pass: number
    fail: number
    partial: number
    skipped: number
    success_rate: number
    avg_latency_ms: number
  }>
  results: CopilotToolProbeResult[]
}

export interface AgentMonitoringRange {
  hours: number
  bucket: string
}

export interface AgentMonitoringStatusSummary {
  status: 'healthy' | 'degraded' | 'down' | 'unknown' | string
  success_rate_24h?: number
  failure_rate_24h?: number
  call_count_24h?: number
  p95_latency_ms_24h?: number
  [key: string]: string | number | string[] | undefined
}

export interface AgentMonitoringLlmSummary extends AgentMonitoringStatusSummary {
  models: string[]
}

export interface AgentMonitoringOverviewResponse {
  range: AgentMonitoringRange
  ibkr: AgentMonitoringStatusSummary
  longbridge: AgentMonitoringStatusSummary
  llm: AgentMonitoringLlmSummary
  recent_failure_count: number
  last_probe_at: string
}

export interface AgentMetricSeriesItem {
  bucket_start: string
  success_rate: number
  failure_rate: number
  call_count: number
  avg_latency_ms: number
  p95_latency_ms: number
}

export interface AgentToolMetricsResponse {
  range: AgentMonitoringRange
  ibkr: {
    series: AgentMetricSeriesItem[]
  }
  longbridge: {
    series: AgentMetricSeriesItem[]
  }
}

export interface AgentLlmMetricSeriesItem extends AgentMetricSeriesItem {
  avg_prompt_tokens: number
  avg_completion_tokens: number
  avg_total_tokens: number
}

export interface AgentLlmModelSeries {
  model: string
  provider: string
  series: AgentLlmMetricSeriesItem[]
}

export interface AgentLlmMetricsResponse {
  range: AgentMonitoringRange
  models: AgentLlmModelSeries[]
}

export interface AgentMonitoringFailureItem {
  created_at: string
  kind: 'tool' | 'llm'
  name: string
  domain: string
  agent_name?: string
  node_name?: string
  source?: string
  error_code?: string | null
  error_message?: string | null
  latency_ms: number
  run_id: string
  task_id?: string
}

export interface AgentMonitoringFailureResponse {
  items: AgentMonitoringFailureItem[]
}

export interface AgentRecentToolCall {
  id: string
  created_at: string
  run_id: string
  task_id: string
  session_id: string
  agent_name: string
  node_name: string
  tool_domain: 'ibkr' | 'longbridge' | string
  tool_name: string
  ok: boolean
  latency_ms: number
  error_code?: string | null
  error_message?: string | null
  source: 'runtime' | 'probe' | string
  metadata: Record<string, any>
  empty_result: boolean
  raw_ok?: boolean | null
  compact_ok?: boolean | null
  parsed_fields_count: number
  missing_fields_count: number
  fallback_used: boolean
  rolling_success_rate_10: number
  rolling_failure_rate_10: number
  rolling_window_size: number
}

export interface AgentRecentToolCallsResponse {
  items: AgentRecentToolCall[]
}

export interface AgentRecentLlmCall {
  id: string
  created_at: string
  run_id: string
  task_id: string
  session_id: string
  agent_name: string
  node_name: string
  provider: string
  model: string
  call_type: string
  ok: boolean
  latency_ms: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  error_code?: string | null
  error_message?: string | null
  metadata: Record<string, any>
  rolling_success_rate_10: number
  rolling_failure_rate_10: number
  rolling_window_size: number
}

export interface AgentRecentLlmCallsResponse {
  items: AgentRecentLlmCall[]
}

export interface AgentStructuredOutputEvent {
  id: string
  created_at: string
  source: string
  agent_name: string
  node_name: string
  contract_name: string
  run_id: string
  task_id: string
  session_id: string
  ok: boolean
  schema_validation_passed: boolean
  repaired: boolean
  repair_attempts: number
  fallback_used: boolean
  error_code?: string | null
  error_message?: string | null
  output_model_name: string
  rolling_success_rate_10: number
  rolling_repair_rate_10: number
  rolling_fallback_rate_10: number
  rolling_window_size: number
}

export interface AgentStructuredOutputResponse {
  items: AgentStructuredOutputEvent[]
}
