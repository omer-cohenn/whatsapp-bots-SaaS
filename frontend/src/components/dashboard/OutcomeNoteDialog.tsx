// An accessible modal dialog that asks the owner for a short outcome note before
// a lead is marked as "בוצעה עסקה" (deal) or "סגירת פנייה" (closed). The note is
// MANDATORY here (the confirm button stays disabled until it's non-empty), even
// though the API itself accepts it optionally.
//
// Accessibility: role="dialog" + aria-modal, labelled by its title and described
// by its hint, focus moved to the textarea on open, Escape closes, a focus trap
// keeps Tab inside the dialog, and the backdrop click cancels. Tenant scoping is
// entirely server-side — this component only collects text and reports it up.

import { useEffect, useId, useRef, useState } from 'react'
import Button from '../ui/Button'
import Icon from '../ui/Icon'

type Props = {
  /** Which outcome we're confirming — drives the title + verb. */
  outcome: 'deal' | 'closed'
  /** Hidden while false; mounted+focused when true. */
  open: boolean
  /** True while the parent's save request is in flight. */
  saving?: boolean
  /** Error text from a failed save, announced inside the dialog. */
  error?: string | null
  /** Cancel (Escape / backdrop / "ביטול"). Ignored while saving. */
  onCancel: () => void
  /** Confirm with the trimmed note (guaranteed non-empty). */
  onConfirm: (note: string) => void
}

const TITLES: Record<Props['outcome'], string> = {
  deal: 'סימון כעסקה שבוצעה',
  closed: 'סגירת הפנייה',
}

export default function OutcomeNoteDialog({
  outcome,
  open,
  saving = false,
  error = null,
  onCancel,
  onConfirm,
}: Props) {
  const [note, setNote] = useState('')
  const dialogRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const titleId = useId()
  const hintId = useId()

  // Reset the field each time the dialog (re)opens, and move focus into it.
  useEffect(() => {
    if (!open) return
    setNote('')
    // Focus after paint so the element exists and is visible.
    const t = window.setTimeout(() => textareaRef.current?.focus(), 0)
    return () => window.clearTimeout(t)
  }, [open])

  // Escape to cancel + a simple focus trap that keeps Tab within the dialog.
  useEffect(() => {
    if (!open) return
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.preventDefault()
        if (!saving) onCancel()
        return
      }
      if (e.key !== 'Tab') return
      const root = dialogRef.current
      if (!root) return
      const focusable = root.querySelectorAll<HTMLElement>(
        'button:not([disabled]), textarea:not([disabled]), [href], input:not([disabled])',
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
  }, [open, saving, onCancel])

  if (!open) return null

  const trimmed = note.trim()
  const canConfirm = trimmed.length > 0 && !saving

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={hintId}
        className="w-full max-w-md rounded-xl border border-black/10 bg-white p-5 shadow-xl"
      >
        <h2 id={titleId} className="text-base font-semibold text-slate-900">
          {TITLES[outcome]}
        </h2>
        <p id={hintId} className="mt-1 text-sm text-slate-500">
          מה היה בשיחה? למשל: סגרנו ביטוח חיים ב-100 ₪ לחודש
        </p>

        <label htmlFor={`${titleId}-note`} className="sr-only">
          סיכום השיחה
        </label>
        <textarea
          id={`${titleId}-note`}
          ref={textareaRef}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={4}
          maxLength={2000}
          disabled={saving}
          required
          placeholder="כתבו סיכום קצר…"
          className="mt-3 w-full resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 outline-none focus-visible:ring-2 focus-visible:ring-leaf focus-visible:ring-offset-2 disabled:opacity-60"
        />

        {error ? (
          <p role="alert" className="mt-2 text-xs text-bad">
            {error}
          </p>
        ) : null}

        <div className="mt-4 flex items-center justify-end gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={onCancel}
            disabled={saving}
          >
            ביטול
          </Button>
          <Button
            type="button"
            onClick={() => onConfirm(trimmed)}
            disabled={!canConfirm}
            className="!bg-leaf text-white hover:!bg-leaf-dark"
          >
            <Icon name="checks" size={16} />
            {saving ? 'שומר…' : 'אישור'}
          </Button>
        </div>
      </div>
    </div>
  )
}
