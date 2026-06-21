// RTL Hebrew calendar built on react-day-picker, themed with the leaf palette.
// Used by both the owner reschedule dialog and the public booking page. We feed
// it the Hebrew locale (date-fns/locale/he) + `dir="rtl"` so the week starts on
// Sunday and reads right-to-left, and restrict the range to [today, max].
//
// Selection is reported up as a "YYYY-MM-DD" string (the wall-clock day), so the
// caller never juggles Date objects or timezones.

import 'react-day-picker/dist/style.css'
import { DayPicker } from 'react-day-picker'
import { he } from 'date-fns/locale'
import { addDays, fromDateString, toDateString, todayMidnight } from '../../lib/bookingDates'

type Props = {
  /** Currently selected day as "YYYY-MM-DD", or undefined for none. */
  value?: string
  /** Called with the picked day as "YYYY-MM-DD". */
  onChange: (date: string) => void
  /** How many days ahead are bookable (the picker disables the rest). */
  maxDaysAhead?: number
}

export default function DatePicker({ value, onChange, maxDaysAhead = 30 }: Props) {
  const today = todayMidnight()
  const selected = value ? fromDateString(value) : undefined

  return (
    <DayPicker
      mode="single"
      dir="rtl"
      locale={he}
      selected={selected}
      onSelect={(day) => {
        if (day) onChange(toDateString(day))
      }}
      fromDate={today}
      toDate={addDays(today, maxDaysAhead)}
      disabled={{ before: today }}
      // Leaf-green selected day + a soft hover, AA-safe and reduced-motion safe.
      modifiersClassNames={{ selected: '!bg-leaf !text-white' }}
      classNames={{
        caption_label: 'text-sm font-medium text-slate-900',
        head_cell: 'text-xs font-medium text-slate-400',
        day: 'rounded-lg text-sm text-slate-800 hover:bg-leaf-soft focus-visible:ring-2 focus-visible:ring-leaf',
        nav_button: 'text-slate-500 hover:text-leaf-ink',
      }}
      styles={{ root: { margin: 0 } }}
    />
  )
}
