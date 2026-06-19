// Labelled native <select>, same a11y pattern as Field/Textarea. Native select
// keeps full keyboard support and screen-reader semantics for free. Options are
// passed as a typed list so callers can't forget a label.

import { useId, type SelectHTMLAttributes } from 'react'

export type SelectOption = { value: string; label: string }

type SelectProps = SelectHTMLAttributes<HTMLSelectElement> & {
  label: string
  options: SelectOption[]
  hint?: string
}

export default function Select({
  label,
  options,
  hint,
  id,
  className = '',
  ...rest
}: SelectProps) {
  const autoId = useId()
  const selectId = id ?? autoId
  const hintId = hint ? `${selectId}-hint` : undefined

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={selectId} className="text-sm font-medium text-slate-800">
        {label}
      </label>
      <select
        id={selectId}
        aria-describedby={hintId}
        className={`rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 ${className}`}
        {...rest}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      {hint ? (
        <p id={hintId} className="text-xs text-slate-500">
          {hint}
        </p>
      ) : null}
    </div>
  )
}
