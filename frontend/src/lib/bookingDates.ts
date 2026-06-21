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
