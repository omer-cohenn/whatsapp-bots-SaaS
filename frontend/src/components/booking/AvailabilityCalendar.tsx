// A CUSTOM month calendar for the public booking flow (NOT react-day-picker).
// It draws a 7-column Israeli-week grid (א..ש, Sun-first), with prev/next month
// navigation. Days that have availability (driven by GET /availability for the
// visible month) are shown in BLUE with a small dot; today gets a green ring; the
// selected day is filled blue; past/unavailable days are muted and not clickable.
//
// The calendar is purely presentational: the parent owns "which month is visible"
// and "which days are available" so it can fetch availability per month. Selection
// is reported up as a "YYYY-MM-DD" string (never a Date), matching bookingDates.
//
// A11y: the grid is a radiogroup of <button role="radio">; weekday headers are
// aria-hidden decoration; each day button has an aria-label with its full date;
// disabled days are real `disabled` buttons (skipped by keyboard + SR).

import type { YearMonth } from '../../lib/bookingDates'
import {
  monthGrid,
  monthLabel,
  sameDay,
  shiftMonth,
  toDateString,
  todayMidnight,
} from '../../lib/bookingDates'
import Icon from '../ui/Icon'

// Hebrew weekday initials, Sunday-first (matches the Israeli week + getDay()).
const WEEKDAYS = ['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש']

type Props = {
  /** The visible month. */
  month: YearMonth
  /** Change the visible month (prev/next). */
  onMonthChange: (next: YearMonth) => void
  /** "YYYY-MM-DD" days with ≥1 free slot in this month (a Set for O(1) lookup). */
  availableDates: Set<string>
  /** Currently selected day "YYYY-MM-DD", or '' for none. */
  value: string
  /** Called with the picked day "YYYY-MM-DD". */
  onChange: (date: string) => void
  /** While true, the nav is disabled and we don't claim "no availability". */
  loading?: boolean
}

export default function AvailabilityCalendar({
  month,
  onMonthChange,
  availableDates,
  value,
  onChange,
  loading = false,
}: Props) {
  const today = todayMidnight()
  const cells = monthGrid(month)
  const label = monthLabel(month)
  const hasAny = availableDates.size > 0

  return (
    <div>
      {/* Month nav. In RTL, "previous" sits on the right and uses chevron-right. */}
      <div className="mb-3 flex items-center justify-between">
        <button
          type="button"
          onClick={() => onMonthChange(shiftMonth(month, -1))}
          disabled={loading}
          aria-label="חודש קודם"
          style={{ color: 'var(--bp-muted, #64748b)' }}
          className="rounded-lg p-1.5 transition hover:brightness-75 disabled:opacity-40"
        >
          <Icon name="chevron-right" size={20} />
        </button>
        <span
          aria-live="polite"
          className="text-sm font-bold"
          style={{ color: 'var(--bp-text, #0f172a)' }}
        >
          {label}
        </span>
        <button
          type="button"
          onClick={() => onMonthChange(shiftMonth(month, 1))}
          disabled={loading}
          aria-label="חודש הבא"
          style={{ color: 'var(--bp-muted, #64748b)' }}
          className="rounded-lg p-1.5 transition hover:brightness-75 disabled:opacity-40"
        >
          <Icon name="chevron-left" size={20} />
        </button>
      </div>

      {/* Weekday header row (decorative). */}
      <div aria-hidden="true" className="mb-1 grid grid-cols-7 gap-1 text-center">
        {WEEKDAYS.map((d) => (
          <span
            key={d}
            className="text-xs font-medium opacity-70"
            style={{ color: 'var(--bp-muted, #94a3b8)' }}
          >
            {d}
          </span>
        ))}
      </div>

      {/* Day grid. */}
      <div role="radiogroup" aria-label="בחירת תאריך" className="grid grid-cols-7 gap-1">
        {cells.map((cell, i) => {
          if (!cell) return <span key={`pad-${i}`} aria-hidden="true" />

          const iso = toDateString(cell)
          const isToday = sameDay(cell, today)
          const isPast = cell < today
          const isAvailable = availableDates.has(iso)
          const selected = iso === value
          const disabled = isPast || !isAvailable

          const fullLabel = cell.toLocaleDateString('he-IL', {
            weekday: 'long',
            day: 'numeric',
            month: 'long',
          })

          // Palette-driven, with neutral fallbacks for the un-themed shell:
          // unavailable = muted and faded, available = the accent, selected =
          // filled with the accent.
          let tone: React.CSSProperties = {
            color: 'var(--bp-muted, #cbd5e1)',
            opacity: 0.45,
          }
          if (selected) {
            tone = {
              backgroundColor: 'var(--bp-primary, #2563eb)',
              color: 'var(--bp-on-primary, #ffffff)',
            }
          } else if (isAvailable) {
            tone = { color: 'var(--bp-primary, #2563eb)' }
          }

          return (
            <button
              key={iso}
              type="button"
              role="radio"
              aria-checked={selected}
              aria-label={
                isAvailable
                  ? `${fullLabel} — יש מועדים פנויים`
                  : `${fullLabel} — אין מועדים פנויים`
              }
              disabled={disabled}
              onClick={() => onChange(iso)}
              style={{
                ...tone,
                ...(isToday && !selected
                  ? { boxShadow: '0 0 0 2px var(--bp-primary, #2563eb)' }
                  : {}),
              }}
              className={[
                'relative flex aspect-square items-center justify-center rounded-[var(--bp-radius,12px)] text-sm font-semibold transition',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--bp-primary,#2563eb)]',
                disabled ? 'cursor-not-allowed' : 'cursor-pointer hover:brightness-95',
              ].join(' ')}
            >
              {cell.getDate()}
              {isAvailable && !selected ? (
                <span
                  aria-hidden="true"
                  className="absolute bottom-1.5 h-1 w-1 rounded-full"
                  style={{ backgroundColor: 'var(--bp-primary, #2563eb)' }}
                />
              ) : null}
            </button>
          )
        })}
      </div>

      {!loading && !hasAny ? (
        <p
          className="mt-3 rounded-xl border border-dashed px-4 py-4 text-center text-sm"
          style={{ borderColor: 'var(--bp-border, #cbd5e1)', color: 'var(--bp-muted, #64748b)' }}
        >
          אין מועדים פנויים בחודש זה
        </p>
      ) : null}
    </div>
  )
}
