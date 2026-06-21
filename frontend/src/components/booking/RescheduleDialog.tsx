// Accessible modal for moving a booking to a new date + time. Used by the owner
// (PATCH /api/bookings/{id}) and by the customer (public reschedule). The parent
// performs the actual request via onConfirm(date, time) and reports success/error
// back through `saving` + `error`; the server validates the slot (409 if taken).
//
// Accessibility mirrors OutcomeNoteDialog: role="dialog" + aria-modal, focus trap,
// Escape to cancel, labelled controls.

import { useEffect, useRef, useState } from 'react'
import DatePicker from './DatePicker'
import Button from '../ui/Button'
import Icon from '../ui/Icon'

type Props = {
  open: boolean
  /** How far ahead the picker allows (defaults to 30). */
  maxDaysAhead?: number
  saving?: boolean
  error?: string | null
  onCancel: () => void
  /** date = "YYYY-MM-DD", time = "HH:MM". */
  onConfirm: (date: string, time: string) => void
}

export default function RescheduleDialog({
  open,
  maxDaysAhead = 30,
  saving = false,
  error = null,
  onCancel,
  onConfirm,
}: Props) {
  const [date, setDate] = useState('')
  const [time, setTime] = useState('')
  const dialogRef = useRef<HTMLDivElement>(null)

  // Reset fields each time the dialog opens.
  useEffect(() => {
    if (open) {
      setDate('')
      setTime('')
    }
  }, [open])

  // Escape to cancel + focus trap.
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
        'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
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

  const canConfirm = date !== '' && time !== '' && !saving

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="reschedule-title"
        className="w-full max-w-md rounded-xl border border-black/10 bg-white p-5 shadow-xl"
      >
        <h2 id="reschedule-title" className="text-base font-semibold text-slate-900">
          קביעת מועד חדש
        </h2>

        <div className="mt-3 flex flex-col items-center gap-4">
          <DatePicker value={date} onChange={setDate} maxDaysAhead={maxDaysAhead} />
          <div className="w-full">
            <label htmlFor="reschedule-time" className="text-sm font-medium text-slate-800">
              שעה
            </label>
            <input
              id="reschedule-time"
              type="time"
              value={time}
              onChange={(ev) => setTime(ev.target.value)}
              disabled={saving}
              className="mt-1.5 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
            />
          </div>
        </div>

        {error ? (
          <p role="alert" className="mt-3 text-xs text-bad">
            {error}
          </p>
        ) : null}

        <div className="mt-4 flex items-center justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onCancel} disabled={saving}>
            ביטול
          </Button>
          <Button
            type="button"
            onClick={() => onConfirm(date, time)}
            disabled={!canConfirm}
            className="!bg-leaf text-white hover:!bg-leaf-dark"
          >
            <Icon name="check" size={16} />
            {saving ? 'שומר…' : 'אישור מועד'}
          </Button>
        </div>
      </div>
    </div>
  )
}
