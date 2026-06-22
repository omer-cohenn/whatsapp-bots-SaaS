-- ============================================================================
-- 0015_admin_plans_subscriptions.sql — M12 back-office: catalog + billing state
-- ----------------------------------------------------------------------------
-- Source of truth: docs/decisions/0016-m12-back-office.md (the frozen contract).
-- This is the FIRST of three migrations for the platform-operator admin panel —
-- the ONE surface that deliberately crosses the tenant wall. NOTHING here weakens
-- an existing tenant table's RLS.
--
-- Two new tables + one column:
--   * plans            — a GLOBAL catalog of subscription plans (free/basic/pro).
--                        Has NO business_id and NO RLS — it is non-sensitive
--                        reference data every tenant may read (e.g. a dropdown).
--                        app_role gets SELECT only.
--   * subscriptions    — one row per business (PK = business_id). Holds the
--                        manually-managed plan + status (no Stripe yet). app_role
--                        gets NO direct CRUD: it is read/written ONLY through the
--                        admin SECURITY DEFINER functions in 0017 (same isolation
--                        idea as whatsapp_credentials — reachable only by a
--                        privileged path, never by a normal tenant query).
--   * businesses.is_active — the suspend switch. `admin_set_subscription` keeps
--                        it in sync with status (active → true, otherwise false);
--                        the bot pipeline reads it to go SILENT for a suspended
--                        business. The businesses RLS policy (0004) lets a bot
--                        read its OWN row, so it can see its own is_active.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS /
-- INSERT ... ON CONFLICT DO NOTHING / DROP TRIGGER IF EXISTS before CREATE /
-- idempotent REVOKE+GRANT. Safe to re-run.
-- ============================================================================

-- 1) plans — GLOBAL catalog (no tenant key, no RLS). Reference data only.
CREATE TABLE IF NOT EXISTS plans (
  code        text PRIMARY KEY,                       -- 'free' / 'basic' / 'pro'
  name        text NOT NULL,                          -- display label (Hebrew default)
  price       numeric(10,2) NOT NULL DEFAULT 0,       -- monthly price; 0 = free
  sort_order  int NOT NULL DEFAULT 0,                 -- display ordering in the UI
  limits      jsonb NOT NULL DEFAULT '{}'::jsonb,     -- soft caps (msgs/leads/…), v1 unused
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Seed the three default plans. Names are Hebrew defaults Omer can edit later;
-- ON CONFLICT DO NOTHING means re-runs never clobber edited rows.
INSERT INTO plans (code, name, price, sort_order) VALUES
  ('free',  'חינם',    0,    0),
  ('basic', 'בסיסי',   49,   1),
  ('pro',   'מקצועי',  149,  2)
ON CONFLICT (code) DO NOTHING;

-- 2) subscriptions — one row per business. Manually managed (no billing yet).
--    PK = business_id → exactly one subscription per tenant. NO RLS, NO direct
--    app_role grant: accessed only via the admin SD functions (0017).
CREATE TABLE IF NOT EXISTS subscriptions (
  business_id        uuid PRIMARY KEY REFERENCES businesses(id) ON DELETE CASCADE,
  plan_code          text NOT NULL REFERENCES plans(code) DEFAULT 'free',
  status             text NOT NULL DEFAULT 'active',
  started_at         timestamptz NOT NULL DEFAULT now(),
  current_period_end timestamptz,                      -- nullable; for future Stripe
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT subscriptions_status_chk
    CHECK (status IN ('active', 'suspended', 'cancelled'))
);

-- keep updated_at fresh on every UPDATE (same helper as 0003's tenant tables).
DROP TRIGGER IF EXISTS trg_subscriptions_updated ON subscriptions;
CREATE TRIGGER trg_subscriptions_updated BEFORE UPDATE ON subscriptions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 3) businesses.is_active — the suspend switch (additive, defaults true so every
--    existing business stays live until an admin explicitly suspends it).
ALTER TABLE businesses ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;

-- ----- Grants ------------------------------------------------------------- --
-- plans: non-sensitive catalog → app_role may read it (dropdown / display).
REVOKE ALL ON plans FROM app_role, gateway_role;
GRANT SELECT ON plans TO app_role;

-- subscriptions: NO direct grant to app_role or gateway_role. The admin SD
-- functions in 0017 run as the table owner and are the ONLY way in. REVOKE ALL
-- is harmless on the first run and keeps re-runs from accumulating stray grants.
REVOKE ALL ON subscriptions FROM app_role, gateway_role;
