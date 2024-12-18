import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, buildQuery, clearTokens, getToken, setTokens } from '../src/api/client'

describe('token storage', () => {
  afterEach(() => clearTokens())

  it('stores and clears auth tokens', () => {
    setTokens('access-1', 'refresh-1')
    expect(getToken()).toBe('access-1')
    clearTokens()
    expect(getToken()).toBeNull()
  })
})

describe('buildQuery', () => {
  it('omits empty values and arrays correctly', () => {
    const qs = buildQuery({ a: 1, b: '', c: null, d: ['x', 'y'], e: 0 })
    expect(qs).toBe('?a=1&d=x&d=y&e=0')
  })

  it('returns empty string when nothing to send', () => {
    expect(buildQuery({})).toBe('')
    expect(buildQuery({ a: undefined })).toBe('')
  })
})

describe('ApiError', () => {
  it('carries status and details', () => {
    const err = new ApiError('boom', 422, { field: 'scores' })
    expect(err.message).toBe('boom')
    expect(err.status).toBe(422)
    expect(err.details).toEqual({ field: 'scores' })
    expect(err.name).toBe('ApiError')
  })
})

describe('fetch wiring', () => {
  it('sends the bearer token and parses JSON', async () => {
    setTokens('tok-123', 'ref-123')
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const headers = init.headers as Headers
      expect(headers.get('Authorization')).toBe('Bearer tok-123')
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)

    const { api } = await import('../src/api/client')
    const res = await api.get<{ ok: boolean }>('/api/anything')
    expect(res).toEqual({ ok: true })
    expect(fetchMock).toHaveBeenCalledOnce()
    vi.unstubAllGlobals()
    clearTokens()
  })

  it('surfaces server error messages', async () => {
    clearTokens()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: 'Rating already submitted.' }), {
          status: 409,
          headers: { 'content-type': 'application/json' },
        }),
      ),
    )
    const { api } = await import('../src/api/client')
    await expect(api.get('/api/x')).rejects.toThrow('Rating already submitted.')
    vi.unstubAllGlobals()
  })
})
