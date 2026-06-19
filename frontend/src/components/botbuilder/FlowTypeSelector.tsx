// The flow-type segmented control shown below the active flow tab.
// It's a mutually-exclusive choice, so it's built as an ARIA radiogroup
// (each option role="radio"; arrow keys move within the group; the disabled
// "בסיס ידע" option is announced aria-disabled with a "בקרוב" tag).

import { useRef, type KeyboardEvent } from 'react'
import type { FlowType } from '../../botbuilder/types'
import Badge from '../ui/Badge'

type Option = {
  value: FlowType | 'knowledge'
  label: string
  enabled: boolean
}

// Order + labels mirror the approved prototype.
const OPTIONS: Option[] = [
  { value: 'lead', label: 'איסוף ליד', enabled: true },
  { value: 'human_handoff', label: 'מעבר לנציג', enabled: true },
  { value: 'booking', label: 'קביעת פגישה', enabled: true },
  { value: 'knowledge', label: 'בסיס ידע', enabled: false },
]

type Props = {
  value: FlowType
  onChange: (value: FlowType) => void
}

export default function FlowTypeSelector({ value, onChange }: Props) {
  const enabled = OPTIONS.filter((o) => o.enabled) as { value: FlowType; label: string }[]
  const refs = useRef<Record<string, HTMLButtonElement | null>>({})

  function move(current: FlowType, delta: number) {
    const idx = enabled.findIndex((o) => o.value === current)
    if (idx < 0) return
    const next = enabled[(idx + delta + enabled.length) % enabled.length]
    onChange(next.value)
    requestAnimationFrame(() => refs.current[next.value]?.focus())
  }

  function onKeyDown(e: KeyboardEvent<HTMLButtonElement>, optValue: FlowType) {
    // RTL: ArrowLeft = visual next, ArrowRight = visual previous.
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') {
      e.preventDefault()
      move(optValue, 1)
    } else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') {
      e.preventDefault()
      move(optValue, -1)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
      <span id="flow-type-label" className="text-sm font-medium text-slate-800">
        סוג המסלול
      </span>
      <div
        role="radiogroup"
        aria-labelledby="flow-type-label"
        className="inline-flex rounded-full bg-slate-100 p-1"
      >
        {OPTIONS.map((opt) => {
          if (!opt.enabled) {
            return (
              <span
                key={opt.value}
                aria-disabled="true"
                className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs text-slate-400"
              >
                {opt.label}
                <Badge tone="leaf">בקרוב</Badge>
              </span>
            )
          }
          const selected = value === opt.value
          return (
            <button
              key={opt.value}
              ref={(el) => {
                refs.current[opt.value] = el
              }}
              type="button"
              role="radio"
              aria-checked={selected}
              tabIndex={selected ? 0 : -1}
              onClick={() => onChange(opt.value as FlowType)}
              onKeyDown={(e) => onKeyDown(e, opt.value as FlowType)}
              className={`rounded-full px-4 py-1.5 text-xs font-medium transition ${
                selected
                  ? 'bg-leaf text-white shadow-sm'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              {opt.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
