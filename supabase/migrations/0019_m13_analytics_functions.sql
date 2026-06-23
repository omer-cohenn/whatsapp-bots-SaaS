-- ============================================================================
-- 0019_m13_analytics_functions.sql — M13 back-office: the analytics SD functions
-- ----------------------------------------------------------------------------
-- Source of truth: docs/decisions/0017-m13-backoffice-analytics-crm.md.
--
-- Same doorway pattern as M12's 0017: a small set of SECURITY DEFINER functions
-- that run with the OWNER's rights and so BYPASS RLS by design — they span all
-- tenants on purpose (the back-office is the ONE surface that crosses the tenant
-- wall). The only guard is the application's admin gate (deps.current_admin →
-- ADMIN_EMAILS), exactly like the M12 admin_* functions. They return aggregates
-- only — never lead/booking PII (which is ciphertext anyway), never the crown
-- jewel. These are ADDITIVE: they do NOT touch any M12 function.
--
-- SAFETY (every function below, mirroring 0017):
--   * SECURITY DEFINER + SET search_path = public, pg_temp.
--   * REVOKE ALL FROM PUBLIC, then GRANT EXECUTE TO app_role only.
--   * Read-only → LANGUAGE sql STABLE.
-- Idempotent: CREATE OR REPLACE + idempotent REVOKE/GRANT. Safe to re-run.
--
-- LEAD-TYPE TAXONOMY (decision 0017 §"הלוגיקה"):
--   * booking  = a row in bookings.
--   * handoff  = a lead with a flow_events.event='handed_off' row (the runtime
--                also names that lead 'פנייה לנציג' — bot_runtime.py).
--   * lead     = every OTHER non-test lead: NOT a handoff lead, i.e. lead_name is
--                not 'פנייה לנציג' AND it has no handed_off event.
--   is_test traffic is excluded EVERYWHERE.
-- ============================================================================


-- ----- 1) admin_leads_by_type(p_period, p_plan) ----------------------------- --
-- The donut: how many of each lead type across the platform, for a period and an
-- optional plan filter. p_period ∈ 'week'|'month'|'all' picks the time window per
-- table (bookings.created_at, leads.started_at, flow_events.created_at). p_plan ∈
-- a plan code or 'all' filters businesses by COALESCE(subscriptions.plan_code,
-- 'free'). Anything outside the vocab falls back to the widest sane default
-- ('all' window, all plans).
CREATE OR REPLACE FUNCTION admin_leads_by_type(p_period text, p_plan text)
RETURNS TABLE(
  booking_count bigint,
  lead_count    bigint,
  handoff_count bigint
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  WITH win AS (
    -- the lower bound for the chosen period; NULL = no lower bound ('all').
    SELECT CASE lower(coalesce(p_period, 'all'))
             WHEN 'week'  THEN (current_date - 7)::timestamptz
             WHEN 'month' THEN date_trunc('month', current_date)
             ELSE NULL
           END AS lo
  ),
  -- the set of businesses that match the plan filter (default-plan aware).
  scoped AS (
    SELECT b.id
    FROM businesses b
    LEFT JOIN subscriptions s ON s.business_id = b.id
    WHERE coalesce(p_plan, 'all') = 'all'
       OR coalesce(s.plan_code, 'free') = p_plan
  ),
  -- handoff leads = leads that have a 'handed_off' flow event (non-test).
  handoff_leads AS (
    SELECT DISTINCT fe.lead_id
    FROM flow_events fe
    JOIN scoped sc ON sc.id = fe.business_id
    CROSS JOIN win
    WHERE fe.event = 'handed_off'
      AND fe.lead_id IS NOT NULL
      AND NOT fe.is_test
      AND (win.lo IS NULL OR fe.created_at >= win.lo)
  )
  SELECT
    (SELECT count(*)
       FROM bookings bk
       JOIN scoped sc ON sc.id = bk.business_id
       CROSS JOIN win
       WHERE NOT bk.is_test
         AND (win.lo IS NULL OR bk.created_at >= win.lo))            AS booking_count,
    (SELECT count(*)
       FROM leads l
       JOIN scoped sc ON sc.id = l.business_id
       CROSS JOIN win
       WHERE NOT l.is_test
         AND coalesce(l.lead_name, '') <> 'פנייה לנציג'
         AND l.id NOT IN (SELECT lead_id FROM handoff_leads)
         AND (win.lo IS NULL OR l.started_at >= win.lo))             AS lead_count,
    (SELECT count(*) FROM handoff_leads)                             AS handoff_count
$$;

REVOKE ALL ON FUNCTION admin_leads_by_type(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_leads_by_type(text, text) TO app_role;


-- ----- 2) admin_messages_by_business(p_period) ------------------------------ --
-- The BILLING view: total inbound/outbound message counts per business over the
-- period, joined to the business name + its plan. total = in + out, ordered by
-- total DESC. p_period ∈ 'week'|'month'|'all'. Businesses with zero messages in
-- the window are omitted (the SUM/GROUP BY only yields rows that have counters).
CREATE OR REPLACE FUNCTION admin_messages_by_business(p_period text)
RETURNS TABLE(
  business_id uuid,
  name        text,
  plan_code   text,
  msg_in      bigint,
  msg_out     bigint,
  total       bigint
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  WITH win AS (
    SELECT CASE lower(coalesce(p_period, 'all'))
             WHEN 'week'  THEN (current_date - 7)
             WHEN 'month' THEN date_trunc('month', current_date)::date
             ELSE NULL
           END AS lo
  )
  SELECT
    b.id                                                            AS business_id,
    b.name,
    coalesce(s.plan_code, 'free')                                   AS plan_code,
    coalesce(sum(u.count) FILTER (WHERE u.metric = 'msg_in'),  0)   AS msg_in,
    coalesce(sum(u.count) FILTER (WHERE u.metric = 'msg_out'), 0)   AS msg_out,
    coalesce(sum(u.count), 0)                                       AS total
  FROM usage_daily u
  CROSS JOIN win
  JOIN businesses b ON b.id = u.business_id
  LEFT JOIN subscriptions s ON s.business_id = b.id
  WHERE u.metric IN ('msg_in', 'msg_out')
    AND (win.lo IS NULL OR u.day >= win.lo)
  GROUP BY b.id, b.name, coalesce(s.plan_code, 'free')
  ORDER BY total DESC, b.name ASC
$$;

REVOKE ALL ON FUNCTION admin_messages_by_business(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_messages_by_business(text) TO app_role;


-- ----- 3) admin_ai_ops_series(p_from, p_to) --------------------------------- --
-- AI activity over time: daily SUM of usage_daily.count where metric='ai_call'
-- across ALL businesses, one row per day that has data. Range guarded INSIDE
-- exactly like 0017's admin_usage_series: NULLs → last 30 days; swap if to<from;
-- span capped at 92 days from the high end.
CREATE OR REPLACE FUNCTION admin_ai_ops_series(p_from date, p_to date)
RETURNS TABLE(
  day   date,
  count bigint
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
    SELECT greatest(lo, hi - 92) AS lo, hi FROM bounds
  )
  SELECT u.day, coalesce(sum(u.count), 0) AS count
  FROM usage_daily u, capped c
  WHERE u.metric = 'ai_call'
    AND u.day >= c.lo
    AND u.day <= c.hi
  GROUP BY u.day
  ORDER BY u.day ASC
$$;

REVOKE ALL ON FUNCTION admin_ai_ops_series(date, date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_ai_ops_series(date, date) TO app_role;


-- ----- 4) admin_by_plan(p_metric, p_period) --------------------------------- --
-- Slice ONE usage metric by plan: SUM(count) over the period grouped by
-- COALESCE(subscriptions.plan_code, 'free'). One row per plan that has data.
-- p_metric ∈ the usage vocabulary (msg_in/msg_out/lead/booking/login/ai_call);
-- p_period ∈ 'week'|'month'|'all'.
CREATE OR REPLACE FUNCTION admin_by_plan(p_metric text, p_period text)
RETURNS TABLE(
  plan_code text,
  value     bigint
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  WITH win AS (
    SELECT CASE lower(coalesce(p_period, 'all'))
             WHEN 'week'  THEN (current_date - 7)
             WHEN 'month' THEN date_trunc('month', current_date)::date
             ELSE NULL
           END AS lo
  )
  SELECT
    coalesce(s.plan_code, 'free') AS plan_code,
    coalesce(sum(u.count), 0)     AS value
  FROM usage_daily u
  CROSS JOIN win
  LEFT JOIN subscriptions s ON s.business_id = u.business_id
  WHERE u.metric = p_metric
    AND (win.lo IS NULL OR u.day >= win.lo)
  GROUP BY coalesce(s.plan_code, 'free')
  ORDER BY value DESC, plan_code ASC
$$;

REVOKE ALL ON FUNCTION admin_by_plan(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_by_plan(text, text) TO app_role;


-- ----- 5) admin_trends_series(p_from, p_to) --------------------------------- --
-- The trend graphs: the stored daily platform_snapshots rows in [from,to]. Same
-- range guard as admin_ai_ops_series (NULL→30d, swap, 92d cap). Returns history
-- exactly as snapshotted — past gaps cannot be filled (no scheduler before M13).
CREATE OR REPLACE FUNCTION admin_trends_series(p_from date, p_to date)
RETURNS TABLE(
  day              date,
  total_businesses int,
  active_count     int,
  paid_count       int,
  mrr              numeric,
  churn_count      int
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
    SELECT greatest(lo, hi - 92) AS lo, hi FROM bounds
  )
  SELECT ps.day, ps.total_businesses, ps.active_count,
         ps.paid_count, ps.mrr, ps.churn_count
  FROM platform_snapshots ps, capped c
  WHERE ps.day >= c.lo
    AND ps.day <= c.hi
  ORDER BY ps.day ASC
$$;

REVOKE ALL ON FUNCTION admin_trends_series(date, date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_trends_series(date, date) TO app_role;


-- ----- 6) admin_business_extra(p_business_id) ------------------------------- --
-- The BusinessDetail enrichment: an LTV ESTIMATE, all-time AI calls, and the
-- business's CRM state (defaults applied when no business_crm row exists yet).
--   ltv_estimate = plan price × months since subscription started (>= 1),
--                  free/no-subscription → 0. Clearly an ESTIMATE (no real billing
--                  yet). months = whole months between started_at and now, floored
--                  at 1 so a brand-new paid sub is worth at least one month.
--   ai_calls     = all-time SUM of usage_daily where metric='ai_call'.
--   crm_*        = LEFT JOIN business_crm, defaulting stage 'new' + null times.
CREATE OR REPLACE FUNCTION admin_business_extra(p_business_id uuid)
RETURNS TABLE(
  ltv_estimate      numeric,
  ai_calls          bigint,
  crm_stage         text,
  last_contacted_at timestamptz,
  next_followup_at  timestamptz
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT
    coalesce(p.price, 0)
      * greatest(
          1,
          (extract(year  FROM age(now(), coalesce(s.started_at, now())))::int * 12
           + extract(month FROM age(now(), coalesce(s.started_at, now())))::int)
        )                                                            AS ltv_estimate,
    (SELECT coalesce(sum(u.count), 0)
       FROM usage_daily u
       WHERE u.business_id = p_business_id
         AND u.metric = 'ai_call')                                  AS ai_calls,
    coalesce(c.stage, 'new')                                        AS crm_stage,
    c.last_contacted_at,
    c.next_followup_at
  FROM businesses b
  LEFT JOIN subscriptions s ON s.business_id = b.id
  LEFT JOIN plans p         ON p.code = s.plan_code
  LEFT JOIN business_crm c  ON c.business_id = b.id
  WHERE b.id = p_business_id
$$;

REVOKE ALL ON FUNCTION admin_business_extra(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_business_extra(uuid) TO app_role;


-- ----- 7) admin_ltv_summary() ----------------------------------------------- --
-- Platform LTV roll-up: the average and total LTV ESTIMATE across ALL businesses,
-- using the exact same per-business formula as admin_business_extra (free → 0).
-- avg_ltv averages over EVERY business (including the 0-valued free ones), so it
-- reflects the real blended value per customer.
CREATE OR REPLACE FUNCTION admin_ltv_summary()
RETURNS TABLE(
  avg_ltv   numeric,
  total_ltv numeric
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  WITH per_business AS (
    SELECT
      coalesce(p.price, 0)
        * greatest(
            1,
            (extract(year  FROM age(now(), coalesce(s.started_at, now())))::int * 12
             + extract(month FROM age(now(), coalesce(s.started_at, now())))::int)
          ) AS ltv
    FROM businesses b
    LEFT JOIN subscriptions s ON s.business_id = b.id
    LEFT JOIN plans p         ON p.code = s.plan_code
  )
  SELECT
    coalesce(round(avg(ltv), 2), 0) AS avg_ltv,
    coalesce(sum(ltv), 0)           AS total_ltv
  FROM per_business
$$;

REVOKE ALL ON FUNCTION admin_ltv_summary() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_ltv_summary() TO app_role;
