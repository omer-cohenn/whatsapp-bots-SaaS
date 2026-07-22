// One shared "turn an error into a friendly Hebrew message" helper, mirroring
// the per-page toFriendlyError used in TryMePage / AIChatPanel. Centralised so
// the M7 dashboard pages all speak the same language for 401 / 5xx / network.

import { ApiError } from './apiClient'

/**
 * Map any thrown error to a short, reassuring Hebrew sentence.
 * `fallback` is used for anything we don't specifically recognise.
 */
export function toFriendlyError(
  err: unknown,
  fallback = 'אירעה תקלה. נסו שוב.',
): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return 'פג תוקף ההתחברות. רעננו את העמוד והתחברו מחדש.'
    // 403 on a write from the public demo session. The server refuses it on
    // purpose (app/core/demo_guard.py) and sends a Hebrew explanation, so show
    // THAT rather than a generic failure: a visitor who is told "השמירה נכשלה,
    // נסו שוב" will keep trying something that can never succeed.
    if (err.status === 403 && err.detail) return err.detail
    if (err.status === 0) return 'אין חיבור לשרת. בדקו את החיבור ונסו שוב.'
    if (err.status === 422) return 'הנתונים שנשלחו אינם תקינים. נסו שוב.'
    if (err.status >= 500) return 'אירעה תקלה זמנית בשרת. נסו שוב בעוד רגע.'
  }
  return fallback
}
