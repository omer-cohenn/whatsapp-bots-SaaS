// PUBLIC booking page (route /book/:slug, NO auth). The customer:
//   1) picks a service, 2) picks a date (react-day-picker), 3) picks an available
//   slot (GET slots), 4) fills name/phone/email/notes, 5) submits (POST create),
//   6) sees a confirmation with their manage link (cancel/reschedule by token).
//
// The tenant is resolved server-side from the verified {slug} in the path — the
// client never sends a business_id. PII is only ever sent to the backend (which
// encrypts it). We validate client-side too, but the server is authoritative.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import type {
  PublicBookingResponse,
  PublicService,
} from '../dashboard/appointmentTypes'
import {
  createPublicBooking,
  getPublicServices,
  getPublicSlots,
} from '../lib/publicBookingClient'
import { ApiError } from '../lib/apiClient'
import { toFriendlyError } from '../lib/friendlyError'
import { fullDateTime } from '../lib/formatDate'
import PublicBookingLayout from '../components/booking/PublicBookingLayout'
import DatePicker from '../components/booking/DatePicker'
import SlotGrid from '../components/booking/SlotGrid'
import CopyButton from '../components/ui/CopyButton'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'
import Field from '../components/ui/Field'
import Textarea from '../components/ui/Textarea'
import Button from '../components/ui/Button'
import Icon from '../components/ui/Icon'

// Israeli phone: 9-10 digits, optionally with a leading + and separators.
function isValidPhone(phone: string): boolean {
  const digits = phone.replace(/[\s-]/g, '')
  return /^\+?\d{9,15}$/.test(digits)
}

function isValidEmail(email: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)
}

export default function PublicBookingPage() {
  const { slug = '' } = useParams()

  // Step 0: load services for this slug.
  const [businessName, setBusinessName] = useState<string>('')
  const [services, setServices] = useState<PublicService[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  // Selection state.
  const [serviceId, setServiceId] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('')

  // Slots for the chosen service+date.
  const [slots, setSlots] = useState<string[] | null>(null)
  const [slotsLoading, setSlotsLoading] = useState(false)
  const [slotsError, setSlotsError] = useState<string | null>(null)

  // Customer form.
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [notes, setNotes] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  // Submit + result.
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [result, setResult] = useState<PublicBookingResponse | null>(null)

  // Load services once.
  useEffect(() => {
    let cancelled = false
    getPublicServices(slug)
      .then((res) => {
        if (cancelled) return
        setBusinessName(res.business_name)
        setServices(res.services)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) {
          setLoadError('דף הקביעה לא נמצא. ודאו שהקישור תקין.')
        } else {
          setLoadError(toFriendlyError(err, 'טעינת השירותים נכשלה. נסו שוב.'))
        }
      })
    return () => {
      cancelled = true
    }
  }, [slug])

  const selectedService = useMemo(
    () => services?.find((s) => s.id === serviceId) ?? null,
    [services, serviceId],
  )

  // Fetch slots whenever service + date are both chosen. Picking a new date
  // clears the previously chosen time.
  const loadSlots = useCallback(() => {
    if (!serviceId || !date) {
      setSlots(null)
      return
    }
    let cancelled = false
    setSlotsLoading(true)
    setSlotsError(null)
    setTime('')
    getPublicSlots(slug, serviceId, date)
      .then((res) => {
        if (!cancelled) setSlots(res.slots)
      })
      .catch((err) => {
        if (!cancelled) {
          setSlots([])
          setSlotsError(toFriendlyError(err, 'טעינת השעות הפנויות נכשלה. נסו שוב.'))
        }
      })
      .finally(() => {
        if (!cancelled) setSlotsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [slug, serviceId, date])

  useEffect(() => loadSlots(), [loadSlots])

  function validate(): string | null {
    if (!serviceId) return 'בחרו שירות.'
    if (!date) return 'בחרו תאריך.'
    if (!time) return 'בחרו שעה.'
    if (name.trim().length < 2) return 'הזינו שם מלא.'
    if (!isValidPhone(phone)) return 'הזינו מספר טלפון תקין.'
    if (email.trim() && !isValidEmail(email.trim())) return 'הזינו כתובת אימייל תקינה.'
    return null
  }

  async function submit(ev: React.FormEvent) {
    ev.preventDefault()
    const err = validate()
    if (err) {
      setFormError(err)
      return
    }
    setFormError(null)
    setSubmitError(null)
    setSubmitting(true)
    try {
      const res = await createPublicBooking(slug, {
        service_id: serviceId,
        date,
        time,
        name: name.trim(),
        phone: phone.trim(),
        email: email.trim() || undefined,
        notes: notes.trim() || undefined,
      })
      setResult(res)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setSubmitError('המועד הזה נתפס זה עתה. בחרו שעה אחרת.')
        loadSlots() // refresh availability
      } else if (e instanceof ApiError && e.status === 429) {
        setSubmitError('יותר מדי ניסיונות. המתינו מעט ונסו שוב.')
      } else if (e instanceof ApiError && e.status === 422) {
        setSubmitError('הפרטים אינם תקינים. בדקו ונסו שוב.')
      } else {
        setSubmitError(toFriendlyError(e, 'קביעת התור נכשלה. נסו שוב.'))
      }
    } finally {
      setSubmitting(false)
    }
  }

  // --- render: error / loading / confirmation / form ---

  if (loadError) {
    return (
      <PublicBookingLayout>
        <Alert tone="error">{loadError}</Alert>
      </PublicBookingLayout>
    )
  }

  if (!services) {
    return (
      <PublicBookingLayout>
        <Spinner label="טוען…" className="py-16" />
      </PublicBookingLayout>
    )
  }

  // Confirmation screen.
  if (result) {
    const manageUrl = `${window.location.origin}/book/${slug}/manage/${result.cancel_token}`
    return (
      <PublicBookingLayout businessName={businessName}>
        <div className="rounded-2xl border border-leaf/30 bg-white p-6 text-center shadow-sm">
          <span
            aria-hidden="true"
            className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-leaf-soft text-leaf-ink"
          >
            <Icon name="check" size={28} />
          </span>
          <h1 className="text-xl font-bold text-slate-900">התור נקבע!</h1>
          <p className="mt-2 text-sm text-slate-600">
            {selectedService ? `${selectedService.name} · ` : ''}
            {fullDateTime(result.scheduled_at)}
          </p>

          <div className="mt-5 rounded-xl border border-black/10 bg-slate-50 p-4 text-start">
            <p className="text-sm font-medium text-slate-800">לניהול התור (ביטול / שינוי מועד):</p>
            <p className="mt-1 break-all text-xs text-slate-500" dir="ltr">
              {manageUrl}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <CopyButton value={manageUrl} label="העתק קישור ניהול" />
              <Link
                to={`/book/${slug}/manage/${result.cancel_token}`}
                className="inline-flex items-center gap-1.5 rounded-lg border border-leaf px-3 py-1.5 text-sm font-medium text-leaf-ink transition hover:bg-leaf-soft"
              >
                <Icon name="external-link" size={16} />
                נהל את התור
              </Link>
            </div>
          </div>

          <p className="mt-4 text-xs text-slate-400">שמרו את הקישור — תצטרכו אותו לשינויים.</p>
        </div>
      </PublicBookingLayout>
    )
  }

  // Booking form.
  return (
    <PublicBookingLayout businessName={businessName}>
      <form onSubmit={(ev) => void submit(ev)} className="flex flex-col gap-6">
        {/* Step 1: service */}
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-semibold text-slate-900">1 · בחרו שירות</h2>
          {services.length === 0 ? (
            <p className="text-sm text-slate-500">אין כרגע שירותים זמינים לקביעה.</p>
          ) : (
            <div role="radiogroup" aria-label="בחירת שירות" className="flex flex-col gap-2">
              {services.map((svc) => {
                const selected = svc.id === serviceId
                return (
                  <button
                    key={svc.id}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => {
                      setServiceId(svc.id)
                      setTime('')
                    }}
                    className={`flex items-center justify-between rounded-xl border px-4 py-3 text-start transition ${
                      selected
                        ? 'border-leaf bg-leaf-soft'
                        : 'border-slate-300 bg-white hover:border-leaf'
                    }`}
                  >
                    <span className="text-sm font-medium text-slate-900">{svc.name}</span>
                    <span className="text-xs text-slate-500">{svc.duration_minutes} דק׳</span>
                  </button>
                )
              })}
            </div>
          )}
        </section>

        {/* Step 2: date */}
        {serviceId ? (
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold text-slate-900">2 · בחרו תאריך</h2>
            <div className="flex justify-center">
              <DatePicker value={date} onChange={setDate} />
            </div>
          </section>
        ) : null}

        {/* Step 3: slot */}
        {serviceId && date ? (
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold text-slate-900">3 · בחרו שעה</h2>
            {slotsLoading ? (
              <Spinner label="טוען שעות פנויות…" className="py-6" />
            ) : slotsError ? (
              <Alert tone="error">{slotsError}</Alert>
            ) : (
              <SlotGrid slots={slots ?? []} value={time} onChange={setTime} />
            )}
          </section>
        ) : null}

        {/* Step 4: details */}
        {serviceId && date && time ? (
          <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
            <h2 className="mb-3 text-sm font-semibold text-slate-900">4 · הפרטים שלכם</h2>
            <div className="flex flex-col gap-3">
              <Field
                label="שם מלא"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
                required
                maxLength={120}
              />
              <Field
                label="טלפון"
                type="tel"
                dir="ltr"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                autoComplete="tel"
                required
                maxLength={20}
              />
              <Field
                label="אימייל (לא חובה)"
                type="email"
                dir="ltr"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                hint="נשלח לכם אישור והזמנה ליומן אם תזינו אימייל"
                maxLength={200}
              />
              <Textarea
                label="הערות (לא חובה)"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                maxLength={1000}
              />
            </div>

            {formError ? (
              <p role="alert" className="mt-3 text-sm text-bad">
                {formError}
              </p>
            ) : null}
            {submitError ? (
              <Alert tone="error" className="mt-3">
                {submitError}
              </Alert>
            ) : null}

            <Button
              type="submit"
              disabled={submitting}
              className="mt-4 w-full !bg-leaf hover:!bg-leaf-dark"
            >
              <Icon name="check" size={18} />
              {submitting ? 'קובע תור…' : 'קבע תור'}
            </Button>
          </section>
        ) : null}
      </form>
    </PublicBookingLayout>
  )
}
