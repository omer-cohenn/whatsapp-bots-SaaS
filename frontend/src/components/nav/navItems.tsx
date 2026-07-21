// The single source of truth for the owner-app navigation.
//
// Both shells render the SAME items with the SAME markup:
//   • the deep-green sidebar in <DashboardLayout> (lg and up)
//   • the slide-in drawer in <MobileNav>          (below lg)
// Keeping the list and the item markup here means a new tab is added once and
// shows up in both places — the mobile shell can never drift from the desktop
// one.

import { NavLink } from 'react-router-dom'
import Icon, { type IconName } from '../ui/Icon'
import Badge from '../ui/Badge'

export type NavSpec = {
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
// filtered out for non-admins by the caller (it never reaches the DOM for them).
export const NAV_ITEMS: NavSpec[] = [
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
  { to: '/settings', label: 'הגדרות', icon: 'settings', enabled: true },
]

/** The tab that carries the unread count — used by the shell and by the drawer. */
export const UNREAD_NAV_PATH = '/conversations'

// WhatsApp-style unread pill: a white count on bright WhatsApp-green
// (brand.light token), sized like WhatsApp's bubble. Hidden when zero; caps at
// "99+". Carries its own accessible label and is RTL-safe (ms-auto pushes it to
// the inline-end / far edge in the dir="rtl" sidebar, like WhatsApp).
export function UnreadBadge({ count }: { count: number }) {
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

export function NavItem({ item, unread = 0 }: { item: NavSpec; unread?: number }) {
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
        // py-2.5 on touch shells is still short of the 44px target on its own,
        // so the drawer bumps it further via its own wrapper padding.
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

/**
 * The nav body shared by the sidebar and the drawer: logo, the items, and the
 * logout button pinned to the bottom. The surrounding <nav>/<dialog> element and
 * its width live with the caller, because they differ between the two shells.
 */
export function NavBody({
  items,
  unreadTotal,
  onLogout,
}: {
  items: NavSpec[]
  unreadTotal: number
  onLogout: () => void
}) {
  return (
    <>
      <div className="pb-4 pt-1">
        {/* white wordmark variant — the nav surface is deep-green (dark) */}
        <img src="/botik-icon.png" alt="Botik" className="h-14 w-auto" />
      </div>

      {items.map((item) => (
        <NavItem
          key={item.to}
          item={item}
          // Only the conversations tab carries the unread count.
          unread={item.to === UNREAD_NAV_PATH ? unreadTotal : 0}
        />
      ))}

      <button
        type="button"
        onClick={onLogout}
        className="mt-auto flex items-center gap-3 rounded-xl px-3 py-2 text-sm text-leaf-light transition hover:bg-white/10 hover:text-white"
      >
        <Icon name="logout" size={19} />
        <span>יציאה</span>
      </button>
    </>
  )
}
