// Back-office home (M12, route /admin). The platform operator's "control room":
// platform-wide KPI cards from GET /api/admin/overview, plus a compact slice of
// the newest businesses (GET /api/admin/businesses) that links into each
// business's detail page. A "כל העסקים" link opens the full searchable list.
//
// Renders inside <DashboardLayout> (sidebar, header, skip-link, <main>). Every
// /api/admin/* read is admin-gated server-side; the tenant wall is crossed only
// here, on purpose, for the operator.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import DashboardLayout from '../../components/DashboardLayout'
import StatCard from '../../components/dashboard/StatCard'
import BusinessesTable from '../../components/admin/BusinessesTable'
import TrendsCard from '../../components/admin/TrendsCard'
import LeadsByTypeCard from '../../components/admin/LeadsByTypeCard'
import ByPlanCard from '../../components/admin/ByPlanCard'
import AiOpsCard from '../../components/admin/AiOpsCard'
import Spinner from '../../components/ui/Spinner'
import Alert from '../../components/ui/Alert'
import Icon from '../../components/ui/Icon'
import { getOverview, listBusinesses, getPlans } from '../../lib/adminClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { formatMoney } from '../../admin/labels'
import type { AdminOverview, BusinessRow, Plan } from '../../admin/types'

export default function AdminHome() {
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // A compact recent slice for the home table (full list lives at /admin/businesses).
  const [recent, setRecent] = useState<BusinessRow[]>([])
  const [plans, setPlans] = useState<Plan[]>([])

  // KPI overview (fatal if it fails — it's the page's headline).
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getOverview()
      .then((res) => {
        if (!cancelled) setOverview(res)
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

  // Recent businesses + plan catalog (non-fatal — the table just hides).
  useEffect(() => {
    let cancelled = false
    Promise.all([listBusinesses({ limit: 8 }), getPlans()])
      .then(([list, planRes]) => {
        if (cancelled) return
        setRecent(list.businesses)
        setPlans(planRes.plans)
      })
      .catch(() => {
        if (!cancelled) {
          setRecent([])
          setPlans([])
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <DashboardLayout>
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-6 py-10">
        <header>
          <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900 sm:text-3xl">
            <Icon name="shield" size={26} className="text-leaf" />
            ניהול הפלטפורמה
          </h1>
          <p className="mt-2 text-base text-slate-600">
            מבט‑על על כל העסקים ב‑Bizz_up — נתוני שימוש וניהול מנויים.
          </p>
        </header>

        {/* KPI cards */}
        <section aria-labelledby="kpi-heading" className="flex flex-col gap-4">
          <h2 id="kpi-heading" className="text-lg font-medium text-slate-900">
            סיכום פלטפורמה
          </h2>

          {loading ? (
            <Spinner label="טוען נתונים…" className="py-12" />
          ) : error ? (
            <Alert tone="error">{error}</Alert>
          ) : overview ? (
            <div
              className="grid grid-cols-2 gap-3 sm:grid-cols-4"
              aria-label="סיכום נתוני הפלטפורמה"
            >
              <StatCard
                icon="building-store"
                chipClassName="bg-[#27500A]"
                value={overview.total_businesses}
                label="סך עסקים"
              />
              <StatCard
                icon="checks"
                chipClassName="bg-[#1D9E75]"
                value={overview.active_count}
                label="פעילים"
              />
              <StatCard
                icon="clock"
                chipClassName="bg-[#D85A30]"
                value={overview.suspended_count}
                label="מושהים"
              />
              <StatCard
                icon="x"
                chipClassName="bg-slate-500"
                value={overview.cancelled_count}
                label="מבוטלים"
              />
              <StatCard
                icon="user-plus"
                chipClassName="bg-[#639922]"
                value={overview.new_7d}
                label="חדשים השבוע"
              />
              <StatCard
                icon="users"
                chipClassName="bg-[#378ADD]"
                value={overview.total_leads}
                label="סך לידים"
              />
              <StatCard
                icon="message-circle"
                chipClassName="bg-[#128C7E]"
                value={overview.msgs_today}
                label="הודעות היום"
              />
              <StatCard
                icon="activity"
                chipClassName="bg-[#7C3AED]"
                value={overview.msgs_month}
                label="הודעות החודש"
              />
              {/* LTV is money|null → render a StatCard-shaped card by hand so the
                  shared StatCard primitive can stay number-only. */}
              <div className="flex flex-col gap-2 rounded-xl border border-black/10 bg-white p-3">
                <span
                  aria-hidden="true"
                  className="flex h-8 w-8 items-center justify-center rounded-lg bg-[#534AB7] text-white"
                >
                  <Icon name="currency-shekel" size={18} />
                </span>
                <span className="text-2xl font-medium leading-none text-slate-900">
                  {formatMoney(overview.avg_ltv)}
                </span>
                <span className="text-xs text-slate-500">LTV ממוצע (הערכה)</span>
              </div>
            </div>
          ) : null}
        </section>

        {/* Analytics (M13): trends + leads-by-type + by-plan + AI ops. Each card
            owns its own fetch/loading/empty/error state. */}
        <section aria-labelledby="analytics-heading" className="flex flex-col gap-4">
          <h2
            id="analytics-heading"
            className="flex items-center gap-2 text-lg font-medium text-slate-900"
          >
            <Icon name="chart-bar" size={20} className="text-leaf" />
            אנליטיקה
          </h2>
          <div className="grid gap-4 lg:grid-cols-2">
            <TrendsCard />
            <LeadsByTypeCard />
            <ByPlanCard />
            <AiOpsCard />
          </div>
        </section>

        {/* Recent businesses */}
        <section aria-labelledby="recent-heading" className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2
              id="recent-heading"
              className="flex items-center gap-2 text-lg font-medium text-slate-900"
            >
              <Icon name="building-store" size={20} className="text-leaf" />
              עסקים אחרונים
            </h2>
            <Link
              to="/admin/businesses"
              className="inline-flex items-center gap-1 rounded text-sm font-medium text-leaf-ink underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2"
            >
              כל העסקים
              <Icon name="chevron-left" size={16} />
            </Link>
          </div>

          {recent.length > 0 ? (
            <BusinessesTable rows={recent} plans={plans} caption="העסקים שנרשמו לאחרונה" />
          ) : !loading ? (
            <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-12 text-center text-sm text-slate-500">
              אין עדיין עסקים להצגה.
            </p>
          ) : null}
        </section>
      </div>
    </DashboardLayout>
  )
}
