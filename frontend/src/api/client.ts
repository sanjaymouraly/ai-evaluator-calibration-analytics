// Minimal typed API client. Uses relative /api URLs so the Vite dev
// server (or any reverse proxy) forwards them to the backend — the
// browser never needs to know the backend's host.

export class ApiError extends Error {
  status: number
  details: unknown

  constructor(message: string, status: number, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}

const TOKEN_KEY = 'evalplatform.token'
const REFRESH_KEY = 'evalplatform.refresh'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setTokens(access: string, refresh: string): void {
  localStorage.setItem(TOKEN_KEY, access)
  localStorage.setItem(REFRESH_KEY, refresh)
}

export function clearTokens(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

async function request<T>(path: string, options: RequestInit = {}, retry = true): Promise<T> {
  const headers = new Headers(options.headers)
  headers.set('Accept', 'application/json')
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const response = await fetch(path, { ...options, headers })

  if (response.status === 401 && retry && token) {
    const refreshed = await tryRefresh()
    if (refreshed) return request<T>(path, options, false)
    clearTokens()
    window.location.assign('/login')
  }

  if (!response.ok) {
    let message = `Request failed (${response.status})`
    let details: unknown
    try {
      const body = await response.json()
      details = body
      if (typeof body?.detail === 'string') message = body.detail
      else if (Array.isArray(body?.detail)) {
        message = body.detail
          .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg}`)
          .join('; ')
      } else if (body?.detail) message = JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body; keep generic message */
    }
    throw new ApiError(message, response.status, details)
  }

  if (response.status === 204) return undefined as T
  const text = await response.text()
  if (!text) return undefined as T
  const contentType = response.headers.get('content-type') ?? ''
  return (contentType.includes('application/json') ? JSON.parse(text) : text) as T
}

async function tryRefresh(): Promise<boolean> {
  const refresh = localStorage.getItem(REFRESH_KEY)
  if (!refresh) return false
  try {
    const response = await fetch(`/api/auth/refresh?refresh_token=${encodeURIComponent(refresh)}`, {
      method: 'POST',
    })
    if (!response.ok) return false
    const body = await response.json()
    setTokens(body.access_token, body.refresh_token)
    return true
  } catch {
    return false
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body === undefined ? undefined : JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  downloadUrl: (path: string) => path,
}

export function buildQuery(params: Record<string, unknown>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) value.forEach((v) => search.append(key, String(v)))
    else search.set(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}
