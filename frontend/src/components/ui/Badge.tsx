// Small pill label (status / "בקרוב" tags). Tones are AA-contrast-safe text on
// soft backgrounds, matching the approved design palette.

import type { ReactNode } from 'react'

type Tone = 'neutral' | 'leaf' | 'info' | 'warning'

const TONES: Record<Tone, string> = {
  neutral: 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-200',
  leaf: 'bg-leaf-soft text-leaf-ink',
  info: 'bg-blue-50 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  warning: 'bg-amber-50 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
}

type BadgeProps = {
  tone?: Tone
  children: ReactNode
  className?: string
}

export default function Badge({ tone = 'neutral', children, className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${TONES[tone]} ${className}`}
    >
      {children}
    </span>
  )
}
