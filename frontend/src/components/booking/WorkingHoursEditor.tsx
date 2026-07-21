// Split working-hours editor: one row per weekday (Sun..Sat), each holding a
// LIST of {s,e} time ranges the owner can add/remove. An empty list = "closed".
// This is a controlled component — the parent owns the WorkingHours object and
// gets a new copy on every edit (we never mutate in place).
//
// Accessibility: each time input is a real <input type="time"> with a label
// (visually hidden but read by screen readers), add/remove buttons have explicit
// aria-labels naming the weekday, and the "closed" state is announced as text.

import type { HoursRange, WorkingHours } from '../../dashboard/appointmentTypes'
import Icon from '../ui/Icon'

// Sun=0 .. Sat=6, matching the backend's "0".."6" keys.
const WEEKDAYS: { key: string; label: string }[] = [
  { key: '0', label: 'ראשון' },
  { key: '1', label: 'שני' },
  { key: '2', label: 'שלישי' },
  { key: '3', label: 'רביעי' },
  { key: '4', label: 'חמישי' },
  { key: '5', label: 'שישי' },
  { key: '6', label: 'שבת' },
]

type Props = {
  value: WorkingHours
  onChange: (next: WorkingHours) => void
}

export default function WorkingHoursEditor({ value, onChange }: Props) {
  // Replace one weekday's range list, returning a fresh WorkingHours object.
  function setDay(dayKey: string, ranges: HoursRange[]) {
    onChange({ ...value, [dayKey]: ranges })
  }

  function addRange(dayKey: string) {
    const ranges = value[dayKey] ?? []
    setDay(dayKey, [...ranges, { s: '09:00', e: '17:00' }])
  }

  function removeRange(dayKey: string, idx: number) {
    const ranges = value[dayKey] ?? []
    setDay(
      dayKey,
      ranges.filter((_, i) => i !== idx),
    )
  }

  function updateRange(dayKey: string, idx: number, field: 's' | 'e', v: string) {
    const ranges = value[dayKey] ?? []
    setDay(
      dayKey,
      ranges.map((r, i) => (i === idx ? { ...r, [field]: v } : r)),
    )
  }

  return (
    <ul className="flex flex-col gap-3">
      {WEEKDAYS.map(({ key, label }) => {
        const ranges = value[key] ?? []
        return (
          <li
            key={key}
            className="flex flex-col gap-2 rounded-xl border border-black/10 bg-white p-3 sm:flex-row sm:items-start"
          >
            {/* Phone: the weekday is a header line, with "סגור" beside it so a
                closed day costs one short line instead of two. Desktop keeps the
                fixed 80px label column on the right of the ranges. */}
            <div className="flex items-center justify-between sm:w-20 sm:flex-shrink-0 sm:justify-start sm:pt-2.5">
              <span className="text-sm font-medium text-slate-800">{label}</span>
              {ranges.length === 0 ? (
                <span className="text-sm text-slate-400 sm:hidden">סגור</span>
              ) : null}
            </div>

            <div className="flex min-w-0 flex-1 flex-col gap-2">
              {ranges.length === 0 ? (
                <p className="hidden py-1.5 text-sm text-slate-400 sm:block">סגור</p>
              ) : (
                ranges.map((range, idx) => (
                  // Phone: a fixed 4-track grid (start · – · end · bin). A
                  // wrapping flex row at 390px dropped the "–" and the bin onto
                  // a line of their own and the day stopped reading as ONE
                  // range; the grid keeps it on one line and lets the two time
                  // inputs split whatever is left. From `sm` up it goes back to
                  // the original flex row, where the inputs keep their natural
                  // width instead of stretching across the card.
                  <div
                    key={idx}
                    className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)_auto] items-center gap-1.5 sm:flex sm:flex-wrap sm:gap-2"
                  >
                    <label className="sr-only" htmlFor={`d${key}-${idx}-s`}>
                      {label} – שעת התחלה {idx + 1}
                    </label>
                    <input
                      id={`d${key}-${idx}-s`}
                      type="time"
                      value={range.s}
                      onChange={(ev) => updateRange(key, idx, 's', ev.target.value)}
                      className="w-full min-w-0 rounded-lg border border-slate-300 px-2 py-2.5 text-sm text-slate-900 sm:w-auto sm:py-1.5"
                    />
                    <span aria-hidden="true" className="text-slate-400">
                      –
                    </span>
                    <label className="sr-only" htmlFor={`d${key}-${idx}-e`}>
                      {label} – שעת סיום {idx + 1}
                    </label>
                    <input
                      id={`d${key}-${idx}-e`}
                      type="time"
                      value={range.e}
                      onChange={(ev) => updateRange(key, idx, 'e', ev.target.value)}
                      className="w-full min-w-0 rounded-lg border border-slate-300 px-2 py-2.5 text-sm text-slate-900 sm:w-auto sm:py-1.5"
                    />
                    <button
                      type="button"
                      onClick={() => removeRange(key, idx)}
                      aria-label={`הסר טווח שעות מ${label}`}
                      className="rounded-lg p-2.5 text-slate-400 transition hover:bg-red-50 hover:text-bad sm:p-1.5"
                    >
                      <Icon name="trash" size={16} />
                    </button>
                  </div>
                ))
              )}

              <button
                type="button"
                onClick={() => addRange(key)}
                className="inline-flex min-h-[44px] w-fit items-center gap-1 text-sm font-medium text-leaf-ink transition hover:text-leaf-dark sm:min-h-0"
              >
                <Icon name="plus" size={16} />
                הוסף טווח שעות
              </button>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
