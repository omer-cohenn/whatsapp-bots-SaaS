// Date helpers for the M11 booking flows. The backend speaks two formats:
//   - calendar dates as plain "YYYY-MM-DD" strings (Asia/Jerusalem local day)
//   - instants as UTC ISO strings (scheduled_at)
//
// react-day-picker hands us a JS Date at the *browser's* local midnight for the
// day the user clicked. We turn that into a "YYYY-MM-DD" using the date's local
// Y/M/D fields (NOT toISOString(), which would shift across the UTC boundary and
// can land on the wrong day). The customer picks a wall-clock day; the server
// interprets that day in Asia/Jerusalem.

/** A clicked react-day-picker Date → "YYYY-MM-DD" (using local Y/M/D fields). */
export function toDateString(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** "YYYY-MM-DD" → a JS Date at local midnight (for react-day-picker `selected`). */
export function fromDateString(s: string): Date | undefined {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)
  if (!m) return undefined
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
}

/** Today at local midnight — the earliest selectable day in the picker. */
export function todayMidnight(): Date {
  const now = new Date()
  return new Date(now.getFullYear(), now.getMonth(), now.getDate())
}

/** `base` + n days, at local midnight (for the picker's max-days-ahead bound). */
export function addDays(base: Date, n: number): Date {
  return new Date(base.getFullYear(), base.getMonth(), base.getDate() + n)
}

// --- custom month-grid helpers (M11.1 BookingFlow calendar) ------------------
// The public booking flow draws its own 7-column month grid (no react-day-picker
// there). These keep all the date math in one tested place. A "month" is the JS
// (year, month0) pair where month0 is 0-based (Jan = 0).

/** A year + 0-based month, the unit our custom calendar navigates by. */
export type YearMonth = { year: number; month0: number }

/** The YearMonth that contains `d` (defaults to today). */
export function monthOf(d: Date = new Date()): YearMonth {
  return { year: d.getFullYear(), month0: d.getMonth() }
}

/** Step a YearMonth by `delta` months (handles year wrap). */
export function shiftMonth(ym: YearMonth, delta: number): YearMonth {
  const d = new Date(ym.year, ym.month0 + delta, 1)
  return { year: d.getFullYear(), month0: d.getMonth() }
}

/** "<month name> <year>" in Hebrew, e.g. "יוני 2026". */
export function monthLabel(ym: YearMonth): string {
  return new Date(ym.year, ym.month0, 1).toLocaleDateString('he-IL', {
    month: 'long',
    year: 'numeric',
  })
}

/** First "YYYY-MM-DD" of the month — the inclusive `from` for availability. */
export function monthStart(ym: YearMonth): string {
  return toDateString(new Date(ym.year, ym.month0, 1))
}

/** Last "YYYY-MM-DD" of the month — the inclusive `to` for availability. */
export function monthEnd(ym: YearMonth): string {
  // Day 0 of the next month = the last day of this month.
  return toDateString(new Date(ym.year, ym.month0 + 1, 0))
}

/**
 * The grid cells for a month: leading nulls to pad to the weekday of the 1st
 * (Sunday=0, matching the Israeli week), then each day as a Date. The caller
 * lays these out in a 7-column grid; nulls render as empty cells.
 */
export function monthGrid(ym: YearMonth): (Date | null)[] {
  const first = new Date(ym.year, ym.month0, 1)
  const leading = first.getDay() // 0 (Sun) .. 6 (Sat)
  const daysInMonth = new Date(ym.year, ym.month0 + 1, 0).getDate()
  const cells: (Date | null)[] = []
  for (let i = 0; i < leading; i++) cells.push(null)
  for (let day = 1; day <= daysInMonth; day++) {
    cells.push(new Date(ym.year, ym.month0, day))
  }
  return cells
}

/** True if `a` and `b` are the same wall-clock calendar day. */
export function sameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}
