-- ============================================================================
-- 0020_m13_crm_functions.sql — M13 back-office: the CRM + snapshot SD functions
-- ----------------------------------------------------------------------------
-- Source of truth: docs/decisions/0017-m13-backoffice-analytics-crm.md.
--
-- The platform sales pipeline (Omer working his business-customers from 'new' to
-- 'won') plus the daily snapshot writer. Same doorway pattern as 0017/0019:
-- SECURITY DEFINER, run as owner → bypass RLS by design, guarded only by the
-- app's admin gate. Every CRM WRITE leaves an admin_audit trail. The mutating
-- functions are plpgsql + atomic. ADDITIVE — they touch no M12 object.
--
-- SAFETY (every function below): SECURITY DEFINER + SET search_path =
-- public, pg_temp; REVOKE ALL FROM PUBLIC + GRANT EXECUTE TO app_role only.
-- Idempotent: CREATE OR REPLACE + idempotent REVOKE/GRANT. Safe to re-run.
--
-- M12 LESSON BAKED IN: any function whose RETURNS TABLE names a column that also
-- exists on a table it UPSERTs must target ON CONFLICT by the PK CONSTRAINT NAME
-- (business_crm_pkey), not the bare column, or the OUT var vs table column is
-- ambiguous at runtime (the bug that bit admin_set_subscription in M12).
-- ============================================================================


-- ----- 1) admin_crm_list() -------------------------------------------------- --
-- The pipeline board: EVERY business with its CRM state, plan, and note count.
-- LEFT JOIN business_crm so a business with no CRM row still appears (default
-- stage 'new', null times). Ordered by the follow-up reminder (soonest first,
-- nulls last) then name. Read-only.
CREATE OR REPLACE FUNCTION admin_crm_list()
RETURNS TABLE(
  business_id       uuid,
  name              text,
  plan_code         text,
  stage             text,
  last_contacted_at timestamptz,
  next_followup_at  timestamptz,
  note_count        bigint
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT
    b.id                            AS business_id,
    b.name,
    coalesce(s.plan_code, 'free')   AS plan_code,
    coalesce(c.stage, 'new')        AS stage,
    c.last_contacted_at,
    c.next_followup_at,
    (SELECT count(*) FROM crm_notes n WHERE n.business_id = b.id) AS note_count
  FROM businesses b
  LEFT JOIN subscriptions s ON s.business_id = b.id
  LEFT JOIN business_crm c  ON c.business_id = b.id
  ORDER BY c.next_followup_at ASC NULLS LAST, b.name ASC
$$;

REVOKE ALL ON FUNCTION admin_crm_list() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_crm_list() TO app_role;


-- ----- 2) admin_set_crm_stage(...) ------------------------------------------ --
-- The pipeline write path. Atomic, plpgsql: validate the stage + the business,
-- UPSERT business_crm, stamp last_contacted_at when moving into an "engaged"
-- stage (contacted/warming), record an admin_audit row, return the new state.
-- admin_user_id/admin_email come from the verified admin session server-side —
-- never from the client body. A bad stage raises check_violation; an unknown
-- business raises foreign_key_violation (the caller surfaces a 4xx).
CREATE OR REPLACE FUNCTION admin_set_crm_stage(
  p_admin_user_id text,
  p_admin_email   text,
  p_business_id   uuid,
  p_stage         text,
  p_next_followup timestamptz
)
RETURNS TABLE(
  business_id      uuid,
  stage            text,
  next_followup_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_contact timestamptz;
BEGIN
  -- (a) validate the stage against the same set the CHECK constraint enforces.
  IF p_stage IS NULL OR p_stage NOT IN ('new', 'contacted', 'warming', 'won', 'lost') THEN
    RAISE EXCEPTION 'invalid stage: %', p_stage
      USING ERRCODE = 'check_violation';
  END IF;

  -- (b) the business must exist (FK + audit target meaningful).
  IF NOT EXISTS (SELECT 1 FROM businesses WHERE id = p_business_id) THEN
    RAISE EXCEPTION 'unknown business_id: %', p_business_id
      USING ERRCODE = 'foreign_key_violation';
  END IF;

  -- (c) stamp last_contacted_at when the stage means we just engaged them.
  v_contact := CASE WHEN p_stage IN ('contacted', 'warming') THEN now() ELSE NULL END;

  -- (d) UPSERT the CRM row. The RETURNS TABLE declares OUT columns named
  -- business_id / stage / next_followup_at, which also exist on business_crm, so
  -- a bare ON CONFLICT (business_id) is ambiguous. Target the PK by its
  -- constraint name (the M12 admin_set_subscription lesson). On update we keep an
  -- existing last_contacted_at if this move does not re-engage (COALESCE).
  INSERT INTO business_crm (business_id, stage, last_contacted_at, next_followup_at)
  VALUES (p_business_id, p_stage, v_contact, p_next_followup)
  ON CONFLICT ON CONSTRAINT business_crm_pkey DO UPDATE
    SET stage             = EXCLUDED.stage,
        last_contacted_at = coalesce(EXCLUDED.last_contacted_at, business_crm.last_contacted_at),
        next_followup_at  = EXCLUDED.next_followup_at,
        updated_at        = now();

  -- (e) accountability trail.
  INSERT INTO admin_audit (admin_user_id, admin_email, action, target_business_id, detail)
  VALUES (
    p_admin_user_id,
    p_admin_email,
    'crm_stage',
    p_business_id,
    jsonb_build_object('stage', p_stage)
  );

  -- (f) return the new state.
  RETURN QUERY
    SELECT c.business_id, c.stage, c.next_followup_at
    FROM business_crm c
    WHERE c.business_id = p_business_id;
END
$$;

REVOKE ALL ON FUNCTION admin_set_crm_stage(text, text, uuid, text, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_set_crm_stage(text, text, uuid, text, timestamptz) TO app_role;


-- ----- 3) admin_add_crm_note(...) ------------------------------------------- --
-- Append a free-text note to a business's CRM log. Atomic, plpgsql: validate the
-- note is non-blank + the business exists, INSERT the note, bump the CRM row's
-- last_contacted_at (creating a default 'new' CRM row if none exists yet), record
-- an admin_audit row, return the new note id. admin identity comes from the
-- session server-side.
CREATE OR REPLACE FUNCTION admin_add_crm_note(
  p_admin_user_id text,
  p_admin_email   text,
  p_business_id   uuid,
  p_note          text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_note_id uuid;
BEGIN
  -- (a) the note must carry actual text.
  IF p_note IS NULL OR btrim(p_note) = '' THEN
    RAISE EXCEPTION 'note must not be blank'
      USING ERRCODE = 'check_violation';
  END IF;

  -- (b) the business must exist.
  IF NOT EXISTS (SELECT 1 FROM businesses WHERE id = p_business_id) THEN
    RAISE EXCEPTION 'unknown business_id: %', p_business_id
      USING ERRCODE = 'foreign_key_violation';
  END IF;

  -- (c) insert the note and capture its id.
  INSERT INTO crm_notes (business_id, admin_user_id, admin_email, note)
  VALUES (p_business_id, p_admin_user_id, p_admin_email, btrim(p_note))
  RETURNING id INTO v_note_id;

  -- (d) a note IS a contact → bump last_contacted_at (upsert a default CRM row if
  -- none yet). PK constraint name avoids the ambiguous-column trap (no OUT cols
  -- here, but it stays consistent and future-proof).
  INSERT INTO business_crm (business_id, last_contacted_at)
  VALUES (p_business_id, now())
  ON CONFLICT ON CONSTRAINT business_crm_pkey DO UPDATE
    SET last_contacted_at = now(),
        updated_at        = now();

  -- (e) accountability trail.
  INSERT INTO admin_audit (admin_user_id, admin_email, action, target_business_id, detail)
  VALUES (
    p_admin_user_id,
    p_admin_email,
    'crm_note',
    p_business_id,
    jsonb_build_object('note_id', v_note_id)
  );

  RETURN v_note_id;
END
$$;

REVOKE ALL ON FUNCTION admin_add_crm_note(text, text, uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_add_crm_note(text, text, uuid, text) TO app_role;


-- ----- 4) admin_crm_notes(p_business_id) ------------------------------------ --
-- The note history for one business, newest first. Read-only. Carries the admin's
-- display email + the note text + timestamp — no end-customer PII.
CREATE OR REPLACE FUNCTION admin_crm_notes(p_business_id uuid)
RETURNS TABLE(
  id          uuid,
  admin_email text,
  note        text,
  created_at  timestamptz
)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT n.id, n.admin_email, n.note, n.created_at
  FROM crm_notes n
  WHERE n.business_id = p_business_id
  ORDER BY n.created_at DESC
$$;

REVOKE ALL ON FUNCTION admin_crm_notes(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_crm_notes(uuid) TO app_role;


-- ----- 5) admin_upsert_today_snapshot() ------------------------------------- --
-- Stamp today's platform aggregates into platform_snapshots so the trend graphs
-- accrue real history. There is no scheduler in M13, so the backend calls this on
-- every GET /api/admin/overview — hence it must be idempotent for the day. plpgsql
-- + RETURNS void.
--   total_businesses = all businesses.
--   active_count     = businesses where is_active = true.
--   paid_count       = subscriptions with plan_code <> 'free' AND status='active'.
--   mrr              = sum of plan prices for those active non-free subscriptions.
--   churn_count      = subscriptions with status IN ('suspended','cancelled').
-- ON CONFLICT (day) → overwrite, so repeated calls within the day just refresh
-- today's row with the latest numbers.
CREATE OR REPLACE FUNCTION admin_upsert_today_snapshot()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_total  int;
  v_active int;
  v_paid   int;
  v_mrr    numeric(12,2);
  v_churn  int;
BEGIN
  SELECT count(*) INTO v_total FROM businesses;

  SELECT count(*) INTO v_active FROM businesses WHERE is_active = true;

  SELECT count(*) INTO v_paid
  FROM subscriptions s
  WHERE s.plan_code <> 'free' AND s.status = 'active';

  SELECT coalesce(sum(p.price), 0) INTO v_mrr
  FROM subscriptions s
  JOIN plans p ON p.code = s.plan_code
  WHERE s.plan_code <> 'free' AND s.status = 'active';

  SELECT count(*) INTO v_churn
  FROM subscriptions s
  WHERE s.status IN ('suspended', 'cancelled');

  INSERT INTO platform_snapshots
    (day, total_businesses, active_count, paid_count, mrr, churn_count)
  VALUES
    (current_date, v_total, v_active, v_paid, v_mrr, v_churn)
  ON CONFLICT (day) DO UPDATE
    SET total_businesses = EXCLUDED.total_businesses,
        active_count     = EXCLUDED.active_count,
        paid_count       = EXCLUDED.paid_count,
        mrr              = EXCLUDED.mrr,
        churn_count      = EXCLUDED.churn_count;
END
$$;

REVOKE ALL ON FUNCTION admin_upsert_today_snapshot() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_upsert_today_snapshot() TO app_role;
