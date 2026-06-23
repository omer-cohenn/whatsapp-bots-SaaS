// AI-operations card (M13, AdminHome). GET /api/admin/analytics/ai-ops returns
// successful Gemini calls per day. We reuse the existing in-house UsageBarChart
// (one bar per day) rather than build a new chart — a plain bar fits perfectly.
// The metric accrues forward from M13, so an empty window is normal early on.

import { useEffect, useMemo, useState } from 'react'
import Card from '../ui/Card'
import Spinner from '../ui/Spinner'
import Alert from '../ui/Alert'
import Icon from '../ui/Icon'
import UsageBarChart from './UsageBarChart'
import { getAiOps } from '../../lib/adminClient'
import { toFriendlyError } from '../../lib/friendlyError'
import type { AiOpsPoint } from '../../admin/types'

const AI_COLOR = '#534AB7' // purple

export default function AiOpsCard() {
  const [series, setSeries] = useState<AiOpsPoint[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getAiOps()
      .then((res) => {
        if (!cancelled) setSeries(res.series)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת פעולות ה‑AI נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const { points, total } = useMemo(() => {
    const pts = series.map((p) => ({ day: p.day, value: p.count }))
    return { points: pts, total: pts.reduce((sum, p) => sum + p.value, 0) }
  }, [series])

  return (
    <Card className="!p-4">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700">
          <Icon name="sparkles-ai" size={18} className="text-leaf" />
          פעולות AI ליום
        </h3>
        <span className="text-lg font-semibold tabular-nums text-slate-900">
          {total}
        </span>
      </div>

      {loading ? (
        <Spinner label="טוען פעולות AI…" className="py-10" />
      ) : error ? (
        <Alert tone="error">{error}</Alert>
      ) : points.length > 0 ? (
        <UsageBarChart
          points={points}
          color={AI_COLOR}
          ariaLabel={`פעולות AI ליום: סך ${total} לאורך התקופה`}
        />
      ) : (
        <p className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
          עדיין אין פעולות AI מתועדות. הספירה מצטברת קדימה.
        </p>
      )}
    </Card>
  )
}
