// The subscription-control panel on the business detail page (M12). The admin
// picks a plan + a status and saves; PATCH /api/admin/businesses/{id}/subscription
// upserts both and syncs the bot's on/off switch server-side. We update
// optimistically and surface success/error via an Alert (role="alert", so it's
// announced). 404/422 map to friendly Hebrew via toFriendlyError.
//
// A clear note explains that "מושהה"/"בוטל" SILENCE the bot — this is a real
// action, not just a label.

import { useEffect, useState } from 'react'
import Card from '../ui/Card'
import Select from '../ui/Select'
import Button from '../ui/Button'
import Alert from '../ui/Alert'
import Icon from '../ui/Icon'
import { setSubscription } from '../../lib/adminClient'
import { toFriendlyError } from '../../lib/friendlyError'
import { STATUS_META, formatPrice } from '../../admin/labels'
import type { Plan, SubscriptionStatus } from '../../admin/types'

const STATUSES: SubscriptionStatus[] = ['active', 'suspended', 'cancelled']

type Props = {
  businessId: string
  plans: Plan[]
  /** Current plan/status — the panel seeds its selects from these. */
  planCode: string
  status: SubscriptionStatus
  /** Called after a successful save with the new values (parent re-syncs header). */
  onSaved: (planCode: string, status: SubscriptionStatus, isActive: boolean) => void
}

export default function SubscriptionPanel({
  businessId,
  plans,
  planCode,
  status,
  onSaved,
}: Props) {
  const [plan, setPlan] = useState(planCode)
  const [newStatus, setNewStatus] = useState<SubscriptionStatus>(status)
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<{ tone: 'info' | 'error'; text: string } | null>(
    null,
  )

  // Re-seed when the parent's current values change (e.g. after a refetch).
  useEffect(() => {
    setPlan(planCode)
    setNewStatus(status)
  }, [planCode, status])

  const planOptions = plans.map((p) => ({
    value: p.code,
    label: `${p.name || p.code} · ${formatPrice(p.price)}`,
  }))
  const statusOptions = STATUSES.map((s) => ({
    value: s,
    label: STATUS_META[s].label,
  }))

  const dirty = plan !== planCode || newStatus !== status
  // A non-active status silences the bot — warn before/while saving.
  const willSilence = newStatus !== 'active'

  async function onSave() {
    setSaving(true)
    setResult(null)
    try {
      const res = await setSubscription(businessId, plan, newStatus)
      onSaved(res.plan_code, res.status, res.is_active)
      setResult({ tone: 'info', text: 'המנוי עודכן בהצלחה.' })
    } catch (err) {
      setResult({ tone: 'error', text: toFriendlyError(err, 'עדכון המנוי נכשל. נסו שוב.') })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <h2 className="flex items-center gap-2 text-lg font-medium text-slate-900">
        <Icon name="currency-shekel" size={20} className="text-leaf" />
        ניהול מנוי
      </h2>
      <p className="mt-1 text-sm text-slate-500">
        שינוי התוכנית או הסטטוס של העסק. סטטוס <span className="font-medium">מושהה</span>{' '}
        או <span className="font-medium">בוטל</span> משתיק את הבוט של העסק בפועל — הוא יפסיק
        לענות ללקוחות.
      </p>

      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Select
          label="תוכנית"
          options={planOptions}
          value={plan}
          onChange={(e) => setPlan(e.target.value)}
          disabled={saving || planOptions.length === 0}
        />
        <Select
          label="סטטוס מנוי"
          options={statusOptions}
          value={newStatus}
          onChange={(e) => setNewStatus(e.target.value as SubscriptionStatus)}
          disabled={saving}
        />
      </div>

      {willSilence ? (
        <p className="mt-3">
          <Alert tone="warning">
            בסטטוס זה הבוט של העסק יושתק ולא יענה ללקוחות עד שתחזירו אותו ל"פעיל".
          </Alert>
        </p>
      ) : null}

      <div className="mt-4 flex items-center gap-3">
        <Button onClick={() => void onSave()} disabled={saving || !dirty}>
          <Icon name="device-floppy" size={18} />
          {saving ? 'שומר…' : 'שמירת שינויים'}
        </Button>
        {!dirty && !result ? (
          <span className="text-sm text-slate-400">אין שינויים לשמירה.</span>
        ) : null}
      </div>

      {result ? (
        <p className="mt-3">
          <Alert tone={result.tone}>{result.text}</Alert>
        </p>
      ) : null}
    </Card>
  )
}
