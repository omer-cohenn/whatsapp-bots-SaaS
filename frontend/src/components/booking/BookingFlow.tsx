// <BookingFlow> — the reusable, end-to-end public booking experience built to the
// approved M11.1 prototype (welcome hero, service cards, a custom month calendar,
// a slot grid, a summary + customer form, and a confirmation screen).
//
// It runs in one of two MODES:
//   * "live"    — real data + a real POST on submit (the public /book/:slug page).
//   * "preview" — read-only owner preview inside booking settings. Services +
//                 welcome come from the current owner draft; the calendar/slots
//                 stay inert (no fetching, no POST) so the owner just sees the look.
//
// Tenant is server-side only: live mode resolves everything from the verified
// {slug}. The client never sends a business_id. PII is sent only to the backend
// (which encrypts it); we validate client-side too, but the server is authoritative.
//
// A11y: step sections are landmarks with numbered badges; service cards + slots +
// calendar days are radiogroups; the form is a real <form> (Enter submits); async
// status uses aria-live; errors use role="alert".

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  PublicBookingCreate,
  PublicBookingResponse,
  PublicService,
} from '../../dashboard/appointmentTypes'
import {
  createPublicBooking,
  getPublicAvailability,
  getPublicSlots,
} from '../../lib/publicBookingClient'
import { ApiError } from '../../lib/apiClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { fullDateTime } from '../../lib/formatDate'
import {
  monthEnd,
  monthOf,
  monthStart,
  type YearMonth,
} from '../../lib/bookingDates'
import AvailabilityCalendar from './AvailabilityCalendar'
import SlotGrid from './SlotGrid'
import Field from '../ui/Field'
import Textarea from '../ui/Textarea'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import Spinner from '../ui/Spinner'
import Icon from '../ui/Icon'

const DEFAULT_WELCOME =
  'שמחים שבחרתם לקבוע תור! בחרו את השירות, התאריך והשעה הנוחים לכם — וניצור איתכם קשר לאישור.'

// Israeli phone: 9-15 digits, optionally with a leading + and separators.
function isValidPhone(phone: string): boolean {
  const digits = phone.replace(/[\s-]/g, '')
  return /^\+?\d{9,15}$/.test(digits)
}

function isValidEmail(email: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)
}

/** "ללא עלות" when no price is set, else "₪{price}". */
function priceLabel(price: number | null): string {
  return price == null ? 'ללא עלות' : `₪${price}`
}

type Props =
  | {
      mode: 'live'
      slug: string
      services: PublicService[]
      welcomeMessage: string | null
    }
  | {
      mode: 'preview'
      services: PublicService[]
      welcomeMessage: string | null
    }

export default function BookingFlow(props: Props) {
  const { mode, services, welcomeMessage } = props
  const isLive = mode === 'live'

  // Selection state.
  const [serviceId, setServiceId] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('')

  // Visible calendar month + the available days for it.
  const [month, setMonth] = useState<YearMonth>(() => monthOf())
  const [availableDates, setAvailableDates] = useState<Set<string>>(new Set())
  const [availLoading, setAvailLoading] = useState(false)
  const [availError, setAvailError] = useState<string | null>(null)

  // Slots for the chosen service + date.
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

  const selectedService = useMemo(
    () => services.find((s) => s.id === serviceId) ?? null,
    [services, serviceId],
  )

  // Reset selections if the underlying services change (owner editing in preview).
  const servicesKey = services.map((s) => s.id).join(',')
  const prevServicesKey = useRef(servicesKey)
  useEffect(() => {
    if (prevServicesKey.current !== servicesKey) {
      prevServicesKey.current = servicesKey
      if (serviceId && !services.some((s) => s.id === serviceId)) {
        setServiceId('')
        setDate('')
        setTime('')
      }
    }
  }, [servicesKey, serviceId, services])

  // --- availability: fetch the visible month whenever service/month changes ---
  useEffect(() => {
    if (!isLive || !serviceId) {
      setAvailableDates(new Set())
      return
    }
    const { slug } = props as Extract<Props, { mode: 'live' }>
    let cancelled = false
    setAvailLoading(true)
    setAvailError(null)
    getPublicAvailability(slug, serviceId, monthStart(month), monthEnd(month))
      .then((res) => {
        if (!cancelled) setAvailableDates(new Set(res.dates))
      })
      .catch((err) => {
        if (!cancelled) {
          setAvailableDates(new Set())
          setAvailError(toFriendlyError(err, 'טעינת הזמינות נכשלה. נסו שוב.'))
        }
      })
      .finally(() => {
        if (!cancelled) setAvailLoading(false)
      })
    return () => {
      cancelled = true
    }
    // props is stable enough here; serviceId+month+isLive drive the fetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLive, serviceId, month.year, month.month0])

  // --- slots: fetch whenever service + date are both chosen ---
  const loadSlots = useCallback(() => {
    if (!isLive || !serviceId || !date) {
      setSlots(null)
      return
    }
    const { slug } = props as Extract<Props, { mode: 'live' }>
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLive, serviceId, date])

  useEffect(() => loadSlots(), [loadSlots])

  function pickService(id: string) {
    setServiceId(id)
    setDate('')
    setTime('')
    setSlots(null)
  }

  function pickDate(d: string) {
    setDate(d)
    setTime('')
  }

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
    if (!isLive) return // preview never POSTs
    const err = validate()
    if (err) {
      setFormError(err)
      return
    }
    setFormError(null)
    setSubmitError(null)
    setSubmitting(true)
    const { slug } = props as Extract<Props, { mode: 'live' }>
    const body: PublicBookingCreate = {
      service_id: serviceId,
      date,
      time,
      name: name.trim(),
      phone: phone.trim(),
      email: email.trim() || undefined,
      notes: notes.trim() || undefined,
    }
    try {
      const res = await createPublicBooking(slug, body)
      setResult(res)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setSubmitError('המועד הזה נתפס זה עתה. בחרו שעה אחרת.')
        loadSlots() // refresh availability for the day
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

  // --- confirmation screen (live only) ---
  if (isLive && result) {
    const { slug } = props as Extract<Props, { mode: 'live' }>
    const manageUrl = `${window.location.origin}/book/${slug}/manage/${result.cancel_token}`
    return (
      <div className="rounded-[22px] border border-leaf/30 bg-white p-7 text-center shadow-sm">
        <span
          aria-hidden="true"
          className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-leaf-soft text-leaf-ink"
        >
          <Icon name="check" size={32} />
        </span>
        <h2 className="text-2xl font-bold text-slate-900">ההזמנה אושרה</h2>
        <p className="mt-2 text-sm text-slate-600">
          {selectedService ? `${selectedService.name} · ` : ''}
          {fullDateTime(result.scheduled_at)}
        </p>

        <div className="mt-6 rounded-2xl border border-black/10 bg-slate-50 p-4 text-start">
          <p className="text-sm font-medium text-slate-800">לניהול ההזמנה (ביטול / שינוי מועד):</p>
          <a
            href={`/book/${slug}/manage/${result.cancel_token}`}
            className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-leaf px-3 py-1.5 text-sm font-medium text-leaf-ink transition hover:bg-leaf-soft"
          >
            <Icon name="external-link" size={16} />
            ניהול ההזמנה
          </a>
          <p className="mt-2 break-all text-xs text-slate-500" dir="ltr">
            {manageUrl}
          </p>
        </div>
        <p className="mt-4 text-xs text-slate-400">שמרו את הקישור — תצטרכו אותו לשינויים.</p>
      </div>
    )
  }

  const showSummary = Boolean(serviceId && date && time)

  return (
    <div className="flex flex-col gap-5">
      {/* Welcome hero */}
      <header className="rounded-[22px] bg-white p-6 shadow-sm">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-leaf-soft px-3 py-1 text-xs font-medium text-leaf-ink">
          <Icon name="sparkles" size={14} />
          קביעת תור
        </span>
        <h1 className="mt-3 text-2xl font-bold text-slate-900">בואו נקבע תור</h1>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-600">
          {welcomeMessage?.trim() || DEFAULT_WELCOME}
        </p>
      </header>

      <form onSubmit={(ev) => void submit(ev)} className="flex flex-col gap-5">
        {/* Step 1 — choose service */}
        <StepSection step={1} done={Boolean(serviceId)} title="בחרו שירות">
          {services.length === 0 ? (
            <p className="text-sm text-slate-500">אין כרגע שירותים זמינים לקביעה.</p>
          ) : (
            <div
              role="radiogroup"
              aria-label="בחירת שירות"
              className="grid grid-cols-1 gap-3 sm:grid-cols-2"
            >
              {services.map((svc) => {
                const selected = svc.id === serviceId
                return (
                  <button
                    key={svc.id}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => pickService(svc.id)}
                    className={[
                      'relative flex flex-col gap-3 overflow-hidden rounded-2xl border bg-white p-3 text-start transition',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-leaf',
                      selected
                        ? 'border-[#2563EB] ring-2 ring-[#2563EB]'
                        : 'border-slate-200 hover:border-[#2563EB]/60',
                    ].join(' ')}
                  >
                    {/* Image frame on top: the photo, or a placeholder when empty. */}
                    <span className="relative block aspect-[16/9] w-full overflow-hidden rounded-2xl border border-[#2563EB]/15 bg-[#2563EB]/5">
                      {svc.image_url ? (
                        <img
                          src={svc.image_url}
                          alt=""
                          className="h-full w-full object-cover"
                          loading="lazy"
                        />
                      ) : (
                        <span className="flex h-full w-full flex-col items-center justify-center gap-1 text-slate-400">
                          <Icon name="photo" size={28} />
                          <span className="text-xs font-medium">מקום לתמונה</span>
                        </span>
                      )}
                      {selected ? (
                        <span
                          aria-hidden="true"
                          className="absolute top-2 left-2 flex h-6 w-6 items-center justify-center rounded-full bg-[#2563EB] text-white shadow"
                        >
                          <Icon name="check" size={15} />
                        </span>
                      ) : null}
                    </span>

                    {/* Title + description */}
                    <span className="block px-1 text-base font-semibold text-slate-900">
                      {svc.name}
                    </span>
                    {svc.description ? (
                      <span className="block px-1 text-sm leading-relaxed text-slate-500">
                        {svc.description}
                      </span>
                    ) : null}

                    {/* Duration chip + price */}
                    <span className="mt-auto flex items-center justify-between gap-2 px-1">
                      <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
                        <Icon name="clock" size={13} />
                        {svc.duration_minutes} דק׳
                      </span>
                      <span className="text-sm font-semibold text-leaf-ink">
                        {priceLabel(svc.price)}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </StepSection>

        {/* Step 2 — choose date */}
        {serviceId ? (
          <StepSection step={2} done={Boolean(date)} title="בחרו תאריך">
            {!isLive ? (
              <p className="rounded-xl border border-dashed border-slate-300 px-4 py-4 text-center text-sm text-slate-500">
                בתצוגה מקדימה — לוח התאריכים יוצג ללקוח לפי הזמינות שלכם.
              </p>
            ) : availError ? (
              <Alert tone="error">{availError}</Alert>
            ) : (
              <AvailabilityCalendar
                month={month}
                onMonthChange={setMonth}
                availableDates={availableDates}
                value={date}
                onChange={pickDate}
                loading={availLoading}
              />
            )}
          </StepSection>
        ) : null}

        {/* Step 3 — choose time */}
        {serviceId && date ? (
          <StepSection step={3} done={Boolean(time)} title="בחרו שעה">
            {slotsLoading ? (
              <Spinner label="טוען שעות פנויות…" className="py-6" />
            ) : slotsError ? (
              <Alert tone="error">{slotsError}</Alert>
            ) : (
              <SlotGrid slots={slots ?? []} value={time} onChange={setTime} />
            )}
          </StepSection>
        ) : null}

        {/* Summary + customer form */}
        {showSummary ? (
          <section className="rounded-[22px] border border-leaf/30 bg-white p-5 shadow-sm">
            <h2 className="mb-3 text-base font-semibold text-slate-900">סיכום ופרטים</h2>

            <dl className="mb-4 grid grid-cols-2 gap-3 rounded-2xl bg-leaf-soft/60 p-4 text-sm">
              <div>
                <dt className="text-xs text-slate-500">שירות</dt>
                <dd className="font-medium text-slate-900">{selectedService?.name}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">מתי</dt>
                <dd className="font-medium text-slate-900">{`${date} · ${time}`}</dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">משך</dt>
                <dd className="font-medium text-slate-900">
                  {selectedService?.duration_minutes} דק׳
                </dd>
              </div>
              <div>
                <dt className="text-xs text-slate-500">מחיר</dt>
                <dd className="font-medium text-slate-900">
                  {priceLabel(selectedService?.price ?? null)}
                </dd>
              </div>
            </dl>

            <div className="flex flex-col gap-3">
              <Field
                label="שם מלא"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
                required
                maxLength={120}
                disabled={!isLive}
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
                disabled={!isLive}
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
                disabled={!isLive}
              />
              <Textarea
                label="הערות (לא חובה)"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                maxLength={1000}
                disabled={!isLive}
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
              disabled={submitting || !isLive}
              className="mt-4 w-full !bg-leaf hover:!bg-leaf-dark"
            >
              <Icon name="check" size={18} />
              {isLive ? (submitting ? 'מאשר…' : 'אישור הזמנה') : 'אישור הזמנה (תצוגה מקדימה)'}
            </Button>
          </section>
        ) : null}
      </form>
    </div>
  )
}

// A numbered step card with a badge that flips to a check when the step is done.
function StepSection({
  step,
  done,
  title,
  children,
}: {
  step: number
  done: boolean
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-[22px] bg-white p-5 shadow-sm">
      <h2 className="mb-4 flex items-center gap-2.5 text-base font-semibold text-slate-900">
        <span
          aria-hidden="true"
          className={[
            'flex h-7 w-7 items-center justify-center rounded-full text-sm font-semibold',
            done ? 'bg-leaf text-white' : 'bg-slate-100 text-slate-500',
          ].join(' ')}
        >
          {done ? <Icon name="check" size={16} /> : step}
        </span>
        {title}
      </h2>
      {children}
    </section>
  )
}
