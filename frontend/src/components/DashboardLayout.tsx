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
import { useUnread } from '../dashboard/UnreadContext'
import OwnerHeader from './OwnerHeader'
import Icon, { type IconName } from './ui/Icon'
import Badge from './ui/Badge'

type NavSpec = {
  to: string
  label: string
  icon: IconName
  /** When false the item is shown but disabled with a "בקרוב" badge. */
  enabled: boolean
  /** When true the item renders only for platform admins (M12). */
  adminOnly?: boolean
  /** Optional distinct accent so a special item stands out (M12 admin = blue). */
  accent?: 'blue'
}

// Order + labels mirror the prototype sidebar. The admin-only "ניהול" entry is
// filtered out for non-admins below (it never reaches the DOM for them).
const NAV_ITEMS: NavSpec[] = [
  { to: '/', label: 'בית', icon: 'home', enabled: true },
  { to: '/bot-builder', label: 'בונה הבוט', icon: 'robot', enabled: true },
  { to: '/try-me', label: 'נסה אותי', icon: 'player-play', enabled: true },
  { to: '/leads', label: 'לידים', icon: 'users', enabled: true },
  { to: '/conversations', label: 'שיחות', icon: 'message-circle', enabled: true },
  { to: '/appointments', label: 'ניהול פגישות', icon: 'calendar-event', enabled: true },
  { to: '/whatsapp', label: 'וואטסאפ', icon: 'brand-whatsapp', enabled: true },
  { to: '/admin', label: 'ניהול', icon: 'shield', enabled: true, adminOnly: true, accent: 'blue' },
  { to: '/admin/crm', label: 'צינור מכירות', icon: 'layout-columns', enabled: true, adminOnly: true, accent: 'blue' },
  { to: '/admin/billing', label: 'שימוש וחיוב', icon: 'chart-bar', enabled: true, adminOnly: true, accent: 'blue' },
  { to: '/settings', label: 'הגדרות', icon: 'settings', enabled: false },
]

// WhatsApp-style unread pill: a white count on bright WhatsApp-green
// (brand.light token), sized like WhatsApp's bubble. Hidden when zero; caps at
// "99+". Carries its own accessible label and is RTL-safe (ms-auto pushes it to
// the inline-end / far edge in the dir="rtl" sidebar, like WhatsApp).
function UnreadBadge({ count }: { count: number }) {
  if (count <= 0) return null
  const display = count > 99 ? '99+' : String(count)
  return (
    <span
      role="status"
      aria-label={`${count} הודעות שלא נקראו`}
      className="ms-auto inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-brand-light px-1.5 text-[11px] font-bold leading-none text-white"
    >
      <span aria-hidden="true">{display}</span>
    </span>
  )
}

function NavItem({ item, unread = 0 }: { item: NavSpec; unread?: number }) {
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

  // The admin item gets a distinct, always-on blue treatment (a blue-tinted pill
  // with a blue outline) so it's instantly recognizable among the green tabs.
  const isBlue = item.accent === 'blue'

  return (
    <NavLink
      to={item.to}
      // `/` and the admin home `/admin` must match exactly, otherwise the admin
      // sub-routes (/admin/crm, /admin/billing) would also light up the parent.
      end={item.to === '/' || item.to === '/admin'}
      className={({ isActive }) => {
        const base = 'flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition'
        if (isBlue) {
          return `${base} ${
            isActive
              ? 'bg-[#378ADD] font-medium text-white'
              : 'bg-[#378ADD]/20 text-[#bfe0ff] ring-1 ring-inset ring-[#378ADD]/50 hover:bg-[#378ADD]/35 hover:text-white'
          }`
        }
        return `${base} ${
          isActive
            ? 'bg-leaf font-medium text-white'
            : 'text-leaf-light hover:bg-white/10 hover:text-white'
        }`
      }}
    >
      <Icon name={item.icon} size={19} />
      <span>{item.label}</span>
      <UnreadBadge count={unread} />
    </NavLink>
  )
}

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const { logout, isAdmin } = useAuth()
  const { unreadTotal } = useUnread()

  // The admin-only "ניהול" link is removed entirely for non-admins (route is
  // also guarded server-side and by <AdminGate>).
  const navItems = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin)

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
        <div className="pb-4 pt-1">
          {/* white wordmark variant — the sidebar is deep-green (dark) */}
          <img src="/logo-on-dark.png" alt="בוטיק" className="h-14 w-auto" />
        </div>

        {navItems.map((item) => (
          <NavItem
            key={item.to}
            item={item}
            // Only the conversations tab carries the unread count.
            unread={item.to === '/conversations' ? unreadTotal : 0}
          />
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
