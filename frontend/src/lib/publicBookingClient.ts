// Typed wrappers around the M11 PUBLIC booking endpoints (no session required).
// The customer is NOT logged in: there's no cookie and no business_id from the
// client. The tenant is resolved server-side purely from the verified {slug} in
// the path. We still reuse `api` so we share the same timeout / error handling;
// `credentials:'include'` is harmless here (there's simply no session cookie).

import { api } from './apiClient'
import type {
  PublicAvailabilityResponse,
  PublicBookingCreate,
  PublicBookingResponse,
  PublicManageResponse,
  PublicServicesResponse,
  SlotsResponse,
} from '../dashboard/appointmentTypes'

// Build a query string from defined params (omits undefined/'').
function qs(params: Record<string, string | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue
    search.set(key, value)
  }
  const str = search.toString()
  return str ? `?${str}` : ''
}

const slugPath = (slug: string) => `/api/book/${encodeURIComponent(slug)}`

/**
 * GET /api/book/{slug}/services — the business name + its active services.
 * 404 (ApiError) if the slug is unknown.
 */
export function getPublicServices(slug: string): Promise<PublicServicesResponse> {
  return api.get<PublicServicesResponse>(`${slugPath(slug)}/services`)
}

/**
 * GET /api/book/{slug}/slots?service_id=&date=YYYY-MM-DD — the available local
 * "HH:MM" start times for that service on that date (taken/out-of-window removed).
 */
export function getPublicSlots(
  slug: string,
  serviceId: string,
  date: string,
): Promise<SlotsResponse> {
  return api.get<SlotsResponse>(
    `${slugPath(slug)}/slots${qs({ service_id: serviceId, date })}`,
  )
}

/**
 * GET /api/book/{slug}/availability?service_id=&from=&to= — the days in the
 * [from,to] window (inclusive, "YYYY-MM-DD") that have ≥1 free slot for that
 * service. The server bounds the span to ≤62 days (422 otherwise); an unknown
 * or inactive service simply yields an empty list.
 */
export function getPublicAvailability(
  slug: string,
  serviceId: string,
  from: string,
  to: string,
): Promise<PublicAvailabilityResponse> {
  return api.get<PublicAvailabilityResponse>(
    `${slugPath(slug)}/availability${qs({ service_id: serviceId, from, to })}`,
  )
}

/**
 * POST /api/book/{slug} — create the booking. Returns the cancel_token so the
 * customer can manage it later. 409 if the slot was just taken, 422 if invalid,
 * 429 if rate-limited (too many attempts).
 */
export function createPublicBooking(
  slug: string,
  body: PublicBookingCreate,
): Promise<PublicBookingResponse> {
  return api.post<PublicBookingResponse>(slugPath(slug), body)
}

/**
 * POST /api/book/{slug}/cancel/{token} — customer cancels via their non-guessable
 * token. 404 if the token is wrong.
 */
export function cancelPublicBooking(
  slug: string,
  token: string,
): Promise<PublicManageResponse> {
  return api.post<PublicManageResponse>(
    `${slugPath(slug)}/cancel/${encodeURIComponent(token)}`,
  )
}

/**
 * POST /api/book/{slug}/reschedule/{token} — customer moves the booking to a new
 * date+time. 409 if taken, 422 if invalid, 404 if the token is wrong.
 */
export function reschedulePublicBooking(
  slug: string,
  token: string,
  date: string,
  time: string,
): Promise<PublicManageResponse> {
  return api.post<PublicManageResponse>(
    `${slugPath(slug)}/reschedule/${encodeURIComponent(token)}`,
    { date, time },
  )
}
