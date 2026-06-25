// Shared layout for the static legal pages (Terms / Privacy). Carries the draft
// banner that flags the copy as not-yet-lawyer-reviewed.

import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import Alert from '../components/ui/Alert'
import SiteFooter from '../components/SiteFooter'

type LegalPageProps = {
  title: string
  children: ReactNode
}

export default function LegalPage({ title, children }: LegalPageProps) {
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="skip-link">
        דלגו לתוכן
      </a>

      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-3xl items-center px-6 py-4">
          <Link to="/" aria-label="בוטיק — לדף הבית">
            <img src="/logo.png" alt="בוטיק" className="h-11 w-auto" />
          </Link>
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-3xl flex-1 px-6 py-10">
        <h1 className="mb-6 text-3xl font-bold text-slate-900">{title}</h1>

        <Alert tone="warning" className="mb-8">
          טיוטה — דורש בדיקת עו״ד לפני השקה.
        </Alert>

        <div className="space-y-4 text-slate-700 leading-relaxed">{children}</div>
      </main>

      <SiteFooter />
    </div>
  )
}
