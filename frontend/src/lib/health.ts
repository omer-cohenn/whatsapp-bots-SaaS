// Talks to the backend health endpoint THROUGH the Vite dev proxy (same-origin
// "/healthz" -> http://backend:8000/healthz). We never call the backend host
// directly, so no backend URL or secret is ever exposed to the browser.

const HEALTH_PATH = '/healthz'
const TIMEOUT_MS = 4000

const TRUTHY = ['ok', 'up', 'healthy', 'true', 'connected']

export type HealthResult = {
  ok: boolean
  status: number | null
  postgres: boolean | null
  redis: boolean | null
  error: string | null
  raw: unknown
}

// Pull a boolean-ish sub-check out of whatever shape the backend returns.
// The contract only guarantees "200 + Postgres+Redis reachable", not an exact
// JSON shape, so we look in a few sensible places and stay tolerant.
function readCheck(body: unknown, keys: string[]): boolean | null {
  if (!body || typeof body !== 'object') return null
  const record = body as Record<string, unknown>
  const nested = record.checks
  const bag: Record<string, unknown> =
    nested && typeof nested === 'object' ? (nested as Record<string, unknown>) : record

  for (const key of keys) {
    if (!(key in bag)) continue
    const v = bag[key]
    if (typeof v === 'boolean') return v
    if (typeof v === 'string') return TRUTHY.includes(v.toLowerCase())
    if (v && typeof v === 'object') {
      const inner = v as Record<string, unknown>
      const s = inner.status ?? inner.ok ?? inner.healthy
      if (typeof s === 'boolean') return s
      if (typeof s === 'string') return TRUTHY.includes(s.toLowerCase())
    }
  }
  return null // unknown — caller renders this as "unknown", not pass/fail
}

/** Fetch backend health. Tolerant of body shape; HTTP status drives up/down. */
export async function fetchHealth(): Promise<HealthResult> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const res = await fetch(HEALTH_PATH, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })

    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      body = null
    }

    return {
      ok: res.ok,
      status: res.status,
      postgres: readCheck(body, ['postgres', 'db', 'database']),
      redis: readCheck(body, ['redis', 'cache']),
      error: res.ok ? null : `HTTP ${res.status}`,
      raw: body,
    }
  } catch (err) {
    const error = (err as Error)?.name === 'AbortError' ? 'timeout' : 'unreachable'
    return { ok: false, status: null, postgres: null, redis: null, error, raw: null }
  } finally {
    clearTimeout(timer)
  }
}
