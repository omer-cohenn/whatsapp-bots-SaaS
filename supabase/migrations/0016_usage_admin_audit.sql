-- ============================================================================
-- 0016_usage_admin_audit.sql — M12 back-office: usage counters + admin audit log
-- ----------------------------------------------------------------------------
-- Source of truth: docs/decisions/0016-m12-back-office.md.
-- Two new tables, each isolated the right way for its purpose:
--
--   * usage_daily  — a TENANT table of pure counters (zero content, zero PII).
--                    Each business bumps ONLY its own row, so it gets the SAME
--                    forced-RLS treatment as every other tenant table (0004):
--                    ENABLE + FORCE + USING/WITH CHECK on business_id. app_role
--                    gets SELECT/INSERT/UPDATE so `usage.bump()` can UPSERT +1;
--                    RLS guarantees A can never bump B. The admin reads ACROSS
--                    tenants only via the SD functions in 0017 (which bypass RLS
--                    by running as the owner) — not through this grant.
--                    Metrics (free text, no enum): msg_in · msg_out · lead ·
--                    booking · login.
--
--   * admin_audit  — the accountability trail for every admin action. Written
--                    ONLY by admin_set_subscription (a SD function that runs as
--                    the owner), so there is NO direct app_role grant — exactly
--                    like subscriptions in 0015. No RLS: it is a global,
--                    operator-only log, never reachable on a tenant connection.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS / DROP POLICY IF EXISTS before CREATE /
-- idempotent REVOKE+GRANT. Safe to re-run.
-- ============================================================================

-- 1) usage_daily — per-business, per-day, per-metric counter. PURE NUMBERS.
CREATE TABLE IF NOT EXISTS usage_daily (
  business_id uuid   NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  day         date   NOT NULL,
  metric      text   NOT NULL,                         -- msg_in/msg_out/lead/booking/login
  count       bigint NOT NULL DEFAULT 0,
  PRIMARY KEY (business_id, day, metric)
);

-- Tenant wall ON (same two fences as every tenant table in 0004/0009).
ALTER TABLE usage_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_daily FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON usage_daily;
CREATE POLICY p_tenant_isolation ON usage_daily
  USING (business_id = current_business_id())
  WITH CHECK (business_id = current_business_id());

-- app_role: read + bump its OWN counters (RLS enforces "own"). No DELETE — the
-- app never deletes counters. gateway_role gets nothing here.
REVOKE ALL ON usage_daily FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE ON usage_daily TO app_role;

-- 2) admin_audit — operator action log. Global (no tenant key, no RLS). Written
--    ONLY by the admin SD function (runs as owner) → NO direct app_role grant.
CREATE TABLE IF NOT EXISTS admin_audit (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  admin_user_id      text REFERENCES users(id) ON DELETE SET NULL,
  admin_email        text,
  action             text NOT NULL,                    -- e.g. 'set_subscription'
  target_business_id uuid,                             -- which business was acted on
  detail             jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_admin_audit_created ON admin_audit(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_admin_audit_target  ON admin_audit(target_business_id);

-- No direct grant: only the SD writer touches this table.
REVOKE ALL ON admin_audit FROM app_role, gateway_role;
