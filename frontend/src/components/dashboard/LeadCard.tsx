// One lead, expanded to show EVERY collected detail (the owner explicitly wants
// no hiding). Header: avatar initials, contact name, flow + status. Body: a grid
// of every key/value in `answers`, plus the lead's metadata (phone, step, times).
//
// Abandoned leads (the נוטשים list) reuse this card — they simply carry partial
// answers and an "abandoned" status, which the badge + step text make clear.

import type { Lead } from '../../dashboard/types'
import { fullDateTime, relativeTime } from '../../lib/formatDate'
import Badge from '../ui/Badge'

// Status → Hebrew label + Badge tone.
const STATUS_META: Record<Lead['status'], { label: string; tone: 'leaf' | 'info' | 'warning' }> = {
  new: { label: 'חדש', tone: 'leaf' },
  in_progress: { label: 'פתוח', tone: 'info' },
  abandoned: { label: 'ננטש', tone: 'warning' },
}

// First letters of the contact name for the avatar (falls back to a glyph).
function initials(name: string | null): string {
  if (!name) return '—'
  const parts = name.trim().split(/\s+/).slice(0, 2)
  return parts.map((p) => p[0]).join('') || '—'
}

export default function LeadCard({ lead }: { lead: Lead }) {
  const meta = STATUS_META[lead.status]
  const answers = Object.entries(lead.answers ?? {})

  return (
    <article className="rounded-xl border border-black/10 bg-white p-4">
      <div className="flex items-center gap-3">
        <span
          aria-hidden="true"
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-leaf-soft text-sm font-medium text-leaf-ink"
        >
          {initials(lead.contact_name)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-slate-900">
            {lead.contact_name || 'ליד ללא שם'}
          </p>
          <p className="truncate text-xs text-slate-500">
            {lead.lead_name}
            {lead.status === 'abandoned'
              ? ` · עצר בשלב ${lead.last_step_index + 1}`
              : ''}
            {lead.is_test ? ' · בדיקה' : ''}
          </p>
        </div>
        <Badge tone={meta.tone}>{meta.label}</Badge>
      </div>

      {/* Every collected answer — nothing hidden. */}
      {answers.length > 0 ? (
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 border-t border-black/10 pt-3 sm:grid-cols-3">
          {answers.map(([key, value]) => (
            <div key={key} className="min-w-0">
              <dt className="text-[11px] text-slate-400">{key}</dt>
              <dd className="truncate text-sm text-slate-800" title={value}>
                {value || <span className="text-slate-400">טרם נענה</span>}
              </dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mt-3 border-t border-black/10 pt-3 text-sm text-slate-400">
          עדיין לא נאספו פרטים.
        </p>
      )}

      {/* Metadata footer */}
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-slate-400">
        {lead.phone ? <span>טלפון: {lead.phone}</span> : null}
        {lead.started_at ? <span>התחיל: {relativeTime(lead.started_at)}</span> : null}
        {lead.submitted_at ? (
          <span title={fullDateTime(lead.submitted_at)}>
            הושלם: {relativeTime(lead.submitted_at)}
          </span>
        ) : lead.last_activity_at ? (
          <span title={fullDateTime(lead.last_activity_at)}>
            פעילות אחרונה: {relativeTime(lead.last_activity_at)}
          </span>
        ) : null}
      </div>
    </article>
  )
}
