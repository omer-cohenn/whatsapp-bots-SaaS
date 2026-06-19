// Typed wrappers around the six M7 back-office endpoints (the dashboard /
// leads / conversations / publish contract).
//
// Everything goes through `api` (src/lib/apiClient.ts), which sends the session
// cookie same-origin with `credentials: 'include'`. The tenant (business_id) is
// derived entirely from that server session — we NEVER send it from the client.

import { api } from './apiClient'
import type {
  ConversationStatus,
  ConversationsResponse,
  DashboardStats,
  LeadStatusFilter,
  LeadsResponse,
  Period,
  PublishResponse,
  ReplyResponse,
  SetStatusResponse,
} from '../dashboard/types'

// Build a query string from defined, non-empty params (omits undefined/'').
function qs(params: Record<string, string | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const str = search.toString()
  return str ? `?${str}` : ''
}

/**
 * GET /api/dashboard — funnel/KPI counts for a period.
 * `period` defaults to all; `includeTest` defaults to false (hide test leads).
 */
export function getDashboard(opts: {
  period?: Period
  includeTest?: boolean
} = {}): Promise<DashboardStats> {
  return api.get<DashboardStats>(
    `/api/dashboard${qs({ period: opts.period, include_test: opts.includeTest })}`,
  )
}

/**
 * GET /api/leads — the full lead list (newest first), each with its complete
 * decrypted answers. Filter by period, status and/or flow (lead_name).
 * `status` 'open' means new + in_progress; 'abandoned' is the נוטשים list.
 */
export function getLeads(opts: {
  period?: Period
  status?: LeadStatusFilter
  flow?: string
  includeTest?: boolean
} = {}): Promise<LeadsResponse> {
  return api.get<LeadsResponse>(
    `/api/leads${qs({
      period: opts.period,
      status: opts.status,
      flow: opts.flow,
      include_test: opts.includeTest,
    })}`,
  )
}

/**
 * GET /api/conversations — the live conversation list (newest activity first).
 * Optional `status` narrows to bot | human | closed.
 */
export function getConversations(
  status?: ConversationStatus,
): Promise<ConversationsResponse> {
  return api.get<ConversationsResponse>(`/api/conversations${qs({ status })}`)
}

/**
 * POST /api/conversations/{id}/status — flip a conversation between bot/human/
 * closed. Returns the new status (422 if status is out of range).
 */
export function setConversationStatus(
  conversationId: string,
  status: ConversationStatus,
): Promise<SetStatusResponse> {
  return api.post<SetStatusResponse>(
    `/api/conversations/${encodeURIComponent(conversationId)}/status`,
    { status },
  )
}

/**
 * POST /api/conversations/{id}/reply — queue a human reply (1..2000 chars) for
 * the WhatsApp sender. Returns `{ queued: true }`.
 */
export function replyToConversation(
  conversationId: string,
  text: string,
): Promise<ReplyResponse> {
  return api.post<ReplyResponse>(
    `/api/conversations/${encodeURIComponent(conversationId)}/reply`,
    { text },
  )
}

/**
 * PUT /api/bot/publish — set the bot live (published) or back to draft.
 * Returns the new published state.
 */
export function setPublished(isPublished: boolean): Promise<PublishResponse> {
  return api.put<PublishResponse>('/api/bot/publish', { is_published: isPublished })
}
