// פרטי העסק (M20) — שם, סלוגן, תיאור, כתובת וארבעת פרטי הקשר
//
// The text half of the "פרטי העסק וזמינות" tab. The working-hours and
// availability editors live alongside it in BookingSettingsPanel; this card owns
// everything that goes into the public page's hero.
//
// The one rule that shapes this whole file: PUT /api/booking/page is a PARTIAL
// update where an omitted key is left alone and an explicit null CLEARS the
// column (contract §5). So `save()` diffs the draft against what the server last
// told us and sends ONLY what moved. Spreading the whole draft would look like
// it worked and quietly overwrite fields the owner never opened.
//
// That same rule is the product behaviour the owner sees: emptying the phone
// field is how the call button disappears from their page. We say so in plain
// Hebrew right next to the inputs instead of leaving them to discover it.

import { useState } from 'react'
import type { BusinessPage, BusinessPageUpdate } from '../../../dashboard/businessPageTypes'
import { updateBusinessPage } from '../../../lib/businessPageClient'
import { toFriendlyError } from '../../../lib/friendlyError'
import { ApiError } from '../../../lib/apiClient'
import Alert from '../../ui/Alert'
import Button from '../../ui/Button'
import Card from '../../ui/Card'
import Field from '../../ui/Field'
import Icon from '../../ui/Icon'
import Textarea from '../../ui/Textarea'
import LogoUploader from './LogoUploader'

/** The editable text fields, as strings — '' stands for "cleared". */
type Draft = {
  business_name: string
  tagline: string
  about: string
  address: string
  phone: string
  whatsapp: string
  instagram_url: string
  waze_url: string
}

/**
 * Which draft keys map 1:1 onto the PUT body as nullable text columns.
 * `business_name` is deliberately NOT here — it is the one field that cannot be
 * cleared, so it is diffed separately below.
 */
const FIELDS = [
  'tagline',
  'about',
  'address',
  'phone',
  'whatsapp',
  'instagram_url',
  'waze_url',
] as const

function draftFrom(page: BusinessPage): Draft {
  return {
    business_name: page.business_name ?? '',
    tagline: page.tagline ?? '',
    about: page.about ?? '',
    address: page.address ?? '',
    phone: page.phone ?? '',
    whatsapp: page.whatsapp ?? '',
    instagram_url: page.instagram_url ?? '',
    waze_url: page.waze_url ?? '',
  }
}

// The three link fields are rendered as href/src on a public page, so the server
// rejects anything that isn't http(s) with a 422. Catch it here first — a
// pointed message beats a generic "הנתונים אינם תקינים".
function badLink(value: string): boolean {
  const trimmed = value.trim()
  if (!trimmed) return false
  return !/^https?:\/\//i.test(trimmed)
}

type Props = {
  page: BusinessPage
  /** Hand the server's fresh copy back to the parent after a save. */
  onSaved: (page: BusinessPage) => void
}

export default function BusinessDetailsCard({ page, onSaved }: Props) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(page))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  function set<K extends keyof Draft>(key: K, value: string) {
    setDraft((prev) => ({ ...prev, [key]: value }))
    setSaved(false)
  }

  const linkError = badLink(draft.instagram_url) || badLink(draft.waze_url)

  // The server enforces min_length 1; catching it here means the owner gets a
  // sentence instead of a 422, and the save button simply stays off.
  const nameEmpty = draft.business_name.trim().length === 0

  const dirty =
    FIELDS.some((key) => draft[key].trim() !== (page[key] ?? '')) ||
    draft.business_name.trim() !== page.business_name

  async function save() {
    if (linkError) {
      setError('קישורים חייבים להתחיל ב-https:// — העתיקו את הכתובת המלאה מהדפדפן.')
      return
    }
    if (nameEmpty) {
      setError('שם העסק לא יכול להישאר ריק — זה מה שמופיע בראש העמוד.')
      return
    }
    // Build the body from the DIFF. `|| null` turns an emptied box into an
    // explicit null, which is what clears the column (and removes the button).
    // Built as a plain record first: every one of FIELDS is a `string | null`
    // column, so one narrow cast at the end beats eight per-key branches.
    const diff: Record<string, string | null> = {}
    for (const key of FIELDS) {
      const next = draft[key].trim()
      if (next !== (page[key] ?? '')) diff[key] = next || null
    }
    // `business_name` writes through to `businesses.name` and can never be
    // nulled, so it is added only when it actually changed AND is non-empty.
    const nextName = draft.business_name.trim()
    if (nextName && nextName !== page.business_name) diff.business_name = nextName

    if (Object.keys(diff).length === 0) return
    const body = diff as BusinessPageUpdate

    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const updated = await updateBusinessPage(body)
      onSaved(updated)
      setDraft(draftFrom(updated))
      setSaved(true)
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setError('אחד השדות ארוך מדי או לא תקין. בדקו את הקישורים ואת אורך הטקסטים.')
      } else {
        setError(toFriendlyError(err, 'שמירת פרטי העסק נכשלה. נסו שוב.'))
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
          <Icon name="building-store" size={20} className="text-leaf" />
          פרטי העסק
        </h2>
        <div className="flex items-center gap-3">
          {saved ? (
            <span role="status" className="text-sm text-ok">
              נשמר
            </span>
          ) : null}
          <Button
            type="button"
            onClick={() => void save()}
            disabled={saving || !dirty}
            className="!bg-leaf hover:!bg-leaf-dark"
          >
            <Icon name="device-floppy" size={16} />
            {saving ? 'שומר…' : 'שמור פרטים'}
          </Button>
        </div>
      </div>

      <p className="mt-1 text-sm text-slate-500">
        כל מה שכתוב כאן מופיע בראש העמוד שהלקוחות רואים.
      </p>

      {error ? (
        <Alert tone="error" className="mt-3">
          {error}
        </Alert>
      ) : null}

      <div className="mt-4 flex flex-col gap-4">
        {/* The name lives on `businesses` and IS editable now (M20 revision).
            The account is named from the Google profile at signup, so a solo
            owner's public page carried their personal name until they renamed
            it — the owner's words: "עומר כהן זה שם של בן אדם לא שם של עסק". */}
        <Field
          label="שם העסק"
          value={draft.business_name}
          onChange={(ev) => set('business_name', ev.target.value)}
          maxLength={120}
          required
          placeholder="לדוגמה: מספרת הרצל"
          hint="זה השם הגדול בראש העמוד שהלקוחות רואים. חייב להיות מלא."
          disabled={saving}
          className={nameEmpty ? 'border-bad' : ''}
        />

        <LogoUploader page={page} onUploaded={onSaved} disabled={saving} />

        <Field
          label="שורת תיאור קצרה (לא חובה)"
          value={draft.tagline}
          onChange={(ev) => set('tagline', ev.target.value)}
          maxLength={160}
          placeholder="לדוגמה: מספרה שכונתית מאז 2010"
          disabled={saving}
        />

        <Textarea
          label="על העסק (לא חובה)"
          value={draft.about}
          onChange={(ev) => set('about', ev.target.value)}
          rows={4}
          maxLength={2000}
          placeholder="כמה מילים על מה שאתם עושים, מי אתם, ומה מיוחד אצלכם."
          disabled={saving}
        />

        <Field
          label="כתובת (לא חובה)"
          value={draft.address}
          onChange={(ev) => set('address', ev.target.value)}
          maxLength={240}
          placeholder="הרצל 10, תל אביב"
          disabled={saving}
        />

        {/* The four hero buttons. */}
        <fieldset className="flex flex-col gap-4 rounded-xl border border-slate-200 p-4">
          <legend className="px-1 text-sm font-medium text-slate-800">
            כפתורי יצירת קשר
          </legend>
          <p className="text-sm text-slate-500">
            כל שדה שתמלאו כאן הופך לכפתור עגול בראש העמוד.{' '}
            <strong className="font-medium text-slate-700">
              שדה שנשאר ריק — הכפתור שלו פשוט לא יופיע.
            </strong>{' '}
            כך אפשר להסיר כפתור: מוחקים את התוכן ושומרים.
          </p>

          <Field
            label="טלפון"
            value={draft.phone}
            onChange={(ev) => set('phone', ev.target.value)}
            maxLength={40}
            type="tel"
            dir="ltr"
            placeholder="03-1234567"
            hint="כפתור חיוג. ריק ⇐ אין כפתור טלפון."
            disabled={saving}
          />

          <Field
            label="WhatsApp"
            value={draft.whatsapp}
            onChange={(ev) => set('whatsapp', ev.target.value)}
            maxLength={40}
            dir="ltr"
            placeholder="972501234567"
            hint="מספר בפורמט בינלאומי, בלי + ובלי מקפים. ריק ⇐ אין כפתור WhatsApp."
            disabled={saving}
          />

          <Field
            label="קישור לאינסטגרם"
            value={draft.instagram_url}
            onChange={(ev) => set('instagram_url', ev.target.value)}
            maxLength={500}
            dir="ltr"
            placeholder="https://instagram.com/…"
            hint="חייב להתחיל ב-https://. ריק ⇐ אין כפתור אינסטגרם."
            disabled={saving}
            className={badLink(draft.instagram_url) ? 'border-bad' : ''}
          />

          <Field
            label="קישור ל-Waze"
            value={draft.waze_url}
            onChange={(ev) => set('waze_url', ev.target.value)}
            maxLength={500}
            dir="ltr"
            placeholder="https://waze.com/ul/…"
            hint="חייב להתחיל ב-https://. ריק ⇐ אין כפתור Waze."
            disabled={saving}
            className={badLink(draft.waze_url) ? 'border-bad' : ''}
          />
        </fieldset>
      </div>
    </Card>
  )
}
