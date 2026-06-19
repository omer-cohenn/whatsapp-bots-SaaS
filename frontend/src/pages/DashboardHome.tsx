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
import { useAuth } from '../auth/AuthContext'
import DashboardLayout from '../components/DashboardLayout'
import ActivityFeed from '../components/dashboard/ActivityFeed'
import StatCard from '../components/dashboard/StatCard'
import SegmentedControl, { type Segment } from '../components/dashboard/SegmentedControl'
import PublishToggle from '../components/dashboard/PublishToggle'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'
import { getDashboard, getLeads } from '../lib/dashboardClient'
import { getSettings } from '../lib/botClient'
import { toFriendlyError } from '../lib/friendlyError'
import type { DashboardStats, Lead, Period } from '../dashboard/types'

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

        <ActivityFeed leads={recentLeads} />
      </div>
    </DashboardLayout>
  )
}
