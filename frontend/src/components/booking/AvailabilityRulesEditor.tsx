// Availability rules + the global Google Meet toggle. Controlled by the parent
// (the settings panel owns the draft settings object). Each numeric rule is a
// labelled <input type="number"> with a hint explaining what it controls.

import type { BookingSettings } from '../../dashboard/appointmentTypes'
import Field from '../ui/Field'

type Props = {
  settings: BookingSettings
  onChange: (patch: Partial<BookingSettings>) => void
}

export default function AvailabilityRulesEditor({ settings, onChange }: Props) {
  // Keep numbers >= 0; empty input is treated as 0 so the field never goes NaN.
  const num = (v: string) => {
    const n = Number(v)
    return Number.isFinite(n) && n >= 0 ? n : 0
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <Field
          label="התראה מוקדמת (דקות)"
          hint="כמה זמן מראש אפשר עוד לקבוע"
          type="number"
          min={0}
          step={15}
          value={String(settings.min_notice_minutes)}
          onChange={(ev) => onChange({ min_notice_minutes: num(ev.target.value) })}
        />
        <Field
          label="מרווח בין פגישות (דקות)"
          hint="זמן פנוי שנשמר אחרי כל פגישה"
          type="number"
          min={0}
          step={5}
          value={String(settings.buffer_minutes)}
          onChange={(ev) => onChange({ buffer_minutes: num(ev.target.value) })}
        />
        <Field
          label="קביעה עד (ימים קדימה)"
          hint="עד כמה רחוק קדימה אפשר לקבוע"
          type="number"
          min={1}
          max={365}
          step={1}
          value={String(settings.max_days_ahead)}
          onChange={(ev) => onChange({ max_days_ahead: num(ev.target.value) })}
        />
      </div>

      <div className="flex items-start gap-3 rounded-xl border border-black/10 bg-white p-3">
        <input
          id="meet-enabled"
          type="checkbox"
          checked={settings.meet_enabled}
          onChange={(ev) => onChange({ meet_enabled: ev.target.checked })}
          aria-describedby="meet-enabled-hint"
          className="mt-0.5 h-4 w-4 rounded border-slate-300 text-leaf focus-visible:ring-leaf"
        />
        <div>
          <label htmlFor="meet-enabled" className="text-sm font-medium text-slate-800">
            צרף קישור Google Meet לכל פגישה
          </label>
          <p id="meet-enabled-hint" className="mt-0.5 text-xs text-slate-500">
            דורש חיבור ליומן Google. אם לא מחובר, הפגישות עדיין נקבעות — פשוט בלי Meet.
          </p>
        </div>
      </div>
    </div>
  )
}
