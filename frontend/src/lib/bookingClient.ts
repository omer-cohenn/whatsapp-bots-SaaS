// Typed wrappers around the M11 ADMIN booking endpoints (settings, services,
// bookings) + the Google Calendar connect endpoints. All of these are gated:
// they go through `api` (src/lib/apiClient.ts), which sends the session cookie
// same-origin with `credentials: 'include'`. The tenant (business_id) is derived
// entirely from that server session — we NEVER send it from the client.

import { api } from './apiClient'
import type {
  BookingMutateResponse,
  BookingPatch,
  BookingSettings,
  BookingSettingsUpdate,
  BookingStatus,
  BookingsResponse,
  GoogleConnectResponse,
  GoogleDisconnectResponse,
  GoogleStatus,
  ServiceCreate,
  ServiceItem,
  ServiceUpdate,
  ServicesResponse,
} from '../dashboard/appointmentTypes'

// Build a query string from defined, non-empty params (omits undefined/'').
function qs(params: Record<string, string | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue
    search.set(key, String(value))
  }
  const str = search.toString()
  return str ? `?${str}` : ''
}

// --- settings ----------------------------------------------------------------

/** GET /api/booking/settings — the owner's booking settings (incl. the slug). */
export function getBookingSettings(): Promise<BookingSettings> {
  return api.get<BookingSettings>('/api/booking/settings')
}

/**
 * PUT /api/booking/settings — save working hours / availability rules / the Meet
 * toggle. The server ignores slug + timezone, so we don't send them.
 */
export function updateBookingSettings(
  body: BookingSettingsUpdate,
): Promise<BookingSettings> {
  return api.put<BookingSettings>('/api/booking/settings', body)
}

// --- services ----------------------------------------------------------------

/** GET /api/services — every service for this business (active + inactive). */
export function getServices(): Promise<ServicesResponse> {
  return api.get<ServicesResponse>('/api/services')
}

/** POST /api/services — create a service (201). */
export function createService(body: ServiceCreate): Promise<ServiceItem> {
  return api.post<ServiceItem>('/api/services', body)
}

/** PATCH /api/services/{id} — partial update (404 if not ours). */
export function updateService(
  id: string,
  body: ServiceUpdate,
): Promise<ServiceItem> {
  return api.patch<ServiceItem>(`/api/services/${encodeURIComponent(id)}`, body)
}

/** DELETE /api/services/{id} — 204 on success (404 if not ours). */
export function deleteService(id: string): Promise<void> {
  return api.delete<void>(`/api/services/${encodeURIComponent(id)}`)
}

// --- bookings ----------------------------------------------------------------

/**
 * GET /api/bookings — the booking list (PII decrypted for the owner). Optional
 * status + date-range (YYYY-MM-DD) filters, and an include_test flag.
 */
export function getBookings(opts: {
  status?: BookingStatus
  from?: string
  to?: string
  includeTest?: boolean
} = {}): Promise<BookingsResponse> {
  return api.get<BookingsResponse>(
    `/api/bookings${qs({
      status: opts.status,
      from: opts.from,
      to: opts.to,
      include_test: opts.includeTest,
    })}`,
  )
}

/**
 * PATCH /api/bookings/{id} — change status OR reschedule (date+time together).
 * 409 if the new slot is taken; 404 if the booking isn't ours.
 */
export function patchBooking(
  id: string,
  body: BookingPatch,
): Promise<BookingMutateResponse> {
  return api.patch<BookingMutateResponse>(
    `/api/bookings/${encodeURIComponent(id)}`,
    body,
  )
}

// --- Google Calendar connect -------------------------------------------------

/**
 * GET /api/google/connect — returns the Google consent URL. The SPA then sends
 * the browser there (window.location). 503 if calendar connect isn't configured.
 */
export function getGoogleConnectUrl(): Promise<GoogleConnectResponse> {
  return api.get<GoogleConnectResponse>('/api/google/connect')
}

/** GET /api/google/status — connected? + which email/scope. */
export function getGoogleStatus(): Promise<GoogleStatus> {
  return api.get<GoogleStatus>('/api/google/status')
}

/** POST /api/google/disconnect — idempotent; re-fetch status afterwards. */
export function disconnectGoogle(): Promise<GoogleDisconnectResponse> {
  return api.post<GoogleDisconnectResponse>('/api/google/disconnect')
}
