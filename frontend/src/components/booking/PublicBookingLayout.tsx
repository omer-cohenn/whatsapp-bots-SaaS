// Minimal shell for the PUBLIC (no-auth) booking pages: a skip-link + <main>
// landmark and the shared site footer. No owner sidebar/header here — the
// customer is not logged in.
//
// Two variants:
//   * "card" (default) — the original narrow, warm-background card. Still what
//     /book/:slug/manage/:token uses; unchanged on purpose.
//   * "page" (M20) — the designed business page: no top bar (the hero carries
//     the name and logo), a wider canvas for the photo mosaic, and colours taken
//     from the palette CSS variables passed in via `themeVars`.

import type { CSSProperties, ReactNode } from 'react'
import SiteFooter from '../SiteFooter'
import Icon from '../ui/Icon'

type Props = {
  /** Business name for the heading (falls back to a generic title). */
  businessName?: string
  /** "page" drops the top bar and widens the canvas — see the note above. */
  variant?: 'card' | 'page'
  /** Palette custom properties from `public/pageTheme.ts` (variant "page"). */
  themeVars?: CSSProperties
  children: ReactNode
}

export default function PublicBookingLayout({
  businessName,
  variant = 'card',
  themeVars,
  children,
}: Props) {
  const isPage = variant === 'page'

  return (
    <div
      className={`flex min-h-screen flex-col ${
        isPage ? 'bg-[color:var(--bp-bg)]' : 'bg-[#ece9e1]'
      }`}
      style={isPage ? themeVars : undefined}
    >
      <a href="#main" className="skip-link">
        דלגו לתוכן
      </a>

      {isPage ? null : (
        <header className="bg-white">
          <div className="mx-auto flex max-w-xl items-center gap-2 px-6 py-4">
            <span
              aria-hidden="true"
              className="flex h-8 w-8 items-center justify-center rounded-lg bg-leaf text-white"
            >
              <Icon name="calendar-event" size={18} />
            </span>
            <span className="text-base font-semibold text-slate-900">
              {businessName || 'קביעת תור'}
            </span>
          </div>
        </header>
      )}

      <main
        id="main"
        className={`mx-auto w-full flex-1 px-4 sm:px-6 ${
          isPage ? 'max-w-5xl py-6 sm:py-8' : 'max-w-xl py-6'
        }`}
      >
        {children}
      </main>

      <SiteFooter />
    </div>
  )
}
