import type { ReactNode } from 'react'

type Tone = 'error' | 'warning' | 'info'

type AlertProps = {
  tone?: Tone
  children: ReactNode
  className?: string
}

const TONES: Record<Tone, string> = {
  error: 'border-red-200 bg-red-50 text-bad dark:border-red-800 dark:bg-red-900/30 dark:text-red-300',
  warning: 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-800 dark:bg-amber-900/30 dark:text-amber-300',
  info: 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300',
}

// role="alert" so assistive tech announces the message immediately.
// Errors get an assertive live region; warning/info are polite.
export default function Alert({ tone = 'info', children, className = '' }: AlertProps) {
  return (
    <div
      role="alert"
      aria-live={tone === 'error' ? 'assertive' : 'polite'}
      className={`rounded-lg border px-4 py-3 text-sm ${TONES[tone]} ${className}`}
    >
      {children}
    </div>
  )
}
