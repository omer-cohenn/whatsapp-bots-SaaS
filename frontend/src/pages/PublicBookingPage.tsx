// PUBLIC business page (route /book/:slug, NO auth).
//
// It loads two public endpoints in parallel:
//   * GET /api/book/{slug}/page     — the designed page: name, address, the four
//                                     contact fields, the palette, the gallery.
//   * GET /api/book/{slug}/services — the services + welcome message that drive
//                                     <BookingFlow>, exactly as before M20.
//
// The page ENDPOINT IS OPTIONAL to the flow: if it fails we still render the
// booking flow on the plain shell, because a customer who came to book must not
// be blocked by a decorative payload. Only a failed /services load is fatal.
//
// The tenant is resolved server-side from the verified {slug} in the path — the
// client never sends a business_id. PII is only ever sent to the backend (which
// encrypts it). We validate client-side too, but the server is authoritative.

import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import type { PublicService } from '../dashboard/appointmentTypes'
import type { PublicBusinessPage } from '../dashboard/businessPageTypes'
import { getPublicServices } from '../lib/publicBookingClient'
import { getPublicBusinessPage } from '../components/booking/public/publicPageClient'
import { paletteVars } from '../components/booking/public/pageTheme'
import { PUBLIC_PAGE_CSS } from '../components/booking/public/publicPageStyles'
import { ApiError } from '../lib/apiClient'
import { toFriendlyError } from '../lib/friendlyError'
import PublicBookingLayout from '../components/booking/PublicBookingLayout'
import BookingFlow from '../components/booking/BookingFlow'
import BusinessPageView from '../components/booking/public/BusinessPageView'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'

export default function PublicBookingPage() {
  const { slug = '' } = useParams()

  const [businessName, setBusinessName] = useState<string>('')
  const [welcomeMessage, setWelcomeMessage] = useState<string | null>(null)
  const [services, setServices] = useState<PublicService[] | null>(null)
  const [page, setPage] = useState<PublicBusinessPage | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    getPublicServices(slug)
      .then((res) => {
        if (cancelled) return
        setBusinessName(res.business_name)
        setWelcomeMessage(res.welcome_message)
        setServices(res.services)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 404) {
          setLoadError('דף הקביעה לא נמצא. ודאו שהקישור תקין.')
        } else {
          setLoadError(toFriendlyError(err, 'טעינת השירותים נכשלה. נסו שוב.'))
        }
      })

    // Decorative — a failure here degrades to the plain shell, never to an error.
    getPublicBusinessPage(slug)
      .then((res) => {
        if (!cancelled) setPage(res)
      })
      .catch(() => {
        if (!cancelled) setPage(null)
      })

    return () => {
      cancelled = true
    }
  }, [slug])

  if (loadError) {
    return (
      <PublicBookingLayout>
        <Alert tone="error">{loadError}</Alert>
      </PublicBookingLayout>
    )
  }

  if (!services) {
    return (
      <PublicBookingLayout>
        <Spinner label="טוען…" className="py-16" />
      </PublicBookingLayout>
    )
  }

  // No page payload ⇒ the pre-M20 look, so booking still works.
  if (!page) {
    return (
      <PublicBookingLayout businessName={businessName}>
        <BookingFlow
          mode="live"
          slug={slug}
          services={services}
          welcomeMessage={welcomeMessage}
        />
      </PublicBookingLayout>
    )
  }

  // <BusinessPageView> is THE page. The owner's wizard preview renders the very
  // same component, which is what keeps the preview from drifting (M20 revision).
  return (
    <PublicBookingLayout variant="page" themeVars={paletteVars(page.page_theme)}>
      <style>{PUBLIC_PAGE_CSS}</style>

      <BusinessPageView page={page}>
        <BookingFlow
          mode="live"
          slug={slug}
          services={services}
          welcomeMessage={welcomeMessage}
        />
      </BusinessPageView>
    </PublicBookingLayout>
  )
}
