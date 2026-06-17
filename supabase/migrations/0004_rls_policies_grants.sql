-- ============================================================================
-- 0004_rls_policies_grants.sql — turn the wall ON
-- ----------------------------------------------------------------------------
-- Two fences, applied together (RLS is never bolted on later):
--   (A) ROW-LEVEL SECURITY on every tenant table: USING (read) + WITH CHECK
--       (write) on `business_id = current_business_id()`. WITH CHECK is what
--       stops a tenant from INSERTing/UPDATing a row into someone else's tenant.
--   (B) LEAST-PRIVILEGE GRANTS: app_role gets the tenant tables it needs but
--       has ZERO grant on whatsapp_credentials (not even SELECT). gateway_role
--       is the ONLY role that can touch whatsapp_credentials.
--
-- ENABLE + FORCE: FORCE makes RLS apply even to a table's owner (defense in
-- depth). The migrate runner is the superuser and BYPASSES RLS — that is how
-- seeding/admin works; the app connects as app_role/gateway_role where RLS is
-- live. Idempotent: DROP POLICY IF EXISTS before CREATE; GRANTs are idempotent.
-- ============================================================================

-- ----- (A) RLS policies --------------------------------------------------- --

-- businesses: the tenant key here is `id` (this row IS the business).
ALTER TABLE businesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE businesses FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON businesses;
CREATE POLICY p_tenant_isolation ON businesses
  USING (id = current_business_id())
  WITH CHECK (id = current_business_id());

-- All other tenant tables isolate on the `business_id` column.
ALTER TABLE business_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_members FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON business_members;
CREATE POLICY p_tenant_isolation ON business_members
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

ALTER TABLE whatsapp_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_connections FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON whatsapp_connections;
CREATE POLICY p_tenant_isolation ON whatsapp_connections
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

ALTER TABLE whatsapp_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_credentials FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON whatsapp_credentials;
CREATE POLICY p_tenant_isolation ON whatsapp_credentials
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

ALTER TABLE bot_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_settings FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON bot_settings;
CREATE POLICY p_tenant_isolation ON bot_settings
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON leads;
CREATE POLICY p_tenant_isolation ON leads
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

ALTER TABLE bot_builder_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE bot_builder_messages FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON bot_builder_messages;
CREATE POLICY p_tenant_isolation ON bot_builder_messages
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

ALTER TABLE flow_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE flow_events FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON flow_events;
CREATE POLICY p_tenant_isolation ON flow_events
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

-- ----- (B) Least-privilege grants ----------------------------------------- --
-- Start from a clean slate so re-runs can't accumulate stray grants, then grant
-- exactly what each role needs. (REVOKE ALL is harmless on the first run.)

-- users (GLOBAL, no RLS): the app reads/creates/updates the login identity.
REVOKE ALL ON users FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE ON users TO app_role;

-- businesses: the app reads/updates its own business (creation = signup/admin).
REVOKE ALL ON businesses FROM app_role, gateway_role;
GRANT SELECT, UPDATE ON businesses TO app_role;

-- business_members: the app reads it to verify ownership.
REVOKE ALL ON business_members FROM app_role, gateway_role;
GRANT SELECT ON business_members TO app_role;

-- whatsapp_connections: the app reads/updates status; the gateway owns the row.
REVOKE ALL ON whatsapp_connections FROM app_role, gateway_role;
GRANT SELECT, UPDATE ON whatsapp_connections TO app_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_connections TO gateway_role;

-- whatsapp_credentials: CROWN JEWEL. gateway_role ONLY. app_role gets NOTHING.
REVOKE ALL ON whatsapp_credentials FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_credentials TO gateway_role;

-- bot_settings / leads / bot_builder_messages / flow_events: app CRUD.
REVOKE ALL ON bot_settings         FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON bot_settings TO app_role;
REVOKE ALL ON leads                FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON leads TO app_role;
REVOKE ALL ON bot_builder_messages FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON bot_builder_messages TO app_role;
REVOKE ALL ON flow_events          FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON flow_events TO app_role;
