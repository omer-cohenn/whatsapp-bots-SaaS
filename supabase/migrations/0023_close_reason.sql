-- ============================================================================
-- 0023_close_reason.sql — conversation/lead status model (decision 0021)
-- ----------------------------------------------------------------------------
-- TWO additive, re-runnable changes that make "why a conversation closed"
-- explicit and let the backend auto-close the matching Redis conversation when
-- a lead is swept to 'abandoned':
--
--   (1) leads.close_reason — a nullable label saying WHY the lead closed,
--       separate from the owner's OUTCOME (deal/closed). NULL = not closed yet.
--       Allowed app values: 'completed' | 'abandoned' | 'answered'.
--       Modeled exactly like leads.status: nullable free-text + a comment, NOT
--       a CHECK constraint (a CHECK would reject the existing NULL rows and
--       fight future label tweaks). The existing leads RLS policies + grants
--       from 0004 already cover this new column — no new RLS/grant needed.
--
--   (2) sweep_abandoned_leads(int) — the ONE cross-tenant SECURITY DEFINER
--       doorway from 0006. Re-created here, UNCHANGED in its security posture
--       (SECURITY DEFINER, owner rights = migrate superuser → bypasses RLS by
--       design, pinned search_path, REVOKE ALL FROM PUBLIC + GRANT only to
--       app_role). Two behaviour changes only:
--         a. When it flips an idle in_progress lead → 'abandoned', it now ALSO
--            stamps close_reason = 'abandoned' on the SAME row (same UPDATE).
--         b. It now RETURNS one row per just-abandoned lead — lead_id +
--            conversation_id — so the backend can close those Redis
--            conversations. conversation_id is the lead's cache_chat_ref
--            (the pointer to its live Redis key; see 0003 + dashboard models),
--            which may be NULL when a lead never had a linked conversation.
--       Still touches ONLY structural columns (status / close_reason) + the
--       PII-free, per-tenant 'abandoned' flow_event. Each row keeps its OWN
--       business_id; the funnel stays perfectly partitioned per tenant.
-- Idempotent: ADD COLUMN IF NOT EXISTS + CREATE OR REPLACE + idempotent
-- DROP/REVOKE/GRANT. NOTE: the return type changes from `integer` (0006) to a
-- TABLE shape, so we DROP the old function first (Postgres forbids changing a
-- function's return type via CREATE OR REPLACE).
-- ============================================================================

-- (1) close_reason column ----------------------------------------------------
ALTER TABLE leads ADD COLUMN IF NOT EXISTS close_reason text;
COMMENT ON COLUMN leads.close_reason IS
  'Why this lead/conversation closed (decision 0021). App values: '
  '''completed'' (all flow details collected → lead status ''new''), '
  '''abandoned'' (60 min with no customer message → lead status ''abandoned''), '
  '''answered'' (business finished handling it manually after human → status ''closed''). '
  'NULL = not closed yet. Nullable free-text + comment (mirrors leads.status); '
  'no CHECK constraint by design. Existing leads RLS/grants (0004) cover this column.';

-- (2) sweep_abandoned_leads — new return shape, same security -----------------
-- Drop the old `RETURNS integer` version (return-type change can't be done by
-- CREATE OR REPLACE). Signature (the arg list) is unchanged: (int).
DROP FUNCTION IF EXISTS sweep_abandoned_leads(int);

CREATE OR REPLACE FUNCTION sweep_abandoned_leads(p_idle_minutes int)
RETURNS TABLE(lead_id uuid, conversation_id text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
  -- (a) Flip every idle in_progress lead → abandoned AND stamp close_reason on
  --     the SAME row, capturing the changed rows so we can both write the
  --     matching funnel events and return them to the backend.
  RETURN QUERY
  WITH swept AS (
    UPDATE leads
    SET status           = 'abandoned',
        close_reason     = 'abandoned',           -- decision 0021: stamp WHY
        last_activity_at = last_activity_at       -- intentionally NOT bumped: the
                                                  -- clock should reflect the real
                                                  -- last activity, not the sweep.
    WHERE status = 'in_progress'
      AND last_activity_at < now() - make_interval(mins => p_idle_minutes)
    RETURNING id, business_id, lead_name, last_step_index, is_test, cache_chat_ref
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
  -- (c) Return one row per just-abandoned lead: its id + the Redis conversation
  --     pointer (cache_chat_ref) so the backend can close that conversation.
  --     conversation_id may be NULL if the lead never had a linked conversation.
  SELECT id, cache_chat_ref FROM swept;
END
$$;

-- Permissions: PUBLIC gets nothing; only app_role (the backend) may EXECUTE.
REVOKE ALL ON FUNCTION sweep_abandoned_leads(int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION sweep_abandoned_leads(int) TO app_role;
