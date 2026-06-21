// Minimal shell for the PUBLIC (no-auth) booking pages: a centered card on a
// warm background, a skip-link + <main> landmark, and the shared site footer.
// No owner sidebar/header here — the customer is not logged in.

import type { ReactNode } from 'react'
import SiteFooter from '../SiteFooter'
import Icon from '../ui/Icon'

type Props = {
  /** Business name for the heading (falls back to a generic title). */
  businessName?: string
  children: ReactNode
}

export default function PublicBookingLayout({ businessName, children }: Props) {
  return (
    <div className="flex min-h-screen flex-col bg-[#ece9e1]">
      <a href="#main" className="skip-link">
        דלגו לתוכן
      </a>

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

      <main id="main" className="mx-auto w-full max-w-xl flex-1 px-4 py-6 sm:px-6">
        {children}
      </main>

      <SiteFooter />
    </div>
  )
}
