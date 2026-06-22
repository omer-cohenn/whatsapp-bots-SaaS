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

import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import DashboardLayout from '../components/DashboardLayout'
import Button from '../components/ui/Button'
import Card from '../components/ui/Card'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'
import Icon from '../components/ui/Icon'
import { getQr, getStatus, link } from '../lib/whatsappClient'
import type { WhatsAppQr, WhatsAppStatus } from '../lib/whatsappClient'
import { toFriendlyError } from '../lib/friendlyError'

const POLL_MS = 4000

// Present the linked own-number digits a little more kindly (grouped, with a
// leading +). Falls back to the raw value if it isn't a plain digit string.
function formatPhone(phone: string): string {
  const digits = phone.replace(/\D/g, '')
  if (!digits) return phone
  return `+${digits}`
}

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
      </div>
    </DashboardLayout>
  )
}

// --- connected ---------------------------------------------------------------

function ConnectedView({ phone }: { phone: string | null }) {
  return (
    <div className="flex flex-col items-center gap-3 py-6 text-center">
      <span
        aria-hidden="true"
        className="flex h-14 w-14 items-center justify-center rounded-full bg-leaf-soft text-leaf-ink"
      >
        <Icon name="brand-whatsapp" size={30} />
      </span>
      <p className="flex items-center gap-2 text-lg font-semibold text-leaf-ink">
        <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full bg-leaf" />
        מחובר
      </p>
      {phone ? (
        <p className="text-sm text-slate-600">
          המספר המחובר:{' '}
          <bdi className="font-medium text-slate-900">{formatPhone(phone)}</bdi>
        </p>
      ) : null}
      <p className="max-w-sm text-sm text-slate-500">
        הוואטסאפ של העסק מחובר. הבוט יקבל הודעות ויענה אוטומטית — בתנאי שהבוט
        מפורסם.
      </p>
    </div>
  )
}

// --- not connected (QR + link) ----------------------------------------------

function ConnectView({
  qr,
  canLink,
  linking,
  onLink,
}: {
  qr: WhatsAppQr | null
  canLink: boolean
  linking: boolean
  onLink: () => void
}) {
  return (
    <div className="flex flex-col items-center gap-5 py-2 text-center">
      <p className="flex items-center gap-2 text-base font-semibold text-slate-800">
        <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full bg-slate-300" />
        לא מחובר
      </p>

      {qr?.qr_data_url ? (
        <img
          src={qr.qr_data_url}
          alt="קוד QR לחיבור הוואטסאפ. סרקו אותו מהטלפון כדי לחבר את החשבון."
          className="h-56 w-56 rounded-xl border border-slate-200 bg-white p-2"
          width={224}
          height={224}
        />
      ) : (
        <div
          className="flex h-56 w-56 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 text-sm text-slate-500"
          role="status"
        >
          הקוד נטען… אם הוא לא מופיע, לחצו על "רענון" למעלה.
        </div>
      )}

      {/* Numbered scan instructions. */}
      <ol className="max-w-sm space-y-1.5 text-start text-sm text-slate-600">
        <li>1. פתחו את WhatsApp בטלפון.</li>
        <li>2. היכנסו להגדרות ← מכשירים מקושרים.</li>
        <li>3. הקישו "קישור מכשיר" וסרקו את הקוד שמופיע כאן.</li>
      </ol>

      <Button onClick={onLink} disabled={!canLink || linking}>
        {linking ? (
          <>
            <span
              aria-hidden="true"
              className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
            />
            מחבר…
          </>
        ) : (
          <>
            <Icon name="check" size={16} />
            חבר
          </>
        )}
      </Button>
      {!canLink ? (
        <p className="text-xs text-slate-400">
          סרקו את הקוד תחילה — כפתור החיבור ייפתח אוטומטית ברגע שהחשבון יזוהה.
        </p>
      ) : null}
    </div>
  )
}

// --- test-mode reminder ------------------------------------------------------

function TestModeCard() {
  return (
    <Card className="border-leaf-soft bg-leaf-soft/40">
      <div className="flex items-start gap-3">
        <span
          aria-hidden="true"
          className="mt-0.5 flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-white text-leaf-ink"
        >
          <Icon name="sparkles" size={20} />
        </span>
        <div className="flex flex-col gap-2">
          <h2 className="text-base font-semibold text-leaf-ink">איך בודקים?</h2>
          <p className="text-sm text-slate-700">
            כדי לבדוק: פרסמו את הבוט (בבונה הבוט), ואז שלחו לעצמכם הודעה בוואטסאפ —
            הבוט יענה.
          </p>
          <Link
            to="/bot-builder"
            className="inline-flex w-fit items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition hover:bg-brand-dark"
          >
            <Icon name="robot" size={16} />
            לבונה הבוט ולפרסום
          </Link>
        </div>
      </div>
    </Card>
  )
}
