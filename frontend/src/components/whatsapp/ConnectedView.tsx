// תצוגת "מחובר" בעמוד וואטסאפ: מציגה שהחשבון מחובר ואת המספר המקושר.

import Icon from '../ui/Icon'

// Present the linked own-number digits a little more kindly (grouped, with a
// leading +). Falls back to the raw value if it isn't a plain digit string.
function formatPhone(phone: string): string {
  const digits = phone.replace(/\D/g, '')
  if (!digits) return phone
  return `+${digits}`
}

export default function ConnectedView({ phone }: { phone: string | null }) {
  return (
    <div className="flex flex-col items-center gap-3 py-6 text-center">
      <span
        aria-hidden="true"
        className="flex h-14 w-14 items-center justify-center rounded-full bg-leaf-soft text-leaf-ink"
      >
        <Icon name="brand-whatsapp" size={30} />
      </span>
      <p className="flex items-center gap-2 text-lg font-semibold text-leaf-ink">
        <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full bg-leaf" />
        מחובר
      </p>
      {phone ? (
        <p className="text-sm text-slate-600">
          המספר המחובר:{' '}
          <bdi className="font-medium text-slate-900">{formatPhone(phone)}</bdi>
        </p>
      ) : null}
      <p className="max-w-sm text-sm text-slate-500">
        הוואטסאפ של העסק מחובר. הבוט יקבל הודעות ויענה אוטומטית — בתנאי שהבוט
        מפורסם.
      </p>
    </div>
  )
}
