-- ============================================================================
-- 0006_abandoned_sweep.sql — the abandoned-lead sweep (M5 runtime background job)
-- ----------------------------------------------------------------------------
-- THE PROBLEM (same shape as 0005's login problem): the backend connects as
-- `app_role`, which has RLS FORCED on `leads` / `flow_events` (see 0004). A
-- normal request scopes itself with `app.business_id` (one tenant per request),
-- so app_role only ever sees that one tenant's rows. But the abandoned-sweep is
-- a BACKGROUND JOB with NO request and NO single tenant — it must touch idle
-- leads ACROSS every business. Under RLS-as-app_role with no context, a plain
-- UPDATE sees 0 rows, so the sweep could never run.
--
-- THE FIX (mirrors 0005): ONE tiny SECURITY DEFINER function. It runs with the
-- OWNER's rights (the migrate superuser), which BYPASSES RLS by design — but it
-- is tightly scoped to a single, well-defined action: flip `in_progress` leads
-- that have been idle longer than p_idle_minutes to 'abandoned', and drop a
-- matching 'abandoned' flow_event. It cannot read or leak PII (it touches only
-- the status column + the structural funnel event) and it stays tenant-correct:
-- every row keeps its OWN business_id, and each flow_event is inserted with that
-- same business_id — so the funnel stays perfectly partitioned per tenant.
--
-- SAFETY NOTES (standard SECURITY DEFINER hygiene, same as 0005):
--   * `SET search_path = public, pg_temp` pins the schema.
--   * EXECUTE is REVOKEd from PUBLIC and GRANTed only to app_role.
--   * is_test is carried onto the flow_event so a swept TEST lead's event stays
--     flagged is_test = true (never mixed into real funnel metrics).
-- Idempotent: CREATE OR REPLACE + idempotent REVOKE/GRANT.
-- ============================================================================

-- REPLAY-SAFETY: the migrate runner has NO schema_migrations ledger — it re-runs
-- EVERY file on each pass. Later migration 0023 redefines this function with a
-- different RETURN TYPE (TABLE instead of integer); on an existing DB this 0006
-- would then hit "cannot change return type of existing function". DROP first so
-- 0006 can always rebuild the integer version, then 0023 rebuilds the TABLE one.
DROP FUNCTION IF EXISTS sweep_abandoned_leads(int);

CREATE OR REPLACE FUNCTION sweep_abandoned_leads(p_idle_minutes int)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_count integer;
BEGIN
  -- (a) Flip every idle in_progress lead → abandoned, capturing the rows we
  --     changed so we can write the matching funnel events in one statement.
  WITH swept AS (
    UPDATE leads
    SET status           = 'abandoned',
        last_activity_at = last_activity_at  -- intentionally NOT bumped: the
                                             -- clock should reflect the real
                                             -- last activity, not the sweep.
    WHERE status = 'in_progress'
      AND last_activity_at < now() - make_interval(mins => p_idle_minutes)
    RETURNING id, business_id, lead_name, last_step_index, is_test
  ),
  -- (b) One 'abandoned' flow_event per swept lead, carrying that lead's OWN
  --     business_id (tenant-correct) + is_test flag (test rows stay flagged).
  logged AS (
    INSERT INTO flow_events
      (business_id, lead_id, flow_key, event, step_index, is_test)
    SELECT business_id, id, lead_name, 'abandoned', last_step_index, is_test
    FROM swept
    RETURNING 1
  )
  SELECT count(*) INTO v_count FROM swept;

  RETURN v_count;
END
$$;

-- Permissions: PUBLIC gets nothing; only app_role (the backend) may EXECUTE.
REVOKE ALL ON FUNCTION sweep_abandoned_leads(int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sweep_abandoned_leads(int) TO app_role;
