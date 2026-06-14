export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  (typeof window !== 'undefined'
    ? window.location.port === '5173'
      ? `${window.location.protocol}//${window.location.hostname}:8000`
      : window.location.origin
    : 'http://localhost:8000')

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

function formatDetail(detail: unknown): string {
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === 'string') {
          return item
        }
        if (item && typeof item === 'object') {
          const message = 'msg' in item ? String(item.msg) : '请求参数非法'
          const location = Array.isArray((item as { loc?: unknown }).loc)
            ? (item as { loc: unknown[] }).loc.join('.')
            : ''
          return location ? `${location}: ${message}` : message
        }
        return String(item)
      })
      .join('；')
  }

  if (typeof detail === 'string') {
    return detail
  }

  if (detail && typeof detail === 'object') {
    if ('message' in detail) {
      return String((detail as { message: unknown }).message)
    }
    if ('error_code' in detail) {
      return String((detail as { error_code: unknown }).error_code)
    }
  }

  return '请求失败'
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers ?? undefined)
  const isFormData = typeof FormData !== 'undefined' && init.body instanceof FormData
  const isBlob = typeof Blob !== 'undefined' && init.body instanceof Blob
  if (init.body !== undefined && !isFormData && !isBlob && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: 'include',
    ...init,
    headers,
  })
  const contentType = response.headers.get('content-type') ?? ''
  const isJson = contentType.includes('application/json')
  const payload = isJson ? await response.json() : await response.text()

  if (!response.ok) {
    const isHtml = typeof payload === 'string' && payload.trimStart().startsWith('<')
    if (isHtml) {
      throw new ApiError('服务网关返回异常，请稍后重试或刷新查看结果。', response.status)
    }
    const detail =
      typeof payload === 'object' && payload !== null && 'detail' in payload
        ? formatDetail(payload.detail)
        : typeof payload === 'string'
          ? payload
          : `Request failed with status ${response.status}`
    if ((response.status === 502 || response.status === 503 || response.status === 504) && detail === `Request failed with status ${response.status}`) {
      throw new ApiError('请求超时，后端可能仍在继续执行，请稍后刷新或等待运行状态更新。', response.status)
    }
    throw new ApiError(detail, response.status)
  }

  return payload as T
}
