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
import ServiceCard, { priceLabel } from './public/ServiceCard'
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
      <div className={`${PANEL} p-7 text-center`}>
        <span
          aria-hidden="true"
          className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--bp-primary, #639922) 16%, transparent)',
            color: 'var(--bp-primary, #639922)',
          }}
        >
          <Icon name="check" size={34} />
        </span>
        <h2 className="text-2xl font-black" style={{ color: 'var(--bp-text, #0f172a)' }}>
          ההזמנה אושרה
        </h2>
        <p className="mt-2 text-sm" style={{ color: 'var(--bp-muted, #64748b)' }}>
          {selectedService ? `${selectedService.name} · ` : ''}
          {fullDateTime(result.scheduled_at)}
        </p>

        <div
          className="mt-6 rounded-[var(--bp-radius,18px)] border p-4 text-start"
          style={{
            borderColor: 'var(--bp-border, #e2e8f0)',
            backgroundColor: 'var(--bp-bg, #f8fafc)',
          }}
        >
          <p className="text-sm font-medium" style={{ color: 'var(--bp-text, #1e293b)' }}>
            לניהול ההזמנה (ביטול / שינוי מועד):
          </p>
          <a
            href={`/book/${slug}/manage/${result.cancel_token}`}
            className="mt-2 inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition hover:brightness-95"
            style={{
              borderColor: 'var(--bp-primary, #639922)',
              color: 'var(--bp-primary, #639922)',
            }}
          >
            <Icon name="external-link" size={16} />
            ניהול ההזמנה
          </a>
          <p className="mt-2 break-all text-xs" dir="ltr" style={{ color: 'var(--bp-muted, #94a3b8)' }}>
            {manageUrl}
          </p>
        </div>
        <p className="mt-4 text-xs" style={{ color: 'var(--bp-muted, #94a3b8)' }}>
          שמרו את הקישור — תצטרכו אותו לשינויים.
        </p>
      </div>
    )
  }

  const showSummary = Boolean(serviceId && date && time)

  // ONE surface for the whole flow, with hairlines between the steps — the owner
  // rejected the previous look ("לא אהבתי שזה מחולק ככה לתיבות"), which was four
  // separate white cards stacked with gaps.
  return (
    <div className={`${PANEL} overflow-hidden`}>
      {/* Welcome */}
      <header className="px-5 py-6 sm:px-7">
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--bp-primary, #639922) 14%, transparent)',
            color: 'var(--bp-primary, #639922)',
          }}
        >
          <Icon name="sparkles" size={14} />
          קביעת תור
        </span>
        <h2
          className="mt-3 text-xl font-black"
          style={{ color: 'var(--bp-text, #0f172a)' }}
        >
          בואו נקבע תור
        </h2>
        <p
          className="mt-2 whitespace-pre-wrap text-sm leading-relaxed"
          style={{ color: 'var(--bp-muted, #64748b)' }}
        >
          {welcomeMessage?.trim() || DEFAULT_WELCOME}
        </p>
      </header>

      <StepTrail current={showSummary ? 4 : serviceId ? (date ? 3 : 2) : 1} />

      <form onSubmit={(ev) => void submit(ev)}>
        {/* Step 1 — choose service */}
        <StepSection step={1} done={Boolean(serviceId)} title="בחרו שירות">
          {services.length === 0 ? (
            <p className="text-sm" style={{ color: 'var(--bp-muted, #64748b)' }}>
              אין כרגע שירותים זמינים לקביעה.
            </p>
          ) : (
            <div
              role="radiogroup"
              aria-label="בחירת שירות"
              className="grid grid-cols-1 gap-3 sm:grid-cols-2"
            >
              {services.map((svc) => (
                <ServiceCard
                  key={svc.id}
                  name={svc.name}
                  description={svc.description}
                  durationMinutes={svc.duration_minutes}
                  price={svc.price}
                  selected={svc.id === serviceId}
                  onSelect={() => pickService(svc.id)}
                />
              ))}
            </div>
          )}
        </StepSection>

        {/* Step 2 — choose date */}
        {serviceId ? (
          <StepSection step={2} done={Boolean(date)} title="בחרו תאריך">
            {!isLive ? (
              <p
                className="rounded-xl border border-dashed px-4 py-4 text-center text-sm"
                style={{
                  borderColor: 'var(--bp-border, #cbd5e1)',
                  color: 'var(--bp-muted, #64748b)',
                }}
              >
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
          <StepSection step={4} done={false} title="סיכום ופרטים">
            <dl
              className="mb-4 grid grid-cols-2 gap-3 rounded-[var(--bp-radius,18px)] p-4 text-sm"
              style={{
                backgroundColor:
                  'color-mix(in srgb, var(--bp-primary, #639922) 10%, transparent)',
              }}
            >
              {[
                ['שירות', selectedService?.name ?? ''],
                ['מתי', `${date} · ${time}`],
                ['משך', `${selectedService?.duration_minutes ?? ''} דק׳`],
                ['מחיר', priceLabel(selectedService?.price ?? null)],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs" style={{ color: 'var(--bp-muted, #64748b)' }}>
                    {label}
                  </dt>
                  <dd className="font-semibold" style={{ color: 'var(--bp-text, #0f172a)' }}>
                    {value}
                  </dd>
                </div>
              ))}
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
              style={{
                backgroundColor: 'var(--bp-primary, #639922)',
                color: 'var(--bp-on-primary, #ffffff)',
              }}
              className="mt-4 w-full rounded-[var(--bp-radius,12px)] py-3 text-base font-bold transition hover:brightness-110"
            >
              <Icon name="check" size={18} />
              {isLive ? (submitting ? 'מאשר…' : 'אישור הזמנה') : 'אישור הזמנה (תצוגה מקדימה)'}
            </Button>
          </StepSection>
        ) : null}
      </form>
    </div>
  )
}

/**
 * The whole flow's surface. A palette variable with a neutral fallback, so the
 * same component looks right on the designed page AND on the plain shell.
 * `bp-booking` is what the CSS in `index.css` hooks onto to theme the inputs.
 */
const PANEL =
  'bp-booking rounded-[var(--bp-radius,22px)] border border-[color:var(--bp-border,transparent)] bg-[color:var(--bp-surface,#ffffff)] shadow-sm'

/**
 * The reference's three-dot progress rail, themed by the palette. Purely
 * decorative (aria-hidden) — the real, announced progress is the numbered
 * <StepSection> headings, which are landmarks a screen reader already walks.
 */
function StepTrail({ current }: { current: number }) {
  const steps = ['שירות', 'תאריך', 'שעה', 'פרטים']
  return (
    <div
      aria-hidden="true"
      className="mx-auto flex max-w-md items-center gap-1 px-5 pb-6 sm:px-7"
    >
      {steps.map((label, i) => {
        const n = i + 1
        const reached = current >= n
        return (
          <div key={label} className="flex flex-1 items-center gap-1 last:flex-none">
            <div className="flex flex-col items-center gap-1">
              <span
                className="flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold transition"
                style={
                  reached
                    ? {
                        backgroundColor: 'var(--bp-primary, #639922)',
                        color: 'var(--bp-on-primary, #ffffff)',
                      }
                    : {
                        backgroundColor:
                          'color-mix(in srgb, var(--bp-muted, #94a3b8) 18%, transparent)',
                        color: 'var(--bp-muted, #64748b)',
                      }
                }
              >
                {n}
              </span>
              <span
                className="text-[10px] font-semibold"
                style={{ color: reached ? 'var(--bp-primary, #639922)' : 'var(--bp-muted, #94a3b8)' }}
              >
                {label}
              </span>
            </div>
            {n < steps.length ? (
              <span
                className="mb-4 h-0.5 flex-1 rounded-full"
                style={{
                  backgroundColor:
                    current > n
                      ? 'var(--bp-primary, #639922)'
                      : 'color-mix(in srgb, var(--bp-muted, #94a3b8) 18%, transparent)',
                }}
              />
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

// A numbered step, separated from its neighbours by ONE hairline instead of
// being its own floating card. Same information, continuous surface.
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
    <section
      className="border-t px-5 py-6 sm:px-7"
      style={{ borderColor: 'var(--bp-border, #e2e8f0)' }}
    >
      <h3
        className="mb-4 flex items-center gap-2.5 text-base font-bold"
        style={{ color: 'var(--bp-text, #0f172a)' }}
      >
        <span
          aria-hidden="true"
          className="flex h-7 w-7 items-center justify-center rounded-full text-sm font-bold"
          style={
            done
              ? {
                  backgroundColor: 'var(--bp-primary, #639922)',
                  color: 'var(--bp-on-primary, #ffffff)',
                }
              : {
                  backgroundColor:
                    'color-mix(in srgb, var(--bp-muted, #94a3b8) 18%, transparent)',
                  color: 'var(--bp-muted, #64748b)',
                }
          }
        >
          {done ? <Icon name="check" size={16} /> : step}
        </span>
        {title}
      </h3>
      {children}
    </section>
  )
}
