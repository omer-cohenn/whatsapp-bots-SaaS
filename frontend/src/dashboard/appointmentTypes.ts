// TypeScript mirror of the M11 booking contract (backend/app/models/booking.py
// + backend/app/api/booking.py / public_booking.py, plus the Google connect
// contract in backend/app/api/google_oauth.py). The SERVER is authoritative: it
// scopes everything by the session's business_id (admin endpoints) or by the
// verified slug (public endpoints), decrypts PII for the owner only, and
// validates all bodies. These types exist for editor types + UX.
//
// Timezone is FIXED to 'Asia/Jerusalem' server-side; all timestamps that cross
// the wire are UTC ISO strings, and slots are local "HH:MM" strings.

// --- shared shapes -----------------------------------------------------------

/** A single time range inside a weekday (split working hours). */
export type HoursRange = {
  /** "HH:MM" (24h), e.g. "09:00". */
  s: string
  /** "HH:MM" (24h), e.g. "13:00". */
  e: string
}

/**
 * Working hours keyed by weekday string "0".."6" (Sun=0 .. Sat=6), each mapping
 * to a LIST of ranges. A missing/empty list means "closed that day".
 */
export type WorkingHours = Record<string, HoursRange[]>

// --- admin: GET/PUT /api/booking/settings ------------------------------------

export type BookingSettings = {
  /** The public booking slug (read-only here — the server owns it). */
  slug: string
  /** Always 'Asia/Jerusalem' (server-fixed; sent for display, ignored on PUT). */
  timezone: string
  working_hours: WorkingHours
  /** Minimum lead time before a slot can be booked. */
  min_notice_minutes: number
  /** Padding added after each booking (kept free). */
  buffer_minutes: number
  /** How far ahead customers may book. */
  max_days_ahead: number
  /** Global per-business Google Meet toggle (needs Google connected to take effect). */
  meet_enabled: boolean
}

/** Body of PUT /api/booking/settings — slug/timezone are ignored by the server. */
export type BookingSettingsUpdate = {
  working_hours: WorkingHours
  min_notice_minutes: number
  buffer_minutes: number
  max_days_ahead: number
  meet_enabled: boolean
}

// --- admin: services CRUD ----------------------------------------------------

export type ServiceItem = {
  id: string
  name: string
  duration_minutes: number
  active: boolean
  created_at: string
}

export type ServicesResponse = {
  services: ServiceItem[]
}

export type ServiceCreate = {
  name: string
  duration_minutes: number
  active?: boolean
}

export type ServiceUpdate = {
  name?: string
  duration_minutes?: number
  active?: boolean
}

// --- admin: bookings ---------------------------------------------------------

/** A booking's lifecycle status (server-validated). */
export type BookingStatus = 'pending' | 'confirmed' | 'cancelled' | 'completed'

export type BookingItem = {
  id: string
  service_id: string | null
  service_name: string | null
  lead_id: string | null
  /** PII — decrypted for the owner only. */
  client_name: string | null
  client_phone: string | null
  client_email: string | null
  /** UTC ISO start time. Render in the browser's locale. */
  scheduled_at: string
  duration_minutes: number
  status: BookingStatus
  notes: string | null
  google_event_id: string | null
  /** "Join Google Meet" link, or null when not synced / Meet disabled. */
  meet_link: string | null
  is_test: boolean
  created_at: string
  updated_at: string
}

export type BookingsResponse = {
  bookings: BookingItem[]
}

/** A home notification: a customer cancelled/rescheduled their booking. */
export type BookingAlert = {
  booking_id: string
  kind: 'cancelled' | 'rescheduled'
  at: string | null
  client_name: string | null
  service_name: string | null
  scheduled_at: string | null
}

export type BookingAlertsResponse = {
  alerts: BookingAlert[]
}

/**
 * Body of PATCH /api/bookings/{id}. Either change `status`, or reschedule by
 * sending `date`+`time` together (both-or-neither). At least one is required.
 */
export type BookingPatch = {
  status?: BookingStatus
  /** "YYYY-MM-DD" — must be sent together with `time`. */
  date?: string
  /** "HH:MM" — must be sent together with `date`. */
  time?: string
}

/** Response of PATCH /api/bookings/{id}. */
export type BookingMutateResponse = {
  booking_id: string
  status: BookingStatus
  scheduled_at: string
}

// --- public booking ----------------------------------------------------------

/** A bookable service as the public page sees it (active only, no PII). */
export type PublicService = {
  id: string
  name: string
  duration_minutes: number
}

/** GET /api/book/{slug}/services. */
export type PublicServicesResponse = {
  business_name: string
  services: PublicService[]
}

/** GET /api/book/{slug}/slots — local Asia/Jerusalem "HH:MM" starts. */
export type SlotsResponse = {
  date: string
  slots: string[]
}

/** Body of POST /api/book/{slug} (the customer's booking request). */
export type PublicBookingCreate = {
  service_id: string
  /** "YYYY-MM-DD" (Asia/Jerusalem local date). */
  date: string
  /** "HH:MM" (Asia/Jerusalem local time). */
  time: string
  name: string
  phone: string
  email?: string
  notes?: string
}

/** Response of POST /api/book/{slug} — the cancel_token lets the customer manage. */
export type PublicBookingResponse = {
  booking_id: string
  cancel_token: string
  scheduled_at: string
}

/** Response of cancel / reschedule. */
export type PublicManageResponse = {
  booking_id: string
  status: BookingStatus
  scheduled_at: string
}

// --- Google Calendar connect (admin) -----------------------------------------

/** GET /api/google/connect — the SPA redirects the browser to `auth_url`. */
export type GoogleConnectResponse = {
  auth_url: string
}

/** GET /api/google/status — drives the connect/disconnect UI. */
export type GoogleStatus = {
  connected: boolean
  email: string | null
  scope: string | null
}

/** POST /api/google/disconnect — idempotent. */
export type GoogleDisconnectResponse = {
  connected: boolean
}
