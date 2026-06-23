// Shared Hebrew labels + display helpers for the M12 back-office pages, so the
// businesses table, the detail header and the subscription panel all speak the
// same language. Pure functions only — no React here.

import type {
  ByPlanMetric,
  CrmStage,
  SubscriptionStatus,
  UsageMetric,
} from './types'

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
  ai_call: { label: 'פעולות AI', color: '#BA7517' },
}

/** Order metrics appear in (matches the funnel mental model). */
export const METRIC_ORDER: UsageMetric[] = [
  'msg_in',
  'msg_out',
  'lead',
  'booking',
  'login',
  'ai_call',
]

/** Format a plan price as shekels, e.g. 49 → "₪49", 0 → "חינם". */
export function formatPrice(price: number): string {
  if (!price || price <= 0) return 'חינם'
  // Whole numbers show clean (₪49); real decimals keep their fraction (₪49.9).
  return `₪${price}`
}

// === M13 shared display helpers ============================================

/**
 * Format a money amount (LTV / MRR) as shekels with grouping. null → '—'.
 * Whole numbers stay clean (₪1,200); decimals round to two places (₪1,234.5).
 */
export function formatMoney(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return '—'
  const rounded = Math.round(amount * 100) / 100
  const text = Number.isInteger(rounded)
    ? rounded.toLocaleString('he-IL')
    : rounded.toLocaleString('he-IL', { maximumFractionDigits: 2 })
  return `₪${text}`
}

/** The CRM pipeline stages in board order, with a Hebrew label + accent hex. */
export const CRM_STAGE_META: Record<CrmStage, { label: string; color: string }> = {
  new: { label: 'חדש', color: '#888780' },
  contacted: { label: 'יצרתי קשר', color: '#378ADD' },
  warming: { label: 'מחמם', color: '#D85A30' },
  won: { label: 'נסגר', color: '#639922' },
  lost: { label: 'אבד', color: '#534AB7' },
}

/** Left→right board order (matches the funnel: new → … → won/lost). */
export const CRM_STAGE_ORDER: CrmStage[] = [
  'new',
  'contacted',
  'warming',
  'won',
  'lost',
]

/** Hebrew label + chart colour for the three derived lead types (M13). */
export const LEAD_TYPE_META: Record<
  'booking' | 'lead' | 'handoff',
  { label: string; color: string }
> = {
  booking: { label: 'פגישה', color: '#378ADD' },
  lead: { label: 'ליד', color: '#639922' },
  handoff: { label: 'נציג', color: '#D85A30' },
}

/** Hebrew label for each by-plan metric option. */
export const BY_PLAN_METRIC_META: Record<ByPlanMetric, string> = {
  msg_in: 'הודעות נכנסות',
  msg_out: 'הודעות יוצאות',
  lead: 'לידים',
  booking: 'פגישות',
  login: 'כניסות',
  ai_call: 'פעולות AI',
}

/**
 * Friendly Hebrew label for a plan code (Title-cased fallback when we don't
 * have the plan catalog handy — e.g. on the analytics charts).
 */
export function planCodeLabel(code: string): string {
  const known: Record<string, string> = {
    free: 'חינם',
    basic: 'בסיסי',
    pro: 'מקצועי',
  }
  return known[code] ?? code
}
