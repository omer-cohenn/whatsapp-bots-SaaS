// Labelled multi-line input, mirroring Field's a11y pattern (label/textarea
// association + optional hint wired through aria-describedby).

import { useId, type TextareaHTMLAttributes } from 'react'

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & {
  label: string
  hint?: string
}

export default function Textarea({
  label,
  hint,
  id,
  className = '',
  rows = 3,
  ...rest
}: TextareaProps) {
  const autoId = useId()
  const textareaId = id ?? autoId
  const hintId = hint ? `${textareaId}-hint` : undefined

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={textareaId} className="text-sm font-medium text-slate-800">
        {label}
      </label>
      <textarea
        id={textareaId}
        rows={rows}
        aria-describedby={hintId}
        className={`rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 ${className}`}
        {...rest}
      />
      {hint ? (
        <p id={hintId} className="text-xs text-slate-500">
          {hint}
        </p>
      ) : null}
    </div>
  )
}
