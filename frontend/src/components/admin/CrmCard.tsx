// One business card on the CRM pipeline board (M13). Shows the business name, a
// plan badge, the next-follow-up date and the note count, plus a stage <select>
// that moves the card to another column (the quick action) and a "פרטים" button
// that opens the full panel dialog. Keeping the move on a native <select> keeps
// it fully keyboard-operable without drag-and-drop (which the goal lists as
// optional). The select is labelled per-card for screen readers.

import { useId } from 'react'
import Badge from '../ui/Badge'
import Icon from '../ui/Icon'
import { CRM_STAGE_META, CRM_STAGE_ORDER, planCodeLabel } from '../../admin/labels'
import type { CrmBusiness, CrmStage } from '../../admin/types'

// Short follow-up date, e.g. "19 ביוני". null → null.
function shortDate(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleDateString('he-IL', { day: 'numeric', month: 'short' })
}

type Props = {
  business: CrmBusiness
  /** Move to another stage (the quick action). */
  onMove: (stage: CrmStage) => void
  /** Open the full panel (set follow-up, add/read notes). */
  onOpen: () => void
  /** True while a move for THIS card is in flight (disables the select). */
  busy?: boolean
}

export default function CrmCard({ business, onMove, onOpen, busy }: Props) {
  const selectId = useId()
  const followup = shortDate(business.next_followup_at)

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={onOpen}
          className="rounded text-start text-sm font-medium text-slate-900 underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2"
        >
          {business.name || 'עסק ללא שם'}
        </button>
        <Badge tone="neutral">{planCodeLabel(business.plan_code)}</Badge>
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        {followup ? (
          <span className="inline-flex items-center gap-1">
            <Icon name="calendar-due" size={14} />
            חזרה: {followup}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-slate-400">
            <Icon name="calendar-due" size={14} />
            ללא תזכורת
          </span>
        )}
        <span className="inline-flex items-center gap-1">
          <Icon name="note" size={14} />
          {business.note_count} פתקים
        </span>
      </div>

      <div className="mt-1 flex items-center gap-2">
        <label htmlFor={selectId} className="sr-only">
          שינוי שלב עבור {business.name || 'עסק'}
        </label>
        <select
          id={selectId}
          value={business.stage}
          disabled={busy}
          onChange={(e) => onMove(e.target.value as CrmStage)}
          className="flex-1 rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-900 outline-none focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2 disabled:opacity-60"
        >
          {CRM_STAGE_ORDER.map((s) => (
            <option key={s} value={s}>
              {CRM_STAGE_META[s].label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={onOpen}
          className="rounded-lg border border-slate-300 px-2 py-1.5 text-xs font-medium text-slate-700 outline-none transition hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2"
        >
          פרטים
        </button>
      </div>
    </div>
  )
}
