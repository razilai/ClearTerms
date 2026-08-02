// Fetch wrapper: attaches the Bearer token, normalizes backend errors
// ({detail: string}) into ApiError, and force-logs-out on 401 from
// authenticated endpoints.

import { clearAuth, getToken } from '../auth/storage'

export class ApiError extends Error {
  status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
  }
}

// The contract says stubbed features return 501, but today the stub routes
// raise NotImplementedError and app/api/errors.py only maps DomainError, so
// they surface as plain 500. Accept both; drop 500 once the backend maps 501.
export function isNotReady(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 501 || err.status === 500)
}

async function parseDetail(res: Response): Promise<string> {
  try {
    const data = await res.json()
    if (typeof data.detail === 'string') return data.detail
    // 422 validation errors carry a list of {loc, msg, type}.
    if (Array.isArray(data.detail)) {
      return data.detail.map((e: { msg: string }) => e.msg).join('; ')
    }
  } catch {
    // fall through
  }
  return res.statusText || `Request failed (${res.status})`
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers)
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  const res = await fetch(path, { ...options, headers })

  if (!res.ok) {
    // Expired/invalid token: drop credentials and send the user to /login.
    // Auth endpoints (401 = wrong password) handle their own errors inline.
    if (res.status === 401 && token && !path.startsWith('/auth/')) {
      clearAuth()
      window.location.assign('/login')
    }
    throw new ApiError(res.status, await parseDetail(res))
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export function requestJson<T>(path: string, method: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
