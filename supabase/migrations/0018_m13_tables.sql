-- ============================================================================
-- 0018_m13_tables.sql — M13 back-office analytics + sales CRM: the three tables
-- ----------------------------------------------------------------------------
-- Source of truth: docs/decisions/0017-m13-backoffice-analytics-crm.md (frozen).
-- This EXTENDS M12 (0015/0016/0017). It changes / drops NOTHING from M12.
--
-- Three new tables, all PLATFORM-OPERATOR (cross-tenant) data. Same isolation
-- model as subscriptions / admin_audit (0015/0016): NO direct app_role grant.
-- They are reachable ONLY through the tightly-scoped admin SECURITY DEFINER
-- functions in 0019/0020 (which run as the table owner and so bypass RLS by
-- design), behind the application's admin gate. A plain app_role connection gets
-- "permission denied" on a direct SELECT — verified at the end of this milestone.
--
--   * platform_snapshots — one row PER DAY of platform-wide aggregates
--                          (total/active/paid/MRR/churn). Gives the trend graphs
--                          real history: there is no scheduler, so the backend
--                          upserts today's row on every GET /api/admin/overview
--                          (admin_upsert_today_snapshot, 0020). It accrues from
--                          today forward — past days cannot be reconstructed.
--   * business_crm       — the platform sales pipeline: ONE row per business with
--                          a stage (new→contacted→warming→won/lost), the last
--                          contact time, and a follow-up reminder. Operator-only.
--   * crm_notes          — the per-business action log (free-text notes by the
--                          admin). Carries the admin's identity, never end-customer
--                          PII. Operator-only.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
-- DROP TRIGGER IF EXISTS before CREATE / idempotent REVOKE. Safe to re-run.
-- ============================================================================

-- 1) platform_snapshots — daily platform aggregates (trend history).
--    PK = day → exactly one snapshot per calendar day (idempotent upsert).
--    Global, operator-only: no business_id, no RLS, no app_role grant.
CREATE TABLE IF NOT EXISTS platform_snapshots (
  day              date PRIMARY KEY,
  total_businesses int           NOT NULL DEFAULT 0,
  active_count     int           NOT NULL DEFAULT 0,    -- businesses.is_active = true
  paid_count       int           NOT NULL DEFAULT 0,    -- active non-free subscriptions
  mrr              numeric(12,2) NOT NULL DEFAULT 0,     -- sum of paid plan prices
  churn_count      int           NOT NULL DEFAULT 0,    -- suspended/cancelled subscriptions
  created_at       timestamptz   NOT NULL DEFAULT now()
);

-- 2) business_crm — the sales pipeline, one row per business. Operator-only.
--    stage is constrained to the 5 pipeline columns; defaults to 'new' so a brand
--    new business appears in the board with no setup. last/next timestamps drive
--    the follow-up reminders. updated_at kept fresh by the shared trigger.
CREATE TABLE IF NOT EXISTS business_crm (
  business_id        uuid PRIMARY KEY REFERENCES businesses(id) ON DELETE CASCADE,
  stage              text        NOT NULL DEFAULT 'new'
    CHECK (stage IN ('new', 'contacted', 'warming', 'won', 'lost')),
  last_contacted_at  timestamptz,
  next_followup_at   timestamptz,
  updated_at         timestamptz NOT NULL DEFAULT now()
);

-- keep updated_at fresh on every UPDATE (same helper as 0003's tenant tables).
DROP TRIGGER IF EXISTS trg_business_crm_updated ON business_crm;
CREATE TRIGGER trg_business_crm_updated BEFORE UPDATE ON business_crm
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 3) crm_notes — per-business action log. Operator-only. admin_user_id is a soft
--    FK to users(id) (SET NULL on delete so history survives); admin_email is the
--    denormalized display label so the note still reads if the user row is gone.
CREATE TABLE IF NOT EXISTS crm_notes (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id   uuid        NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  admin_user_id text        REFERENCES users(id) ON DELETE SET NULL,
  admin_email   text,
  note          text        NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_crm_notes_business_created
  ON crm_notes(business_id, created_at DESC);

-- ----- Grants ------------------------------------------------------------- --
-- All three are operator-only: NO direct grant to app_role or gateway_role. The
-- admin SD functions in 0019/0020 run as the owner and are the ONLY way in
-- (exactly like subscriptions / admin_audit in M12). REVOKE ALL is harmless on
-- the first run and keeps re-runs from accumulating stray grants.
REVOKE ALL ON platform_snapshots FROM app_role, gateway_role;
REVOKE ALL ON business_crm        FROM app_role, gateway_role;
REVOKE ALL ON crm_notes           FROM app_role, gateway_role;
