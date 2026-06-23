// Accessible modal dialog primitive (extracted on its second real use — the M13
// CRM card dialog needs the same role="dialog" + aria-modal + Escape + focus-
// trap + backdrop-cancel behaviour the OutcomeNoteDialog hand-rolled). Mirrors
// that pattern exactly so a11y stays consistent across the app.
//
// Usage: <Modal open={…} title="…" onClose={…}>…body…</Modal>. The title wires
// aria-labelledby; focus moves into the dialog on open; Escape/backdrop call
// onClose. The caller owns the body (and any footer buttons).

import { useEffect, useId, useRef, type ReactNode } from 'react'
import Icon from './Icon'

type Props = {
  open: boolean
  title: string
  /** Close request (Escape / backdrop / the × button). */
  onClose: () => void
  children: ReactNode
  /** Tailwind max-width class for the panel (default max-w-md). */
  maxWidthClassName?: string
}

export default function Modal({
  open,
  title,
  onClose,
  children,
  maxWidthClassName = 'max-w-md',
}: Props) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const titleId = useId()

  // Move focus into the dialog on open (first focusable element).
  useEffect(() => {
    if (!open) return
    const t = window.setTimeout(() => {
      const root = dialogRef.current
      if (!root) return
      const focusable = root.querySelector<HTMLElement>(
        'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [href]',
      )
      focusable?.focus()
    }, 0)
    return () => window.clearTimeout(t)
  }, [open])

  // Escape closes; a simple focus trap keeps Tab inside the dialog.
  useEffect(() => {
    if (!open) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
        return
      }
      if (e.key !== 'Tab') return
      const root = dialogRef.current
      if (!root) return
      const focusable = root.querySelectorAll<HTMLElement>(
        'button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [href]',
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  if (!open) return null

  // Close via Escape or the × button (matches the project's other dialogs; we
  // deliberately don't make the backdrop itself an interactive element).
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={`max-h-[90vh] w-full overflow-y-auto rounded-xl border border-black/10 bg-white p-5 shadow-xl ${maxWidthClassName}`}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <h2 id={titleId} className="text-base font-semibold text-slate-900">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="סגירה"
            className="rounded-lg p-1 text-slate-500 outline-none transition hover:bg-slate-100 hover:text-slate-800 focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2"
          >
            <Icon name="x" size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
