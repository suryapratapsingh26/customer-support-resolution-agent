import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiClient, ApiError, setCsrfToken } from './client'

afterEach(() => { vi.unstubAllGlobals(); setCsrfToken(undefined) })

describe('same-origin BFF client', () => {
  it('sends cookies on same-origin API requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(new ApiClient().get('/customers')).resolves.toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledWith('/api/bff/customers', expect.objectContaining({ credentials: 'same-origin' }))
  })

  it('attaches the CSRF token to state-changing requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    setCsrfToken('csrf-only-not-an-auth-credential')
    await new ApiClient().post('/auth/logout', {})
    expect(fetchMock.mock.calls[0][1].headers.get('X-CSRF-Token')).toBe('csrf-only-not-an-auth-credential')
  })

  it('sanitizes authentication failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'secret internal detail' }), { status: 401 })))
    await expect(new ApiClient().get('/private')).rejects.toThrow('Your access has expired')
  })

  it('preserves only the safe execution identifier from failed agent responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: { message: 'Agent execution failed.', execution_id: 27, provider_secret: 'hidden' } }), { status: 503 })))
    try {
      await new ApiClient().get('/agent')
      throw new Error('expected request failure')
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError)
      expect(error).toMatchObject({ message: 'Agent execution failed.', executionId: 27 })
      expect(JSON.stringify(error)).not.toContain('hidden')
    }
  })
})
