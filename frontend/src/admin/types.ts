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

/** Platform-wide KPI counts. All ints. */
export type AdminOverview = {
  total_businesses: number
  active_count: number
  suspended_count: number
  cancelled_count: number
  new_7d: number
  total_leads: number
  msgs_today: number
  msgs_month: number
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
