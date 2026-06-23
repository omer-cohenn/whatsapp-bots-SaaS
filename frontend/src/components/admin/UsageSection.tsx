// The usage-charts section on the business detail page (M12). The admin picks a
// window (30 / 90 days) via the SegmentedControl; we fetch GET .../usage for
// that range and render one in-house bar chart per metric (msg_in, msg_out,
// lead, booking, login). Absent metrics chart as all-zero — we always show the
// metric and its total so a quiet business reads as "0", not "missing".
//
// NO chart library: UsageBarChart is a plain SVG, deliberately, to avoid the
// project's stale-node_modules dependency trap.

import { useEffect, useMemo, useState } from 'react'
import Card from '../ui/Card'
import Spinner from '../ui/Spinner'
import Alert from '../ui/Alert'
import Icon from '../ui/Icon'
import SegmentedControl, { type Segment } from '../dashboard/SegmentedControl'
import UsageBarChart from './UsageBarChart'
import LineChart from './LineChart'
import { getUsage } from '../../lib/adminClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { METRIC_META, METRIC_ORDER } from '../../admin/labels'
import type { UsageMetric, UsageResponse } from '../../admin/types'

type WindowDays = '30' | '90'

const WINDOW_SEGMENTS: Segment<WindowDays>[] = [
  { value: '30', label: '30 ימים' },
  { value: '90', label: '90 ימים' },
]

// Two ways to read the same numbers: a per-day bar chart ("מקלות"), or the
// running total accumulating over the window ("מצטבר") — a line that only ever
// climbs, so growth over time is obvious at a glance.
type ChartMode = 'bars' | 'cumulative'

const MODE_SEGMENTS: Segment<ChartMode>[] = [
  { value: 'bars', label: 'מקלות' },
  { value: 'cumulative', label: 'מצטבר' },
]

// Format a Date as YYYY-MM-DD in local time (what the API expects).
function toYmd(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export default function UsageSection({ businessId }: { businessId: string }) {
  const [days, setDays] = useState<WindowDays>('30')
  const [mode, setMode] = useState<ChartMode>('bars')
  const [data, setData] = useState<UsageResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Compute the [from, to] window from the selected day-count.
  const { from, to } = useMemo(() => {
    const today = new Date()
    const start = new Date(today)
    start.setDate(start.getDate() - (Number(days) - 1))
    return { from: toYmd(start), to: toYmd(today) }
  }, [days])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getUsage(businessId, from, to)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת נתוני השימוש נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [businessId, from, to])

  // Per-metric series (oldest → newest) + a total, always for every metric so a
  // zero-activity metric still shows a "0" chart rather than disappearing.
  const charts = useMemo(() => {
    const series = data?.series ?? []
    return METRIC_ORDER.map((metric: UsageMetric) => {
      const points = series.map((d) => ({
        day: d.day,
        value: d.metrics[metric] ?? 0,
      }))
      // Running total per day (for the "מצטבר" line). The last value is the sum.
      let run = 0
      const cumulative = points.map((p) => (run += p.value))
      return { metric, points, cumulative, total: run }
    })
  }, [data])

  return (
    <section aria-labelledby="usage-heading" className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2
          id="usage-heading"
          className="flex items-center gap-2 text-lg font-medium text-slate-900"
        >
          <Icon name="activity" size={20} className="text-leaf" />
          נתוני שימוש
        </h2>
        <div className="flex flex-wrap items-center gap-2">
          <SegmentedControl
            label="סוג גרף"
            segments={MODE_SEGMENTS}
            value={mode}
            onChange={setMode}
          />
          <SegmentedControl
            label="טווח זמן"
            segments={WINDOW_SEGMENTS}
            value={days}
            onChange={setDays}
          />
        </div>
      </div>

      {loading ? (
        <Spinner label="טוען נתוני שימוש…" className="py-12" />
      ) : error ? (
        <Alert tone="error">{error}</Alert>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {charts.map(({ metric, points, cumulative, total }) => (
            <Card key={metric} className="!p-4">
              <div className="mb-3 flex items-baseline justify-between gap-2">
                <h3 className="text-sm font-medium text-slate-700">
                  {METRIC_META[metric].label}
                </h3>
                <span className="text-lg font-semibold tabular-nums text-slate-900">
                  {total}
                </span>
              </div>
              {mode === 'bars' ? (
                <UsageBarChart
                  points={points}
                  color={METRIC_META[metric].color}
                  ariaLabel={`${METRIC_META[metric].label}: סך ${total} לאורך ${days} הימים האחרונים`}
                />
              ) : (
                <LineChart
                  labels={points.map((p) => p.day)}
                  series={[
                    {
                      values: cumulative,
                      color: METRIC_META[metric].color,
                      name: METRIC_META[metric].label,
                    },
                  ]}
                  ariaLabel={`${METRIC_META[metric].label}: מצטבר ל-${total} לאורך ${days} הימים האחרונים`}
                />
              )}
            </Card>
          ))}
        </div>
      )}
    </section>
  )
}
