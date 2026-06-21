// The owner's booking-settings tab. Loads settings + services together, lets the
// owner edit working hours / availability rules / the Meet toggle (saved with one
// PUT), manage services (each saved on its own), connect Google Calendar, and
// copy the public booking link. Tenant is server-side only.

import { useCallback, useEffect, useState } from 'react'
import type { BookingSettings, ServiceItem } from '../../dashboard/appointmentTypes'
import {
  getBookingSettings,
  getServices,
  updateBookingSettings,
} from '../../lib/bookingClient'
import { toFriendlyError } from '../../lib/friendlyError'
import Spinner from '../ui/Spinner'
import Alert from '../ui/Alert'
import Card from '../ui/Card'
import Icon from '../ui/Icon'
import Button from '../ui/Button'
import CopyButton from '../ui/CopyButton'
import WorkingHoursEditor from './WorkingHoursEditor'
import ServicesEditor from './ServicesEditor'
import AvailabilityRulesEditor from './AvailabilityRulesEditor'
import GoogleConnectPanel from './GoogleConnectPanel'

// The customer-facing booking URL for a slug (same origin as the app — the bot
// sends exactly this path: {PUBLIC_BASE_URL}/book/{slug}).
function publicBookingUrl(slug: string): string {
  return `${window.location.origin}/book/${slug}`
}

export default function BookingSettingsPanel() {
  const [settings, setSettings] = useState<BookingSettings | null>(null)
  const [services, setServices] = useState<ServiceItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

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
      })
      setSettings(updated)
      setSaved(true)
    } catch (err) {
      setSaveError(toFriendlyError(err, 'שמירת ההגדרות נכשלה. נסו שוב.'))
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Spinner label="טוען הגדרות…" className="py-12" />
  if (error) return <Alert tone="error">{error}</Alert>
  if (!settings) return null

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
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <code dir="ltr" className="rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-800">
            {publicBookingUrl(settings.slug)}
          </code>
          <CopyButton value={publicBookingUrl(settings.slug)} />
          <a
            href={publicBookingUrl(settings.slug)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            <Icon name="external-link" size={16} />
            פתח
          </a>
        </div>
      </Card>

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

      {/* Services */}
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
