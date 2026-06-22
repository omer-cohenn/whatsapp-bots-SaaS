// Root "/" route. While auth is resolving we show a centered spinner; once
// resolved, logged-in owners get the dashboard (which renders its own
// DashboardLayout) and everyone else sees the public marketing landing page.

import { useAuth } from '../auth/AuthContext'
import DashboardHome from './DashboardHome'
import LandingPage from './LandingPage'
import Spinner from '../components/ui/Spinner'

export default function Home() {
  const { loading, authed } = useAuth()

  if (loading) {
    return (
      <main id="main" className="flex min-h-screen items-center justify-center p-6">
        <Spinner label="טוען…" />
      </main>
    )
  }

  // DashboardHome already wraps itself in <DashboardLayout> — do not double-wrap.
  return authed ? <DashboardHome /> : <LandingPage />
}
