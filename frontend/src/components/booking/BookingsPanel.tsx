// The owner's bookings tab: a month/week/day CALENDAR (per the approved
// prototype) with a status filter, and BELOW it the selected day's bookings —
// each manageable inline (status / reschedule). One read: GET /api/bookings
// (filtered server-side by status). Reschedule respects the owner's
// max_days_ahead from settings. Tenant is server-side only.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { format, isSameDay } from 'date-fns'
import { he } from 'date-fns/locale'
import type { BookingItem, BookingStatus } from '../../dashboard/appointmentTypes'
import { getBookings, getBookingSettings } from '../../lib/bookingClient'
import { toFriendlyError } from '../../lib/friendlyError'
import SegmentedControl, { type Segment } from '../dashboard/SegmentedControl'
import Spinner from '../ui/Spinner'
import Alert from '../ui/Alert'
import Icon from '../ui/Icon'
import BookingCard from './BookingCard'
import BookingsCalendar from './BookingsCalendar'

type StatusFilter = 'all' | BookingStatus

const FILTERS: Segment<StatusFilter>[] = [
  { value: 'all', label: 'הכול' },
  { value: 'pending', label: 'ממתינות' },
  { value: 'confirmed', label: 'מאושרות' },
  { value: 'completed', label: 'הושלמו' },
  { value: 'cancelled', label: 'בוטלו' },
]

export default function BookingsPanel() {
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [bookings, setBookings] = useState<BookingItem[] | null>(null)
  const [selectedDay, setSelectedDay] = useState<Date>(() => new Date())
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

  // The selected day's bookings (chronological), from the status-filtered set.
  const dayBookings = useMemo(() => {
    return [...(bookings ?? [])]
      .filter((b) => isSameDay(new Date(b.scheduled_at), selectedDay))
      .sort((a, b) => new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime())
  }, [bookings, selectedDay])

  return (
    <div className="flex flex-col gap-5">
      <SegmentedControl
        label="סינון לפי סטטוס"
        segments={FILTERS}
        value={filter}
        onChange={setFilter}
      />

      {loading ? (
        <Spinner label="טוען פגישות…" className="py-12" />
      ) : error ? (
        <Alert tone="error">{error}</Alert>
      ) : (
        <>
          {/* The calendar (month / week / day) */}
          <BookingsCalendar
            bookings={bookings ?? []}
            selectedDay={selectedDay}
            onSelectDay={setSelectedDay}
          />

          {/* The selected day's bookings, below the calendar */}
          <section aria-label="פגישות היום שנבחר" className="flex flex-col gap-3">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-700">
              <Icon name="calendar-event" size={16} className="text-leaf" />
              {format(selectedDay, 'EEEE, d בMMMM', { locale: he })}
              <span className="font-normal text-slate-400">· {dayBookings.length} פגישות</span>
            </h3>

            {dayBookings.length > 0 ? (
              <ul className="flex flex-col gap-3">
                {dayBookings.map((booking) => (
                  <li key={booking.id}>
                    <BookingCard
                      booking={booking}
                      maxDaysAhead={maxDaysAhead}
                      onChanged={refresh}
                    />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-10 text-center text-sm text-slate-500">
                אין פגישות ביום זה. בחרו יום אחר בלוח למעלה.
              </p>
            )}
          </section>
        </>
      )}
    </div>
  )
}
