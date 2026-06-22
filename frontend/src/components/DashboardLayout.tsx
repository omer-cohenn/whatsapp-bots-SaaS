// Authenticated dashboard shell: the deep-green right-side sidebar (from the
// approved prototype) + the existing OwnerHeader above the page content.
//
// Layout (RTL): the <nav> sidebar is the first flex child, so it sits on the
// RIGHT in a dir="rtl" page — exactly like the prototype. Enabled items use
// NavLink (real routing + aria-current); not-yet-built items render as disabled
// buttons with a "בקרוב" (coming soon) badge so owners can see what's planned.

import type { ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import OwnerHeader from './OwnerHeader'
import Icon, { type IconName } from './ui/Icon'
import Badge from './ui/Badge'

type NavSpec = {
  to: string
  label: string
  icon: IconName
  /** When false the item is shown but disabled with a "בקרוב" badge. */
  enabled: boolean
}

// Order + labels mirror the prototype sidebar.
const NAV_ITEMS: NavSpec[] = [
  { to: '/', label: 'בית', icon: 'home', enabled: true },
  { to: '/bot-builder', label: 'בונה הבוט', icon: 'robot', enabled: true },
  { to: '/try-me', label: 'נסה אותי', icon: 'player-play', enabled: true },
  { to: '/leads', label: 'לידים', icon: 'users', enabled: true },
  { to: '/conversations', label: 'שיחות', icon: 'message-circle', enabled: true },
  { to: '/appointments', label: 'ניהול פגישות', icon: 'calendar-event', enabled: true },
  { to: '/whatsapp', label: 'וואטסאפ', icon: 'brand-whatsapp', enabled: true },
  { to: '/settings', label: 'הגדרות', icon: 'settings', enabled: false },
]

function NavItem({ item }: { item: NavSpec }) {
  if (!item.enabled) {
    return (
      <span
        // Disabled-but-visible: communicate state to assistive tech without a link.
        aria-disabled="true"
        className="flex items-center gap-3 rounded-xl px-3 py-2 text-sm text-leaf-light/60"
      >
        <Icon name={item.icon} size={19} />
        <span className="flex-1">{item.label}</span>
        <Badge tone="leaf">בקרוב</Badge>
      </span>
    )
  }

  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) =>
        `flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition ${
          isActive
            ? 'bg-leaf font-medium text-white'
            : 'text-leaf-light hover:bg-white/10 hover:text-white'
        }`
      }
    >
      <Icon name={item.icon} size={19} />
      <span>{item.label}</span>
    </NavLink>
  )
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const { logout } = useAuth()

  return (
    <div className="flex min-h-screen bg-[#ece9e1]">
      <a href="#main" className="skip-link">
        דלגו לתוכן
      </a>

      {/* Right-side deep-green sidebar (first flex child → right in RTL). */}
      <nav
        aria-label="ניווט ראשי"
        className="flex w-40 flex-shrink-0 flex-col gap-1 bg-leaf-dark p-3"
      >
        <div className="flex items-center gap-2 px-1 pb-4 pt-1">
          <span
            aria-hidden="true"
            className="flex h-7 w-7 items-center justify-center rounded-lg bg-leaf text-white"
          >
            <Icon name="message-circle" size={18} />
          </span>
          <span className="text-base font-medium text-white">Bizz_up</span>
        </div>

        {NAV_ITEMS.map((item) => (
          <NavItem key={item.to} item={item} />
        ))}

        <button
          type="button"
          onClick={() => void logout()}
          className="mt-auto flex items-center gap-3 rounded-xl px-3 py-2 text-sm text-leaf-light transition hover:bg-white/10 hover:text-white"
        >
          <Icon name="logout" size={19} />
          <span>יציאה</span>
        </button>
      </nav>

      {/* Content column: the shared header + the routed page. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <OwnerHeader />
        <main id="main" className="min-w-0 flex-1">
          {children}
        </main>
      </div>
    </div>
  )
}
