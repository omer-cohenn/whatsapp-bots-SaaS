// Top bar for the authenticated owner area: brand logo, a live WhatsApp
// connection-status pill, the user chip (avatar + name), and a logout button.

import { useAuth } from '../auth/AuthContext'
import type { ConnectionStatus } from '../auth/types'
import Button from './ui/Button'

type PillSpec = { label: string; classes: string }

// Map each connection status to a label + a contrast-safe colour set.
const PILLS: Record<ConnectionStatus, PillSpec> = {
  disconnected: { label: 'לא מחובר', classes: 'bg-red-50 text-bad border-red-200' },
  connecting: { label: 'מתחבר…', classes: 'bg-amber-50 text-amber-800 border-amber-200' },
  qr_pending: { label: 'מתחבר…', classes: 'bg-amber-50 text-amber-800 border-amber-200' },
  connected: { label: 'מחובר', classes: 'bg-green-50 text-ok border-green-200' },
}

function ConnectionPill({ status }: { status: ConnectionStatus | undefined }) {
  // Unknown status falls back to "disconnected" styling/label.
  const spec = (status && PILLS[status]) || PILLS.disconnected
  return (
    <span
      aria-live="polite"
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${spec.classes}`}
    >
      <span aria-hidden="true" className="h-2 w-2 rounded-full bg-current" />
      <span className="sr-only">סטטוס חיבור וואטסאפ: </span>
      {spec.label}
    </span>
  )
}

function UserChip({ name, picture }: { name: string; picture: string }) {
  return (
    <span className="flex items-center gap-2 text-sm text-slate-700">
      {picture ? (
        <img
          src={picture}
          alt=""
          aria-hidden="true"
          referrerPolicy="no-referrer"
          className="h-7 w-7 rounded-full border border-slate-200"
        />
      ) : null}
      {/* Narrower cap on phones so a long Google display name cannot push the
          header into a horizontal overflow. */}
      <span className="max-w-[7rem] truncate sm:max-w-[10rem]">{name}</span>
    </span>
  )
}

export default function OwnerHeader() {
  const { user, connection, logout } = useAuth()

  return (
    <header className="border-b border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-800">
      {/* px-4 on phones, the original px-6 from `sm` up — the shell adds no
          horizontal padding of its own, so this is the only gutter here. */}
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-end gap-3 px-4 py-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-2 sm:gap-4">
          <ConnectionPill status={connection?.status} />
          {user ? <UserChip name={user.name} picture={user.picture} /> : null}
          {/* Below `lg` the drawer already carries a "יציאה" button, so this
              duplicate is hidden rather than eating scarce header width. */}
          <Button variant="secondary" className="hidden lg:inline-flex" onClick={() => void logout()}>
            יציאה
          </Button>
        </div>
      </div>
    </header>
  )
}
