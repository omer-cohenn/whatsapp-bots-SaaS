// Wraps protected routes. While /api/me is in flight we show an accessible
// spinner; once resolved, an unauthenticated user is redirected to /login
// (preserving where they were trying to go).

import { Navigate, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '../auth/AuthContext'
import Spinner from './ui/Spinner'

export default function AuthGate({ children }: { children: ReactNode }) {
  const { loading, authed } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <main id="main" className="flex min-h-screen items-center justify-center p-6">
        <Spinner label="טוען את החשבון שלך…" />
      </main>
    )
  }

  if (!authed) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <>{children}</>
}
