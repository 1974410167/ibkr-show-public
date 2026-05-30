const REDACTED_VALUE = '***'

const TOKEN_METRIC_KEYS = new Set([
  'prompt_tokens',
  'completion_tokens',
  'total_tokens',
  'cached_tokens',
  'reasoning_tokens',
  'token_count',
  'max_tokens',
  'input_tokens',
  'output_tokens',
  'tokens',
  'total_token_count',
  'prompt_token_count',
  'completion_token_count',
])

const EXACT_SENSITIVE_KEYS = new Set([
  'api_key',
  'apikey',
  'key',
  'token',
  'access_token',
  'refresh_token',
  'id_token',
  'auth_token',
  'bearer_token',
  'authorization',
  'cookie',
  'password',
  'passwd',
  'secret',
  'client_secret',
  'private_key',
  'session',
  'session_id',
  'reasoning',
  'thinking',
  'chain_of_thought',
])

export function isSensitiveJsonKey(key: string): boolean {
  const normalized = key.trim().toLowerCase()
  if (TOKEN_METRIC_KEYS.has(normalized)) {
    return false
  }
  if (EXACT_SENSITIVE_KEYS.has(normalized)) {
    return true
  }
  return (
    normalized.endsWith('_api_key') ||
    normalized.endsWith('_secret') ||
    normalized.endsWith('_password') ||
    normalized.endsWith('_private_key') ||
    normalized.includes('authorization') ||
    normalized.includes('cookie')
  )
}

export function sanitizeJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => sanitizeJsonValue(item))
  }
  if (value && typeof value === 'object') {
    const output: Record<string, unknown> = {}
    Object.entries(value as Record<string, unknown>).forEach(([key, item]) => {
      output[key] = isSensitiveJsonKey(key) ? REDACTED_VALUE : sanitizeJsonValue(item)
    })
    return output
  }
  return value
}
