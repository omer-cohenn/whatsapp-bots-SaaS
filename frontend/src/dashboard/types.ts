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

/** Lead status filter. `open` = new + in_progress; `all` = everything.
 * `deal`/`closed` match the stored lead.status values directly. */
export type LeadStatusFilter =
  | 'all'
  | 'new'
  | 'in_progress'
  | 'abandoned'
  | 'open'
  | 'deal'
  | 'closed'

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
  /** Linked live conversation id (stripped of the "conv:{business_id}:" prefix),
   * or null when no/foreign conversation ref. Used to open the in-app chat. */
  conversation_id: string | null
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

/**
 * A live conversation's handling mode. `waiting` means the customer asked for a
 * human and the bot has stepped aside, but no one has taken it over yet.
 */
export type ConversationStatus = 'bot' | 'waiting' | 'human' | 'closed'

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

// --- 3b) GET /api/conversations/{id} (+ /messages) ---------------------------

/**
 * One line of the transcript. `customer` is the WhatsApp sender, `bot` is an
 * automated reply, `owner` is a manual reply the business owner queued.
 * `at` is an ISO-8601 UTC timestamp (null if the backend has none).
 */
export type Message = {
  role: 'customer' | 'bot' | 'owner'
  body: string
  at: string | null
}

/** GET /api/conversations/{id} — the conversation with its full transcript. */
export type ConversationDetail = {
  conversation_id: string
  status: ConversationStatus
  lead: Lead | null
  /** Oldest → newest. */
  messages: Message[]
}

/** GET /api/conversations/{id}/messages — just the transcript (for polling). */
export type MessagesResponse = {
  conversation_id: string
  /** Oldest → newest. */
  messages: Message[]
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
