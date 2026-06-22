// Shared Hebrew labels + display helpers for the M12 back-office pages, so the
// businesses table, the detail header and the subscription panel all speak the
// same language. Pure functions only — no React here.

import type { SubscriptionStatus, UsageMetric } from './types'

/** Hebrew label + a Badge tone for each subscription status. */
export const STATUS_META: Record<
  SubscriptionStatus,
  { label: string; tone: 'leaf' | 'warning' | 'neutral' }
> = {
  active: { label: 'פעיל', tone: 'leaf' },
  suspended: { label: 'מושהה', tone: 'warning' },
  cancelled: { label: 'בוטל', tone: 'neutral' },
}

/** Friendly Hebrew name for each usage metric, plus a chart colour. */
export const METRIC_META: Record<UsageMetric, { label: string; color: string }> = {
  msg_in: { label: 'הודעות נכנסות', color: '#378ADD' },
  msg_out: { label: 'הודעות יוצאות', color: '#1D9E75' },
  lead: { label: 'לידים', color: '#639922' },
  booking: { label: 'הזמנות', color: '#D85A30' },
  login: { label: 'כניסות', color: '#7C3AED' },
}

/** Order metrics appear in (matches the funnel mental model). */
export const METRIC_ORDER: UsageMetric[] = [
  'msg_in',
  'msg_out',
  'lead',
  'booking',
  'login',
]

/** Format a plan price as shekels, e.g. 49 → "₪49", 0 → "חינם". */
export function formatPrice(price: number): string {
  if (!price || price <= 0) return 'חינם'
  // Whole numbers show clean (₪49); real decimals keep their fraction (₪49.9).
  return `₪${price}`
}
