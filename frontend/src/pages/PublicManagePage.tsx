// PUBLIC manage page (route /book/:slug/manage/:token, NO auth). The customer
// arrives here from their confirmation link and can CANCEL or RESCHEDULE their
// booking using the non-guessable cancel_token in the URL. The backend has no
// "read booking by token" endpoint (the token is action-only), so we don't show
// the existing booking details — we just offer the two actions and confirm the
// new state the server returns.
//
// Tenant is resolved server-side from the verified {slug}; the token authorises
// the action. No business_id or PII is sent from the client beyond the new date.

import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import type { PublicManageResponse } from '../dashboard/appointmentTypes'
import { cancelPublicBooking, reschedulePublicBooking } from '../lib/publicBookingClient'
import { ApiError } from '../lib/apiClient'
import { toFriendlyError } from '../lib/friendlyError'
import { fullDateTime } from '../lib/formatDate'
import PublicBookingLayout from '../components/booking/PublicBookingLayout'
import RescheduleDialog from '../components/booking/RescheduleDialog'
import Alert from '../components/ui/Alert'
import Button from '../components/ui/Button'
import Icon from '../components/ui/Icon'

type Done = { kind: 'cancelled' | 'rescheduled'; res: PublicManageResponse }

export default function PublicManagePage() {
  const { slug = '', token = '' } = useParams()

  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<Done | null>(null)

  const [showReschedule, setShowReschedule] = useState(false)
  const [rescheduling, setRescheduling] = useState(false)
  const [rescheduleError, setRescheduleError] = useState<string | null>(null)

  async function cancel() {
    if (!window.confirm('לבטל את התור?')) return
    setBusy(true)
    setError(null)
    try {
      const res = await cancelPublicBooking(slug, token)
      setDone({ kind: 'cancelled', res })
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setError('הקישור אינו תקין או שהתור כבר אינו קיים.')
      } else {
        setError(toFriendlyError(err, 'ביטול התור נכשל. נסו שוב.'))
      }
    } finally {
      setBusy(false)
    }
  }

  async function reschedule(date: string, time: string) {
    setRescheduling(true)
    setRescheduleError(null)
    try {
      const res = await reschedulePublicBooking(slug, token, date, time)
      setShowReschedule(false)
      setDone({ kind: 'rescheduled', res })
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setRescheduleError('המועד הזה תפוס. בחרו מועד אחר.')
      } else if (err instanceof ApiError && err.status === 404) {
        setRescheduleError('הקישור אינו תקין או שהתור כבר אינו קיים.')
      } else {
        setRescheduleError(toFriendlyError(err, 'שינוי המועד נכשל. נסו שוב.'))
      }
    } finally {
      setRescheduling(false)
    }
  }

  // After an action, show the result + a way back to book again.
  if (done) {
    return (
      <PublicBookingLayout>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-sm">
          <span
            aria-hidden="true"
            className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-leaf-soft text-leaf-ink"
          >
            <Icon name={done.kind === 'cancelled' ? 'x' : 'check'} size={28} />
          </span>
          <h1 className="text-xl font-bold text-slate-900">
            {done.kind === 'cancelled' ? 'התור בוטל' : 'המועד עודכן'}
          </h1>
          {done.kind === 'rescheduled' ? (
            <p className="mt-2 text-sm text-slate-600">{fullDateTime(done.res.scheduled_at)}</p>
          ) : null}
          <Link
            to={`/book/${slug}`}
            className="mt-5 inline-flex items-center gap-1.5 rounded-lg border border-leaf px-4 py-2 text-sm font-medium text-leaf-ink transition hover:bg-leaf-soft"
          >
            <Icon name="calendar-event" size={16} />
            קביעת תור חדש
          </Link>
        </div>
      </PublicBookingLayout>
    )
  }

  return (
    <PublicBookingLayout>
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="text-xl font-bold text-slate-900">ניהול התור שלכם</h1>
        <p className="mt-2 text-sm text-slate-600">בחרו פעולה: שינוי מועד או ביטול.</p>

        {error ? (
          <Alert tone="error" className="mt-4">
            {error}
          </Alert>
        ) : null}

        <div className="mt-5 flex flex-wrap gap-3">
          <Button
            type="button"
            onClick={() => {
              setRescheduleError(null)
              setShowReschedule(true)
            }}
            disabled={busy}
            className="!bg-leaf hover:!bg-leaf-dark"
          >
            <Icon name="clock" size={16} />
            שינוי מועד
          </Button>
          <Button
            type="button"
            variant="secondary"
            onClick={() => void cancel()}
            disabled={busy}
          >
            <Icon name="x" size={16} />
            {busy ? 'מבטל…' : 'ביטול התור'}
          </Button>
        </div>
      </div>

      <RescheduleDialog
        open={showReschedule}
        saving={rescheduling}
        error={rescheduleError}
        onCancel={() => {
          if (!rescheduling) setShowReschedule(false)
        }}
        onConfirm={(date, time) => void reschedule(date, time)}
      />
    </PublicBookingLayout>
  )
}
