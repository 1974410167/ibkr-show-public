import { request } from './http'
import type {
  GlobalInvestmentPolicy,
  GlobalInvestmentPolicyPayload,
  InvestmentPolicySeedDefaultsResponse,
  SymbolInvestmentPolicy,
  SymbolInvestmentPolicyListResponse,
  SymbolInvestmentPolicyPayload,
} from '@/types/investmentPolicy'

export function fetchGlobalInvestmentPolicy(): Promise<GlobalInvestmentPolicy> {
  return request<GlobalInvestmentPolicy>('/api/investment-policy/global')
}

export function updateGlobalInvestmentPolicy(payload: GlobalInvestmentPolicyPayload): Promise<GlobalInvestmentPolicy> {
  return request<GlobalInvestmentPolicy>('/api/investment-policy/global', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function fetchSymbolInvestmentPolicies(includeDisabled = true): Promise<SymbolInvestmentPolicy[]> {
  const response = await request<SymbolInvestmentPolicyListResponse>(`/api/investment-policy/symbols?include_disabled=${includeDisabled ? 'true' : 'false'}`)
  return response.items
}

export function updateSymbolInvestmentPolicy(symbol: string, payload: SymbolInvestmentPolicyPayload): Promise<SymbolInvestmentPolicy> {
  return request<SymbolInvestmentPolicy>(`/api/investment-policy/symbols/${encodeURIComponent(symbol)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function disableSymbolInvestmentPolicy(symbol: string): Promise<SymbolInvestmentPolicy> {
  return request<SymbolInvestmentPolicy>(`/api/investment-policy/symbols/${encodeURIComponent(symbol)}/disable`, {
    method: 'PATCH',
  })
}

export function seedDefaultInvestmentPolicies(force = false): Promise<InvestmentPolicySeedDefaultsResponse> {
  return request<InvestmentPolicySeedDefaultsResponse>(`/api/investment-policy/seed-defaults?force=${force ? 'true' : 'false'}`, {
    method: 'POST',
  })
}
