// עמוד חיבור וואטסאפ (M6a): מנהל מצב/QR/קישור ומרכיב את כרטיסי המקטעים.
// WhatsApp connect page (M6a, route /whatsapp). Renders inside <DashboardLayout>.
//
// What the owner does here:
//   1. If not connected → scan the QR (from GET /api/whatsapp/qr) with their
//      phone's WhatsApp to link the gateway to THEIR account.
//   2. Once the gateway reports `connected`, press "חבר" → POST /api/whatsapp/link
//      records the mapping (business_id ↔ gateway account + phone).
//   3. To test: publish the bot (in the bot builder) and message themselves —
//      the bot replies in that self-chat.
//
// The page polls GET /api/whatsapp/status every ~4s so QR-scan → connected and
// disconnects reflect without a manual refresh. The tenant (business_id) is
// always server-side from the session; we never send it from here, and the
// client never sees the gateway token or any WhatsApp credentials.
//
// The visual cards live in src/components/whatsapp/*; this page keeps the state
// and handlers and wires them together with the same behavior.

import { useCallback, useEffect, useRef, useState } from 'react'
import DashboardLayout from '../components/DashboardLayout'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'
import Icon from '../components/ui/Icon'
import ConnectedView from '../components/whatsapp/ConnectedView'
import ConnectView from '../components/whatsapp/ConnectView'
import TestModeCard from '../components/whatsapp/TestModeCard'
import TestNumbersCard from '../components/whatsapp/TestNumbersCard'
import { getQr, getStatus, link } from '../lib/whatsappClient'
import type { WhatsAppQr, WhatsAppStatus } from '../lib/whatsappClient'
import { toFriendlyError } from '../lib/friendlyError'

const POLL_MS = 4000

export default function WhatsAppPage() {
  const [status, setStatus] = useState<WhatsAppStatus | null>(null)
  const [qr, setQr] = useState<WhatsAppQr | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [linking, setLinking] = useState(false)
  const [linkError, setLinkError] = useState<string | null>(null)

  // Keep the latest status in a ref so the polling effect can read it without
  // re-subscribing (and re-creating the interval) on every state change.
  const statusRef = useRef<WhatsAppStatus | null>(null)
  statusRef.current = status

  // Fetch the QR only while there's something to scan (not connected). When
  // connected we clear it so no stale code lingers on screen.
  const refreshQr = useCallback(async (current: WhatsAppStatus | null) => {
    if (current?.connected) {
      setQr(null)
      return
    }
    try {
      setQr(await getQr())
    } catch {
      // A failed QR fetch isn't fatal — the status card still drives the page.
      setQr(null)
    }
  }, [])

  // One status read; on success also refresh the QR when appropriate.
  const refreshStatus = useCallback(
    async (opts: { silent?: boolean } = {}) => {
      if (!opts.silent) {
        setLoading(true)
        setError(null)
      }
      try {
        const next = await getStatus()
        setStatus(next)
        if (!opts.silent) setError(null)
        await refreshQr(next)
      } catch (err) {
        if (!opts.silent) {
          setError(toFriendlyError(err, 'טעינת מצב החיבור נכשלה. נסו שוב.'))
        }
      } finally {
        if (!opts.silent) setLoading(false)
      }
    },
    [refreshQr],
  )

  // Initial load.
  useEffect(() => {
    void refreshStatus()
  }, [refreshStatus])

  // Poll quietly while the page is open (no spinner flicker on each tick).
  useEffect(() => {
    const id = window.setInterval(() => {
      void refreshStatus({ silent: true })
    }, POLL_MS)
    return () => window.clearInterval(id)
  }, [refreshStatus])

  async function handleLink() {
    if (linking) return
    setLinking(true)
    setLinkError(null)
    try {
      const next = await link()
      setStatus(next)
      await refreshQr(next)
    } catch (err) {
      setLinkError(toFriendlyError(err, 'שמירת החיבור נכשלה. נסו שוב.'))
    } finally {
      setLinking(false)
    }
  }

  const connected = status?.connected ?? false
  // The gateway socket is up but we haven't recorded the mapping yet → let the
  // owner press "חבר" to persist it. Disabled until the socket is actually up.
  const canLink = connected && !status?.linked

  return (
    <DashboardLayout>
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900">
            <Icon name="brand-whatsapp" size={22} className="text-leaf" />
            וואטסאפ
          </h1>
          <Button
            variant="secondary"
            onClick={() => void refreshStatus()}
            disabled={loading}
          >
            <Icon name="refresh" size={16} />
            רענון
          </Button>
        </div>

        <p className="text-sm text-slate-600">
          חברו את חשבון הוואטסאפ של העסק כדי שהבוט יוכל לקבל הודעות ולענות
          ללקוחות שלכם.
        </p>

        {/* Connection status / QR card. */}
        <Card>
          <section aria-labelledby="wa-status-heading" aria-busy={loading}>
            <h2 id="wa-status-heading" className="sr-only">
              מצב חיבור הוואטסאפ
            </h2>

            <div aria-live="polite">
              {loading && !status ? (
                <Spinner label="טוען מצב חיבור…" className="py-10" />
              ) : error ? (
                <Alert tone="error">{error}</Alert>
              ) : connected ? (
                <ConnectedView phone={status?.phone ?? null} />
              ) : (
                <ConnectView
                  qr={qr}
                  canLink={canLink}
                  linking={linking}
                  onLink={() => void handleLink()}
                />
              )}
            </div>

            {linkError ? (
              <Alert tone="error" className="mt-4">
                {linkError}
              </Alert>
            ) : null}
          </section>
        </Card>

        {/* Test-mode reminder. */}
        <TestModeCard />

        {/* Allowlist of external numbers that get bot replies. */}
        <TestNumbersCard />
      </div>
    </DashboardLayout>
  )
}
