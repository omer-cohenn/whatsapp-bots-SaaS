// A pill-style segmented control (the prototype's `.seg` group). Used for the
// period filter (week/month/all) and the leads status filter. Built as an
// accessible radio group so arrow keys + screen readers work for free.

import { useId } from 'react'

export type Segment<T extends string> = {
  value: T
  label: string
}

type Props<T extends string> = {
  /** Accessible group name (e.g. "טווח זמן"). */
  label: string
  segments: Segment<T>[]
  value: T
  onChange: (value: T) => void
  className?: string
}

export default function SegmentedControl<T extends string>({
  label,
  segments,
  value,
  onChange,
  className = '',
}: Props<T>) {
  const name = useId()

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={`inline-flex flex-wrap rounded-full bg-[#f4f3ee] p-1 dark:bg-slate-800 ${className}`}
    >
      {segments.map((seg) => {
        const selected = seg.value === value
        return (
          <button
            key={seg.value}
            type="button"
            role="radio"
            name={name}
            aria-checked={selected}
            onClick={() => onChange(seg.value)}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition ${
              selected
                ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-slate-100'
                : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200'
            }`}
          >
            {seg.label}
          </button>
        )
      })}
    </div>
  )
}
