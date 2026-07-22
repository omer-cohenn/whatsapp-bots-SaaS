-- 0031 — מנקה הנטישות מדלג על עסק הדמו
--
-- WHY: the abandoned-sweep flips any idle `in_progress` lead to `abandoned` and
-- closes its conversation after `p_idle_minutes` of silence. For a real business
-- that is correct and is the whole point of the feature.
--
-- The public demo tenant is not a real business — it is a FIXTURE. Its data is
-- seeded once and is meant to keep showing a lively inbox (leads mid-flow, chats
-- waiting for a human) to every visitor who presses "המשך בתור דמו". Under the
-- normal sweep it decays instead: measured 2026-07-22, 13 of its 15 seeded
-- conversations were already abandoned and closed within the hour, so a later
-- visitor saw a nearly-empty inbox and a wall of abandoned leads. The
-- alternative — re-seeding before every demo — is a manual step that will be
-- forgotten exactly when it matters.
--
-- The exclusion keys off `demo_slug IS NOT NULL`, the same marker /auth/demo
-- resolves against, so it covers precisely the one fixture tenant and cannot
-- widen: a real business has demo_slug NULL and is swept exactly as before.
--
-- The Redis-side stale-handoff sweep gets the matching exclusion in
-- app/services/stale_handoff_sweep.py.
--
-- This body is 0023's VERBATIM, with ONE added predicate — marked below. It is
-- reproduced in full rather than patched because CREATE OR REPLACE FUNCTION has
-- no partial form, and the migrate step replays every file on each boot with no
-- ledger, so 0023 runs first and this must land on top of it unchanged in every
-- other respect. Keep the two in sync if 0023 is ever edited.

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
      -- ↓↓↓ THE ONLY CHANGE FROM 0023 ↓↓↓
      -- Never sweep the public demo fixture (see the header).
      AND business_id NOT IN (
            SELECT id FROM businesses WHERE demo_slug IS NOT NULL
          )
      -- ↑↑↑ THE ONLY CHANGE FROM 0023 ↑↑↑
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
