// One lead, expanded to show EVERY collected detail (the owner explicitly wants
// no hiding). Header: avatar initials, contact name, flow + status badge. Body:
// a grid of every key/value in `answers`, plus the lead's metadata (phone, step,
// times). Footer actions (shown at ANY status): a WhatsApp chat button + a
// control to manually mark the lead as a deal / closed.
//
// Abandoned leads (the נוטשים list) reuse this card — they simply carry partial
// answers and an "abandoned" status, which the badge + step text make clear.

import { useState } from 'react'
import type { Lead, LeadStatus } from '../../dashboard/types'
import { fullDateTime, relativeTime } from '../../lib/formatDate'
import { waLink } from '../../lib/waLink'
import { setLeadStatus } from '../../lib/dashboardClient'
import { toFriendlyError } from '../../lib/friendlyError'
import Badge from '../ui/Badge'
import Icon from '../ui/Icon'

// Status → Hebrew label + Badge tone (covers every concrete LeadStatus).
const STATUS_META: Record<LeadStatus, { label: string; tone: 'leaf' | 'info' | 'warning' | 'neutral' }> = {
  new: { label: 'חדש', tone: 'leaf' },
  in_progress: { label: 'פתוח', tone: 'info' },
  abandoned: { label: 'ננטש', tone: 'warning' },
  deal: { label: 'בוצעה עסקה', tone: 'leaf' },
  closed: { label: 'ליד סגור', tone: 'neutral' },
}

// First letters of the contact name for the avatar (falls back to a glyph).
function initials(name: string | null): string {
  if (!name) return '—'
  const parts = name.trim().split(/\s+/).slice(0, 2)
  return parts.map((p) => p[0]).join('') || '—'
}

type Props = {
  lead: Lead
  /** Called after a manual status change succeeds, so the page can refetch. */
  onStatusChange?: () => void
}

export default function LeadCard({ lead, onStatusChange }: Props) {
  const meta = STATUS_META[lead.status]
  const answers = Object.entries(lead.answers ?? {})
  const chatHref = waLink(lead.phone)

  const [saving, setSaving] = useState<LeadStatus | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  async function changeStatus(next: LeadStatus) {
    setSaving(next)
    setActionError(null)
    try {
      await setLeadStatus(lead.id, next)
      onStatusChange?.()
    } catch (err) {
      setActionError(toFriendlyError(err, 'עדכון הסטטוס נכשל. נסו שוב.'))
    } finally {
      setSaving(null)
    }
  }

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

      {/* Actions: WhatsApp chat + manual status. Shown at any status. */}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-black/10 pt-3">
        {chatHref ? (
          <a
            href={chatHref}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#1D9E75] px-3 py-1.5 text-sm font-medium text-white outline-none transition-colors hover:bg-[#178060] focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2"
          >
            <Icon name="message-circle" size={16} />
            פתח שיחה בוואטסאפ
            <span className="sr-only"> עם {lead.contact_name || 'הליד'}</span>
          </a>
        ) : null}

        {lead.status !== 'deal' ? (
          <button
            type="button"
            onClick={() => changeStatus('deal')}
            disabled={saving !== null}
            className="inline-flex items-center gap-1.5 rounded-lg border border-leaf px-3 py-1.5 text-sm font-medium text-leaf-ink outline-none transition-colors hover:bg-leaf-soft focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Icon name="checks" size={16} />
            {saving === 'deal' ? 'מעדכן…' : 'בוצעה עסקה'}
          </button>
        ) : null}

        {lead.status !== 'closed' ? (
          <button
            type="button"
            onClick={() => changeStatus('closed')}
            disabled={saving !== null}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 outline-none transition-colors hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <Icon name="x" size={16} />
            {saving === 'closed' ? 'מעדכן…' : 'ליד סגור'}
          </button>
        ) : null}
      </div>

      {actionError ? (
        <p role="alert" className="mt-2 text-xs text-bad">
          {actionError}
        </p>
      ) : null}
    </article>
  )
}
