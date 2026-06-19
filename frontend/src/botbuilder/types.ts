// TypeScript mirror of the backend bot-config contract
// (backend/app/models/bot_builder.py — Pydantic v2). The SERVER is the
// authoritative validator (PUT /api/bot/settings returns 422 on any violation);
// these types + the bound constants below exist only for editor types and for
// friendly client-side UX hints. We never treat the client copy as truth.
//
// Two shapes that are easy to get wrong, so they're called out here:
//   * `lead_steps` is an OBJECT keyed by snake_case flow name — NOT an array.
//   * the per-step extra-validation hint field is wire-named `validate`
//     (matches the frozen contract; it is just a data field).

// --- bound constants (mirror the Pydantic bounds, for UX only) ---------------
export const MAX_FLOWS = 20
export const MAX_STEPS_PER_FLOW = 30
export const MIN_CHOICE_OPTIONS = 2
export const MAX_CHOICE_OPTIONS = 12
export const MAX_HANDOFF_KEYWORDS = 30
export const FLOW_NAME_PATTERN = /^[a-z0-9_֐-׿ ]{1,40}$/
export const STEP_KEY_PATTERN = /^[a-z0-9_֐-׿ ]{1,40}$/

export type StepType = 'text' | 'phone' | 'email' | 'choice'
export type FlowType = 'lead' | 'human_handoff' | 'booking'

// One question inside a flow (contract §2.1).
export type Step = {
  key: string
  question: string
  type: StepType
  required: boolean
  /** Optional extra-validation hint (e.g. "phone"); wire name is `validate`. */
  validate?: string | null
  /** REQUIRED (2..12) only when type === 'choice'; ignored otherwise. */
  options?: string[] | null
  error_message?: string | null
}

// One conversational path, keyed by name at the top level (contract §2).
export type Flow = {
  label: string
  flow_type: FlowType
  steps: Step[]
  /** booking-only; stripped by the server for other flow types. */
  service_name?: string | null
  /** Customer-facing message for human_handoff / booking flows. */
  message?: string | null
}

// The bot's identity + global behavior (contract §1).
// On a brand-new business GET returns `{}` for this, so every field is optional
// in the read shape; `name` + `system_prompt` are required on SAVE.
export type BotProfile = {
  name?: string
  system_prompt?: string
  tone?: string
  language?: 'he' | 'en'
  greeting?: string
  escalation_message?: string
  auto_close_minutes?: number
  menu_keywords?: string[]
}

// The full bot_settings shape (the GET/PUT body, minus DB-managed columns).
// `bot_profile` is permissive ({} for a never-configured business) on read.
export type BotSettings = {
  lead_steps: Record<string, Flow>
  bot_profile: BotProfile
  handoff_keywords: string[]
  is_published: boolean
}

// --- AI builder chat wire types ----------------------------------------------
export type BotAiChatResponse = {
  reply: string
  /** Full validated+merged BotSettings to apply LIVE when present; else null. */
  changes?: BotSettings | null
}

export type BotAiRole = 'user' | 'assistant'

export type BotAiMessage = {
  role: BotAiRole
  content: string
  created_at: string
}

export type BotAiHistoryResponse = {
  messages: BotAiMessage[]
}
