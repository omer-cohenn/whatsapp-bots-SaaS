// תצוגת "לא מחובר" בעמוד וואטסאפ: קוד QR, הוראות סריקה וכפתור "חבר".

import Button from '../ui/Button'
import Icon from '../ui/Icon'
import type { WhatsAppQr } from '../../lib/whatsappClient'

export default function ConnectView({
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
      ) : qr?.status === 'logged_out' ? (
        <div
          className="flex h-56 w-56 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 text-sm text-slate-500"
          role="status"
        >
          <span
            aria-hidden="true"
            className="h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-leaf"
          />
          <p className="font-medium text-slate-600">מרעננים את החיבור…</p>
          <p className="text-center text-xs text-slate-500">
            קוד QR חדש יופיע כאן בעוד רגע.
          </p>
        </div>
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
