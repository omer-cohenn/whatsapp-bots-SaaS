-- ============================================================================
-- 0011_booking_service_extras.sql — public booking page polish (M11.1, decision 0012)
-- ----------------------------------------------------------------------------
-- Three additive columns so the public booking page can show richer service
-- cards + a per-business welcome message:
--   services.description          — free-text blurb under the service title.
--   services.price                — OPTIONAL price in ₪ (whole shekels). NULL =>
--                                   the UI shows "ללא עלות". >=0 enforced in app.
--   booking_settings.welcome_message — short Hebrew greeting shown atop the
--                                   public page (editable + AI-generatable).
--
-- Purely additive: no new table, no RLS/grant change. `services` and
-- `booking_settings` already have RLS + app_role grants (0009), both of which
-- cover any new column automatically. NONE of these hold PII/ciphertext —
-- they are public, owner-authored marketing copy. Idempotent via
-- ADD COLUMN IF NOT EXISTS.
-- ============================================================================

ALTER TABLE services         ADD COLUMN IF NOT EXISTS description     text;  -- service blurb (public)
ALTER TABLE services         ADD COLUMN IF NOT EXISTS price           int;   -- ₪ whole shekels, NULL=free, >=0 (app-enforced)
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS welcome_message text;  -- public-page greeting (Hebrew)
