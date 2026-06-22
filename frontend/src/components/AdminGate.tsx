// Wraps the platform-operator (super-admin) routes. Must be used INSIDE an
// <AuthGate> so the session is already resolved: by the time we render, the
// user is authenticated. Here we only check the admin flag — a logged-in
// non-admin is redirected to "/" (they don't see the nav link either, but the
// route is guarded too). The server is the real authority: every /api/admin/*
// call re-checks admin identity and returns 403 otherwise.

import { Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '../auth/AuthContext'
import Spinner from './ui/Spinner'

export default function AdminGate({ children }: { children: ReactNode }) {
  const { loading, authed, isAdmin } = useAuth()

  if (loading) {
    return (
      <main id="main" className="flex min-h-screen items-center justify-center p-6">
        <Spinner label="טוען…" />
      </main>
    )
  }

  // AuthGate already handled the unauthenticated case, but be defensive.
  if (!authed) return <Navigate to="/login" replace />

  // A logged-in non-admin has no business here → bounce home.
  if (!isAdmin) return <Navigate to="/" replace />

  return <>{children}</>
}
