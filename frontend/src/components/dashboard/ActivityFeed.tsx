// "התראות" — a recent-activity feed styled like the approved prototype's
// iPhone-style notification cards (.noti / .nicon). Items are derived ENTIRELY
// on the client from the most recent leads (no new backend endpoint): one
// notification per lead, its wording + icon + chip colour chosen by status, with
// a Hebrew relative time on the side.

import type { Lead } from '../../dashboard/types'
import { relativeTime } from '../../lib/formatDate'
import Icon, { type IconName } from '../ui/Icon'

// How many of the newest leads to surface as notifications.
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

// Pick the timestamp that best represents "when this happened" for a lead.
function leadTimestamp(lead: Lead): string | null {
  return lead.submitted_at ?? lead.last_activity_at ?? lead.started_at
}

// Map one lead → one notification, by status. (Per the M7 feedback wording.)
function toNotification(lead: Lead): Notification {
  const name = leadDisplayName(lead)
  const at = leadTimestamp(lead)
  switch (lead.status) {
    case 'deal':
      return {
        id: lead.id,
        icon: 'checks',
        chipClassName: 'bg-[#1D9E75]',
        title: `בוצעה עסקה: ${name}`,
        at,
      }
    case 'abandoned':
      return {
        id: lead.id,
        icon: 'user-off',
        chipClassName: 'bg-[#D85A30]',
        title: `ליד ננטש: ${name}`,
        at,
      }
    case 'in_progress':
      return {
        id: lead.id,
        icon: 'clock',
        chipClassName: 'bg-[#378ADD]',
        title: `התחיל/ה למלא: ${name}`,
        at,
      }
    case 'closed':
      return {
        id: lead.id,
        icon: 'checks',
        chipClassName: 'bg-slate-400',
        title: `ליד סגור: ${name}`,
        at,
      }
    case 'new':
    default:
      return {
        id: lead.id,
        icon: 'user-plus',
        chipClassName: 'bg-[#639922]',
        title: `ליד חדש: ${name} (${lead.lead_name})`,
        at,
      }
  }
}

export default function ActivityFeed({ leads }: { leads: Lead[] }) {
  const items = leads.slice(0, MAX_ITEMS).map(toNotification)

  return (
    <section aria-labelledby="activity-heading" className="flex flex-col gap-3">
      <h2 id="activity-heading" className="text-lg font-medium text-slate-900">
        התראות
      </h2>

      {items.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {items.map((n) => (
            <li
              key={n.id}
              className="flex items-center gap-3 rounded-xl border border-black/10 bg-white px-3 py-2.5"
            >
              <span
                aria-hidden="true"
                className={`flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl text-white ${n.chipClassName}`}
              >
                <Icon name={n.icon} size={20} />
              </span>
              <p className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900">
                {n.title}
              </p>
              {n.at ? (
                <time
                  dateTime={n.at}
                  className="flex-shrink-0 text-xs text-slate-400"
                >
                  {relativeTime(n.at)}
                </time>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-8 text-center text-sm text-slate-500">
          אין פעילות אחרונה להצגה.
        </p>
      )}
    </section>
  )
}
