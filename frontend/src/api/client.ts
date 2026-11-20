const configuredBase = import.meta.env.VITE_API_BASE_URL || '/api/bff'
const API_BASE = configuredBase.startsWith('/') && !configuredBase.startsWith('//')
  ? configuredBase.replace(/\/$/, '')
  : '/api/bff'
let csrfToken: string | undefined

export function setCsrfToken(value?: string) { csrfToken = value }

export class ApiError extends Error {
  constructor(message: string, public status?: number, public executionId?: number) { super(message); this.name = 'ApiError' }
}

export class ApiClient {
  async get<T>(path: string): Promise<T> {
    return this.request<T>(path, { method: 'GET' })
  }

  async post<T>(path: string, body: unknown): Promise<T> {
    return this.request<T>(path, { method: 'POST', body: JSON.stringify(body) })
  }

  private async request<T>(path: string, init: RequestInit): Promise<T> {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 60_000)
    try {
      const headers = new Headers(init.headers)
      headers.set('Content-Type', 'application/json')
      if (init.method !== 'GET') {
        if (!csrfToken) throw new ApiError('Your session needs to be refreshed before this action.')
        headers.set('X-CSRF-Token', csrfToken)
      }
      const response = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers,
        signal: controller.signal,
        credentials: 'same-origin',
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { detail?: unknown } | null
        const detail = typeof payload?.detail === 'string'
          ? payload.detail
          : payload?.detail && typeof payload.detail === 'object' && 'message' in payload.detail && typeof payload.detail.message === 'string'
            ? payload.detail.message
            : ''
        const executionId = payload?.detail && typeof payload.detail === 'object' && 'execution_id' in payload.detail && typeof payload.detail.execution_id === 'number'
          ? payload.detail.execution_id
          : undefined
        const message = response.status === 401 || response.status === 403
          ? 'Your access has expired or does not include this operation. Sign in again or contact an administrator.'
          : detail || `Request failed (${response.status}).`
        throw new ApiError(message, response.status, executionId)
      }
      if (response.status === 204) return undefined as T
      return await response.json() as T
    } catch (error) {
      if (error instanceof ApiError) throw error
      if (error instanceof DOMException && error.name === 'AbortError') throw new ApiError('The request timed out. Please try again.')
      throw new ApiError('The service could not be reached. Check your connection and try again.')
    } finally {
      window.clearTimeout(timeout)
    }
  }
}

export const api = new ApiClient()
