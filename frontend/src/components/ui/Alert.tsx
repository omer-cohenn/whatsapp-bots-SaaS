import type { ReactNode } from 'react'

type Tone = 'error' | 'warning' | 'info'

type AlertProps = {
  tone?: Tone
  children: ReactNode
  className?: string
}

const TONES: Record<Tone, string> = {
  error: 'border-red-200 bg-red-50 text-bad',
  warning: 'border-amber-200 bg-amber-50 text-amber-800',
  info: 'border-slate-200 bg-slate-50 text-slate-700',
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
