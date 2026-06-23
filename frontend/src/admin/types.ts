// TypeScript mirror of the frozen M12 back-office API contract
// (backend/app/api/admin.py). Every /api/admin/* route sits behind the
// `current_admin` gate (session + email ∈ ADMIN_EMAILS) — 401 without a
// session, 403 for a logged-in non-admin. These are the only routes that cross
// the tenant wall, and they do so server-side: the client NEVER sends a
// business_id for scoping; it only passes one as a path param to read/act on a
// specific business the admin chose. The SERVER is the authoritative source.

// --- subscription enums ------------------------------------------------------

/** A business subscription status. `suspended`/`cancelled` silence the bot. */
export type SubscriptionStatus = 'active' | 'suspended' | 'cancelled'

/** Usage metric names tracked per day (v1). Absent metrics chart as 0. */
export type UsageMetric = 'msg_in' | 'msg_out' | 'lead' | 'booking' | 'login'

// --- GET /api/admin/overview -------------------------------------------------

/**
 * Platform-wide KPI counts. All ints, except the M13 LTV fields which are
 * float|null (null when there's nothing to estimate — e.g. no paying tenants).
 */
export type AdminOverview = {
  total_businesses: number
  active_count: number
  suspended_count: number
  cancelled_count: number
  new_7d: number
  total_leads: number
  msgs_today: number
  msgs_month: number
  // M13 additive — Lifetime-Value estimate (plan price × tenure). "הערכה".
  avg_ltv: number | null
  total_ltv: number | null
}

// --- GET /api/admin/businesses ----------------------------------------------

/** One row in the all-businesses table. */
export type BusinessRow = {
  business_id: string
  name: string | null
  owner_email: string | null
  created_at: string | null // ISO
  last_login_at: string | null // ISO
  plan_code: string
  status: SubscriptionStatus
  is_active: boolean
  leads_count: number
  msgs_30d: number
}

export type BusinessesResponse = {
  businesses: BusinessRow[]
  limit: number
  offset: number
}

// --- GET /api/admin/businesses/{id} -----------------------------------------

/** A single business profile (the row fields + WhatsApp status + type). */
export type BusinessDetail = {
  business_id: string
  name: string | null
  business_type: string | null
  owner_email: string | null
  created_at: string | null // ISO
  last_login_at: string | null // ISO
  plan_code: string
  status: SubscriptionStatus
  is_active: boolean
  wa_status: string | null
  leads_count: number
  msgs_30d: number
  // M13 additive — LTV estimate, successful AI calls, and CRM snapshot.
  ltv_estimate: number | null
  ai_calls: number | null
  crm: BusinessCrmSummary | null
}

/** The CRM snapshot embedded in a business detail (M13). */
export type BusinessCrmSummary = {
  stage: CrmStage
  last_contacted_at: string | null // ISO
  next_followup_at: string | null // ISO
}

// --- GET /api/admin/businesses/{id}/usage -----------------------------------

/** One day of usage: a metric→count map (absent metrics default to 0). */
export type UsageDay = {
  day: string // ISO date (YYYY-MM-DD)
  metrics: Partial<Record<UsageMetric, number>>
}

export type UsageResponse = {
  business_id: string
  /** Which metric names actually appear in this window. */
  metrics_present: string[]
  series: UsageDay[]
}

// --- GET /api/admin/plans ----------------------------------------------------

export type Plan = {
  code: string
  name: string | null
  price: number
  sort_order: number
  limits: Record<string, unknown>
}

export type PlansResponse = {
  plans: Plan[]
}

// --- PATCH /api/admin/businesses/{id}/subscription --------------------------

export type SetSubscriptionResponse = {
  business_id: string
  plan_code: string
  status: SubscriptionStatus
  is_active: boolean
}

// === M13: back-office analytics ============================================
// All under /api/admin/analytics/*, same current_admin gate (401/403).

/** Time window for the analytics filters. `all` = since the start of time. */
export type AnalyticsPeriod = 'week' | 'month' | 'all'

/**
 * GET /api/admin/analytics/leads-by-type — derived lead counts split three
 * ways: bookings (פגישה), plain leads (ליד) and handoff requests (נציג).
 */
export type LeadsByType = {
  booking: number
  lead: number
  handoff: number
}

/**
 * GET /api/admin/analytics/messages — total messages per business, the basis
 * for billing. Sorted by `total` DESC server-side.
 */
export type MessagesByBusinessRow = {
  business_id: string
  name: string | null
  plan_code: string
  msg_in: number
  msg_out: number
  total: number
}

export type MessagesByBusinessResponse = {
  businesses: MessagesByBusinessRow[]
}

/** One day in the AI-ops series — successful Gemini calls that day. */
export type AiOpsPoint = {
  day: string // ISO date (YYYY-MM-DD)
  count: number
}

export type AiOpsResponse = {
  series: AiOpsPoint[]
}

/**
 * GET /api/admin/analytics/by-plan — one metric, split per plan code. `metric`
 * is required server-side (no default); `value` is the metric total per plan.
 */
export type ByPlanMetric =
  | 'msg_in'
  | 'msg_out'
  | 'lead'
  | 'booking'
  | 'login'
  | 'ai_call'

export type ByPlanRow = {
  plan_code: string
  value: number
}

export type ByPlanResponse = {
  metric: ByPlanMetric
  period: AnalyticsPeriod
  rows: ByPlanRow[]
}

/**
 * GET /api/admin/analytics/trends — the daily platform snapshot series
 * (accrues forward; can't be back-filled). MRR is a float; the rest are ints.
 */
export type TrendPoint = {
  day: string // ISO date (YYYY-MM-DD)
  total_businesses: number
  active_count: number
  paid_count: number
  mrr: number
  churn_count: number
}

export type TrendsResponse = {
  series: TrendPoint[]
}

// === M13: platform sales CRM ===============================================
// All under /api/admin/crm + /api/admin/businesses/{id}/crm. admin-only.

/** A sales-pipeline stage for a business (a customer of the SaaS). */
export type CrmStage = 'new' | 'contacted' | 'warming' | 'won' | 'lost'

/** One card on the pipeline board. */
export type CrmBusiness = {
  business_id: string
  name: string | null
  plan_code: string
  stage: CrmStage
  last_contacted_at: string | null // ISO
  next_followup_at: string | null // ISO
  note_count: number
}

export type CrmResponse = {
  businesses: CrmBusiness[]
}

/** PATCH /api/admin/businesses/{id}/crm response. */
export type SetCrmStageResponse = {
  business_id: string
  stage: CrmStage
  next_followup_at: string | null // ISO
}

/** POST /api/admin/businesses/{id}/crm/notes response (201). */
export type AddCrmNoteResponse = {
  note_id: string
}

/** One note in a business's CRM activity log. */
export type CrmNote = {
  id: string
  admin_email: string | null
  note: string
  created_at: string | null // ISO
}

export type CrmNotesResponse = {
  notes: CrmNote[]
}
