import { request } from './http'
import type {
  AgentRegressionRunPayload,
  AgentRegressionRunResponse,
  AgentReplaySnapshot,
  AgentReplaysListParams,
  AgentRunsListParams,
  AgentRunTraceDetail,
  AgentRunTraceListItem,
  BadCaseFeedback,
  BadCaseFeedbackCreatePayload,
  BadCaseFeedbackListParams,
  BadCaseFeedbackListResponse,
  BadCaseFeedbackUpdatePayload,
  CorrectnessSummaryParams,
  CorrectnessSummaryResponse,
  EvalCase,
  EvalCasesListParams,
  EvalCaseBulkUpdatePayload,
  EvalCaseBulkUpdateResponse,
  EvalCaseClonePayload,
  EvalCaseUpdatePayload,
  EvalCoverageParams,
  EvalCoverageResponse,
  EvalRun,
  EvalRunPayload,
  EvalRunsListParams,
  HarnessListResponse,
  ImpactAnalysisChangedFilesPayload,
  ImpactAnalysisGitDiffPayload,
  ImpactAnalysisResult,
  LLMCallMetric,
  LlmCallListParams,
  RegressionProfile,
  RegressionProfileListResponse,
  RegressionProfileUpsertPayload,
} from '@/types/adminHarness'

function queryString(params: object): string {
  const search = new URLSearchParams()
  Object.entries(params as Record<string, unknown>).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    search.set(key, String(value))
  })
  const text = search.toString()
  return text ? `?${text}` : ''
}

export function listLlmCalls(params: LlmCallListParams = {}): Promise<HarnessListResponse<LLMCallMetric>> {
  return request<HarnessListResponse<LLMCallMetric>>(`/api/admin/llm-calls${queryString(params)}`)
}

export function listAgentRuns(params: AgentRunsListParams = {}): Promise<HarnessListResponse<AgentRunTraceListItem>> {
  return request<HarnessListResponse<AgentRunTraceListItem>>(`/api/admin/agent-runs${queryString(params)}`)
}

export function getAgentRun(runId: string): Promise<AgentRunTraceDetail> {
  return request<AgentRunTraceDetail>(`/api/admin/agent-runs/${encodeURIComponent(runId)}`)
}

export function listAgentReplays(params: AgentReplaysListParams = {}): Promise<HarnessListResponse<AgentReplaySnapshot>> {
  return request<HarnessListResponse<AgentReplaySnapshot>>(`/api/admin/agent-replays${queryString(params)}`)
}

export function getAgentReplay(replayId: string): Promise<AgentReplaySnapshot> {
  return request<AgentReplaySnapshot>(`/api/admin/agent-replays/${encodeURIComponent(replayId)}`)
}

export function getAgentReplayByRun(runId: string): Promise<AgentReplaySnapshot> {
  return request<AgentReplaySnapshot>(`/api/admin/agent-replays/by-run/${encodeURIComponent(runId)}`)
}

export function exportAgentReplay(replayId: string): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/admin/agent-replays/${encodeURIComponent(replayId)}/export`)
}

export function listEvalCases(params: EvalCasesListParams = {}): Promise<HarnessListResponse<EvalCase>> {
  return request<HarnessListResponse<EvalCase>>(`/api/admin/agent-eval/cases${queryString(params)}`)
}

export function getEvalCase(caseId: string): Promise<EvalCase> {
  return request<EvalCase>(`/api/admin/agent-eval/cases/${encodeURIComponent(caseId)}`)
}

export function seedEvalCases(force = false): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/admin/agent-eval/cases/seed${queryString({ force })}`, {
    method: 'POST',
  })
}

export function createEvalCase(payload: Partial<EvalCase>): Promise<EvalCase> {
  return request<EvalCase>('/api/admin/agent-eval/cases', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateEvalCase(caseId: string, payload: EvalCaseUpdatePayload): Promise<EvalCase> {
  return request<EvalCase>(`/api/admin/agent-eval/cases/${encodeURIComponent(caseId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function archiveEvalCase(caseId: string, reason?: string): Promise<EvalCase> {
  return request<EvalCase>(`/api/admin/agent-eval/cases/${encodeURIComponent(caseId)}/archive`, {
    method: 'PATCH',
    body: JSON.stringify({ reason }),
  })
}

export function unarchiveEvalCase(caseId: string): Promise<EvalCase> {
  return request<EvalCase>(`/api/admin/agent-eval/cases/${encodeURIComponent(caseId)}/unarchive`, {
    method: 'PATCH',
  })
}

export function createEvalCaseFromReplay(replayId: string, save = true): Promise<EvalCase> {
  return request<EvalCase>(`/api/admin/agent-eval/cases/from-replay/${encodeURIComponent(replayId)}${queryString({ save })}`, {
    method: 'POST',
  })
}

export function createEvalCaseFromLlmCall(callId: string, save = false): Promise<EvalCase> {
  return request<EvalCase>(`/api/admin/agent-eval/cases/from-llm-call/${encodeURIComponent(callId)}${queryString({ save })}`, {
    method: 'POST',
  })
}

export function createEvalCaseFromNodeTrace(
  runId: string,
  nodeTraceId: string,
  save = false,
): Promise<EvalCase> {
  return request<EvalCase>(
    `/api/admin/agent-eval/cases/from-node-trace/${encodeURIComponent(runId)}/${encodeURIComponent(nodeTraceId)}${queryString({ save })}`,
    {
      method: 'POST',
    },
  )
}

export function runEval(payload: EvalRunPayload): Promise<EvalRun> {
  return request<EvalRun>('/api/admin/agent-eval/runs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listEvalRuns(params: EvalRunsListParams = {}): Promise<HarnessListResponse<EvalRun>> {
  return request<HarnessListResponse<EvalRun>>(`/api/admin/agent-eval/runs${queryString(params)}`)
}

export function getEvalRun(evalRunId: string): Promise<EvalRun> {
  return request<EvalRun>(`/api/admin/agent-eval/runs/${encodeURIComponent(evalRunId)}`)
}

export function compareEvalRuns(params: {
  baseline_run_id: string
  candidate_run_id: string
}): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/admin/agent-eval/runs/compare${queryString(params)}`)
}

export function bulkUpdateEvalCases(payload: EvalCaseBulkUpdatePayload): Promise<EvalCaseBulkUpdateResponse> {
  return request<EvalCaseBulkUpdateResponse>('/api/admin/agent-eval/cases/bulk', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function cloneEvalCase(caseId: string, payload?: EvalCaseClonePayload): Promise<EvalCase> {
  return request<EvalCase>(`/api/admin/agent-eval/cases/${encodeURIComponent(caseId)}/clone`, {
    method: 'POST',
    body: payload ? JSON.stringify(payload) : undefined,
  })
}

export function listBadCaseFeedback(params: BadCaseFeedbackListParams = {}): Promise<BadCaseFeedbackListResponse> {
  return request<BadCaseFeedbackListResponse>(`/api/admin/agent-eval/feedback${queryString(params)}`)
}

export function createBadCaseFeedback(payload: BadCaseFeedbackCreatePayload): Promise<BadCaseFeedback> {
  return request<BadCaseFeedback>('/api/admin/agent-eval/feedback', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getBadCaseFeedback(feedbackId: string): Promise<BadCaseFeedback> {
  return request<BadCaseFeedback>(`/api/admin/agent-eval/feedback/${encodeURIComponent(feedbackId)}`)
}

export function updateBadCaseFeedback(feedbackId: string, payload: BadCaseFeedbackUpdatePayload): Promise<BadCaseFeedback> {
  return request<BadCaseFeedback>(`/api/admin/agent-eval/feedback/${encodeURIComponent(feedbackId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function createEvalCaseFromFeedback(feedbackId: string, payload?: { title?: string; enabled?: boolean }): Promise<EvalCase> {
  return request<EvalCase>(`/api/admin/agent-eval/feedback/${encodeURIComponent(feedbackId)}/create-case`, {
    method: 'POST',
    body: payload ? JSON.stringify(payload) : undefined,
  })
}

export function createFeedbackFromEvalRunFailures(evalRunId: string): Promise<{ created: number; skipped: number; total_failures: number }> {
  return request<{ created: number; skipped: number; total_failures: number }>(`/api/admin/agent-eval/runs/${encodeURIComponent(evalRunId)}/feedback-from-failures`, {
    method: 'POST',
  })
}

export function runAgentRegressionEval(payload: AgentRegressionRunPayload): Promise<AgentRegressionRunResponse> {
  return request<AgentRegressionRunResponse>('/api/admin/agent-eval/regression-runs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getEvalCoverage(params: EvalCoverageParams = {}): Promise<EvalCoverageResponse> {
  return request<EvalCoverageResponse>(`/api/admin/agent-eval/coverage${queryString(params)}`)
}

export function fetchCorrectnessSummary(
  params: CorrectnessSummaryParams = {},
): Promise<CorrectnessSummaryResponse> {
  return request<CorrectnessSummaryResponse>(
    `/api/admin/agent-eval/correctness-summary${queryString(params)}`,
  )
}

export function listRegressionProfiles(params: { enabled?: boolean; query?: string; limit?: number } = {}): Promise<RegressionProfileListResponse> {
  return request<RegressionProfileListResponse>(`/api/admin/agent-eval/regression-profiles${queryString(params)}`)
}

export function getRegressionProfile(agentName: string): Promise<RegressionProfile> {
  return request<RegressionProfile>(`/api/admin/agent-eval/regression-profiles/${encodeURIComponent(agentName)}`)
}

export function upsertRegressionProfile(agentName: string, payload: RegressionProfileUpsertPayload): Promise<RegressionProfile> {
  return request<RegressionProfile>(`/api/admin/agent-eval/regression-profiles/${encodeURIComponent(agentName)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function disableRegressionProfile(agentName: string): Promise<RegressionProfile> {
  return request<RegressionProfile>(`/api/admin/agent-eval/regression-profiles/${encodeURIComponent(agentName)}/disable`, {
    method: 'POST',
  })
}

export function buildRegressionPayloadFromProfile(agentName: string, overrides?: Record<string, unknown>): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/admin/agent-eval/regression-profiles/${encodeURIComponent(agentName)}/build-payload`, {
    method: 'POST',
    body: JSON.stringify({ overrides: overrides || {} }),
  })
}

export function analyzeImpactChangedFiles(payload: ImpactAnalysisChangedFilesPayload): Promise<ImpactAnalysisResult> {
  return request<ImpactAnalysisResult>('/api/admin/agent-eval/impact-analysis/changed-files', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function analyzeImpactGitDiff(payload: ImpactAnalysisGitDiffPayload): Promise<ImpactAnalysisResult> {
  return request<ImpactAnalysisResult>('/api/admin/agent-eval/impact-analysis/git-diff', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export interface RegressionGateDryRunPayload {
  changed_files?: string[]
  base_ref?: string
  head_ref?: string
  max_agents?: number
}

export interface RegressionGateResult {
  ok: boolean
  mode: string
  base_ref?: string | null
  head_ref?: string | null
  dry_run?: boolean
  summary: {
    changed_file_count: number
    impacted_agent_count: number
    recommended_run_count: number
    executed_run_count: number
    passed_run_count: number
    failed_run_count: number
  }
  impact_analysis: ImpactAnalysisResult
  runs: Array<{
    agent_name: string
    recommended?: boolean
    eval_run_id?: string | null
    gate_passed?: boolean | null
    gate_result?: Record<string, unknown> | null
    regression_payload?: Record<string, unknown> | null
    dry_run?: boolean
    error?: string | null
  }>
  reasons: string[]
}

export function regressionGateDryRun(payload: RegressionGateDryRunPayload): Promise<RegressionGateResult> {
  return request<RegressionGateResult>('/api/admin/agent-eval/regression-gate/dry-run', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export interface RegressionGateReport {
  report_id: string
  mode: string
  trigger: string
  status: string
  ok: boolean
  dry_run: boolean
  base_ref: string | null
  head_ref: string | null
  changed_files: string[]
  impacted_agents: string[]
  recommended_agents: string[]
  executed_agents: string[]
  summary: {
    changed_file_count: number
    impacted_agent_count: number
    recommended_run_count: number
    executed_run_count: number
    passed_run_count: number
    failed_run_count: number
  }
  impact_analysis: ImpactAnalysisResult
  runs: Array<Record<string, unknown>>
  reasons: string[]
  created_at: string
  created_by: string | null
  git: Record<string, unknown>
  metadata: Record<string, unknown>
}

export interface RegressionGateReportListResponse {
  items: RegressionGateReport[]
  summary: {
    report_count: number
    passed_count: number
    failed_count: number
    dry_run_count: number
    error_count: number
  }
}

export function listRegressionGateReports(params: {
  status?: string; trigger?: string; ok?: boolean; dry_run?: boolean;
  agent_name?: string; hours?: number; limit?: number
} = {}): Promise<RegressionGateReportListResponse> {
  return request<RegressionGateReportListResponse>(`/api/admin/agent-eval/regression-gate/reports${queryString(params)}`)
}

export function getRegressionGateReport(reportId: string): Promise<RegressionGateReport> {
  return request<RegressionGateReport>(`/api/admin/agent-eval/regression-gate/reports/${encodeURIComponent(reportId)}`)
}
