// Typed wrappers around the four /api/bot/* endpoints (the M4 backend contract).
//
// All requests go through `api` (src/lib/apiClient.ts), which sends the session
// cookie same-origin with `credentials: 'include'`. The tenant (business_id) is
// derived entirely from that server session — we NEVER send it from the client.

import { api } from './apiClient'
import type {
  BotAiChatResponse,
  BotAiHistoryResponse,
  BotSettings,
  BotTryMeResponse,
  ConvState,
} from '../botbuilder/types'

/**
 * GET /api/bot/settings — the current config. Permissive read: a brand-new
 * business returns `bot_profile: {}`, `lead_steps: {}`, and default
 * handoff_keywords (render a blank slate).
 */
export function getSettings(): Promise<BotSettings> {
  return api.get<BotSettings>('/api/bot/settings')
}

/**
 * PUT /api/bot/settings — validate + save. The server enforces the full
 * contract and answers 422 (ApiError) on any out-of-bounds body. Returns the
 * saved (normalized) settings on success.
 */
export function saveSettings(cfg: BotSettings): Promise<BotSettings> {
  return api.put<BotSettings>('/api/bot/settings', cfg)
}

/**
 * POST /api/bot/ai/chat — one AI builder turn. `currentConfig` is the builder's
 * working copy (untrusted prompt context; the tenant is never read from it).
 * The reply always comes back; `changes` is the full validated BotSettings to
 * apply live when the model proposed a valid change, else null/absent.
 *
 * Errors surface as ApiError: 503 = AI not configured, 502 = temporary, 422 =
 * bad message.
 */
export function aiChat(
  message: string,
  currentConfig: BotSettings,
): Promise<BotAiChatResponse> {
  return api.post<BotAiChatResponse>('/api/bot/ai/chat', {
    message,
    current_config: currentConfig,
  })
}

/**
 * GET /api/bot/ai/history — up to 50 recent build-chat messages, ordered
 * oldest→newest (ready to render straight into the chat panel).
 */
export function aiHistory(): Promise<BotAiHistoryResponse> {
  return api.get<BotAiHistoryResponse>('/api/bot/ai/history')
}

/**
 * POST /api/bot/tryme — one turn of the deterministic test-chat engine ("נסה
 * אותי"). The owner types as if they were a customer; the bot replies come back
 * in `replies`.
 *
 *   * `message` empty ('') → the "open" turn (greeting + menu).
 *   * `state` null → the engine starts fresh; otherwise pass back EXACTLY the
 *     `state` returned by the previous turn (it is opaque — never inspected or
 *     trusted, and never used to scope the tenant; that comes from the session).
 *
 * No data is persisted: `lead` (only present on event 'lead_completed') is just
 * this conversation's own typed answers, shown in test mode and discarded.
 */
export function tryMe(
  message: string,
  state: ConvState,
): Promise<BotTryMeResponse> {
  return api.post<BotTryMeResponse>('/api/bot/tryme', { message, state })
}
