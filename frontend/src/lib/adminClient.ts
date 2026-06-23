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
  AddCrmNoteResponse,
  AdminOverview,
  AiOpsResponse,
  AnalyticsPeriod,
  ByPlanMetric,
  ByPlanResponse,
  BusinessDetail,
  BusinessesResponse,
  CrmNotesResponse,
  CrmResponse,
  CrmStage,
  DeleteBusinessResponse,
  LeadsByType,
  MessagesByBusinessResponse,
  PlansResponse,
  SetCrmStageResponse,
  SetSubscriptionResponse,
  SubscriptionStatus,
  TrendsResponse,
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

// === M13: analytics reads ===================================================

/**
 * GET /api/admin/analytics/leads-by-type — booking/lead/handoff counts.
 * `period` defaults to month server-side; `plan` (a plan code) or 'all'.
 */
export function getLeadsByType(
  opts: { period?: AnalyticsPeriod; plan?: string } = {},
): Promise<LeadsByType> {
  return api.get<LeadsByType>(
    `/api/admin/analytics/leads-by-type${qs({
      period: opts.period,
      plan: opts.plan,
    })}`,
  )
}

/**
 * GET /api/admin/analytics/messages — total messages per business (the billing
 * basis), sorted by total DESC. `period` defaults to month server-side.
 */
export function getMessagesByBusiness(
  period?: AnalyticsPeriod,
): Promise<MessagesByBusinessResponse> {
  return api.get<MessagesByBusinessResponse>(
    `/api/admin/analytics/messages${qs({ period })}`,
  )
}

/**
 * GET /api/admin/analytics/ai-ops — successful Gemini calls per day. `from`/`to`
 * are YYYY-MM-DD and optional (the server picks a sensible default window).
 */
export function getAiOps(from?: string, to?: string): Promise<AiOpsResponse> {
  return api.get<AiOpsResponse>(`/api/admin/analytics/ai-ops${qs({ from, to })}`)
}

/**
 * GET /api/admin/analytics/by-plan — one metric split per plan. `metric` is
 * required; `period` defaults to month server-side.
 */
export function getByPlan(
  metric: ByPlanMetric,
  period?: AnalyticsPeriod,
): Promise<ByPlanResponse> {
  return api.get<ByPlanResponse>(
    `/api/admin/analytics/by-plan${qs({ metric, period })}`,
  )
}

/**
 * GET /api/admin/analytics/trends — the daily snapshot series (MRR / active /
 * paid / churn). Accrues forward from M13; no back-fill. `from`/`to` optional.
 */
export function getTrends(from?: string, to?: string): Promise<TrendsResponse> {
  return api.get<TrendsResponse>(`/api/admin/analytics/trends${qs({ from, to })}`)
}

// === M13: sales CRM =========================================================

/** GET /api/admin/crm — the whole pipeline board (businesses by stage). */
export function getCrm(): Promise<CrmResponse> {
  return api.get<CrmResponse>('/api/admin/crm')
}

/**
 * PATCH /api/admin/businesses/{id}/crm — move a business to a stage and/or set
 * its next-follow-up date. Bad stage → 422, unknown business → 404.
 */
export function setCrmStage(
  id: string,
  stage: CrmStage,
  nextFollowup?: string | null,
): Promise<SetCrmStageResponse> {
  const body: { stage: CrmStage; next_followup?: string | null } = { stage }
  // Only send next_followup when the caller explicitly passed one (incl. null
  // to clear it); omitting it leaves the existing date untouched.
  if (nextFollowup !== undefined) body.next_followup = nextFollowup
  return api.patch<SetCrmStageResponse>(
    `/api/admin/businesses/${encodeURIComponent(id)}/crm`,
    body,
  )
}

/**
 * POST /api/admin/businesses/{id}/crm/notes — append a note (1..2000 chars).
 * Blank → 422. Returns the new note's id (201).
 */
export function addCrmNote(id: string, note: string): Promise<AddCrmNoteResponse> {
  return api.post<AddCrmNoteResponse>(
    `/api/admin/businesses/${encodeURIComponent(id)}/crm/notes`,
    { note },
  )
}

/** GET /api/admin/businesses/{id}/crm/notes — the activity log (newest first). */
export function getCrmNotes(id: string): Promise<CrmNotesResponse> {
  return api.get<CrmNotesResponse>(
    `/api/admin/businesses/${encodeURIComponent(id)}/crm/notes`,
  )
}

/**
 * DELETE /api/admin/businesses/{id} — PERMANENTLY delete a business and ALL its
 * data (cascade). Irreversible. The server refuses to delete the admin's OWN
 * session business (→ 400); unknown id → 404.
 */
export function deleteBusiness(id: string): Promise<DeleteBusinessResponse> {
  return api.delete<DeleteBusinessResponse>(
    `/api/admin/businesses/${encodeURIComponent(id)}`,
  )
}
