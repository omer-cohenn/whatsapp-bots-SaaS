// Pure helpers for editing the bot config locally. The config's `lead_steps` is
// an OBJECT keyed by snake_case flow name, which makes a few operations (rename,
// add, ensure-unique-key) fiddly — so they live here, tested-shaped and reused
// by the builder components.
//
// None of this is the validation gate — the SERVER re-validates on PUT. These
// helpers just keep the in-memory working copy well-formed enough to edit.

import type { BotProfile, BotSettings, Flow, FlowType, Step, StepType } from './types'
import { FILE_KINDS } from './types'

/** Make a key that doesn't collide with any in `taken` (append _2, _3, …). */
export function uniqueKey(base: string, taken: Iterable<string>): string {
  const set = new Set(taken)
  const seed = base || 'flow'
  if (!set.has(seed)) return seed
  for (let i = 2; i < 1000; i++) {
    const candidate = `${seed}_${i}`.slice(0, 40)
    if (!set.has(candidate)) return candidate
  }
  // Extremely unlikely fallback.
  return `${seed}_${Date.now()}`.slice(0, 40)
}

/** A new step, PRE-FILLED with a real example (the owner edits it, or keeps it).
 * `addStep` makes the key unique when more than one step is added. */
export function emptyStep(type: StepType = 'text'): Step {
  return {
    key: 'שם_מלא',
    question: 'מה השם המלא שלך?',
    type,
    required: true,
    options: type === 'choice' ? ['', ''] : null,
    // A `file` step defaults to accepting everything we support (M16).
    accept: type === 'file' ? [...FILE_KINDS] : null,
  }
}

/** Default customer-facing messages for the message-based flow types. */
export const DEFAULT_HANDOFF_MESSAGE = 'תודה שפנית אלינו! נציג מטעמנו יחזור אליך בהקדם.'
export const DEFAULT_BOOKING_MESSAGE = 'נשמח להיפגש! לקביעת פגישה נא היכנס/י למערכת: {link}'

/** A blank flow of the given type. `lead` starts with one step; handoff has none. */
export function emptyFlow(label: string, flowType: FlowType): Flow {
  return {
    label,
    flow_type: flowType,
    steps: flowType === 'lead' ? [emptyStep()] : [],
    service_name: flowType === 'booking' ? '' : null,
    message:
      flowType === 'human_handoff'
        ? DEFAULT_HANDOFF_MESSAGE
        : flowType === 'booking'
          ? DEFAULT_BOOKING_MESSAGE
          : null,
  }
}

/** The minimal valid empty config (used before settings load / as a fallback). */
export function emptySettings(): BotSettings {
  return {
    lead_steps: {},
    bot_profile: {},
    handoff_keywords: ['נציג', 'אדם', 'human', 'agent'],
    is_published: false,
  }
}

/**
 * Fill the real default customer-facing message on any handoff/booking flow that
 * has none, so the owner ALWAYS sees a working message (not an empty box with a
 * grey hint). They can edit it; if untouched, the sensible default is saved.
 * The AI one-shot build often omits these, which is exactly when this matters.
 */
function withDefaultMessages(flows: Record<string, Flow>): Record<string, Flow> {
  const out: Record<string, Flow> = {}
  for (const [key, flow] of Object.entries(flows)) {
    if (!flow || typeof flow !== 'object') {
      out[key] = flow
      continue
    }
    let message = flow.message
    if (flow.flow_type === 'human_handoff' && !(message ?? '').trim()) {
      message = DEFAULT_HANDOFF_MESSAGE
    } else if (flow.flow_type === 'booking' && !(message ?? '').trim()) {
      message = DEFAULT_BOOKING_MESSAGE
    }
    out[key] = message === flow.message ? flow : { ...flow, message }
  }
  return out
}

/**
 * Normalize a raw config (from GET, or an AI `changes` payload) into the editor
 * shape. Defensive against missing keys so the builder never crashes on the
 * permissive read (bot_profile may be {}).
 */
export function normalizeSettings(raw: Partial<BotSettings> | null | undefined): BotSettings {
  const base = emptySettings()
  if (!raw || typeof raw !== 'object') return base
  return {
    lead_steps: withDefaultMessages(
      raw.lead_steps && typeof raw.lead_steps === 'object' ? raw.lead_steps : {},
    ),
    bot_profile: (raw.bot_profile as BotProfile) ?? {},
    handoff_keywords: Array.isArray(raw.handoff_keywords)
      ? raw.handoff_keywords
      : base.handoff_keywords,
    is_published: Boolean(raw.is_published),
  }
}
