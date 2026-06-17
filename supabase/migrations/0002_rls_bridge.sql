-- ============================================================================
-- 0002_rls_bridge.sql — the hand-wired RLS bridge (decision 0005)
-- ----------------------------------------------------------------------------
-- current_business_id() is the single function every Row-Level Security policy
-- depends on. The backend sets a per-request, transaction-local session value
-- (SET LOCAL app.business_id = '<uuid>' — actually via set_config(...,true)),
-- and this function reads it back for the RLS predicates in 0004.
--
-- The critical safety property: when the session value is UNSET, this returns
-- NULL, so every policy predicate `business_id = current_business_id()` is
-- false → ZERO rows. That is DENY-BY-DEFAULT — it kills the old C2 bug where
-- an unauthenticated request silently fell back to a shared tenant.
--
-- STABLE: result is constant within a single statement (lets the planner cache
-- it per query). It is NOT immutable — it depends on the session setting.
-- ============================================================================

CREATE OR REPLACE FUNCTION current_business_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
  -- current_setting(..., true) → NULL instead of erroring when unset.
  -- nullif('') guards the "set to empty string" case → also NULL.
  SELECT nullif(current_setting('app.business_id', true), '')::uuid
$$;
