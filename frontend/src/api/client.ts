import type { DashboardHost, RequestContext } from '../types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message: string, public status?: number, public executionId?: number) { super(message); this.name = 'ApiError' }
}

export class ApiClient {
  constructor(private readonly configuredHost?: DashboardHost) {}

  async get<T>(path: string, context: RequestContext): Promise<T> {
    return this.request<T>(path, { method: 'GET' }, context)
  }

  async post<T>(path: string, body: unknown, context: RequestContext): Promise<T> {
    return this.request<T>(path, { method: 'POST', body: JSON.stringify(body) }, context)
  }

  private async request<T>(path: string, init: RequestInit, context: RequestContext): Promise<T> {
    const host = this.configuredHost ?? window.supportDashboardHost
    if (!host) {
      throw new ApiError('Secure dashboard identity integration is not connected. Ask your administrator to configure the host authentication bridge.')
    }
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 60_000)
    try {
      const response = await host.request(`${API_BASE}${path}`, {
        ...init,
        headers: { 'Content-Type': 'application/json', ...init.headers },
        signal: controller.signal,
        credentials: 'same-origin',
      }, context)
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
