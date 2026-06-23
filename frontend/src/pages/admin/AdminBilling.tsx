// Usage & billing page (M13, route /admin/billing). The messages-per-business
// table from GET /api/admin/analytics/messages — incoming + outgoing + total,
// sorted by total DESC server-side. This is the usage basis for billing, so we
// say so plainly. A period SegmentedControl (שבוע/חודש/הכול) re-queries.
//
// Admin-gated server-side (401/403); a deliberate cross-tenant operator view —
// counts only, no end-customer PII.

import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import DashboardLayout from '../../components/DashboardLayout'
import Spinner from '../../components/ui/Spinner'
import Alert from '../../components/ui/Alert'
import Icon from '../../components/ui/Icon'
import SegmentedControl, { type Segment } from '../../components/dashboard/SegmentedControl'
import { getMessagesByBusiness } from '../../lib/adminClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { planCodeLabel } from '../../admin/labels'
import type { AnalyticsPeriod, MessagesByBusinessRow } from '../../admin/types'

const PERIOD_SEGMENTS: Segment<AnalyticsPeriod>[] = [
  { value: 'week', label: 'שבוע' },
  { value: 'month', label: 'חודש' },
  { value: 'all', label: 'הכול' },
]

export default function AdminBilling() {
  const [period, setPeriod] = useState<AnalyticsPeriod>('month')
  const [rows, setRows] = useState<MessagesByBusinessRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getMessagesByBusiness(period)
      .then((res) => {
        if (!cancelled) setRows(res.businesses)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת נתוני החיוב נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [period])

  // Platform-wide totals for the summary line.
  const totals = useMemo(() => {
    return rows.reduce(
      (acc, r) => ({
        in: acc.in + r.msg_in,
        out: acc.out + r.msg_out,
        total: acc.total + r.total,
      }),
      { in: 0, out: 0, total: 0 },
    )
  }, [rows])

  return (
    <DashboardLayout>
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-6 py-10">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
            <Icon name="chart-bar" size={22} className="text-leaf" />
            שימוש וחיוב
          </h1>
          <Link
            to="/admin"
            className="inline-flex items-center gap-1 rounded text-sm font-medium text-leaf-ink underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2"
          >
            <Icon name="chevron-right" size={16} />
            חזרה לניהול
          </Link>
        </div>

        <p className="text-sm text-slate-600">
          סך ההודעות לכל עסק — <span className="font-medium">בסיס החיוב</span> של
          הפלטפורמה. הטבלה ממוינת לפי סך ההודעות, מהגבוה לנמוך.
        </p>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <SegmentedControl
            label="טווח זמן"
            segments={PERIOD_SEGMENTS}
            value={period}
            onChange={setPeriod}
          />
          {!loading && !error && rows.length > 0 ? (
            <p className="text-sm text-slate-500" aria-live="polite">
              סך הפלטפורמה:{' '}
              <span className="font-medium tabular-nums text-slate-800">
                {totals.total.toLocaleString('he-IL')}
              </span>{' '}
              הודעות
            </p>
          ) : null}
        </div>

        <section aria-labelledby="billing-heading" aria-busy={loading}>
          <h2 id="billing-heading" className="sr-only">
            סך ההודעות לכל עסק
          </h2>
          {loading ? (
            <Spinner label="טוען נתוני חיוב…" className="py-12" />
          ) : error ? (
            <Alert tone="error">{error}</Alert>
          ) : rows.length > 0 ? (
            <div className="overflow-x-auto rounded-2xl border border-slate-200 bg-white">
              <table className="w-full min-w-[640px] border-collapse text-sm">
                <caption className="sr-only">
                  סך ההודעות לכל עסק, בסיס החיוב, ממוין לפי סך הכול
                </caption>
                <thead>
                  <tr className="border-b border-slate-200 text-right text-xs font-medium text-slate-500">
                    <th scope="col" className="px-4 py-3">עסק</th>
                    <th scope="col" className="px-4 py-3">תוכנית</th>
                    <th scope="col" className="px-4 py-3">נכנסות</th>
                    <th scope="col" className="px-4 py-3">יוצאות</th>
                    <th scope="col" className="px-4 py-3">סה״כ</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr
                      key={row.business_id}
                      className="border-b border-slate-100 last:border-0 transition-colors hover:bg-slate-50"
                    >
                      <td className="px-4 py-3 font-medium text-slate-900">
                        <Link
                          to={`/admin/businesses/${encodeURIComponent(row.business_id)}`}
                          className="rounded text-leaf-ink underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2"
                        >
                          {row.name || 'ללא שם'}
                        </Link>
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {planCodeLabel(row.plan_code)}
                      </td>
                      <td className="px-4 py-3 tabular-nums text-slate-900">{row.msg_in}</td>
                      <td className="px-4 py-3 tabular-nums text-slate-900">{row.msg_out}</td>
                      <td className="px-4 py-3 font-semibold tabular-nums text-slate-900">
                        {row.total}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-slate-200 bg-slate-50 text-right font-medium text-slate-700">
                    <td className="px-4 py-3" colSpan={2}>
                      סך הכול
                    </td>
                    <td className="px-4 py-3 tabular-nums">{totals.in}</td>
                    <td className="px-4 py-3 tabular-nums">{totals.out}</td>
                    <td className="px-4 py-3 tabular-nums">{totals.total}</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          ) : (
            <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-12 text-center text-sm text-slate-500">
              אין נתוני הודעות בטווח שנבחר.
            </p>
          )}
        </section>
      </div>
    </DashboardLayout>
  )
}
