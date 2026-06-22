-- ============================================================================
-- 0013_whatsapp_account_resolve.sql — gateway_account_id → business_id (M6a)
-- ----------------------------------------------------------------------------
-- THE PROBLEM (mirrors 0010's slug bootstrap): the inbound webhook
-- (POST /webhook/whatsapp) is PUBLIC — the gateway calls it with only a shared
-- service token, NOT a user session. So there is no tenant context yet
-- (`app.business_id` / current_business_id() is unset). To learn WHICH business
-- a `gateway_account_id` belongs to we must read whatsapp_connections, which has
-- RLS FORCED (0004) under app_role → a plain SELECT returns 0 rows. The inbound
-- path can't even discover the tenant it should write as.
--
-- THE FIX: ONE tiny SECURITY DEFINER function, resolve_wa_account(account_id),
-- that runs with the owner's rights (BYPASSES RLS) and returns ONLY the
-- business_id mapped to that exact gateway account (or NULL). It exposes nothing
-- else — no phone (🔒 ciphertext), no status, no other tenant data. The webhook
-- calls it FIRST to learn the tenant, then opens a normal tenant_connection
-- bound to that business_id so EVERY subsequent read/write (run_turn's leads +
-- funnel) is RLS-scoped exactly like an authenticated request. Same pattern as
-- resolve_booking_slug / provision_owner: a minimal definer used ONLY to
-- bootstrap the tenant context that RLS then enforces.
--
-- SAFETY:
--   * SET search_path = public, pg_temp (standard SECURITY DEFINER hygiene).
--   * EXECUTE revoked from PUBLIC, granted only to app_role.
--   * Returns a single uuid (or NULL) — the account id is the gateway's own,
--     server-side routing key, never a client-chosen value.
-- Idempotent: CREATE OR REPLACE + idempotent REVOKE/GRANT.
-- ============================================================================

CREATE OR REPLACE FUNCTION resolve_wa_account(p_account_id text)
RETURNS uuid
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT business_id
  FROM whatsapp_connections
  WHERE gateway_account_id = p_account_id
  LIMIT 1
$$;

REVOKE ALL ON FUNCTION resolve_wa_account(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION resolve_wa_account(text) TO app_role;


-- ----------------------------------------------------------------------------
-- app_role INSERT on whatsapp_connections — the owner records the mapping (M6a).
-- ----------------------------------------------------------------------------
-- Originally (0004) only gateway_role could INSERT a connection row; app_role
-- had SELECT+UPDATE (read/update status only). M6a's owner-driven "Link" flow
-- (POST /api/whatsapp/link) must CREATE the business_id ↔ gateway_account_id
-- mapping from the admin app, which connects as app_role. We add INSERT here.
--
-- This does NOT widen tenant isolation: the row stays under the SAME forced RLS
-- policy (USING + WITH CHECK business_id = current_business_id()), so an owner
-- can only ever insert a row for THEIR OWN business, and the upsert runs inside
-- tenant_connection so app.business_id is the verified session tenant. The
-- crown-jewel whatsapp_credentials table is untouched — app_role still gets
-- NOTHING there.
GRANT INSERT ON whatsapp_connections TO app_role;
