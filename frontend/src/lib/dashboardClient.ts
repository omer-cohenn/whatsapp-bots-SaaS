// Typed wrappers around the six M7 back-office endpoints (the dashboard /
// leads / conversations / publish contract).
//
// Everything goes through `api` (src/lib/apiClient.ts), which sends the session
// cookie same-origin with `credentials: 'include'`. The tenant (business_id) is
// derived entirely from that server session — we NEVER send it from the client.

import { api } from './apiClient'
import type {
  ConversationDetail,
  ConversationStatus,
  ConversationsResponse,
  DashboardStats,
  LeadStatus,
  LeadStatusFilter,
  LeadsResponse,
  MessagesResponse,
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

/** Response of PATCH /api/leads/{id}/status. */
export type LeadStatusResponse = {
  lead_id: string
  status: string
}

/**
 * PATCH /api/leads/{id}/status — manually set a lead's status (the owner uses
 * this to mark a lead as "בוצעה עסקה" / "ליד סגור"). An optional `note` is
 * encrypted at rest into the lead's outcome_note; the UI requires it for
 * deal/closed. Tenant-scoped server-side; 404 if the lead isn't ours. Callers
 * refresh the list afterwards.
 */
export function setLeadStatus(
  leadId: string,
  status: LeadStatus,
  note?: string,
): Promise<LeadStatusResponse> {
  // Only send `note` when provided — the API forbids extra/empty fields.
  const body = note === undefined ? { status } : { status, note }
  return api.patch<LeadStatusResponse>(
    `/api/leads/${encodeURIComponent(leadId)}/status`,
    body,
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
 * GET /api/conversations/{id} — one conversation with its lead and full
 * transcript (oldest → newest). 404 if it isn't ours.
 */
export function getConversation(
  conversationId: string,
): Promise<ConversationDetail> {
  return api.get<ConversationDetail>(
    `/api/conversations/${encodeURIComponent(conversationId)}`,
  )
}

/**
 * GET /api/conversations/{id}/messages — just the transcript (oldest → newest).
 * Lighter than the full detail; the chat panel polls this while open.
 */
export function getConversationMessages(
  conversationId: string,
): Promise<MessagesResponse> {
  return api.get<MessagesResponse>(
    `/api/conversations/${encodeURIComponent(conversationId)}/messages`,
  )
}

/**
 * POST /api/conversations/{id}/status — flip a conversation between bot/waiting/
 * human/closed. Returns the new status (422 if status is out of range).
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
 * DELETE /api/leads/{id} — permanently delete a lead from the DB.
 * Returns nothing (204). 404 if the lead doesn't exist or isn't ours.
 */
export function deleteLead(leadId: string): Promise<void> {
  return api.delete<void>(`/api/leads/${encodeURIComponent(leadId)}`)
}

/**
 * POST /api/leads/{id}/seen — dismiss one lead from the home feed.
 * Stamps feed_seen_at so it no longer shows in the notifications list.
 */
export function markLeadSeen(leadId: string): Promise<{ lead_id: string }> {
  return api.post<{ lead_id: string }>(
    `/api/leads/${encodeURIComponent(leadId)}/seen`,
  )
}

/**
 * POST /api/leads/seen-all — dismiss ALL unseen home-feed notifications.
 * Returns { count: N } — how many leads were stamped.
 */
export function markAllLeadsSeen(): Promise<{ count: number }> {
  return api.post<{ count: number }>('/api/leads/seen-all')
}

/**
 * DELETE /api/account — permanently delete the authenticated owner's business
 * account (all leads, conversations, bot config, WhatsApp session). Returns
 * nothing (204). The caller must redirect away and clear the session client-side.
 */
export function deleteAccount(): Promise<void> {
  return api.delete<void>('/api/account')
}

/**
 * PUT /api/bot/publish — set the bot live (published) or back to draft.
 * Returns the new published state.
 */
export function setPublished(isPublished: boolean): Promise<PublishResponse> {
  return api.put<PublishResponse>('/api/bot/publish', { is_published: isPublished })
}
