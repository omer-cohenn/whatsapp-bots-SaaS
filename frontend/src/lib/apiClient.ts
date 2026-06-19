// Tiny same-origin fetch wrapper for the FastAPI backend.
//
// The browser always talks same-origin (the Vite dev proxy forwards /api, /auth
// to the backend), so the HttpOnly session cookie stays same-origin and no
// backend URL or secret ever ships to the client. `credentials: 'include'` makes
// the browser attach that cookie automatically — the frontend never reads it.
//
// A 401 is special: it means "not logged in". We throw a typed error so the
// AuthContext can decide to redirect to /login, rather than treating it as a
// generic failure.

const TIMEOUT_MS = 8000

/** Thrown for any non-2xx response. `status === 401` means "not authenticated". */
export class ApiError extends Error {
  status: number
  body: unknown

  constructor(status: number, message: string, body: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }

  get isUnauthorized(): boolean {
    return this.status === 401
  }
}

// Parse the body tolerantly: try JSON, fall back to null (same idea as health.js).
async function parseBody(res: Response): Promise<unknown> {
  try {
    return await res.json()
  } catch {
    return null
  }
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const res = await fetch(path, {
      ...init,
      credentials: 'include', // send the session cookie same-origin
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
      signal: controller.signal,
    })

    if (!res.ok) {
      const body = await parseBody(res)
      throw new ApiError(res.status, `HTTP ${res.status}`, body)
    }

    // 204 No Content (e.g. logout) has no JSON body.
    if (res.status === 204) return undefined as T
    return (await parseBody(res)) as T
  } catch (err) {
    if (err instanceof ApiError) throw err
    const reason = (err as Error)?.name === 'AbortError' ? 'timeout' : 'unreachable'
    // Status 0 = network-level failure (couldn't even reach the server).
    throw new ApiError(0, reason, null)
  } finally {
    clearTimeout(timer)
  }
}

export const api = {
  get: <T>(path: string): Promise<T> => request<T>(path, { method: 'GET' }),
  post: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, {
      method: 'POST',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  put: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, {
      method: 'PUT',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body?: unknown): Promise<T> =>
    request<T>(path, {
      method: 'PATCH',
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  delete: <T>(path: string): Promise<T> => request<T>(path, { method: 'DELETE' }),
}
