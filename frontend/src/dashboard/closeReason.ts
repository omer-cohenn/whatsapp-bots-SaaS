// Shared Hebrew label + Badge tone for a lead's `close_reason` (decision 0021).
// Used by the conversation + lead cards so "why it closed" reads the same
// everywhere. Pure data — no React, no hand-picked colours (tones map to the
// shared Badge tokens). A null close_reason renders nothing (handled by callers).

import type { CloseReason } from './types'

type Meta = { label: string; tone: 'leaf' | 'info' | 'neutral' | 'warning' }

// abandoned → warning (muted/attention), completed → leaf (green/success),
// answered → neutral. All tones resolve to existing Badge palette tokens.
export const CLOSE_REASON_META: Record<
  Exclude<CloseReason, null>,
  Meta
> = {
  completed: { label: 'ליד הושלם', tone: 'leaf' },
  abandoned: { label: 'ליד ננטש', tone: 'warning' },
  answered: { label: 'מענה הושלם', tone: 'neutral' },
}

/** Meta for a close_reason, or null when there's nothing to show. */
export function closeReasonMeta(reason: CloseReason): Meta | null {
  return reason ? CLOSE_REASON_META[reason] : null
}
