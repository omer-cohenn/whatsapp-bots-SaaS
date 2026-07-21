// Month / week / day calendar for the owner's bookings (matches the approved
// prototype: docs/prototype/bizzup-prototype.html → "ניהול פגישות" → "יומן").
//
//  - A view toggle (יום / שבוע / חודש) + period navigation (‹ חודש ›).
//  - Month: a 7-column grid (Israeli week, Sun→Sat). Each day shows its number +
//    the count of active bookings, coloured by load (green 1–2, amber 3+).
//  - Week: a 7-day strip with the same per-day counts.
//  - Day: just the navigation/label — the selected day's bookings render BELOW
//    (the parent owns the list, per the prototype layout).
//
// Clicking a day selects it; the parent shows that day's bookings underneath.
// Cancelled bookings are excluded from the load counts.

import { useMemo, useState } from 'react'
import {
  addDays,
  addMonths,
  addWeeks,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
  isSameMonth,
  isToday,
  startOfMonth,
  startOfWeek,
} from 'date-fns'
import { he } from 'date-fns/locale'
import type { BookingItem } from '../../dashboard/appointmentTypes'
import Icon from '../ui/Icon'

type View = 'day' | 'week' | 'month'

// Israeli week starts on Sunday.
const WEEK_OPTS = { weekStartsOn: 0 as const }
const HEB_DOW = ['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש']

const VIEWS: { id: View; label: string }[] = [
  { id: 'day', label: 'יום' },
  { id: 'week', label: 'שבוע' },
  { id: 'month', label: 'חודש' },
]

function dayKey(d: Date | string): string {
  return format(typeof d === 'string' ? new Date(d) : d, 'yyyy-MM-dd')
}

type Props = {
  bookings: BookingItem[]
  selectedDay: Date
  onSelectDay: (d: Date) => void
}

export default function BookingsCalendar({ bookings, selectedDay, onSelectDay }: Props) {
  const [view, setView] = useState<View>('month')
  // The focused month/week/day the grid is built around.
  const [cursor, setCursor] = useState<Date>(selectedDay)

  // Active (non-cancelled) bookings per local day → the load colours.
  const countByDay = useMemo(() => {
    const m = new Map<string, number>()
    for (const b of bookings) {
      if (b.status === 'cancelled') continue
      const k = dayKey(b.scheduled_at)
      m.set(k, (m.get(k) ?? 0) + 1)
    }
    return m
  }, [bookings])

  function changeView(next: View) {
    setView(next)
    // Day view focuses the currently selected day.
    if (next === 'day') setCursor(selectedDay)
  }

  function step(dir: 1 | -1) {
    if (view === 'day') {
      const next = addDays(cursor, dir)
      setCursor(next)
      onSelectDay(next)
      return
    }
    setCursor((c) => (view === 'month' ? addMonths(c, dir) : addWeeks(c, dir)))
  }

  function pickDay(day: Date) {
    onSelectDay(day)
    setCursor(day)
  }

  const label =
    view === 'month'
      ? format(cursor, 'LLLL yyyy', { locale: he })
      : view === 'week'
        ? `${format(startOfWeek(cursor, WEEK_OPTS), 'd MMM', { locale: he })} – ${format(
            endOfWeek(cursor, WEEK_OPTS),
            'd MMM',
            { locale: he },
          )}`
        : format(cursor, 'EEEE, d בMMMM', { locale: he })

  // The cells to render (6 weeks for month, 1 week for week).
  const cells = useMemo(() => {
    if (view === 'day') return []
    const start =
      view === 'month' ? startOfWeek(startOfMonth(cursor), WEEK_OPTS) : startOfWeek(cursor, WEEK_OPTS)
    const end =
      view === 'month' ? endOfWeek(endOfMonth(cursor), WEEK_OPTS) : endOfWeek(cursor, WEEK_OPTS)
    return eachDayOfInterval({ start, end })
  }, [view, cursor])

  function loadClasses(count: number): string {
    if (count >= 3) return 'bg-amber-100 text-amber-800'
    if (count >= 1) return 'bg-leaf-soft text-leaf-ink'
    return 'bg-white text-slate-700'
  }

  return (
    <div className="rounded-xl border border-black/10 bg-white p-3 sm:p-4">
      {/* Toolbar: view toggle + period navigation.
          The two together need ~330px and the card only offers ~285px on a
          phone, so instead of letting them wrap into a ragged line they stack:
          the toggle on top, then the navigation spread edge to edge so ‹ › land
          under the thumbs rather than bunched in the middle. */}
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-3">
        <div role="tablist" aria-label="תצוגת יומן" className="flex rounded-full bg-slate-100 p-1 sm:inline-flex">
          {VIEWS.map((v) => {
            const on = v.id === view
            return (
              <button
                key={v.id}
                type="button"
                role="tab"
                aria-selected={on}
                onClick={() => changeView(v.id)}
                className={`flex-1 rounded-full px-3 py-2 text-sm font-medium transition sm:flex-none sm:py-1 ${
                  on ? 'bg-leaf text-white' : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {v.label}
              </button>
            )
          })}
        </div>

        <div className="flex items-center justify-between gap-1 sm:justify-start">
          <button
            type="button"
            onClick={() => step(1)}
            aria-label="הבא"
            className="rounded-lg p-2.5 text-slate-500 hover:bg-slate-100 sm:p-1.5"
          >
            <Icon name="chevron-right" size={18} />
          </button>
          <span className="min-w-0 flex-1 text-center text-sm font-semibold text-slate-800 sm:min-w-[7.5rem] sm:flex-none">
            {label}
          </span>
          <button
            type="button"
            onClick={() => step(-1)}
            aria-label="הקודם"
            className="rounded-lg p-2.5 text-slate-500 hover:bg-slate-100 sm:p-1.5"
          >
            <Icon name="chevron-left" size={18} />
          </button>
        </div>
      </div>

      {view !== 'day' ? (
        <>
          {/* Weekday headers */}
          <div className="grid grid-cols-7 gap-1 sm:gap-1.5">
            {HEB_DOW.map((d) => (
              <div key={d} className="pb-1 text-center text-[11px] font-medium text-slate-400">
                {d}
              </div>
            ))}
          </div>

          {/* Day cells */}
          {/* gap-1 on a phone: 7 columns in ~285px, and every 2px of gutter comes
              straight out of the tap target of every day cell. */}
          <div className="grid grid-cols-7 gap-1 sm:gap-1.5">
            {cells.map((day) => {
              const count = countByDay.get(dayKey(day)) ?? 0
              const muted = view === 'month' && !isSameMonth(day, cursor)
              const selected = isSameDay(day, selectedDay)
              return (
                <button
                  key={day.toISOString()}
                  type="button"
                  onClick={() => pickDay(day)}
                  aria-pressed={selected}
                  aria-label={`${format(day, 'EEEE d MMMM', { locale: he })}${
                    count ? `, ${count} פגישות` : ''
                  }`}
                  className={[
                    view === 'month' ? 'aspect-square' : 'min-h-[4.5rem]',
                    'flex flex-col items-center justify-center rounded-lg border text-sm transition',
                    loadClasses(count),
                    selected ? 'border-leaf ring-2 ring-leaf/40' : 'border-black/10 hover:border-slate-300',
                    muted ? 'opacity-40' : '',
                  ].join(' ')}
                >
                  <span className={isToday(day) ? 'font-bold text-leaf-ink' : ''}>
                    {format(day, 'd')}
                  </span>
                  {count > 0 ? (
                    <span className="mt-0.5 text-[10px] leading-none opacity-80">{count}</span>
                  ) : null}
                </button>
              )
            })}
          </div>

          {/* Legend */}
          <div className="mt-3 flex items-center justify-end gap-3 text-[11px] text-slate-400">
            <span className="flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-sm bg-leaf-soft" /> 1–2
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-2.5 w-2.5 rounded-sm bg-amber-100" /> 3+
            </span>
          </div>
        </>
      ) : null}
    </div>
  )
}
