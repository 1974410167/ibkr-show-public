import { request } from '@/api/http'
import type {
  SymbolAiAdviceResponse,
  SymbolComparisonResponse,
  SymbolFinancialsResponse,
} from '@/types/symbolAnalysis'

export function fetchSymbolFinancials(symbol: string, periods = 8): Promise<SymbolFinancialsResponse> {
  const query = new URLSearchParams({ periods: String(periods), report: 'qf' })
  return request<SymbolFinancialsResponse>(`/api/symbol-analysis/${encodeURIComponent(symbol)}/financials?${query.toString()}`)
}

export function compareSymbols(left: string, right: string, periods = 8): Promise<SymbolComparisonResponse> {
  const query = new URLSearchParams({
    left,
    right,
    periods: String(periods),
    report: 'qf',
  })
  return request<SymbolComparisonResponse>(`/api/symbol-analysis/compare?${query.toString()}`)
}

export function generateSymbolAiAdvice(payload: {
  left_symbol: string
  right_symbol: string
  question?: string
  comparison?: SymbolComparisonResponse
}): Promise<SymbolAiAdviceResponse> {
  return request<SymbolAiAdviceResponse>('/api/symbol-analysis/compare/ai-advice', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}
