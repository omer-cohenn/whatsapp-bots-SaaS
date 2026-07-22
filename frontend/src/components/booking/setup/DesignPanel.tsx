// טאב "תמונות ועיצוב" (M20) — גלריית התמונות ובורר הפלטות
//
// Both halves of this tab feed the same live preview, which is why they share a
// panel: the owner picks a palette and sees it applied to the photos they just
// uploaded, in the same screen, without saving anything first.
//
// The palette saves on click (one key inside `page_theme`) rather than behind a
// save button — there is nothing to review, and the preview already showed the
// result. Gallery changes save themselves too, per GalleryManager.

import { useEffect, useState } from 'react'
import type { PublicService } from '../../../dashboard/appointmentTypes'
import type { BusinessImage } from '../../../dashboard/businessPageTypes'
import { getBookingSettings, getServices } from '../../../lib/bookingClient'
import { ApiError } from '../../../lib/apiClient'
import { updateBusinessPage } from '../../../lib/businessPageClient'
import { toFriendlyError } from '../../../lib/friendlyError'
import Alert from '../../ui/Alert'
import Card from '../../ui/Card'
import Icon from '../../ui/Icon'
import Spinner from '../../ui/Spinner'
import GalleryManager from './GalleryManager'
import PalettePicker from './PalettePicker'
import { useBusinessPage } from './useBusinessPage'

export default function DesignPanel() {
  const { page, setPage, loading, error } = useBusinessPage()
  const [themeSaving, setThemeSaving] = useState(false)
  const [themeError, setThemeError] = useState<string | null>(null)
  // Demo-mode note: informational, not an error — see selectPalette.
  const [themeNotice, setThemeNotice] = useState<string | null>(null)

  // The preview renders the owner's REAL services and welcome message, not
  // sample content — a preview built from invented data is exactly how the old
  // one drifted out of sync with the live page. Failing to load them is not an
  // error worth blocking the tab for: the preview simply shows no service cards.
  const [services, setServices] = useState<PublicService[]>([])
  const [welcomeMessage, setWelcomeMessage] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getServices()
      .then((res) => {
        if (cancelled) return
        // The preview mirrors the public page, which only ever shows ACTIVE
        // services — including a hidden one here would over-promise.
        setServices(
          res.services
            .filter((s) => s.active)
            .map((s) => ({
              id: s.id,
              name: s.name,
              duration_minutes: s.duration_minutes,
              description: s.description,
              price: s.price,
            })),
        )
      })
      .catch(() => {})
    getBookingSettings()
      .then((res) => {
        if (!cancelled) setWelcomeMessage(res.welcome_message ?? null)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) return <Spinner label="טוען את עיצוב העמוד…" className="py-12" />
  if (error) return <Alert tone="error">{error}</Alert>
  if (!page) return null

  function setImages(images: BusinessImage[]) {
    setPage((prev) => (prev ? { ...prev, images } : prev))
  }

  // Send ONLY page_theme. Sending the surrounding fields too would rewrite text
  // the owner never touched on this tab (contract §5).
  async function selectPalette(paletteId: string) {
    const previous = page?.page_theme
    // Optimistic: the preview is the whole point, so it must not wait on the network.
    setPage((prev) => (prev ? { ...prev, page_theme: { ...prev.page_theme, palette: paletteId } } : prev))
    setThemeSaving(true)
    setThemeError(null)
    try {
      const updated = await updateBusinessPage({
        page_theme: { ...previous, palette: paletteId },
      })
      setPage(updated)
    } catch (err) {
      // In the public demo the server refuses every write by design. KEEP the
      // optimistic change instead of rolling it back: the visitor picked a
      // palette, the preview should show it, and the whole point of the demo is
      // that it feels editable. Nothing was persisted, which is intended. Any
      // OTHER failure is a real one and must still revert, or the owner would be
      // looking at colours that were never saved.
      if (err instanceof ApiError && err.isDemoBlocked) {
        setThemeNotice(err.detail)
      } else {
        setThemeError(toFriendlyError(err, 'שמירת הצבעים נכשלה. נסו שוב.'))
        setPage((prev) => (prev && previous ? { ...prev, page_theme: previous } : prev))
      }
    } finally {
      setThemeSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
          <Icon name="photo" size={20} className="text-leaf" />
          תמונות העסק
        </h2>
        <p className="mt-1 mb-4 text-sm text-slate-500">
          התמונות מופיעות בעמוד לפי הסדר שכאן. הכיתוב נשמר לבד ברגע שאתם יוצאים מהשדה.
        </p>
        <GalleryManager images={page.images} onImagesChange={setImages} />
      </Card>

      <Card>
        <h2 className="flex items-center gap-2 text-lg font-semibold text-slate-900">
          <Icon name="sparkles" size={20} className="text-leaf" />
          צבעי העמוד
        </h2>
        <p className="mt-1 mb-4 text-sm text-slate-500">
          בחרו פלטה — היא נשמרת מיד, והתצוגה למטה מראה איך העמוד ייראה בפועל.
        </p>

        {themeError ? (
          <Alert tone="error" className="mb-3">
            {themeError}
          </Alert>
        ) : null}

        {themeNotice ? (
          <Alert tone="info" className="mb-3">
            {themeNotice}
          </Alert>
        ) : null}

        <PalettePicker
          theme={page.page_theme}
          onSelect={(id) => void selectPalette(id)}
          disabled={themeSaving}
          page={page}
          services={services}
          welcomeMessage={welcomeMessage}
        />
      </Card>
    </div>
  )
}
