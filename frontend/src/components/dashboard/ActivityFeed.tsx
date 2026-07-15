// "התראות" — a recent-activity feed styled like the approved prototype's
// iPhone-style notification cards (.noti / .nicon). Items are derived ENTIRELY
// on the client from the most recent leads (no new backend endpoint): one
// notification per lead, its wording + icon + chip colour chosen by status, with
// a Hebrew relative time on the side.
//
// Decision 0022: leads with feed_seen_at != null are hidden (dismissed). The
// owner can dismiss individual items or all at once; the state lives in the DB
// (feed_seen_at column) so it survives a page refresh.

import type { Lead } from '../../dashboard/types'
import { relativeTime } from '../../lib/formatDate'
import Icon, { type IconName } from '../ui/Icon'

// How many of the newest leads to surface as notifications (pre-filter).
const MAX_ITEMS = 8

type Notification = {
  id: string
  icon: IconName
  /** Tailwind bg class for the round icon chip (decorative colour). */
  chipClassName: string
  title: string
  /** When the activity happened, as an ISO string (rendered relative). */
  at: string | null
}

function leadDisplayName(lead: Lead): string {
  return lead.contact_name || 'ליד ללא שם'
}

function leadTimestamp(lead: Lead): string | null {
  return lead.submitted_at ?? lead.last_activity_at ?? lead.started_at
}

function toNotification(lead: Lead): Notification {
  const name = leadDisplayName(lead)
  const at = leadTimestamp(lead)
  if (lead.lead_name === 'פגישה' && (lead.status === 'new' || lead.status === 'in_progress')) {
    return {
      id: lead.id,
      icon: 'calendar-event',
      chipClassName: 'bg-[#378ADD]',
      title: `בקשה לפגישה: ${name}`,
      at,
    }
  }
  switch (lead.status) {
    case 'deal':
      return { id: lead.id, icon: 'checks', chipClassName: 'bg-[#1D9E75]', title: `בוצעה עסקה: ${name}`, at }
    case 'abandoned':
      return { id: lead.id, icon: 'user-off', chipClassName: 'bg-[#D85A30]', title: `ליד ננטש: ${name}`, at }
    case 'in_progress':
      return { id: lead.id, icon: 'clock', chipClassName: 'bg-[#378ADD]', title: `התחיל/ה למלא: ${name}`, at }
    case 'closed':
      return { id: lead.id, icon: 'checks', chipClassName: 'bg-slate-400', title: `ליד סגור: ${name}`, at }
    case 'new':
    default:
      return { id: lead.id, icon: 'user-plus', chipClassName: 'bg-[#639922]', title: `ליד חדש: ${name} (${lead.lead_name})`, at }
  }
}

type Props = {
  leads: Lead[]
  onMarkSeen: (id: string) => void
  onMarkAllSeen: () => void
}

export default function ActivityFeed({ leads, onMarkSeen, onMarkAllSeen }: Props) {
  // Hide leads the owner already dismissed (decision 0022).
  const visible = leads
    .filter((l) => l.feed_seen_at == null)
    .slice(0, MAX_ITEMS)
    .map(toNotification)

  return (
    <section aria-labelledby="activity-heading" className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h2 id="activity-heading" className="text-lg font-medium text-slate-900 dark:text-slate-100">
          התראות
        </h2>
        {visible.length > 1 ? (
          <button
            type="button"
            onClick={onMarkAllSeen}
            className="text-xs text-leaf hover:text-leaf-dark hover:underline focus-visible:outline-none focus-visible:underline"
          >
            סמן הכל כנקרא
          </button>
        ) : null}
      </div>

      {visible.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {visible.map((n) => (
            <li
              key={n.id}
              className="flex items-center gap-3 rounded-xl border border-black/10 bg-white px-3 py-2.5 dark:border-white/10 dark:bg-slate-800"
            >
              <span
                aria-hidden="true"
                className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl text-white ${n.chipClassName}`}
              >
                <Icon name={n.icon} size={20} />
              </span>
              <p className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                {n.title}
              </p>
              {n.at ? (
                <time dateTime={n.at} className="flex-shrink-0 text-xs text-slate-400">
                  {relativeTime(n.at)}
                </time>
              ) : null}
              <button
                type="button"
                onClick={() => onMarkSeen(n.id)}
                title="סמן כנקרא"
                aria-label={`סמן כנקרא: ${n.title}`}
                className="flex-shrink-0 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-1 dark:hover:bg-slate-700"
              >
                <Icon name="x" size={14} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400">
          אין התראות חדשות.
        </p>
      )}
    </section>
  )
}
