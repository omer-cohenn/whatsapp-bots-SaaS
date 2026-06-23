// Leads-by-type card (M13, AdminHome). GET /api/admin/analytics/leads-by-type
// returns derived counts split three ways — פגישה (bookings), ליד (plain
// leads), נציג (handoff requests). A period SegmentedControl (שבוע/חודש/הכול)
// re-queries; a DonutChart + legend renders the split with a centre total.

import { useEffect, useState } from 'react'
import Card from '../ui/Card'
import Spinner from '../ui/Spinner'
import Alert from '../ui/Alert'
import Icon from '../ui/Icon'
import SegmentedControl, { type Segment } from '../dashboard/SegmentedControl'
import DonutChart from './DonutChart'
import { getLeadsByType } from '../../lib/adminClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { LEAD_TYPE_META } from '../../admin/labels'
import type { AnalyticsPeriod, LeadsByType } from '../../admin/types'

const PERIOD_SEGMENTS: Segment<AnalyticsPeriod>[] = [
  { value: 'week', label: 'שבוע' },
  { value: 'month', label: 'חודש' },
  { value: 'all', label: 'הכול' },
]

export default function LeadsByTypeCard() {
  const [period, setPeriod] = useState<AnalyticsPeriod>('month')
  const [data, setData] = useState<LeadsByType | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getLeadsByType({ period })
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת סוגי הלידים נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [period])

  const total = data ? data.booking + data.lead + data.handoff : 0

  return (
    <Card className="!p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-medium text-slate-700">
          <Icon name="users" size={18} className="text-leaf" />
          לידים לפי סוג
        </h3>
        <SegmentedControl
          label="טווח זמן"
          segments={PERIOD_SEGMENTS}
          value={period}
          onChange={setPeriod}
        />
      </div>

      {loading ? (
        <Spinner label="טוען סוגי לידים…" className="py-10" />
      ) : error ? (
        <Alert tone="error">{error}</Alert>
      ) : data && total > 0 ? (
        <DonutChart
          ariaLabel={`לידים לפי סוג: פגישה ${data.booking}, ליד ${data.lead}, נציג ${data.handoff}`}
          centerCaption="סה״כ"
          slices={[
            {
              label: LEAD_TYPE_META.booking.label,
              value: data.booking,
              color: LEAD_TYPE_META.booking.color,
            },
            {
              label: LEAD_TYPE_META.lead.label,
              value: data.lead,
              color: LEAD_TYPE_META.lead.color,
            },
            {
              label: LEAD_TYPE_META.handoff.label,
              value: data.handoff,
              color: LEAD_TYPE_META.handoff.color,
            },
          ]}
        />
      ) : (
        <p className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-10 text-center text-sm text-slate-500">
          אין לידים בטווח שנבחר.
        </p>
      )}
    </Card>
  )
}
