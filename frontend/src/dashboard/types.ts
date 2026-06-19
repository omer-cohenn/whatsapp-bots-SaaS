// TypeScript mirror of the M7 backend contract (backend/app/api/dashboard.py +
// backend/app/models/dashboard.py). The SERVER is the authoritative source: it
// scopes everything by the session's business_id, decrypts PII for the owner,
// and validates all bodies. These types exist only for editor types + UX.
//
// All six endpoints are session-gated; the tenant (business_id) is NEVER sent
// from the client — it comes only from the cookie session.

// --- shared query enums ------------------------------------------------------

/** Time window for funnel + leads queries. */
export type Period = 'week' | 'month' | 'all'

/** Lead status filter. `open` = new + in_progress; `all` = everything. */
export type LeadStatusFilter = 'all' | 'new' | 'in_progress' | 'abandoned' | 'open'

/**
 * The concrete status a single lead can carry. `deal`/`closed` are set manually
 * by the owner from the lead card (PATCH /api/leads/{id}/status).
 */
export type LeadStatus = 'new' | 'in_progress' | 'abandoned' | 'deal' | 'closed'

// --- 1) GET /api/leads -------------------------------------------------------

export type Lead = {
  id: string
  lead_name: string
  contact_name: string | null
  phone: string | null
  /** Full decrypted collected answers (owner sees everything — no hiding). */
  answers: Record<string, string>
  status: LeadStatus
  last_step_index: number
  is_test: boolean
  started_at: string | null
  last_activity_at: string | null
  submitted_at: string | null
}

export type LeadsResponse = {
  leads: Lead[]
}

// --- 2) GET /api/dashboard ---------------------------------------------------

export type DashboardStats = {
  period: Period
  started: number
  completed: number
  abandoned: number
  total_leads: number
  /** Count of leads the owner manually marked as a closed deal (status="deal"). */
  orders: number
}

// --- 3) GET /api/conversations -----------------------------------------------

/** A live conversation's handling mode. */
export type ConversationStatus = 'bot' | 'human' | 'closed'

export type Conversation = {
  conversation_id: string
  status: ConversationStatus
  last_activity_at: string | null
  preview: string | null
  assigned_user_id: string | null
}

export type ConversationsResponse = {
  conversations: Conversation[]
}

// --- 4) POST /api/conversations/{id}/status ----------------------------------

export type SetStatusResponse = {
  conversation_id: string
  status: ConversationStatus
}

// --- 5) POST /api/conversations/{id}/reply -----------------------------------

export type ReplyResponse = {
  conversation_id: string
  queued: boolean
}

// --- 6) PUT /api/bot/publish -------------------------------------------------

export type PublishResponse = {
  is_published: boolean
}
