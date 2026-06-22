// Typed wrappers around the M12 back-office endpoints (the platform-operator
// super-admin contract). Everything goes through `api` (src/lib/apiClient.ts),
// which sends the session cookie same-origin with `credentials: 'include'`.
//
// These are the ONLY routes that intentionally cross the tenant wall. The server
// enforces admin identity (session + email ∈ ADMIN_EMAILS) on every call — a
// logged-in non-admin gets 403. We never send a business_id for *scoping*; the
// admin picks a specific business and we pass that id as a path param.

import { api } from './apiClient'
import type {
  AdminOverview,
  BusinessDetail,
  BusinessesResponse,
  PlansResponse,
  SetSubscriptionResponse,
  SubscriptionStatus,
  UsageResponse,
} from '../admin/types'

// Build a query string from defined, non-empty params (omits undefined/'').
function qs(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const str = search.toString()
  return str ? `?${str}` : ''
}

/** GET /api/admin/overview — platform-wide KPI counts. */
export function getOverview(): Promise<AdminOverview> {
  return api.get<AdminOverview>('/api/admin/overview')
}

/**
 * GET /api/admin/businesses — the all-businesses table (search + pagination).
 * `search` ILIKEs name/email server-side. limit defaults to 50 (1..200),
 * offset to 0.
 */
export function listBusinesses(opts: {
  search?: string
  limit?: number
  offset?: number
} = {}): Promise<BusinessesResponse> {
  return api.get<BusinessesResponse>(
    `/api/admin/businesses${qs({
      search: opts.search,
      limit: opts.limit,
      offset: opts.offset,
    })}`,
  )
}

/** GET /api/admin/businesses/{id} — one business profile. 404 if unknown. */
export function getBusiness(id: string): Promise<BusinessDetail> {
  return api.get<BusinessDetail>(`/api/admin/businesses/${encodeURIComponent(id)}`)
}

/**
 * GET /api/admin/businesses/{id}/usage — daily usage series for charts.
 * `from`/`to` are YYYY-MM-DD; the range is guarded ≤ ~92 days server-side
 * (a bad date → 422). Absent metrics default to 0 for charting.
 */
export function getUsage(
  id: string,
  from: string,
  to: string,
): Promise<UsageResponse> {
  return api.get<UsageResponse>(
    `/api/admin/businesses/${encodeURIComponent(id)}/usage${qs({ from, to })}`,
  )
}

/** GET /api/admin/plans — the plan catalog (for the subscription dropdown). */
export function getPlans(): Promise<PlansResponse> {
  return api.get<PlansResponse>('/api/admin/plans')
}

/**
 * PATCH /api/admin/businesses/{id}/subscription — set a business's plan +
 * status. Suspending/cancelling flips `is_active` false (the bot goes silent);
 * `active` flips it back true. Errors: bad status/plan → 422; unknown → 404.
 */
export function setSubscription(
  id: string,
  planCode: string,
  status: SubscriptionStatus,
): Promise<SetSubscriptionResponse> {
  return api.patch<SetSubscriptionResponse>(
    `/api/admin/businesses/${encodeURIComponent(id)}/subscription`,
    { plan_code: planCode, status },
  )
}
