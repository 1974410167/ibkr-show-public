import { request } from './http'
import type {
  TradeDecisionHealth,
  TradeDecisionHoldingsResponse,
  TradeDecisionListResponse,
  TradeDecisionOutcomeListResponse,
  TradeDecisionOutcomeSummary,
  TradeDecisionQualitySummary,
  TradeDecisionResult,
} from '@/types/tradeDecision'
import type { AgentTask, AgentTaskListResponse } from '@/types/agentTasks'

function toQueryString(params: Record<string, string | number | undefined | null>): string {
  const searchParams = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.set(key, String(value))
    }
  })
  const queryString = searchParams.toString()
  return queryString ? `?${queryString}` : ''
}

export function fetchTradeDecisionHealth(): Promise<TradeDecisionHealth> {
  return request<TradeDecisionHealth>('/api/agent/trade-decision/health')
}

export function fetchTradeDecisionHoldings(): Promise<TradeDecisionHoldingsResponse> {
  return request<TradeDecisionHoldingsResponse>('/api/agent/trade-decision/holdings')
}

export function startTradeDecisionTask(payload: {
  symbol: string
  force_refresh?: boolean
}): Promise<AgentTask> {
  return request<AgentTask>('/api/agent/trade-decision/tasks', {
    method: 'POST',
    body: JSON.stringify({
      symbol: payload.symbol,
      force_refresh: Boolean(payload.force_refresh),
    }),
  })
}

export function startHoldingDecisionTask(payload: {
  symbol: string
  question?: string
  force_refresh?: boolean
}): Promise<AgentTask> {
  return request<AgentTask>(`/api/agent/trade-decision/holding/${encodeURIComponent(payload.symbol)}/tasks`, {
    method: 'POST',
    body: JSON.stringify({
      question: payload.question || undefined,
      force_refresh: Boolean(payload.force_refresh),
    }),
  })
}

export function analyzeEntryDecision(payload: {
  symbol: string
  question?: string
  force_refresh?: boolean
}): Promise<TradeDecisionResult> {
  return request<TradeDecisionResult>('/api/agent/trade-decision/entry/analyze', {
    method: 'POST',
    body: JSON.stringify({
      symbol: payload.symbol,
      question: payload.question || undefined,
      force_refresh: Boolean(payload.force_refresh),
    }),
  })
}

export function startEntryDecisionTask(payload: {
  symbol: string
  question?: string
  force_refresh?: boolean
}): Promise<AgentTask> {
  return request<AgentTask>('/api/agent/trade-decision/entry/tasks', {
    method: 'POST',
    body: JSON.stringify({
      symbol: payload.symbol,
      question: payload.question || undefined,
      force_refresh: Boolean(payload.force_refresh),
    }),
  })
}

export async function fetchTradeDecisionTasks(limit = 20): Promise<AgentTask[]> {
  const response = await request<AgentTaskListResponse>(`/api/agent/trade-decision/tasks${toQueryString({ limit })}`)
  return response.items
}

export function fetchTradeDecisionTask(taskId: string): Promise<AgentTask> {
  return request<AgentTask>(`/api/agent/trade-decision/tasks/${encodeURIComponent(taskId)}`)
}

export async function fetchRecentTradeDecisions(params: { limit?: number; decision_type?: string } = {}): Promise<TradeDecisionResult[]> {
  const response = await request<TradeDecisionListResponse>(`/api/agent/trade-decision/recent${toQueryString(params)}`)
  return response.items
}

export function fetchTradeDecisionQualitySummary(params: {
  limit?: number
  days?: number
} = {}): Promise<TradeDecisionQualitySummary> {
  return request<TradeDecisionQualitySummary>(
    `/api/agent/trade-decision/quality/summary${toQueryString(params)}`,
  )
}

export function fetchTradeDecisionOutcomeSummary(params: {
  limit?: number
  days?: number
  symbol?: string
  decision_type?: string
  horizons?: string
  action_group?: string
  outcome_label?: string
} = {}): Promise<TradeDecisionOutcomeSummary> {
  return request<TradeDecisionOutcomeSummary>(
    `/api/agent/trade-decision/outcome/summary${toQueryString(params)}`,
  )
}

export function fetchTradeDecisionOutcomeList(params: {
  limit?: number
  days?: number
  symbol?: string
  decision_type?: string
  horizons?: string
  action_group?: string
  outcome_label?: string
} = {}): Promise<TradeDecisionOutcomeListResponse> {
  return request<TradeDecisionOutcomeListResponse>(
    `/api/agent/trade-decision/outcome/list${toQueryString(params)}`,
  )
}

export async function fetchSymbolTradeDecisions(symbol: string, limit = 10): Promise<TradeDecisionResult[]> {
  const response = await request<TradeDecisionListResponse>(
    `/api/agent/trade-decision/symbol/${encodeURIComponent(symbol)}${toQueryString({ limit })}`,
  )
  return response.items
}

export function fetchTradeDecisionDetail(decisionId: string): Promise<TradeDecisionResult> {
  return request<TradeDecisionResult>(`/api/agent/trade-decision/${encodeURIComponent(decisionId)}`)
}
