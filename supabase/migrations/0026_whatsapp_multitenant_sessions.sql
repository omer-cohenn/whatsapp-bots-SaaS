-- ============================================================================
-- 0026_whatsapp_multitenant_sessions.sql — M6b data foundation
-- ----------------------------------------------------------------------------
-- M6b turns WhatsApp multi-tenant: one Baileys socket per business, each with
-- its own envelope-encrypted session in whatsapp_credentials (🔒🔒 CROWN JEWEL).
-- The backend grows an INTERNAL WhatsApp API the gateway calls to (a) discover
-- which businesses to open a socket for and (b) read/write each business's
-- encrypted auth_state. This migration lays the two data-layer pieces that API
-- sits on, WITHOUT ever loosening tenant isolation or the crown-jewel wall.
--
-- (1) CROWN-JEWEL RLS, RE-ASSERTED (idempotent, defense-in-depth).
--     0004 already ENABLE+FORCE'd RLS on whatsapp_credentials, added the
--     USING/WITH CHECK (business_id = current_business_id()) policy, and granted
--     it to gateway_role ONLY — app_role gets ZERO. We re-assert the exact same
--     posture here so the M6b foundation is self-contained and provably correct,
--     and so a future edit to 0004 can't silently drop the wall. The backend's
--     internal WA endpoints connect as gateway_role through the SAME
--     tenant_connection() helper (set_config('app.business_id', <id>, true)), so
--     current_business_id() is bound per transaction and every read/write is
--     scoped to that ONE business's row. No DELETE policy/grant is added on top
--     of 0004's baseline here: removal rides the ON DELETE CASCADE from
--     businesses. app_role is REVOKE'd again to make the "zero grant" explicit.
--
-- (2) wa_list_sessions() — the cross-tenant socket list.
--     The gateway (via an internal backend endpoint) must learn the FULL set of
--     businesses that have a WhatsApp connection so it can open one socket each.
--     That is inherently cross-tenant, but current_business_id() is a single
--     tenant — a normal RLS SELECT can never return more than one business's row.
--     So, exactly like resolve_wa_account (0013), we use one tightly-scoped
--     SECURITY DEFINER function that runs with the owner's rights (BYPASSES RLS)
--     and returns ONLY the business_id column for every business that has a
--     whatsapp_connections row. It exposes nothing else — no phone (🔒
--     ciphertext), no status, no auth_state, no PII of any kind.
--
-- SAFETY (matches 0013):
--   * SECURITY DEFINER + SET search_path = public, pg_temp (definer hygiene).
--   * EXECUTE revoked from PUBLIC, granted only to app_role.
-- Idempotent: ALTER ... ENABLE/FORCE + DROP POLICY IF EXISTS before CREATE;
--             CREATE OR REPLACE FUNCTION; idempotent REVOKE/GRANT.
-- ============================================================================

-- ----- (1) whatsapp_credentials — re-assert the crown-jewel wall ----------- --
ALTER TABLE whatsapp_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_credentials FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON whatsapp_credentials;
CREATE POLICY p_tenant_isolation ON whatsapp_credentials
  USING (business_id = current_business_id())         -- read: only my own row
  WITH CHECK (business_id = current_business_id());    -- write: only INTO my own row

-- CROWN JEWEL grants: gateway_role ONLY. app_role gets NOTHING (not even SELECT).
REVOKE ALL ON whatsapp_credentials FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_credentials TO gateway_role;

-- ----- (2) wa_list_sessions() — cross-tenant list of connected businesses --- --
CREATE OR REPLACE FUNCTION wa_list_sessions()
RETURNS SETOF uuid
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT business_id
  FROM whatsapp_connections
$$;

REVOKE ALL ON FUNCTION wa_list_sessions() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION wa_list_sessions() TO app_role;
