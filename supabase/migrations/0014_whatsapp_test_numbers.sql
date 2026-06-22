-- ============================================================================
-- 0014_whatsapp_test_numbers.sql — owner's external test allow-list (M6a.1)
-- ----------------------------------------------------------------------------
-- WHAT: a per-business list of up to 5 phone numbers (each with an optional
-- label) that the owner may message from OTHER phones to drive the REAL bot
-- pipeline — exactly like the self-chat, but for external test numbers. Anyone
-- NOT on the list is ignored (silent). The webhook reads this table INSIDE
-- tenant_connection(business_id) (the business is already resolved server-side
-- via resolve_wa_account), so normal RLS applies — NO new SECURITY DEFINER fn.
--
-- ISOLATION + PRIVACY:
--   * business_id is the tenant key → RLS USING + WITH CHECK
--     (business_id = current_business_id()), mirroring whatsapp_connections
--     (0004). A tenant can only ever read/write rows for THEIR OWN business, and
--     writes can't be aimed at someone else's tenant (WITH CHECK).
--   * phone_number + label hold CIPHERTEXT only (bytea). The app encrypts them
--     before insert and decrypts on read (PII never stored or logged in clear).
--   * Same app_role grants as whatsapp_connections: SELECT/INSERT/UPDATE/DELETE
--     (the admin app, as app_role, manages the list; set_test_numbers replaces
--     all rows for the business). No gateway_role grant — the webhook reads it
--     through app_role inside the tenant connection.
--
-- ENABLE + FORCE RLS (defense in depth: applies even to the table owner; the
-- migrate superuser still BYPASSES RLS for seeding/admin). Idempotent:
-- CREATE TABLE IF NOT EXISTS, DROP POLICY IF EXISTS before CREATE, idempotent
-- REVOKE/GRANT. Ordered after 0013.
-- ============================================================================

-- The table: encrypted allow-list entries, cascade-deleted with the business.
CREATE TABLE IF NOT EXISTS whatsapp_test_numbers (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id  uuid NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  phone_number bytea NOT NULL,                      -- 🔒 ciphertext: normalized digits
  label        bytea,                               -- 🔒 ciphertext: optional name (nullable)
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- Membership lookups + the "replace all rows for this business" write both scan
-- by business_id; index it (the PK already covers id).
CREATE INDEX IF NOT EXISTS ix_wa_test_numbers_business
  ON whatsapp_test_numbers(business_id);

-- ----- RLS: tenant isolation (mirror whatsapp_connections / 0004) --------- --
ALTER TABLE whatsapp_test_numbers ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_test_numbers FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON whatsapp_test_numbers;
CREATE POLICY p_tenant_isolation ON whatsapp_test_numbers
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

-- ----- Grants: same as whatsapp_connections for app_role ------------------ --
-- Clean slate so re-runs can't accumulate stray grants, then grant the four the
-- admin app needs. No gateway_role grant (read happens as app_role in-tenant).
REVOKE ALL ON whatsapp_test_numbers FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_test_numbers TO app_role;
