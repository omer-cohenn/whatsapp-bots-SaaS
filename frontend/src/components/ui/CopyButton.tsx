// Copy-to-clipboard button with an accessible "הועתק" confirmation. Used for the
// public booking link (owner settings) and the customer's manage link (public
// confirmation). Announces success via an aria-live region so screen-reader
// users hear it; falls back silently if the Clipboard API is unavailable.

import { useEffect, useRef, useState } from 'react'
import Icon from './Icon'

type Props = {
  /** The text to copy. */
  value: string
  /** Visible label (default "העתק קישור"). */
  label?: string
  className?: string
}

export default function CopyButton({ value, label = 'העתק קישור', className = '' }: Props) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  // Clear the pending "reset" timer on unmount so we never setState afterwards.
  useEffect(() => () => window.clearTimeout(timer.current), [])

  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setCopied(false), 2000)
    } catch {
      // Clipboard blocked (e.g. insecure context) — leave the button as-is.
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className={`inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 ${className}`}
    >
      <Icon name={copied ? 'check' : 'copy'} size={16} className={copied ? 'text-ok' : ''} />
      <span aria-live="polite">{copied ? 'הועתק' : label}</span>
    </button>
  )
}
