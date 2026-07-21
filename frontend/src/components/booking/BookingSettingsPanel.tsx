// The owner's booking SETUP, split across two of the three setup tabs (M20).
// Loads settings + services together, then renders one of two sections:
//
//   'details'  — the public link, Google Calendar, the business details card,
//                the welcome message, and working hours + availability rules
//   'services' — the services editor and the live booking preview
//
// One component with a `section` prop rather than two, because both halves need
// the same settings+services fetch and the same save button state; splitting
// them would mean fetching everything twice.
//
// Working hours / availability / Meet are still saved with one PUT; each service
// saves on its own. Tenant is server-side only.

import { useCallback, useEffect, useMemo, useState } from 'react'
import type {
  BookingSettings,
  PublicService,
  ServiceItem,
} from '../../dashboard/appointmentTypes'
import {
  generateWelcomeMessage,
  getBookingSettings,
  getServices,
  updateBookingSettings,
} from '../../lib/bookingClient'
import { ApiError } from '../../lib/apiClient'
import { toFriendlyError } from '../../lib/friendlyError'
import Spinner from '../ui/Spinner'
import Alert from '../ui/Alert'
import Card from '../ui/Card'
import Icon from '../ui/Icon'
import Button from '../ui/Button'
import Textarea from '../ui/Textarea'
import CopyButton from '../ui/CopyButton'
import WorkingHoursEditor from './WorkingHoursEditor'
import ServicesEditor from './ServicesEditor'
import AvailabilityRulesEditor from './AvailabilityRulesEditor'
import GoogleConnectPanel from './GoogleConnectPanel'
import BookingFlow from './BookingFlow'
import DetailsPanel from './setup/DetailsPanel'

const WELCOME_MAX = 600

/** Which half of the setup this instance renders (see the file header). */
export type SettingsSection = 'details' | 'services'

// Friendly Hebrew for the AI generate failures (mirrors the bot-builder panel).
function welcomeAiError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 503) return 'עוזר ה-AI אינו זמין כרגע (לא הוגדר). נסו שוב מאוחר יותר.'
    if (err.status === 502) return 'עוזר ה-AI לא זמין זמנית. נסו שוב בעוד רגע.'
  }
  return toFriendlyError(err, 'ניסוח ההודעה נכשל. נסו שוב.')
}

// The customer-facing booking URL for a slug (same origin as the app — the bot
// sends exactly this path: {PUBLIC_BASE_URL}/book/{slug}).
function publicBookingUrl(slug: string): string {
  return `${window.location.origin}/book/${slug}`
}

export default function BookingSettingsPanel({
  section = 'details',
}: {
  section?: SettingsSection
}) {
  const [settings, setSettings] = useState<BookingSettings | null>(null)
  const [services, setServices] = useState<ServiceItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  // AI welcome generation.
  const [generating, setGenerating] = useState(false)
  const [genError, setGenError] = useState<string | null>(null)

  const load = useCallback(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([getBookingSettings(), getServices()])
      .then(([s, svc]) => {
        if (cancelled) return
        setSettings(s)
        setServices(svc.services)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת ההגדרות נכשלה. נסו שוב.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => load(), [load])

  // Reload only the services list after a CRUD action (keeps settings draft intact).
  const reloadServices = useCallback(() => {
    getServices()
      .then((svc) => setServices(svc.services))
      .catch(() => {
        /* keep the current list; the editor surfaces its own error */
      })
  }, [])

  // Merge a partial patch into the local settings draft.
  function patchSettings(patch: Partial<BookingSettings>) {
    setSettings((prev) => (prev ? { ...prev, ...patch } : prev))
    setSaved(false)
  }

  async function save() {
    if (!settings) return
    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      const updated = await updateBookingSettings({
        working_hours: settings.working_hours,
        min_notice_minutes: settings.min_notice_minutes,
        buffer_minutes: settings.buffer_minutes,
        max_days_ahead: settings.max_days_ahead,
        meet_enabled: settings.meet_enabled,
        // null clears it back to the default greeting; empty string → null.
        welcome_message: settings.welcome_message?.trim() || null,
      })
      setSettings(updated)
      setSaved(true)
    } catch (err) {
      setSaveError(toFriendlyError(err, 'שמירת ההגדרות נכשלה. נסו שוב.'))
    } finally {
      setSaving(false)
    }
  }

  // Ask the AI for a welcome and drop it into the draft textarea (owner then saves).
  async function generateWelcome() {
    setGenerating(true)
    setGenError(null)
    try {
      const res = await generateWelcomeMessage()
      patchSettings({ welcome_message: res.message.slice(0, WELCOME_MAX) })
    } catch (err) {
      setGenError(welcomeAiError(err))
    } finally {
      setGenerating(false)
    }
  }

  // The active services as the public page would see them — feeds the live preview.
  const previewServices = useMemo<PublicService[]>(
    () =>
      services
        .filter((s) => s.active)
        .map((s) => ({
          id: s.id,
          name: s.name,
          duration_minutes: s.duration_minutes,
          description: s.description,
          price: s.price,
        })),
    [services],
  )

  if (loading) return <Spinner label="טוען הגדרות…" className="py-12" />
  if (error) return <Alert tone="error">{error}</Alert>
  if (!settings) return null

  // --- tab 3: "השירותים שהעסק מציע" ---
  if (section === 'services') {
    return (
      <div className="flex flex-col gap-6">
        <Card>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
            <Icon name="calendar-event" size={20} className="text-leaf" />
            שירותים
          </h2>
          <p className="mt-1 mb-3 text-sm text-slate-500">
            כל שירות והמשך שלו — הלקוח בוחר שירות ואז שעה פנויה.
          </p>
          <ServicesEditor services={services} onChanged={reloadServices} />
        </Card>

        {/* Live preview of the public booking flow using the current services */}
        <Card>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
            <Icon name="eye" size={20} className="text-leaf" />
            תצוגה מקדימה
          </h2>
          <p className="mt-1 mb-3 text-sm text-slate-500">
            כך נראה דף קביעת התור ללקוחות (לתצוגה בלבד — בחירת תאריך/שעה והשליחה פעילות
            רק בדף הציבורי).
          </p>
          <div className="rounded-2xl bg-[#ece9e1] p-4">
            <BookingFlow
              mode="preview"
              services={previewServices}
              welcomeMessage={settings.welcome_message}
            />
          </div>
        </Card>
      </div>
    )
  }

  // --- tab 1: "פרטי העסק וזמינות" ---
  // Built once: the link is shown, copied AND opened, and all three must be the
  // exact same string (the copy button must never copy a shortened display text).
  const bookingUrl = publicBookingUrl(settings.slug)

  return (
    <div className="flex flex-col gap-6">
      {/* Public booking link */}
      <Card>
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
          <Icon name="world" size={20} className="text-leaf" />
          קישור לקביעת תור
        </h2>
        <p className="mt-1 text-sm text-slate-500">
          שתפו את הקישור הזה עם הלקוחות — או שהבוט ישלח אותו אוטומטית.
        </p>
        {/* 🔴 A URL is one unbreakable word. As a plain flex item the <code> got
            `min-width: auto` — i.e. the full string — so on a phone it refused to
            shrink, spilled out of the card and shoved "העתק קישור" ו"פתח" off the
            screen. Three things fix it, and all three are needed:
              min-w-0   — lets the box actually shrink below its text width
              break-all — gives the URL somewhere to wrap (it has no spaces)
              flex-col  — on a phone the link gets its own line, the two buttons
                          share the next one, so both stay reachable.
            The buttons still receive the FULL url (bookingUrl), never what the
            box happens to display. */}
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
          <code
            dir="ltr"
            className="min-w-0 flex-1 break-all rounded-lg bg-slate-100 px-3 py-2 text-start text-sm text-slate-800"
          >
            {bookingUrl}
          </code>
          <div className="flex flex-wrap items-center gap-2">
            <CopyButton value={bookingUrl} className="min-h-[44px] sm:min-h-0" />
            <a
              href={bookingUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-[44px] items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 sm:min-h-0"
            >
              <Icon name="external-link" size={16} />
              פתח
            </a>
          </div>
        </div>
      </Card>

      {/* Business details: name, tagline, about, address, the four hero fields.
          Loads GET /api/booking/page itself — see setup/DetailsPanel. */}
      <DetailsPanel />

      {/* Google Calendar */}
      <Card>
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
          <Icon name="brand-google" size={20} />
          יומן Google
        </h2>
        <p className="mt-1 mb-3 text-sm text-slate-500">
          סנכרון פגישות ליומן שלכם והזמנות אוטומטיות ללקוחות.
        </p>
        <GoogleConnectPanel />
      </Card>

      {/* Welcome message (shown atop the public page; saved with the settings PUT) */}
      <Card>
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
          <Icon name="sparkles" size={20} className="text-leaf" />
          הודעת פתיחה
        </h2>
        <p className="mt-1 mb-3 text-sm text-slate-500">
          ההודעה שהלקוחות רואים בראש דף קביעת התור. השאירו ריק כדי להציג ברירת מחדל.
        </p>

        <Textarea
          label="טקסט הפתיחה"
          value={settings.welcome_message ?? ''}
          onChange={(ev) => patchSettings({ welcome_message: ev.target.value })}
          rows={4}
          maxLength={WELCOME_MAX}
          placeholder="לדוגמה: שמחים שבחרתם בנו! בחרו שירות, תאריך ושעה — ונחזור אליכם לאישור."
          disabled={generating}
        />

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="secondary"
            onClick={() => void generateWelcome()}
            disabled={generating}
          >
            <Icon name="sparkles" size={16} />
            {generating ? 'מנסח…' : 'נסח עם AI'}
          </Button>
          <span className="text-xs text-slate-400">
            הניסוח ייכנס לתיבה — לחצו "שמור הגדרות" כדי לשמור.
          </span>
        </div>

        {genError ? (
          <Alert tone="error" className="mt-3">
            {genError}
          </Alert>
        ) : null}
      </Card>

      {/* Working hours + availability rules (saved together) */}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
            <Icon name="clock" size={20} className="text-leaf" />
            שעות פעילות וזמינות
          </h2>
          <div className="flex items-center gap-3">
            {saved ? (
              <span role="status" className="text-sm text-ok">
                נשמר
              </span>
            ) : null}
            <Button
              type="button"
              onClick={() => void save()}
              disabled={saving}
              className="!bg-leaf hover:!bg-leaf-dark"
            >
              <Icon name="device-floppy" size={16} />
              {saving ? 'שומר…' : 'שמור הגדרות'}
            </Button>
          </div>
        </div>

        {saveError ? (
          <Alert tone="error" className="mt-3">
            {saveError}
          </Alert>
        ) : null}

        <div className="mt-4 flex flex-col gap-6">
          <AvailabilityRulesEditor settings={settings} onChange={patchSettings} />
          <div>
            <h3 className="mb-2 text-sm font-medium text-slate-800">שעות פעילות לפי יום</h3>
            <WorkingHoursEditor
              value={settings.working_hours}
              onChange={(working_hours) => patchSettings({ working_hours })}
            />
          </div>
        </div>
      </Card>
    </div>
  )
}
