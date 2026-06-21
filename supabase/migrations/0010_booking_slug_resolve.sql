-- ============================================================================
-- 0010_booking_slug_resolve.sql — public-slug → business_id bootstrap (M11)
-- ----------------------------------------------------------------------------
-- THE PROBLEM (mirrors 0005's login bootstrap): the PUBLIC booking page has NO
-- session, so when a customer opens /api/book/{slug}/... there is no tenant
-- context yet — `app.business_id` / current_business_id() is unset. But to learn
-- WHICH business a slug belongs to we must read booking_settings, which has RLS
-- FORCED (0009) under app_role → a plain SELECT returns 0 rows. So the public
-- path can't even resolve the slug.
--
-- THE FIX: ONE tiny SECURITY DEFINER function, resolve_booking_slug(slug), that
-- runs with the owner's rights (BYPASSES RLS) and returns ONLY the business_id
-- for that exact slug (or NULL). It exposes nothing else — no settings, no PII,
-- no cross-tenant data. The public router calls it FIRST, then opens a normal
-- tenant_connection bound to that business_id so EVERY subsequent read/write is
-- RLS-scoped exactly like an authenticated request. This is the same pattern as
-- provision_owner: a minimal, tightly-scoped definer used only to bootstrap the
-- tenant context that RLS then enforces.
--
-- SAFETY:
--   * SET search_path = public, pg_temp (standard SECURITY DEFINER hygiene).
--   * EXECUTE revoked from PUBLIC, granted only to app_role.
--   * Returns a single uuid (or NULL) — slug is the public, non-guessable handle.
-- Idempotent: CREATE OR REPLACE + idempotent REVOKE/GRANT.
-- ============================================================================

CREATE OR REPLACE FUNCTION resolve_booking_slug(p_slug text)
RETURNS uuid
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT business_id
  FROM booking_settings
  WHERE slug = p_slug
  LIMIT 1
$$;

REVOKE ALL ON FUNCTION resolve_booking_slug(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION resolve_booking_slug(text) TO app_role;


-- ----------------------------------------------------------------------------
-- bookings_due_for_reminder — the background reminder sweep's cross-tenant read.
-- ----------------------------------------------------------------------------
-- THE PROBLEM (mirrors the abandoned-lead sweep, 0006): the reminder sweep is a
-- TENANT-LESS background job. Under app_role, RLS is FORCED on bookings, so a
-- plain SELECT with no app.business_id returns 0 rows. The job needs to see
-- upcoming bookings across ALL businesses to queue confirmations + day-before
-- reminders into the Redis outbox.
--
-- THE FIX: ONE tightly-scoped SECURITY DEFINER read that returns ONLY the
-- structural fields the sweep needs to build an outbox entry — NO PII (no name,
-- phone, email, notes). It returns active (pending/confirmed) bookings whose
-- start is within the next `p_window_hours` and still in the future. The sweep
-- de-dupes "already queued" purely in Redis (a per-booking marker), so this
-- function performs NO write and exposes nothing tenant-sensitive.
--
-- SAFETY: SET search_path; EXECUTE revoked from PUBLIC, granted only to app_role.
-- Idempotent: CREATE OR REPLACE + idempotent REVOKE/GRANT.
CREATE OR REPLACE FUNCTION bookings_due_for_reminder(p_window_hours int)
RETURNS TABLE(
  id           uuid,
  business_id  uuid,
  scheduled_at timestamptz,
  status       text,
  is_test      boolean
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT b.id, b.business_id, b.scheduled_at, b.status, b.is_test
  FROM bookings b
  WHERE b.status IN ('pending', 'confirmed')
    AND b.scheduled_at >= now()
    AND b.scheduled_at <= now() + make_interval(hours => p_window_hours)
$$;

REVOKE ALL ON FUNCTION bookings_due_for_reminder(int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION bookings_due_for_reminder(int) TO app_role;
