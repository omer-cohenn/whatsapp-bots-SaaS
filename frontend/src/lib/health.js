// Talks to the backend health endpoint THROUGH the Vite dev proxy (same-origin
// "/healthz" -> http://backend:8000/healthz). We never call the backend host
// directly, so no backend URL or secret is ever exposed to the browser.

const HEALTH_PATH = '/healthz'
const TIMEOUT_MS = 4000

// Pull a boolean-ish sub-check out of whatever shape the backend returns.
// The contract only guarantees "200 + Postgres+Redis reachable", not an exact
// JSON shape, so we look in a few sensible places and stay tolerant.
function readCheck(body, keys) {
  if (!body || typeof body !== 'object') return null
  const bag = body.checks && typeof body.checks === 'object' ? body.checks : body
  for (const key of keys) {
    if (!(key in bag)) continue
    const v = bag[key]
    if (typeof v === 'boolean') return v
    if (typeof v === 'string') return ['ok', 'up', 'healthy', 'true', 'connected'].includes(v.toLowerCase())
    if (v && typeof v === 'object') {
      const s = v.status ?? v.ok ?? v.healthy
      if (typeof s === 'boolean') return s
      if (typeof s === 'string') return ['ok', 'up', 'healthy', 'true', 'connected'].includes(s.toLowerCase())
    }
  }
  return null // unknown — caller renders this as "unknown", not pass/fail
}

/**
 * Fetch backend health.
 * @returns {Promise<{ok: boolean, status: number|null, postgres: boolean|null, redis: boolean|null, error: string|null, raw: any}>}
 */
export async function fetchHealth() {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const res = await fetch(HEALTH_PATH, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })

    let body = null
    try {
      body = await res.json()
    } catch {
      // Backend answered but not with JSON — that's fine; HTTP status still tells us up/down.
      body = null
    }

    return {
      ok: res.ok, // 2xx => backend process is reachable and healthy
      status: res.status,
      postgres: readCheck(body, ['postgres', 'db', 'database']),
      redis: readCheck(body, ['redis', 'cache']),
      error: res.ok ? null : `HTTP ${res.status}`,
      raw: body,
    }
  } catch (err) {
    // Network error / timeout / proxy can't reach backend.
    const error = err?.name === 'AbortError' ? 'timeout' : 'unreachable'
    return { ok: false, status: null, postgres: null, redis: null, error, raw: null }
  } finally {
    clearTimeout(timer)
  }
}
