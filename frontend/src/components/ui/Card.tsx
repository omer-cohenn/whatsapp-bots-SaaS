import type { HTMLAttributes } from 'react'

// Simple white rounded panel used across pages.
export default function Card({ className = '', ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-2xl border border-slate-200 bg-white p-6 shadow-sm ${className}`}
      {...rest}
    />
  )
}
