// תצוגת "לא מחובר" בעמוד וואטסאפ (M6b): כפתור "התחבר" שיוצר session, ואז QR + הוראות סריקה.

import Button from '../ui/Button'
import Icon from '../ui/Icon'
import type { WhatsAppQr } from '../../lib/whatsappClient'

export default function ConnectView({
  qr,
  linked,
  starting,
  onStart,
}: {
  qr: WhatsAppQr | null
  /** True once a connection row exists (a session is being brought up). */
  linked: boolean
  /** True while the "connect" request is in flight. */
  starting: boolean
  /** Create/ensure this business's WhatsApp session (→ produces a QR). */
  onStart: () => void
}) {
  const hasQr = Boolean(qr?.qr_data_url)

  return (
    <div className="flex flex-col items-center gap-5 py-2 text-center">
      <p className="flex items-center gap-2 text-base font-semibold text-slate-800 dark:text-slate-100">
        <span aria-hidden="true" className="h-2.5 w-2.5 rounded-full bg-slate-300 dark:bg-slate-600" />
        לא מחובר
      </p>

      {/* QR SIZE — the one thing on this page that must not be "made to fit".
          A QR that shrinks below scanning size is worthless, so the floor here
          is 224px (h-56) of drawn code and it is NEVER reduced on small screens.
          That fits: a 390px phone leaves ~358px after the page gutter and ~318px
          inside the card, so 224px clears it with room to spare — no shrinking
          and no horizontal scroll are needed. On roomier screens it grows a
          little (up to 256px) since a bigger code is easier to scan, which is
          why this is w-full with a max, rather than a fixed square. */}
      {hasQr ? (
        <img
          src={qr!.qr_data_url as string}
          alt="קוד QR לחיבור הוואטסאפ. סרקו אותו מהטלפון כדי לחבר את החשבון."
          className="aspect-square h-auto w-full min-w-[224px] max-w-[256px] rounded-xl border border-slate-200 bg-white p-2"
          width={224}
          height={224}
        />
      ) : linked ? (
        // A session is coming up (or re-linking after a logout) — QR is imminent.
        <div
          // Same footprint as the real QR above, so nothing jumps when it loads.
          className="flex aspect-square w-full min-w-[224px] max-w-[256px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 text-sm text-slate-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400"
          role="status"
        >
          <span
            aria-hidden="true"
            className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-leaf dark:border-slate-600"
          />
          <p className="font-medium text-slate-600 dark:text-slate-300">מכינים את החיבור…</p>
          <p className="text-center text-xs text-slate-500 dark:text-slate-400">
            קוד QR יופיע כאן בעוד רגע.
          </p>
        </div>
      ) : (
        // Nothing started yet — invite the owner to begin (creates the session).
        <div
          // Same footprint as the real QR above, so nothing jumps when it loads.
          className="flex aspect-square w-full min-w-[224px] max-w-[256px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 text-sm text-slate-500 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-400"
          role="status"
        >
          <Icon name="brand-whatsapp" size={32} className="text-leaf" />
          <p className="text-center text-xs">לחצו "התחבר" כדי ליצור קוד QR לסריקה.</p>
        </div>
      )}

      {/* Numbered scan instructions (relevant once a QR is on screen). */}
      <ol className="max-w-sm space-y-1.5 text-start text-sm text-slate-600 dark:text-slate-300">
        <li>1. פתחו את WhatsApp בטלפון.</li>
        <li>2. היכנסו להגדרות ← מכשירים מקושרים.</li>
        <li>3. הקישו "קישור מכשיר" וסרקו את הקוד שמופיע כאן.</li>
      </ol>

      {/* The "connect" button only makes sense before a session exists. Once a
          row exists (linked) the QR flow takes over and the page polls to
          'connected' on its own. */}
      {!linked ? (
        <Button onClick={onStart} disabled={starting} className="min-h-[44px] sm:min-h-0">
          {starting ? (
            <>
              <span
                aria-hidden="true"
                className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
              />
              מתחבר…
            </>
          ) : (
            <>
              <Icon name="brand-whatsapp" size={16} />
              התחבר
            </>
          )}
        </Button>
      ) : null}
    </div>
  )
}
