// The owner's bookings tab: a filterable list of bookings (grouped by day),
// each manageable inline (status / reschedule). One read: GET /api/bookings
// (filtered server-side by status). Reschedule respects the owner's max_days_ahead
// from settings. Tenant is server-side only.

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { BookingItem, BookingStatus } from '../../dashboard/appointmentTypes'
import { getBookings, getBookingSettings } from '../../lib/bookingClient'
import { toFriendlyError } from '../../lib/friendlyError'
import SegmentedControl, { type Segment } from '../dashboard/SegmentedControl'
import Spinner from '../ui/Spinner'
import Alert from '../ui/Alert'
import Icon from '../ui/Icon'
import BookingCard from './BookingCard'

type StatusFilter = 'all' | BookingStatus

const FILTERS: Segment<StatusFilter>[] = [
  { value: 'all', label: 'הכול' },
  { value: 'pending', label: 'ממתינות' },
  { value: 'confirmed', label: 'מאושרות' },
  { value: 'completed', label: 'הושלמו' },
  { value: 'cancelled', label: 'בוטלו' },
]

// Group bookings by their local calendar day for a readable, dated list.
function groupByDay(bookings: BookingItem[]): { day: string; items: BookingItem[] }[] {
  const groups = new Map<string, BookingItem[]>()
  for (const b of bookings) {
    const day = new Date(b.scheduled_at).toLocaleDateString('he-IL', {
      weekday: 'long',
      day: 'numeric',
      month: 'long',
    })
    const list = groups.get(day) ?? []
    list.push(b)
    groups.set(day, list)
  }
  return [...groups.entries()].map(([day, items]) => ({ day, items }))
}

export default function BookingsPanel() {
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [bookings, setBookings] = useState<BookingItem[] | null>(null)
  const [maxDaysAhead, setMaxDaysAhead] = useState(30)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback((status: StatusFilter) => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getBookings({ status: status === 'all' ? undefined : status, includeTest: true })
      .then((res) => {
        if (!cancelled) setBookings(res.bookings)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת הפגישות נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => load(filter), [load, filter])

  // Read max_days_ahead once so reschedule's picker matches the owner's rule.
  useEffect(() => {
    getBookingSettings()
      .then((s) => setMaxDaysAhead(s.max_days_ahead))
      .catch(() => {
        /* keep the default; not fatal for listing */
      })
  }, [])

  const refresh = useCallback(() => load(filter), [load, filter])

  // Sort ascending by time so days read top-to-bottom in chronological order.
  const grouped = useMemo(() => {
    const sorted = [...(bookings ?? [])].sort(
      (a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime(),
    )
    return groupByDay(sorted)
  }, [bookings])

  return (
    <div className="flex flex-col gap-5">
      <SegmentedControl
        label="סינון לפי סטטוס"
        segments={FILTERS}
        value={filter}
        onChange={setFilter}
      />

      <section aria-busy={loading}>
        {loading ? (
          <Spinner label="טוען פגישות…" className="py-12" />
        ) : error ? (
          <Alert tone="error">{error}</Alert>
        ) : grouped.length > 0 ? (
          <div className="flex flex-col gap-6">
            {grouped.map((group) => (
              <div key={group.day} className="flex flex-col gap-3">
                <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                  <Icon name="calendar-event" size={16} className="text-leaf" />
                  {group.day}
                </h3>
                <ul className="flex flex-col gap-3">
                  {group.items.map((booking) => (
                    <li key={booking.id}>
                      <BookingCard
                        booking={booking}
                        maxDaysAhead={maxDaysAhead}
                        onChanged={refresh}
                      />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-12 text-center text-sm text-slate-500">
            אין פגישות להצגה בסינון הנוכחי.
          </p>
        )}
      </section>
    </div>
  )
}
