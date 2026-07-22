-- 0030 — סימון עסק הדמו הציבורי
--
-- The login screen has a public "המשך בתור דמו" button (GET /auth/demo) that
-- logs a visitor into ONE fixed tenant with a read-only session.
--
-- WHY A COLUMN AND NOT A HARD-CODED UUID: the backend must resolve that tenant
-- server-side, never from the request, or the button becomes a way to point at
-- an arbitrary business. A uuid pasted into Python would differ between local,
-- staging and production and would silently resolve to nothing (or worse, to
-- whatever row happened to take that id). A slug carried by the data travels
-- with the database, so every environment marks its OWN demo tenant.
--
-- UNIQUE so there can never be two rows claiming to be the demo — the login
-- route does `WHERE demo_slug = $1` and a second row would make which tenant a
-- visitor lands in depend on planner order.
--
-- Nullable, and NULL for every real business: this marks an exception, it is not
-- a property every tenant has. Partial unique index so the many NULLs do not
-- collide (in Postgres NULLs are distinct, but the partial index also keeps the
-- index tiny and states the intent).
--
-- Re-runnable: the migrate step replays every file on each boot, with no ledger.

ALTER TABLE businesses
  ADD COLUMN IF NOT EXISTS demo_slug text;

COMMENT ON COLUMN businesses.demo_slug IS
  'Non-NULL on the single public demo tenant only (see /auth/demo). NULL for every real business.';

CREATE UNIQUE INDEX IF NOT EXISTS ux_businesses_demo_slug
  ON businesses (demo_slug)
  WHERE demo_slug IS NOT NULL;

-- ============================================================================
-- Resolving the demo tenant BEFORE any tenant context exists.
--
-- `businesses` is RLS-protected, so `app_role` sees nothing until
-- `current_business_id()` is set — and at demo-login time it is not, because
-- deciding WHICH business to log into is the whole point of the call. A plain
-- SELECT therefore returns zero rows and the route 404s. (It did. This function
-- is the fix, not a precaution.)
--
-- Same tiny-definer pattern as `resolve_booking_slug` and `provision_owner`: it
-- bypasses RLS to answer exactly one question and nothing more. It returns only
-- the id and name of the row that has been explicitly marked as the demo, so it
-- cannot be steered at a real customer's data even if the caller controls the
-- argument — a non-demo business has demo_slug NULL and can never match.
--
-- SAFETY: search_path pinned; EXECUTE revoked from PUBLIC and granted only to
-- app_role. The caller then opens a normal tenant_connection, so every read
-- after this point is RLS-scoped exactly like an authenticated request.
-- ============================================================================

CREATE OR REPLACE FUNCTION resolve_demo_business(p_demo_slug text)
RETURNS TABLE (id uuid, name text)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT b.id, b.name
  FROM businesses b
  WHERE b.demo_slug = p_demo_slug
    AND b.demo_slug IS NOT NULL
    AND b.is_active
  LIMIT 1
$$;

REVOKE ALL ON FUNCTION resolve_demo_business(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION resolve_demo_business(text) TO app_role;
