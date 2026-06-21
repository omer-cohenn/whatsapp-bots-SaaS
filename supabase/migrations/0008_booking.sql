-- ============================================================================
-- 0008_booking.sql — the booking tables (Bizz_up M11, decision 0011)
-- ----------------------------------------------------------------------------
-- Source of truth: docs/spec/data-model.md + decision 0011. Four new tables for
-- the public booking page + per-business Google Calendar (optional):
--   booking_settings   — per-business booking config (1 row per business).
--   services           — the bookable services (MANY per business, each its own
--                        duration).
--   bookings           — a booked slot; every booking links a LEAD (M9/M10) and
--                        is stored in UTC (timezone is fixed Asia/Jerusalem).
--   google_credentials — the OWNER's Google refresh token (🔒 KEK-encrypted),
--                        used to create calendar events. OPTIONAL per business.
--
-- Conventions (mirror 0003):
--   * uuid PKs via gen_random_uuid() (pgcrypto); business_id uuid → businesses(id)
--     ON DELETE CASCADE is the tenant key.
--   * 🔒 columns hold CIPHERTEXT only (encrypted in the app before insert):
--       bookings.client_name / client_phone / client_email / notes,
--       google_credentials.refresh_token (🔒 KEK envelope).
--   * Timezone is FIXED 'Asia/Jerusalem' (decision 0011); scheduled_at is stored
--     in UTC and converted in the app via zoneinfo.
--   * working_hours is a SPLIT-hours object: weekday "0".."6" (Sun=0) → a LIST of
--     {"s":"HH:MM","e":"HH:MM"} ranges, so a day can have e.g. morning + evening.
--   * RLS + grants are applied separately in 0009 (kept apart for clarity).
-- Idempotent: CREATE TABLE IF NOT EXISTS + ADD COLUMN/INDEX IF NOT EXISTS.
-- NOTE: set_updated_at() already exists (defined in 0003); reused below.
-- ============================================================================

-- 1) booking_settings — per-business booking config. PK = business_id (1:1).
CREATE TABLE IF NOT EXISTS booking_settings (
  business_id        uuid PRIMARY KEY REFERENCES businesses(id) ON DELETE CASCADE,
  timezone           text NOT NULL DEFAULT 'Asia/Jerusalem',   -- FIXED (decision 0011)
  -- weekday "0".."6" (Sun=0) → [ {"s":"09:00","e":"13:00"}, {"s":"16:00","e":"19:00"} ]
  working_hours      jsonb NOT NULL DEFAULT '{}'::jsonb,
  min_notice_minutes int NOT NULL DEFAULT 120,                 -- earliest bookable lead time
  buffer_minutes     int NOT NULL DEFAULT 0,                   -- gap padded around each booking
  max_days_ahead     int NOT NULL DEFAULT 30,                  -- how far ahead a slot may be booked
  meet_enabled       boolean NOT NULL DEFAULT false,           -- global per-business Google Meet toggle
  slug               text UNIQUE NOT NULL,                     -- public booking-page handle
  updated_at         timestamptz NOT NULL DEFAULT now()
);

-- 2) services — the bookable services. MANY per business, each its own duration.
CREATE TABLE IF NOT EXISTS services (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id      uuid NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  name             text NOT NULL,
  duration_minutes int NOT NULL DEFAULT 30,
  active           boolean NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now()
);

-- 3) bookings — a booked slot. Stored in UTC; always links a LEAD (M9/M10). PII 🔒.
CREATE TABLE IF NOT EXISTS bookings (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id      uuid NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  service_id       uuid REFERENCES services(id) ON DELETE SET NULL,
  lead_id          uuid REFERENCES leads(id) ON DELETE SET NULL,  -- every booking links a lead
  client_name      text,                            -- 🔒 ciphertext
  client_phone     text,                            -- 🔒 ciphertext
  client_email     text,                            -- 🔒 ciphertext
  scheduled_at     timestamptz NOT NULL,            -- UTC (tz fixed Asia/Jerusalem in app)
  duration_minutes int NOT NULL,
  status           text NOT NULL DEFAULT 'pending', -- pending→confirmed→cancelled / completed
  notes            text,                            -- 🔒 ciphertext
  google_event_id  text,                            -- the created Google Calendar event id
  meet_link        text,                            -- the Google Meet link (if meet_enabled)
  cancel_token     text NOT NULL,                   -- non-guessable token for cancel/reschedule
  is_test          boolean NOT NULL DEFAULT false,
  key_version      int NOT NULL DEFAULT 1,          -- which KEK encrypted the PII (rotation)
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- 4) google_credentials — the OWNER's Google refresh token. 🔒 KEK. OPTIONAL.
CREATE TABLE IF NOT EXISTS google_credentials (
  business_id     uuid PRIMARY KEY REFERENCES businesses(id) ON DELETE CASCADE,
  refresh_token   text NOT NULL,                    -- 🔒 KEK-encrypted refresh token
  scope           text,                             -- granted OAuth scopes
  connected_email text,                             -- the connected Google account email
  connected_at    timestamptz NOT NULL DEFAULT now()
);

-- Indexes — the hot paths for the booking calendar + public page + cancel link.
CREATE INDEX IF NOT EXISTS ix_bookings_business_scheduled ON bookings(business_id, scheduled_at DESC);
CREATE INDEX IF NOT EXISTS ix_bookings_business_status    ON bookings(business_id, status);
CREATE INDEX IF NOT EXISTS ix_bookings_service            ON bookings(service_id);
CREATE INDEX IF NOT EXISTS ix_bookings_cancel_token       ON bookings(cancel_token);
CREATE INDEX IF NOT EXISTS ix_services_business           ON services(business_id);
-- booking_settings.slug already gets a UNIQUE index from its UNIQUE constraint.

-- updated_at triggers on the mutating tables (drop+create = idempotent).
DROP TRIGGER IF EXISTS trg_booking_settings_updated ON booking_settings;
CREATE TRIGGER trg_booking_settings_updated BEFORE UPDATE ON booking_settings
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_bookings_updated         ON bookings;
CREATE TRIGGER trg_bookings_updated         BEFORE UPDATE ON bookings
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
