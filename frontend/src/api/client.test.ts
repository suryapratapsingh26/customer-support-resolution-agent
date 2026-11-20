import { describe, expect, it, vi } from 'vitest'
import { ApiClient, ApiError } from './client'
import type { DashboardHost } from '../types'

describe('API client', () => {
  it('routes requests through the host auth bridge with scope context', async () => {
    const request = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    const host: DashboardHost = { getAuthorizedCustomers: vi.fn(), request }
    const client = new ApiClient(host)
    await expect(client.get('/customers/7', { role: 'agent', customerId: 7 })).resolves.toEqual({ ok: true })
    expect(request).toHaveBeenCalledWith('/api/v1/customers/7', expect.objectContaining({ method: 'GET' }), { role: 'agent', customerId: 7 })
  })

  it('sanitizes authentication failures', async () => {
    const host: DashboardHost = { getAuthorizedCustomers: vi.fn(), request: vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'secret internal detail' }), { status: 401 })) }
    await expect(new ApiClient(host).get('/private', { role: 'reviewer' })).rejects.toThrow('Your access has expired')
  })

  it('preserves only the safe execution identifier from failed agent responses', async () => {
    const host: DashboardHost = { getAuthorizedCustomers: vi.fn(), request: vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { message: 'Agent execution failed.', execution_id: 27, provider_secret: 'hidden' } }), { status: 503 })) }
    try {
      await new ApiClient(host).get('/agent', { role: 'agent', customerId: 7 })
      throw new Error('expected request failure')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect(error).toMatchObject({ message: 'Agent execution failed.', executionId: 27 })
      expect(JSON.stringify(error)).not.toContain('hidden')
    }
  })

  it('fails closed when no trusted identity bridge is installed', async () => {
    await expect(new ApiClient(undefined).get('/private', { role: 'agent', customerId: 8 })).rejects.toBeInstanceOf(ApiError)
  })
})
