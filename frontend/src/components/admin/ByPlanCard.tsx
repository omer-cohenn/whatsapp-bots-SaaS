// Messages-by-plan card (M13, AdminHome). Two reads of
// GET /api/admin/analytics/by-plan (metric=msg_in and metric=msg_out) merged by
// plan code, rendered as a StackedBarChart: incoming on the bottom, outgoing on
// top, one bar per plan. A period SegmentedControl re-queries both. This shows
// where the message volume (and therefore the billing weight) concentrates.

import { useEffect, useMemo, useState } from 'react'
import Card from '../ui/Card'
import Spinner from '../ui/Spinner'
import Alert from '../ui/Alert'
import Icon from '../ui/Icon'
import SegmentedControl, { type Segment } from '../dashboard/SegmentedControl'
import StackedBarChart, { type StackedCategory } from './StackedBarChart'
import { getByPlan } from '../../lib/adminClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { planCodeLabel } from '../../admin/labels'
import type { AnalyticsPeriod, ByPlanRow } from '../../admin/types'

const PERIOD_SEGMENTS: Segment<AnalyticsPeriod>[] = [
  { value: 'week', label: 'שבוע' },
  { value: 'month', label: 'חודש' },
  { value: 'all', label: 'הכול' },
]

const IN_COLOR = '#378ADD' // blue
const OUT_COLOR = '#1D9E75' // teal

export default function ByPlanCard() {
  const [period, setPeriod] = useState<AnalyticsPeriod>('month')
  const [inRows, setInRows] = useState<ByPlanRow[]>([])
  const [outRows, setOutRows] = useState<ByPlanRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([getByPlan('msg_in', period), getByPlan('msg_out', period)])
      .then(([inRes, outRes]) => {
        if (cancelled) return
        setInRows(inRes.rows)
        setOutRows(outRes.rows)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת הפילוח לפי תוכנית נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [period])

  // Merge msg_in/msg_out by plan code, keeping a stable plan order.
  const categories = useMemo<StackedCategory[]>(() => {
    const codes: string[] = []
    const seen = new Set<string>()
    for (const r of [...inRows, ...outRows]) {
      if (!seen.has(r.plan_code)) {
        seen.add(r.plan_code)
        codes.push(r.plan_code)
      }
    }
    const inMap = new Map(inRows.map((r) => [r.plan_code, r.value]))
    const outMap = new Map(outRows.map((r) => [r.plan_code, r.value]))
    return codes.map((code) => ({
      label: planCodeLabel(code),
      a: inMap.get(code) ?? 0,
      b: outMap.get(code) ?? 0,
    }))
  }, [inRows, outRows])

  const hasData = categories.some((c) => c.a + c.b > 0)

  return (
    <Card className="!p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700">
          <Icon name="message-circle" size={18} className="text-leaf" />
          הודעות לפי תוכנית
        </h3>
        <SegmentedControl
          label="טווח זמן"
          segments={PERIOD_SEGMENTS}
          value={period}
          onChange={setPeriod}
        />
      </div>

      {loading ? (
        <Spinner label="טוען פילוח לפי תוכנית…" className="py-10" />
      ) : error ? (
        <Alert tone="error">{error}</Alert>
      ) : hasData ? (
        <StackedBarChart
          categories={categories}
          aColor={IN_COLOR}
          aName="נכנסות"
          bColor={OUT_COLOR}
          bName="יוצאות"
          ariaLabel="הודעות נכנסות ויוצאות לפי תוכנית מנוי"
        />
      ) : (
        <p className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
          אין נתוני הודעות בטווח שנבחר.
        </p>
      )}
    </Card>
  )
}
