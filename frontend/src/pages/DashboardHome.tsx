// Authenticated landing page. Renders inside <DashboardLayout> (which provides
// the sidebar, header, skip-link and <main> landmark), so here we only supply
// the page content: a greeting + the StackHealth panel.

import { useAuth } from '../auth/AuthContext'
import DashboardLayout from '../components/DashboardLayout'
import StackHealth from '../components/StackHealth'

export default function DashboardHome() {
  const { user, business } = useAuth()

  return (
    <DashboardLayout>
      <div className="mx-auto flex w-full max-w-5xl flex-col items-center gap-10 px-6 py-12">
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
      </div>
    </DashboardLayout>
  )
}
