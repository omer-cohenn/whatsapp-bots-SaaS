// Authenticated dashboard shell: the deep-green right-side sidebar (from the
// approved prototype) + the existing OwnerHeader above the page content.
//
// Layout (RTL): the <nav> sidebar is the first flex child, so it sits on the
// RIGHT in a dir="rtl" page — exactly like the prototype. Enabled items use
// NavLink (real routing + aria-current); not-yet-built items render as disabled
// buttons with a "בקרוב" (coming soon) badge so owners can see what's planned.
//
// Responsive (M21): the sidebar is a fixed 160px column, which is 41% of a
// 390px phone. From `lg` (1024px) up it renders exactly as before; below `lg`
// it is hidden entirely and <MobileNav> takes over with a top bar + a drawer
// that slides in from the right. The nav items themselves live in
// components/nav/navItems.tsx so both shells stay in sync.
//
// Padding contract for pages — see docs/spec/responsive-shell.md:
// the shell adds NO horizontal padding to <main>. Pages own their gutters and
// should use `px-4 sm:px-6` so nothing double-pads or fights the shell.

import type { ReactNode } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useUnread } from '../dashboard/UnreadContext'
import OwnerHeader from './OwnerHeader'
import MobileNav from './nav/MobileNav'
import { NAV_ITEMS, NavBody } from './nav/navItems'

export default function DashboardLayout({ children }: { children: ReactNode }) {
  const { logout, isAdmin } = useAuth()
  const { unreadTotal } = useUnread()

  // The admin-only "ניהול" link is removed entirely for non-admins (route is
  // also guarded server-side and by <AdminGate>).
  const navItems = NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin)

  const handleLogout = () => void logout()

  return (
    // Warm cream page background — the landing hero's #f6f3eb.
    <div className="flex min-h-screen bg-[#f6f3eb] dark:bg-slate-900">
      <a href="#main" className="skip-link">
        דלגו לתוכן
      </a>

      {/* Right-side deep-green sidebar (first flex child → right in RTL).
          Desktop only: below `lg` the drawer in <MobileNav> replaces it. */}
      <nav
        aria-label="ניווט ראשי"
        className="hidden w-40 flex-shrink-0 flex-col gap-1 bg-leaf-dark p-3 lg:flex"
      >
        <NavBody items={navItems} unreadTotal={unreadTotal} onLogout={handleLogout} />
      </nav>

      {/* Content column: the mobile top bar + the shared header + the routed page. */}
      <div className="flex min-w-0 flex-1 flex-col dark:bg-slate-900">
        <MobileNav items={navItems} unreadTotal={unreadTotal} onLogout={handleLogout} />
        <OwnerHeader />
        <main id="main" className="min-w-0 flex-1">
          {children}
        </main>
      </div>
    </div>
  )
}
