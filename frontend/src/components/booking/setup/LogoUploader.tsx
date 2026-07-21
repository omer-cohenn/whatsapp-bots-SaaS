// העלאת הלוגו (M20 revision) — קובץ מהמחשב, לא הדבקה של קישור.
//
// The logo used to be a text box asking for "קישור ללוגו … https://…", which
// quietly assumed the owner hosts an image somewhere on the internet. Almost
// none of them do. It is now uploaded exactly like a gallery photo, through
// POST /api/booking/logo, and the server writes the resulting `/media/...` path
// into `logo_url` itself.
//
// Two things worth knowing:
//   * the logo is NOT a gallery row, so it never shows up in the mosaic and it
//     does not count against the 40-image cap;
//   * the endpoint returns the WHOLE page object, so a successful upload
//     refreshes the wizard from the response with no extra GET.
//
// Removing the logo is a different call — the upload endpoint only ever sets a
// logo — so it goes through the normal partial PUT with an explicit null, which
// is the contract's way of clearing a column.
//
// Same shrink-before-upload path as the gallery: a 12MP phone photo becomes a
// sane file before it ever leaves the device.

import { useId, useState } from 'react'
import type { BusinessPage } from '../../../dashboard/businessPageTypes'
import {
  toUploadError,
  updateBusinessPage,
  uploadBusinessLogo,
} from '../../../lib/businessPageClient'
import { shrinkImageForUpload } from '../../../lib/imageResize'
import { toFriendlyError } from '../../../lib/friendlyError'
import Alert from '../../ui/Alert'
import Icon from '../../ui/Icon'

type Props = {
  page: BusinessPage
  /** Hand the server's fresh page back to the parent (upload returns all of it). */
  onUploaded: (page: BusinessPage) => void
  disabled?: boolean
}

/** Uploaded `/media/...` paths and legacy pasted http(s) URLs both render. */
function logoSrc(raw: string | null): string | null {
  if (!raw) return null
  const url = raw.trim()
  if (/^https?:\/\//i.test(url) || url.startsWith('/media/')) return url
  return null
}

export default function LogoUploader({ page, onUploaded, disabled }: Props) {
  const inputId = useId()
  const [busy, setBusy] = useState(false)
  const [fraction, setFraction] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const current = logoSrc(page.logo_url)
  const locked = busy || disabled

  async function upload(file: File) {
    setBusy(true)
    setFraction(0)
    setError(null)
    try {
      const prepared = await shrinkImageForUpload(file)
      const updated = await uploadBusinessLogo(prepared, { onProgress: setFraction })
      onUploaded(updated)
    } catch (err) {
      setError(toUploadError(err, 'העלאת הלוגו נכשלה. נסו שוב.'))
    } finally {
      setBusy(false)
    }
  }

  async function removeLogo() {
    if (!window.confirm('להסיר את הלוגו? במקומו תופיע האות הראשונה של שם העסק.')) return
    setBusy(true)
    setError(null)
    try {
      // Explicit null is what CLEARS the column (contract §5).
      const updated = await updateBusinessPage({ logo_url: null })
      onUploaded(updated)
    } catch (err) {
      setError(toFriendlyError(err, 'הסרת הלוגו נכשלה. נסו שוב.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <span className="text-sm font-medium text-slate-800">לוגו העסק (לא חובה)</span>

      {error ? <Alert tone="error">{error}</Alert> : null}

      <div className="flex items-center gap-4 rounded-xl border border-slate-200 p-3">
        {/* Round, exactly as it renders in the page hero. */}
        <span className="flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full border-2 border-slate-200 bg-slate-50">
          {current ? (
            <img src={current} alt="הלוגו הנוכחי של העסק" className="h-full w-full object-cover" />
          ) : (
            <span aria-hidden="true" className="text-2xl font-black text-slate-300">
              {page.business_name.trim().charAt(0) || '★'}
            </span>
          )}
        </span>

        <div className="flex min-w-0 flex-1 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <label
              htmlFor={inputId}
              className={[
                'inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50',
                locked ? 'pointer-events-none opacity-50' : 'cursor-pointer',
              ].join(' ')}
            >
              <Icon name="photo" size={16} />
              {current ? 'החלפת הלוגו' : 'בחירת לוגו מהמחשב'}
            </label>
            <input
              id={inputId}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              disabled={locked}
              onChange={(ev) => {
                const file = ev.target.files?.[0]
                // Reset so picking the same file twice still fires onChange.
                ev.target.value = ''
                if (file) void upload(file)
              }}
              className="sr-only"
            />

            {current ? (
              <button
                type="button"
                onClick={() => void removeLogo()}
                disabled={locked}
                className="inline-flex items-center gap-1.5 rounded-lg p-1.5 text-sm text-slate-400 transition hover:bg-red-50 hover:text-bad disabled:opacity-40"
              >
                <Icon name="trash" size={16} />
                הסרה
              </button>
            ) : null}
          </div>

          <p className="text-xs text-slate-500">
            JPG, PNG או WEBP · עד 5MB. הלוגו מוצג בעיגול בראש העמוד, ולא נספר בין 40
            תמונות הגלריה.
          </p>

          {busy ? (
            <span
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(fraction * 100)}
              aria-label="התקדמות העלאת הלוגו"
              className="block h-1.5 w-full overflow-hidden rounded-full bg-slate-200"
            >
              <span
                className="block h-full rounded-full bg-leaf transition-all"
                style={{ width: `${Math.round(fraction * 100)}%` }}
              />
            </span>
          ) : null}
        </div>
      </div>
    </div>
  )
}
