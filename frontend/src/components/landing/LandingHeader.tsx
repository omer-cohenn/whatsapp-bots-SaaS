// Sticky public marketing header. Logo on one side; anchor nav that smooth-
// scrolls to the in-page section ids; auth links (ghost "התחברות" + primary
// "התחילו חינם") on the other. On mobile the anchor nav collapses behind a
// keyboard-accessible toggle; the two auth buttons stay visible.

import { useState } from 'react'
import Icon from '../ui/Icon'

// In-page anchors. The hrefs match the section ids rendered by LandingPage.
const NAV_LINKS = [
  { href: '#how-it-works', label: 'איך זה עובד' },
  { href: '#features', label: 'יכולות' },
  { href: '#pricing', label: 'מסלולים' },
  { href: '#faq', label: 'שאלות' },
]

export default function LandingHeader() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur">
      <nav
        aria-label="ניווט ראשי"
        className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3"
      >
        {/* Logo */}
        <a
          href="#main"
          className="rounded text-xl font-bold text-leaf hover:text-leaf-dark"
        >
          Bizz_up
        </a>

        {/* Desktop anchor nav */}
        <ul className="hidden items-center gap-6 md:flex">
          {NAV_LINKS.map((link) => (
            <li key={link.href}>
              <a
                href={link.href}
                className="rounded text-sm font-medium text-slate-600 transition-colors hover:text-leaf-ink"
              >
                {link.label}
              </a>
            </li>
          ))}
        </ul>

        {/* Auth actions (always visible) + mobile menu toggle */}
        <div className="flex items-center gap-2">
          <a
            href="/auth/google"
            className="hidden rounded-lg px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-100 sm:inline-flex"
          >
            התחברות
          </a>
          <a
            href="/auth/google"
            className="inline-flex items-center justify-center rounded-lg bg-leaf px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-leaf-dark"
          >
            התחילו חינם
          </a>

          {/* Mobile nav toggle */}
          <button
            type="button"
            aria-expanded={menuOpen}
            aria-controls="mobile-nav"
            aria-label={menuOpen ? 'סגירת התפריט' : 'פתיחת התפריט'}
            onClick={() => setMenuOpen((v) => !v)}
            className="inline-flex items-center justify-center rounded-lg p-2 text-slate-700 transition-colors hover:bg-slate-100 md:hidden"
          >
            <Icon name={menuOpen ? 'x' : 'menu'} size={22} />
          </button>
        </div>
      </nav>

      {/* Mobile collapsible anchor nav */}
      {menuOpen ? (
        <div id="mobile-nav" className="border-t border-slate-200 bg-white md:hidden">
          <ul className="mx-auto flex max-w-6xl flex-col px-6 py-2">
            {NAV_LINKS.map((link) => (
              <li key={link.href}>
                <a
                  href={link.href}
                  onClick={() => setMenuOpen(false)}
                  className="block rounded px-1 py-3 text-sm font-medium text-slate-700 transition-colors hover:text-leaf-ink"
                >
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </header>
  )
}
