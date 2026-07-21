import type { HTMLAttributes } from 'react'

// Simple white rounded panel used across pages.
export default function Card({ className = '', ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      // p-4 on phones, p-6 from `sm`. At 390px the old flat p-6 spent 48px — 12% of
      // the screen — on padding, which is what squeezed every card's content to
      // 309px. Shared by every page, so this is the one place to fix it.
      className={`rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6 dark:border-slate-700 dark:bg-slate-800 ${className}`}
      {...rest}
    />
  )
}
