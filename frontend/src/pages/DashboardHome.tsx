// Authenticated landing page (M7). Renders inside <DashboardLayout> (sidebar,
// header, skip-link, <main> landmark). Shows a greeting, a go-live publish
// toggle, the funnel/KPI cards (orders → completed → abandoned → started) with a
// week / month / all period filter, and a "התראות" recent-activity feed.
//
// Three reads on mount: GET /api/dashboard (funnel, re-fetched when the period
// changes), GET /api/leads (newest leads → the activity feed) and
// GET /api/bot/settings (for the current publish state). The tenant is always
// derived server-side from the session — never sent from here.

import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import DashboardLayout from '../components/DashboardLayout'
import ActivityFeed from '../components/dashboard/ActivityFeed'
import StatCard from '../components/dashboard/StatCard'
import SegmentedControl, { type Segment } from '../components/dashboard/SegmentedControl'
import PublishToggle from '../components/dashboard/PublishToggle'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'
import Icon from '../components/ui/Icon'
import { getDashboard, getLeads, getConversations, markLeadSeen, markAllLeadsSeen } from '../lib/dashboardClient'
import { getBookingAlerts } from '../lib/bookingClient'
import { getSettings } from '../lib/botClient'
import { toFriendlyError } from '../lib/friendlyError'
import { relativeTime, fullDateTime } from '../lib/formatDate'
import type { Conversation, DashboardStats, Lead, Period } from '../dashboard/types'
import type { BookingAlert } from '../dashboard/appointmentTypes'

const PERIOD_SEGMENTS: Segment<Period>[] = [
  { value: 'week', label: 'השבוע' },
  { value: 'month', label: 'החודש' },
  { value: 'all', label: 'הכול' },
]

export default function DashboardHome() {
  const { user, business } = useAuth()

  const [period, setPeriod] = useState<Period>('week')
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Newest leads → the "התראות" activity feed (derived client-side, no period).
  const [recentLeads, setRecentLeads] = useState<Lead[]>([])

  // Conversations waiting for a human ("מחכים לך"), surfaced prominently above
  // the feed. Loaded once; non-fatal if it fails (the block just hides).
  const [waiting, setWaiting] = useState<Conversation[]>([])

  // Customer-initiated booking changes (cancel / reschedule) → home alerts.
  // Loaded once; non-fatal if it fails (the block just hides).
  const [bookingAlerts, setBookingAlerts] = useState<BookingAlert[]>([])

  // Publish state lives here so the toggle stays in sync with the loaded config.
  const [isPublished, setIsPublished] = useState<boolean | null>(null)

  // Funnel: re-fetched whenever the period changes.
  const loadStats = useCallback((p: Period) => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getDashboard({ period: p })
      .then((res) => {
        if (!cancelled) setStats(res)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת הנתונים נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => loadStats(period), [loadStats, period])

  // Recent activity: the newest leads (status=all), loaded once. Non-fatal — if
  // it fails the feed just shows its empty state.
  useEffect(() => {
    let cancelled = false
    getLeads({ status: 'all' })
      .then((res) => {
        if (!cancelled) setRecentLeads(res.leads)
      })
      .catch(() => {
        if (!cancelled) setRecentLeads([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Conversations waiting for a human, loaded once. Non-fatal.
  useEffect(() => {
    let cancelled = false
    getConversations('waiting')
      .then((res) => {
        if (!cancelled) setWaiting(res.conversations)
      })
      .catch(() => {
        if (!cancelled) setWaiting([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Booking alerts (customer cancelled / rescheduled), loaded once. Non-fatal.
  useEffect(() => {
    let cancelled = false
    getBookingAlerts()
      .then((res) => {
        if (!cancelled) setBookingAlerts(res.alerts)
      })
      .catch(() => {
        if (!cancelled) setBookingAlerts([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Publish state: loaded once.
  useEffect(() => {
    let cancelled = false
    getSettings()
      .then((cfg) => {
        if (!cancelled) setIsPublished(Boolean(cfg.is_published))
      })
      .catch(() => {
        // Non-fatal: just hide the toggle if settings can't load.
        if (!cancelled) setIsPublished(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <DashboardLayout>
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-6 py-10">
        {/* Greeting + publish toggle */}
        <section className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 sm:text-3xl">
              שלום{user?.name ? `, ${user.name}` : ''} 👋
            </h1>
            {business?.name ? (
              <p className="mt-2 text-base text-slate-600">
                ניהול בוט הוואטסאפ של <span className="font-medium">{business.name}</span>
              </p>
            ) : null}
          </div>
          {isPublished !== null ? (
            <div className="rounded-xl border border-black/10 bg-white px-4 py-3">
              <p className="mb-1 text-xs text-slate-500">מצב הבוט</p>
              <PublishToggle isPublished={isPublished} onChange={setIsPublished} />
            </div>
          ) : null}
        </section>

        {/* Funnel / KPI */}
        <section aria-labelledby="funnel-heading" className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="funnel-heading" className="text-lg font-medium text-slate-900">
              משפך הלידים
            </h2>
            <SegmentedControl
              label="טווח זמן"
              segments={PERIOD_SEGMENTS}
              value={period}
              onChange={setPeriod}
            />
          </div>

          {loading ? (
            <Spinner label="טוען נתונים…" className="py-12" />
          ) : error ? (
            <Alert tone="error">{error}</Alert>
          ) : stats ? (
            <div
              className="grid grid-cols-2 gap-3 sm:grid-cols-4"
              aria-label="סיכום משפך הלידים"
            >
              <StatCard
                icon="user-plus"
                chipClassName="bg-[#639922]"
                value={stats.started}
                label="התחילו"
              />
              <StatCard
                icon="checks"
                chipClassName="bg-[#1D9E75]"
                value={stats.completed}
                label="הושלמו"
              />
              <StatCard
                icon="user-off"
                chipClassName="bg-[#D85A30]"
                value={stats.abandoned}
                label="ננטשו"
              />
              <StatCard
                icon="checks"
                chipClassName="bg-[#378ADD]"
                value={stats.orders}
                label="הזמנות"
              />
            </div>
          ) : null}
        </section>

        {/* "מחכים לך" — conversations where a customer asked for a human and no
            one has taken over yet. Each links to that conversation. */}
        {waiting.length > 0 ? (
          <section aria-labelledby="waiting-heading" className="flex flex-col gap-3">
            <h2
              id="waiting-heading"
              className="flex items-center gap-2 text-lg font-medium text-slate-900"
            >
              <span
                aria-hidden="true"
                className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-100 text-amber-700"
              >
                <Icon name="users" size={15} />
              </span>
              מחכים לך
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
                {waiting.length}
              </span>
            </h2>

            <ul className="flex flex-col gap-2">
              {waiting.map((conv) => (
                <li key={conv.conversation_id}>
                  <Link
                    to={`/conversations?status=waiting&conversation=${encodeURIComponent(
                      conv.conversation_id,
                    )}`}
                    className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50/60 px-3 py-2.5 outline-none transition-colors hover:bg-amber-50 focus-visible:ring-2 focus-visible:ring-amber-400 focus-visible:ring-offset-2"
                  >
                    <span
                      aria-hidden="true"
                      className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-amber-500 text-white"
                    >
                      <Icon name="message-circle" size={20} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-slate-900">
                        לקוח ממתין לנציג
                      </span>
                      <span className="block truncate text-xs text-slate-500">
                        {conv.preview || conv.conversation_id}
                      </span>
                    </span>
                    {conv.last_activity_at ? (
                      <time
                        dateTime={conv.last_activity_at}
                        className="flex-shrink-0 text-xs text-slate-400"
                      >
                        {relativeTime(conv.last_activity_at)}
                      </time>
                    ) : null}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {/* "עדכוני פגישות" — a customer cancelled or moved an appointment. Each
            links to the appointments calendar. */}
        {bookingAlerts.length > 0 ? (
          <section aria-labelledby="booking-alerts-heading" className="flex flex-col gap-3">
            <h2
              id="booking-alerts-heading"
              className="flex items-center gap-2 text-lg font-medium text-slate-900"
            >
              <span
                aria-hidden="true"
                className="flex h-6 w-6 items-center justify-center rounded-full bg-[#D85A30]/15 text-[#D85A30]"
              >
                <Icon name="calendar-event" size={15} />
              </span>
              עדכוני פגישות
              <span className="rounded-full bg-[#D85A30]/15 px-2 py-0.5 text-xs font-semibold text-[#D85A30]">
                {bookingAlerts.length}
              </span>
            </h2>

            <ul className="flex flex-col gap-2">
              {bookingAlerts.map((a) => (
                <li key={`${a.booking_id}-${a.at ?? ''}`}>
                  <Link
                    to="/appointments"
                    className="flex items-center gap-3 rounded-xl border border-orange-200 bg-orange-50/60 px-3 py-2.5 outline-none transition-colors hover:bg-orange-50 focus-visible:ring-2 focus-visible:ring-orange-400 focus-visible:ring-offset-2"
                  >
                    <span
                      aria-hidden="true"
                      className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-xl bg-[#D85A30] text-white"
                    >
                      <Icon name={a.kind === 'cancelled' ? 'x' : 'clock'} size={20} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-slate-900">
                        {a.kind === 'cancelled' ? 'לקוח ביטל פגישה' : 'לקוח שינה מועד פגישה'}
                        {a.client_name ? ` · ${a.client_name}` : ''}
                      </span>
                      <span className="block truncate text-xs text-slate-500">
                        {[a.service_name, a.scheduled_at ? fullDateTime(a.scheduled_at) : null]
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                    </span>
                    {a.at ? (
                      <time dateTime={a.at} className="flex-shrink-0 text-xs text-slate-400">
                        {relativeTime(a.at)}
                      </time>
                    ) : null}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <ActivityFeed
          leads={recentLeads}
          onMarkSeen={(id) => {
            // Optimistic: hide immediately, then persist.
            setRecentLeads((prev) =>
              prev.map((l) => (l.id === id ? { ...l, feed_seen_at: new Date().toISOString() } : l)),
            )
            markLeadSeen(id).catch(() => {
              // On failure, revert the optimistic update.
              setRecentLeads((prev) =>
                prev.map((l) => (l.id === id ? { ...l, feed_seen_at: null } : l)),
              )
            })
          }}
          onMarkAllSeen={() => {
            const now = new Date().toISOString()
            setRecentLeads((prev) =>
              prev.map((l) => (l.feed_seen_at == null ? { ...l, feed_seen_at: now } : l)),
            )
            markAllLeadsSeen().catch(() => {
              // On failure, reload the real state from the server.
              getLeads({ status: 'all' })
                .then((res) => setRecentLeads(res.leads))
                .catch(() => {})
            })
          }}
        />
      </div>
    </DashboardLayout>
  )
}
