// Public login screen. The "המשך עם Google" button is a real link to
// /auth/google (a server redirect to Google OAuth) — NOT a fetch — because the
// browser must follow the 302 across origins. If the user is already logged in,
// we send them to the dashboard.

import { useEffect } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import Card from '../components/ui/Card'
import Alert from '../components/ui/Alert'
import Spinner from '../components/ui/Spinner'
import SiteFooter from '../components/SiteFooter'

export default function LoginPage() {
  const { authed, loading, error } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!loading && authed) navigate('/', { replace: true })
  }, [authed, loading, navigate])

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="skip-link">
        דלגו לתוכן
      </a>

      <main
        id="main"
        className="flex flex-1 flex-col items-center justify-center px-6 py-12"
      >
        <Card className="w-full max-w-sm text-center">
          <img src="/logo.png" alt="בוטיק" className="mx-auto mb-4 h-24 w-auto" />
          <h1 className="sr-only">בוטיק</h1>
          <p className="mb-8 text-sm leading-relaxed text-slate-600">
            התחברו כדי לנהל את בוט הוואטסאפ של העסק שלכם.
          </p>

          {loading ? (
            <Spinner label="בודק התחברות…" />
          ) : (
            <>
              {error ? (
                <Alert tone="error" className="mb-4 text-start">
                  {error}
                </Alert>
              ) : null}

              {/* Real navigation (not fetch) so the browser follows the 302 to Google. */}
              <a
                href="/auth/google"
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 transition hover:border-slate-400 hover:bg-slate-50"
              >
                <span aria-hidden="true" className="text-base">
                  🔑
                </span>
                המשך עם Google
              </a>
            </>
          )}

          <p className="mt-6 text-xs leading-relaxed text-slate-400">
            הנתונים שלכם מאובטחים ומבודלים לפי משתמש.
          </p>
        </Card>

        <p className="mt-6 text-center text-xs text-slate-500">
          בהמשך אתם מאשרים את{' '}
          <Link to="/terms" className="text-brand hover:underline">
            תנאי השימוש
          </Link>{' '}
          ואת{' '}
          <Link to="/privacy" className="text-brand hover:underline">
            מדיניות הפרטיות
          </Link>
          .
        </p>
      </main>

      <SiteFooter />
    </div>
  )
}
