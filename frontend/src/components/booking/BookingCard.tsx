// One booking row: service + when, the customer's (decrypted) details, the linked
// lead, a Google Meet link when present, and manage actions (confirm / complete /
// cancel / reschedule). Status changes + reschedule both go through PATCH
// /api/bookings/{id}; the parent refetches on success. Tenant is server-side only.

import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { BookingItem, BookingStatus } from '../../dashboard/appointmentTypes'
import { patchBooking } from '../../lib/bookingClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { ApiError } from '../../lib/apiClient'
import { fullDateTime } from '../../lib/formatDate'
import Badge from '../ui/Badge'
import Icon from '../ui/Icon'
import RescheduleDialog from './RescheduleDialog'

const STATUS_META: Record<
  BookingStatus,
  { label: string; tone: 'leaf' | 'info' | 'warning' | 'neutral' }
> = {
  pending: { label: 'ממתין', tone: 'info' },
  confirmed: { label: 'מאושר', tone: 'leaf' },
  completed: { label: 'הושלם', tone: 'neutral' },
  cancelled: { label: 'בוטל', tone: 'warning' },
}

type Props = {
  booking: BookingItem
  /** How far ahead reschedule may go (from the owner's settings). */
  maxDaysAhead?: number
  /** Called after a successful status change / reschedule. */
  onChanged: () => void
}

export default function BookingCard({ booking, maxDaysAhead = 30, onChanged }: Props) {
  const meta = STATUS_META[booking.status]
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [showReschedule, setShowReschedule] = useState(false)
  const [rescheduling, setRescheduling] = useState(false)
  const [rescheduleError, setRescheduleError] = useState<string | null>(null)

  async function setStatus(status: BookingStatus) {
    setBusy(true)
    setError(null)
    try {
      await patchBooking(booking.id, { status })
      onChanged()
    } catch (err) {
      setError(toFriendlyError(err, 'עדכון הפגישה נכשל. נסו שוב.'))
    } finally {
      setBusy(false)
    }
  }

  async function reschedule(date: string, time: string) {
    setRescheduling(true)
    setRescheduleError(null)
    try {
      await patchBooking(booking.id, { date, time })
      setShowReschedule(false)
      onChanged()
    } catch (err) {
      // 409 = the new slot is already taken.
      if (err instanceof ApiError && err.status === 409) {
        setRescheduleError('המועד הזה כבר תפוס. בחרו מועד אחר.')
      } else {
        setRescheduleError(toFriendlyError(err, 'שינוי המועד נכשל. נסו שוב.'))
      }
    } finally {
      setRescheduling(false)
    }
  }

  const active = booking.status === 'pending' || booking.status === 'confirmed'

  return (
    <article className="rounded-xl border border-black/10 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-medium text-slate-900">
            <Icon name="calendar-event" size={16} className="text-leaf" />
            {booking.service_name || 'פגישה'}
            {booking.is_test ? (
              <span className="text-xs font-normal text-slate-400">· בדיקה</span>
            ) : null}
          </p>
          <p className="mt-0.5 text-sm text-slate-600">
            {fullDateTime(booking.scheduled_at)} · {booking.duration_minutes} דק׳
          </p>
        </div>
        <Badge tone={meta.tone}>{meta.label}</Badge>
      </div>

      {/* Customer details (decrypted for the owner) */}
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 border-t border-black/10 pt-3 text-sm sm:grid-cols-3">
        {booking.client_name ? (
          <div>
            <dt className="text-[11px] text-slate-400">שם</dt>
            <dd className="text-slate-800">{booking.client_name}</dd>
          </div>
        ) : null}
        {booking.client_phone ? (
          <div>
            <dt className="text-[11px] text-slate-400">טלפון</dt>
            <dd dir="ltr" className="text-start text-slate-800">
              {booking.client_phone}
            </dd>
          </div>
        ) : null}
        {booking.client_email ? (
          <div className="min-w-0">
            <dt className="text-[11px] text-slate-400">אימייל</dt>
            <dd dir="ltr" className="truncate text-start text-slate-800" title={booking.client_email}>
              {booking.client_email}
            </dd>
          </div>
        ) : null}
      </dl>

      {booking.notes ? (
        <p className="mt-2 whitespace-pre-wrap break-words text-sm text-slate-700">
          <span className="text-[11px] text-slate-400">הערות: </span>
          {booking.notes}
        </p>
      ) : null}

      {/* Google Meet link (only when synced + Meet enabled) */}
      {booking.meet_link ? (
        <a
          href={booking.meet_link}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-3 inline-flex items-center gap-1.5 text-sm font-medium text-leaf-ink hover:underline"
        >
          <Icon name="external-link" size={16} />
          הצטרף ל-Google Meet
        </a>
      ) : null}

      {/* Linked lead */}
      {booking.lead_id ? (
        <p className="mt-2 text-xs text-slate-500">
          <Link to="/leads" className="text-leaf-ink hover:underline">
            צפייה בליד המקושר
          </Link>
        </p>
      ) : null}

      {/* Actions */}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-black/10 pt-3">
        {booking.status === 'pending' ? (
          <button
            type="button"
            onClick={() => void setStatus('confirmed')}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg border border-leaf px-3 py-1.5 text-sm font-medium text-leaf-ink transition hover:bg-leaf-soft disabled:opacity-60"
          >
            <Icon name="check" size={16} />
            אשר
          </button>
        ) : null}

        {active ? (
          <>
            <button
              type="button"
              onClick={() => {
                setRescheduleError(null)
                setShowReschedule(true)
              }}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
            >
              <Icon name="clock" size={16} />
              שנה מועד
            </button>
            <button
              type="button"
              onClick={() => void setStatus('completed')}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
            >
              <Icon name="checks" size={16} />
              הושלם
            </button>
            <button
              type="button"
              onClick={() => void setStatus('cancelled')}
              disabled={busy}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-600 transition hover:bg-red-50 hover:text-bad disabled:opacity-60"
            >
              <Icon name="x" size={16} />
              בטל
            </button>
          </>
        ) : null}
      </div>

      {error ? (
        <p role="alert" className="mt-2 text-xs text-bad">
          {error}
        </p>
      ) : null}

      <RescheduleDialog
        open={showReschedule}
        maxDaysAhead={maxDaysAhead}
        saving={rescheduling}
        error={rescheduleError}
        onCancel={() => {
          if (!rescheduling) setShowReschedule(false)
        }}
        onConfirm={(date, time) => void reschedule(date, time)}
      />
    </article>
  )
}
