// Platform trends card (M13, AdminHome). Pulls GET /api/admin/analytics/trends
// — the daily snapshot series — and draws two lines on a shared x-axis: MRR
// (solid, money) and active businesses (dashed). The series accrues forward
// from M13, so an empty/short window is normal early on; we say so rather than
// erroring. The chart is decorative; the latest values + legend carry meaning.

import { useEffect, useMemo, useState } from 'react'
import Card from '../ui/Card'
import Spinner from '../ui/Spinner'
import Alert from '../ui/Alert'
import Icon from '../ui/Icon'
import LineChart from './LineChart'
import { getTrends } from '../../lib/adminClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { formatMoney } from '../../admin/labels'
import type { TrendPoint } from '../../admin/types'

const MRR_COLOR = '#1D9E75' // teal
const ACTIVE_COLOR = '#534AB7' // purple

export default function TrendsCard() {
  const [series, setSeries] = useState<TrendPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getTrends()
      .then((res) => {
        if (!cancelled) setSeries(res.series)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת המגמות נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const { labels, mrr, active, latest } = useMemo(() => {
    return {
      labels: series.map((p) => p.day),
      mrr: series.map((p) => p.mrr),
      active: series.map((p) => p.active_count),
      latest: series.length > 0 ? series[series.length - 1] : null,
    }
  }, [series])

  return (
    <Card className="!p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700">
          <Icon name="trending-up" size={18} className="text-leaf" />
          מגמות פלטפורמה
        </h3>
        {latest ? (
          <div className="flex items-center gap-4 text-xs">
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="h-2.5 w-2.5 rounded-sm"
                style={{ backgroundColor: MRR_COLOR }}
              />
              <span className="text-slate-500">MRR</span>
              <span className="font-semibold tabular-nums text-slate-900">
                {formatMoney(latest.mrr)}
              </span>
            </span>
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden="true"
                className="h-2.5 w-2.5 rounded-sm"
                style={{ backgroundColor: ACTIVE_COLOR }}
              />
              <span className="text-slate-500">פעילים</span>
              <span className="font-semibold tabular-nums text-slate-900">
                {latest.active_count}
              </span>
            </span>
          </div>
        ) : null}
      </div>

      {loading ? (
        <Spinner label="טוען מגמות…" className="py-10" />
      ) : error ? (
        <Alert tone="error">{error}</Alert>
      ) : series.length === 0 ? (
        <p className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
          עדיין אין נתוני מגמה. הנתונים נצברים יום‑יום מרגע ההפעלה ויופיעו כאן בהמשך.
        </p>
      ) : (
        <LineChart
          labels={labels}
          ariaLabel={`מגמת הכנסה חודשית ומספר עסקים פעילים לאורך ${series.length} ימים`}
          series={[
            { values: mrr, color: MRR_COLOR, name: 'MRR' },
            { values: active, color: ACTIVE_COLOR, name: 'פעילים', dashed: true },
          ]}
          formatValue={(v) => String(v)}
        />
      )}
    </Card>
  )
}
