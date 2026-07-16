// "התראות" — a recent-activity feed styled as notification cards: a circular
// initials avatar (colour derived deterministically from the name), the lead's
// name + phone, a flow-name chip + a status chip, a one-line preview of the
// collected answers, and a relative time on the far (left) edge. Items are
// derived ENTIRELY on the client from the most recent leads (no new backend
// endpoint).
//
// Decision 0022: leads with feed_seen_at != null are hidden (dismissed). The
// owner can dismiss individual items or all at once; the state lives in the DB
// (feed_seen_at column) so it survives a page refresh.

import { Link } from 'react-router-dom'
import type { Lead, LeadStatus } from '../../dashboard/types'
import { relativeTime } from '../../lib/formatDate'
import Icon from '../ui/Icon'

// How many of the newest leads to surface as notifications (pre-filter).
const MAX_ITEMS = 8

// Small deterministic palette for the initials avatar (decorative colour; the
// name text next to it carries the meaning). All pass AA for white text.
const AVATAR_COLORS = [
  'bg-leaf', // green
  'bg-[#378ADD]', // blue
  'bg-[#D85A30]', // red-orange
  'bg-amber-600', // amber
  'bg-violet-600', // violet
]

/** Stable colour per name: sum of code points → palette index. */
function avatarColor(name: string): string {
  let sum = 0
  for (const ch of name) sum = (sum + (ch.codePointAt(0) ?? 0)) % 9973
  return AVATAR_COLORS[sum % AVATAR_COLORS.length]
}

/** Up to two Hebrew initials: first letter of the first two words. */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return 'ל'
  if (parts.length === 1) return parts[0].slice(0, 2)
  return `${parts[0][0]}${parts[1][0]}`
}

// Status → chip wording + soft chip colours (text carries the state, colour is
// reinforcement only; both themes are AA-safe).
const STATUS_CHIP: Record<LeadStatus, { label: string; className: string }> = {
  new: {
    label: 'ליד חדש',
    className: 'bg-blue-50 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  },
  in_progress: {
    label: 'בתהליך',
    className: 'bg-orange-50 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
  },
  abandoned: {
    label: 'ננטש',
    className: 'bg-red-50 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  },
  deal: {
    label: 'פניה הושלמה',
    className: 'bg-green-50 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  },
  closed: {
    label: 'נסגר',
    className: 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-300',
  },
}

function leadDisplayName(lead: Lead): string {
  return lead.contact_name || 'ליד ללא שם'
}

function leadTimestamp(lead: Lead): string | null {
  return lead.submitted_at ?? lead.last_activity_at ?? lead.started_at
}

type Props = {
  leads: Lead[]
  onMarkSeen: (id: string) => void
  onMarkAllSeen: () => void
}

export default function ActivityFeed({ leads, onMarkSeen, onMarkAllSeen }: Props) {
  // Hide leads the owner already dismissed (decision 0022).
  const visible = leads.filter((l) => l.feed_seen_at == null).slice(0, MAX_ITEMS)

  return (
    <section aria-labelledby="activity-heading" className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 id="activity-heading" className="text-xl font-bold text-slate-900 dark:text-slate-100">
          התראות
        </h2>
        {visible.length > 1 ? (
          <button
            type="button"
            onClick={onMarkAllSeen}
            className="rounded text-xs font-medium text-leaf-ink hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-leaf dark:text-leaf-light"
          >
            סמן הכל כנקרא
          </button>
        ) : null}
      </div>

      {visible.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {visible.map((lead) => {
            const name = leadDisplayName(lead)
            const at = leadTimestamp(lead)
            const chip = STATUS_CHIP[lead.status]
            return (
              <li
                key={lead.id}
                className="flex items-center gap-3 rounded-2xl bg-white px-4 py-3.5 shadow-[0_10px_26px_rgba(70,60,35,0.07)] transition-colors hover:bg-slate-50 dark:border dark:border-white/10 dark:bg-slate-800 dark:shadow-none dark:hover:bg-slate-700/60"
              >
                {/* The card body is a link → opens this lead in the leads tab. */}
                <Link
                  to={`/leads?highlight=${encodeURIComponent(lead.id)}`}
                  className="flex min-w-0 flex-1 items-center gap-3 rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-leaf"
                  aria-label={`פתיחת הליד של ${name} בלשונית הלידים`}
                >
                  {/* Initials avatar + green presence dot (visual bottom-right). */}
                  <span aria-hidden="true" className="relative flex-shrink-0">
                    <span
                      className={`flex h-11 w-11 items-center justify-center rounded-full text-sm font-bold text-white ${avatarColor(name)}`}
                    >
                      {initials(name)}
                    </span>
                    <span className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full bg-leaf ring-2 ring-white dark:ring-slate-800" />
                  </span>

                  <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="text-sm font-bold text-slate-900 dark:text-slate-100">
                      {name}
                    </span>
                    {lead.phone ? (
                      <span className="text-xs text-slate-400 dark:text-slate-500" dir="ltr">
                        {lead.phone}
                      </span>
                    ) : null}
                    {lead.lead_name ? (
                      <span className="inline-flex items-center rounded-full bg-[#f1ede2] px-2.5 py-0.5 text-xs font-medium text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                        {lead.lead_name}
                      </span>
                    ) : null}
                    <span
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${chip.className}`}
                    >
                      {chip.label}
                    </span>
                  </span>
                </Link>

                {/* Far-left edge (RTL): relative time + dismiss. */}
                <span className="flex flex-shrink-0 items-center gap-1.5 self-start">
                  {at ? (
                    <time dateTime={at} className="text-xs text-slate-400 dark:text-slate-500">
                      {relativeTime(at)}
                    </time>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => onMarkSeen(lead.id)}
                    title="סמן כנקרא"
                    aria-label={`סמן כנקרא: ${name}`}
                    className="rounded-full p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-leaf dark:hover:bg-slate-700 dark:hover:text-slate-300"
                  >
                    <Icon name="x" size={14} />
                  </button>
                </span>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="rounded-2xl border border-dashed border-slate-300 bg-white px-4 py-8 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400">
          אין התראות חדשות.
        </p>
      )}
    </section>
  )
}
