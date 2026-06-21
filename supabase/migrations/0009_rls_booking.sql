-- ============================================================================
-- 0009_rls_booking.sql — turn the wall ON for the booking tables (M11)
-- ----------------------------------------------------------------------------
-- Same two fences as 0004, applied to the four new booking tables:
--   (A) ROW-LEVEL SECURITY on every tenant table: USING (read) + WITH CHECK
--       (write) on `business_id = current_business_id()`. WITH CHECK is what
--       stops a tenant from INSERTing/UPDATing a row into someone else's tenant.
--       NOTE: the PUBLIC booking endpoints have NO session → they resolve the
--       business from the verified slug and set app.business_id server-side, so
--       these RLS predicates still apply to public reads/writes too.
--   (B) LEAST-PRIVILEGE GRANTS: app_role gets full CRUD on all four; gateway_role
--       gets NOTHING (the gateway never touches booking data).
--
-- ENABLE + FORCE: FORCE makes RLS apply even to the table's owner. The migrate
-- runner is the superuser and BYPASSES RLS — that's how seeding works; the app
-- connects as app_role where RLS is live. Idempotent: DROP POLICY IF EXISTS
-- before CREATE; REVOKE/GRANT are idempotent.
-- ============================================================================

-- ----- (A) RLS policies --------------------------------------------------- --

ALTER TABLE booking_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE booking_settings FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON booking_settings;
CREATE POLICY p_tenant_isolation ON booking_settings
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

ALTER TABLE services ENABLE ROW LEVEL SECURITY;
ALTER TABLE services FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON services;
CREATE POLICY p_tenant_isolation ON services
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

ALTER TABLE bookings ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookings FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON bookings;
CREATE POLICY p_tenant_isolation ON bookings
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

ALTER TABLE google_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE google_credentials FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON google_credentials;
CREATE POLICY p_tenant_isolation ON google_credentials
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

-- ----- (B) Least-privilege grants ----------------------------------------- --
-- Start from a clean slate so re-runs can't accumulate stray grants, then grant
-- exactly what app_role needs. gateway_role gets nothing on booking data.

REVOKE ALL ON booking_settings   FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON booking_settings TO app_role;
REVOKE ALL ON services           FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON services TO app_role;
REVOKE ALL ON bookings           FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON bookings TO app_role;
REVOKE ALL ON google_credentials FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON google_credentials TO app_role;
