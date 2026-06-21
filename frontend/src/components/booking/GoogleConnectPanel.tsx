// Google Calendar connect panel for the owner settings. Reads /api/google/status
// on mount, shows connect (redirect the browser to the consent URL) or disconnect
// accordingly, and reacts to the ?google=connected|error flag set when Google
// redirects back to /settings/calendar. The refresh/access token is NEVER seen
// by the client — we only learn `connected` + `email`.

import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ApiError } from '../../lib/apiClient'
import { disconnectGoogle, getGoogleConnectUrl, getGoogleStatus } from '../../lib/bookingClient'
import { toFriendlyError } from '../../lib/friendlyError'
import type { GoogleStatus } from '../../dashboard/appointmentTypes'
import Spinner from '../ui/Spinner'
import Alert from '../ui/Alert'
import Icon from '../ui/Icon'

export default function GoogleConnectPanel() {
  const [status, setStatus] = useState<GoogleStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // One-off toast from the OAuth return (?google=connected|error).
  const [returnFlag, setReturnFlag] = useState<'connected' | 'error' | null>(null)

  const [params, setParams] = useSearchParams()

  const load = useCallback(() => {
    let cancelled = false
    setLoading(true)
    getGoogleStatus()
      .then((s) => {
        if (!cancelled) setStatus(s)
      })
      .catch((err) => {
        if (!cancelled) setError(toFriendlyError(err, 'טעינת מצב Google נכשלה.'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => load(), [load])

  // Read the OAuth return flag once, then strip it from the URL so a refresh
  // doesn't re-toast.
  useEffect(() => {
    const flag = params.get('google')
    if (flag === 'connected' || flag === 'error') {
      setReturnFlag(flag)
      params.delete('google')
      setParams(params, { replace: true })
    }
  }, [params, setParams])

  async function connect() {
    setBusy(true)
    setError(null)
    try {
      const { auth_url } = await getGoogleConnectUrl()
      // Real navigation so the browser follows Google's OAuth flow.
      window.location.assign(auth_url)
    } catch (err) {
      // 503 = the redirect URI isn't configured server-side.
      if (err instanceof ApiError && err.status === 503) {
        setError('חיבור ליומן Google אינו זמין כרגע. פנו לתמיכה.')
      } else {
        setError(toFriendlyError(err, 'פתיחת החיבור ל-Google נכשלה. נסו שוב.'))
      }
      setBusy(false)
    }
  }

  async function disconnect() {
    if (!window.confirm('לנתק את חיבור יומן Google? פגישות חדשות לא יסונכרנו.')) return
    setBusy(true)
    setError(null)
    try {
      await disconnectGoogle()
      load()
    } catch (err) {
      setError(toFriendlyError(err, 'הניתוק נכשל. נסו שוב.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {returnFlag === 'connected' ? (
        <Alert tone="info">יומן Google חובר בהצלחה.</Alert>
      ) : null}
      {returnFlag === 'error' ? (
        <Alert tone="warning">חיבור יומן Google נכשל. נסו שוב.</Alert>
      ) : null}
      {error ? <Alert tone="error">{error}</Alert> : null}

      {loading ? (
        <Spinner label="בודק חיבור ל-Google…" className="py-4" />
      ) : status?.connected ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-leaf/30 bg-leaf-soft p-4">
          <div className="flex items-center gap-2 text-sm text-leaf-ink">
            <Icon name="brand-google" size={20} />
            <span>
              מחובר{status.email ? ` (${status.email})` : ''}
            </span>
          </div>
          <button
            type="button"
            onClick={() => void disconnect()}
            disabled={busy}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50 disabled:opacity-60"
          >
            {busy ? 'מנתק…' : 'נתק'}
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          <button
            type="button"
            onClick={() => void connect()}
            disabled={busy}
            className="inline-flex w-fit items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-800 transition hover:border-slate-400 hover:bg-slate-50 disabled:opacity-60"
          >
            <Icon name="brand-google" size={20} />
            {busy ? 'פותח…' : 'חבר Google Calendar'}
          </button>
          <p className="text-xs text-slate-500">
            כשמחובר, כל פגישה חדשה תיווצר ביומן Google שלכם, והלקוח יקבל הזמנה למייל.
          </p>
        </div>
      )}
    </div>
  )
}
