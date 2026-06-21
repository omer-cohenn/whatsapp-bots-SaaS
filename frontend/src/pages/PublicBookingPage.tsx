// PUBLIC booking page (route /book/:slug, NO auth). It loads the business's
// services + welcome message (GET /services), then renders the reusable
// <BookingFlow mode="live">, which owns the whole flow: welcome hero → pick a
// service → pick a date (custom month calendar driven by GET /availability) →
// pick a slot (GET /slots) → summary + customer form → POST create → confirmation.
//
// The tenant is resolved server-side from the verified {slug} in the path — the
// client never sends a business_id. PII is only ever sent to the backend (which
// encrypts it). We validate client-side too, but the server is authoritative.

import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import type { PublicService } from '../dashboard/appointmentTypes'
import { getPublicServices } from '../lib/publicBookingClient'
import { ApiError } from '../lib/apiClient'
import { toFriendlyError } from '../lib/friendlyError'
import PublicBookingLayout from '../components/booking/PublicBookingLayout'
import BookingFlow from '../components/booking/BookingFlow'
import Spinner from '../components/ui/Spinner'
import Alert from '../components/ui/Alert'

export default function PublicBookingPage() {
  const { slug = '' } = useParams()

  const [businessName, setBusinessName] = useState<string>('')
  const [welcomeMessage, setWelcomeMessage] = useState<string | null>(null)
  const [services, setServices] = useState<PublicService[] | null>(null)
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
