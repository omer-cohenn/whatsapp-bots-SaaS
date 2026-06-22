-- ============================================================================
-- 0017_admin_functions.sql — M12 back-office: the five admin SD functions
-- ----------------------------------------------------------------------------
-- Source of truth: docs/decisions/0016-m12-back-office.md.
--
-- THE PROBLEM: the platform operator (Omer) must see and manage EVERY business
-- at once — created/last-login, plan, status, leads, message volume — and flip a
-- subscription. The backend connects as app_role, which has RLS FORCED on every
-- tenant table (0004/0009/0016). A plain cross-tenant read under app_role returns
-- 0 rows. There is no single tenant context for an "all businesses" view.
--
-- THE FIX (same pattern as 0005 provision_owner / 0010 resolve_booking_slug /
-- 0013 resolve_wa_account): a SMALL set of SECURITY DEFINER functions that run
-- with the OWNER's rights and therefore BYPASS RLS by design. They intentionally
-- span all tenants — that is the whole point of the back-office. The ONLY guard
-- is the application's admin gate (deps.current_admin → ADMIN_EMAILS), which is
-- where these functions are called from, exactly like provision_owner is reached
-- only from the login callback. They expose aggregates + identity fields the
-- operator needs; they never touch the crown-jewel whatsapp_credentials and never
-- return lead/booking PII (which is ciphertext anyway).
--
-- SAFETY (every function below):
--   * SECURITY DEFINER + SET search_path = public, pg_temp (definer hygiene).
--   * REVOKE ALL FROM PUBLIC, then GRANT EXECUTE TO app_role only.
--   * Read functions are STABLE; the mutating one is plpgsql + atomic.
-- Idempotent: CREATE OR REPLACE + idempotent REVOKE/GRANT. Safe to re-run.
--
-- NOTE: tenant tables keep their forced RLS untouched. subscriptions/admin_audit
-- keep their zero-app_role-grant. This file adds the ONLY sanctioned doorway.
-- ============================================================================


-- ----- 1) admin_overview() -------------------------------------------------- --
-- Platform-wide KPI strip (single row). active/suspended/cancelled are derived
-- from subscriptions; a business with NO subscription row counts as 'active'
-- (the default state), so we COALESCE the status before bucketing. total_leads
-- and message volume exclude test traffic / use only the usage counters.
CREATE OR REPLACE FUNCTION admin_overview()
RETURNS TABLE(
  total_businesses bigint,
  active_count     bigint,
  suspended_count  bigint,
  cancelled_count  bigint,
  new_7d           bigint,
  total_leads      bigint,
  msgs_today       bigint,
  msgs_month       bigint
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT
    (SELECT count(*) FROM businesses)                                       AS total_businesses,
    (SELECT count(*) FROM businesses b
       WHERE coalesce((SELECT s.status FROM subscriptions s
                         WHERE s.business_id = b.id), 'active') = 'active')  AS active_count,
    (SELECT count(*) FROM subscriptions s WHERE s.status = 'suspended')      AS suspended_count,
    (SELECT count(*) FROM subscriptions s WHERE s.status = 'cancelled')      AS cancelled_count,
    (SELECT count(*) FROM businesses
       WHERE created_at >= now() - interval '7 days')                        AS new_7d,
    (SELECT count(*) FROM leads WHERE NOT is_test)                           AS total_leads,
    (SELECT coalesce(sum(count), 0) FROM usage_daily
       WHERE metric IN ('msg_in', 'msg_out')
         AND day = current_date)                                            AS msgs_today,
    (SELECT coalesce(sum(count), 0) FROM usage_daily
       WHERE metric IN ('msg_in', 'msg_out')
         AND day >= date_trunc('month', current_date)::date)               AS msgs_month
$$;

REVOKE ALL ON FUNCTION admin_overview() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_overview() TO app_role;


-- ----- 2) admin_list_businesses(p_search, p_limit, p_offset) ---------------- --
-- The businesses table: one row per business with owner identity, plan/status,
-- and rolled-up activity. owner = the 'owner' member, falling back to the
-- earliest member (LATERAL pick). plan/status default to 'free'/'active' when no
-- subscription row exists. Search is case-insensitive over business name OR owner
-- email. limit is clamped to 1..200 (default 50); offset floored at 0.
CREATE OR REPLACE FUNCTION admin_list_businesses(
  p_search text,
  p_limit  int,
  p_offset int
)
RETURNS TABLE(
  business_id   uuid,
  name          text,
  owner_email   text,
  created_at    timestamptz,
  last_login_at timestamptz,
  plan_code     text,
  status        text,
  is_active     boolean,
  leads_count   bigint,
  msgs_30d      bigint
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT
    b.id,
    b.name,
    owner.email,
    b.created_at,
    owner.last_login_at,
    coalesce(s.plan_code, 'free')   AS plan_code,
    coalesce(s.status, 'active')    AS status,
    b.is_active,
    (SELECT count(*) FROM leads l
       WHERE l.business_id = b.id AND NOT l.is_test)        AS leads_count,
    (SELECT coalesce(sum(u.count), 0) FROM usage_daily u
       WHERE u.business_id = b.id
         AND u.metric IN ('msg_in', 'msg_out')
         AND u.day >= current_date - 30)                    AS msgs_30d
  FROM businesses b
  LEFT JOIN subscriptions s ON s.business_id = b.id
  LEFT JOIN LATERAL (
    SELECT u.email, u.last_login_at
    FROM business_members m
    JOIN users u ON u.id = m.user_id
    WHERE m.business_id = b.id
    ORDER BY (m.role = 'owner') DESC, m.created_at ASC
    LIMIT 1
  ) owner ON true
  WHERE
    p_search IS NULL
    OR btrim(p_search) = ''
    OR b.name ILIKE '%' || btrim(p_search) || '%'
    OR owner.email ILIKE '%' || btrim(p_search) || '%'
  ORDER BY b.created_at DESC
  LIMIT  least(greatest(coalesce(p_limit, 50), 1), 200)
  OFFSET greatest(coalesce(p_offset, 0), 0)
$$;

REVOKE ALL ON FUNCTION admin_list_businesses(text, int, int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_list_businesses(text, int, int) TO app_role;


-- ----- 3) admin_business_detail(p_business_id) ------------------------------ --
-- The single-business profile: the list row PLUS business_type and the WhatsApp
-- connection status (default 'disconnected' when no connection row exists). Same
-- owner-pick + COALESCE defaults as the list function.
CREATE OR REPLACE FUNCTION admin_business_detail(p_business_id uuid)
RETURNS TABLE(
  business_id   uuid,
  name          text,
  business_type text,
  owner_email   text,
  created_at    timestamptz,
  last_login_at timestamptz,
  plan_code     text,
  status        text,
  is_active     boolean,
  wa_status     text,
  leads_count   bigint,
  msgs_30d      bigint
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT
    b.id,
    b.name,
    b.business_type,
    owner.email,
    b.created_at,
    owner.last_login_at,
    coalesce(s.plan_code, 'free')   AS plan_code,
    coalesce(s.status, 'active')    AS status,
    b.is_active,
    coalesce(wc.status, 'disconnected') AS wa_status,
    (SELECT count(*) FROM leads l
       WHERE l.business_id = b.id AND NOT l.is_test)        AS leads_count,
    (SELECT coalesce(sum(u.count), 0) FROM usage_daily u
       WHERE u.business_id = b.id
         AND u.metric IN ('msg_in', 'msg_out')
         AND u.day >= current_date - 30)                    AS msgs_30d
  FROM businesses b
  LEFT JOIN subscriptions s        ON s.business_id  = b.id
  LEFT JOIN whatsapp_connections wc ON wc.business_id = b.id
  LEFT JOIN LATERAL (
    SELECT u.email, u.last_login_at
    FROM business_members m
    JOIN users u ON u.id = m.user_id
    WHERE m.business_id = b.id
    ORDER BY (m.role = 'owner') DESC, m.created_at ASC
    LIMIT 1
  ) owner ON true
  WHERE b.id = p_business_id
$$;

REVOKE ALL ON FUNCTION admin_business_detail(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_business_detail(uuid) TO app_role;


-- ----- 4) admin_usage_series(p_business_id, p_from, p_to) ------------------- --
-- Raw daily counters for one business over a date range, for the usage charts.
-- The range is guarded INSIDE: NULLs default to a sane 30-day window ending
-- today; if to < from the bounds are swapped; the span is capped at 92 days
-- (matches the API contract's ≤ ~92-day window) so a single call can't scan
-- unbounded history.
CREATE OR REPLACE FUNCTION admin_usage_series(
  p_business_id uuid,
  p_from        date,
  p_to          date
)
RETURNS TABLE(
  day    date,
  metric text,
  count  bigint
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  WITH bounds AS (
    SELECT
      least(coalesce(p_from, current_date - 30),
            coalesce(p_to,   current_date))            AS lo,
      greatest(coalesce(p_from, current_date - 30),
               coalesce(p_to,   current_date))         AS hi
  ),
  capped AS (
    -- cap the span at 92 days, measured back from the high end.
    SELECT greatest(lo, hi - 92) AS lo, hi FROM bounds
  )
  SELECT u.day, u.metric, u.count
  FROM usage_daily u, capped c
  WHERE u.business_id = p_business_id
    AND u.day >= c.lo
    AND u.day <= c.hi
  ORDER BY u.day ASC, u.metric ASC
$$;

REVOKE ALL ON FUNCTION admin_usage_series(uuid, date, date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_usage_series(uuid, date, date) TO app_role;


-- ----- 5) admin_set_subscription(...) --------------------------------------- --
-- The ONE write path. Atomic, in plpgsql: validate inputs, UPSERT the
-- subscription, sync businesses.is_active (active → true, otherwise false),
-- record an admin_audit row, return the new state. Bad plan_code/status raises
-- (the caller surfaces a 4xx). admin_user_id/admin_email come from the verified
-- admin session server-side — never from the client body.
CREATE OR REPLACE FUNCTION admin_set_subscription(
  p_admin_user_id text,
  p_admin_email   text,
  p_business_id   uuid,
  p_plan_code     text,
  p_status        text
)
RETURNS TABLE(
  business_id uuid,
  plan_code   text,
  status      text,
  is_active   boolean
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_is_active boolean;
BEGIN
  -- (a) validate status against the same set the CHECK constraint enforces.
  IF p_status IS NULL OR p_status NOT IN ('active', 'suspended', 'cancelled') THEN
    RAISE EXCEPTION 'invalid status: %', p_status
      USING ERRCODE = 'check_violation';
  END IF;

  -- (b) validate the plan exists in the catalog.
  IF NOT EXISTS (SELECT 1 FROM plans WHERE code = p_plan_code) THEN
    RAISE EXCEPTION 'unknown plan_code: %', p_plan_code
      USING ERRCODE = 'foreign_key_violation';
  END IF;

  -- (c) the business must exist (so the FK + audit target are meaningful).
  IF NOT EXISTS (SELECT 1 FROM businesses WHERE id = p_business_id) THEN
    RAISE EXCEPTION 'unknown business_id: %', p_business_id
      USING ERRCODE = 'foreign_key_violation';
  END IF;

  v_is_active := (p_status = 'active');

  -- (d) UPSERT the subscription row. NOTE: this RETURNS TABLE declares an OUT
  -- column also named business_id, so a bare `ON CONFLICT (business_id)` is
  -- ambiguous (OUT var vs table column). Target the PK by its constraint name
  -- to avoid the bare column reference entirely.
  INSERT INTO subscriptions (business_id, plan_code, status)
  VALUES (p_business_id, p_plan_code, p_status)
  ON CONFLICT ON CONSTRAINT subscriptions_pkey DO UPDATE
    SET plan_code  = EXCLUDED.plan_code,
        status     = EXCLUDED.status,
        updated_at = now();

  -- (e) sync the suspend switch — suspended/cancelled silence the bot.
  UPDATE businesses
    SET is_active = v_is_active
    WHERE id = p_business_id;

  -- (f) accountability trail.
  INSERT INTO admin_audit (admin_user_id, admin_email, action, target_business_id, detail)
  VALUES (
    p_admin_user_id,
    p_admin_email,
    'set_subscription',
    p_business_id,
    jsonb_build_object('plan_code', p_plan_code, 'status', p_status)
  );

  -- (g) return the new state.
  RETURN QUERY
    SELECT p_business_id, p_plan_code, p_status, v_is_active;
END
$$;

REVOKE ALL ON FUNCTION admin_set_subscription(text, text, uuid, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_set_subscription(text, text, uuid, text, text) TO app_role;
