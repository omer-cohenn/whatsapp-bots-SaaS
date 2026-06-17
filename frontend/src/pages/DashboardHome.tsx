// Minimal authenticated landing page. The full dashboard is a later milestone;
// for now we greet the owner and reuse the StackHealth panel.

import { useAuth } from '../auth/AuthContext'
import OwnerHeader from '../components/OwnerHeader'
import SiteFooter from '../components/SiteFooter'
import StackHealth from '../components/StackHealth'

export default function DashboardHome() {
  const { user, business } = useAuth()

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="skip-link">
        דלגו לתוכן
      </a>

      <OwnerHeader />

      <main
        id="main"
        className="mx-auto flex w-full max-w-5xl flex-1 flex-col items-center gap-10 px-6 py-12"
      >
        <section className="text-center">
          <h1 className="text-3xl font-bold text-slate-900 sm:text-4xl">
            שלום{user?.name ? `, ${user.name}` : ''} 👋
          </h1>
          {business?.name ? (
            <p className="mt-3 text-lg text-slate-600">
              ניהול בוט הוואטסאפ של <span className="font-medium">{business.name}</span>
            </p>
          ) : null}
        </section>

        <StackHealth />
      </main>

      <SiteFooter />
    </div>
  )
}
