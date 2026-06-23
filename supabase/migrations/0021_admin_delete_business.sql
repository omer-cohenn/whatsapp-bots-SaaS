-- ============================================================================
-- 0021_admin_delete_business.sql — admin-only HARD delete of a business (M13)
-- ----------------------------------------------------------------------------
-- The platform operator can permanently remove a customer-business. Deleting the
-- `businesses` row CASCADES to every tenant table that references it ON DELETE
-- CASCADE (business_members, whatsapp_connections/credentials, bot_settings,
-- bot_builder_messages, leads, flow_events, bookings/services/booking_settings/
-- google_credentials, subscriptions, business_crm, crm_notes, usage_daily) — so
-- ALL of that business's data is wiped. The `users` row is NOT deleted
-- (businesses.created_by is ON DELETE SET NULL); a returning person would simply
-- be re-provisioned a fresh business on next login.
--
-- SECURITY DEFINER (bypasses RLS, by design — like the other admin_* funcs):
--   * EXECUTE is REVOKEd from PUBLIC and GRANTed only to app_role.
--   * The app gates the call behind current_admin (the only guard), AND refuses
--     to delete the admin's OWN session business (backend check).
--   * search_path pinned. The admin's REAL identity + the business name are
--     written to admin_audit BEFORE the delete (admin_audit.target_business_id
--     has NO FK, so the audit trail SURVIVES the cascade).
-- Idempotent: CREATE OR REPLACE + idempotent REVOKE/GRANT.
-- ============================================================================

CREATE OR REPLACE FUNCTION admin_delete_business(
  p_admin_user_id text,
  p_admin_email   text,
  p_business_id   uuid
)
RETURNS text  -- the deleted business name (for the audit detail + the UI)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_name text;
BEGIN
  SELECT name INTO v_name FROM businesses WHERE id = p_business_id;
  IF v_name IS NULL THEN
    -- Unknown business → same signal the other admin_* funcs use (mapped to 404).
    RAISE EXCEPTION 'unknown business' USING ERRCODE = 'foreign_key_violation';
  END IF;

  -- Audit FIRST (the row survives the cascade; capture the name so the trail is
  -- meaningful after the business is gone). Stamped with the real admin identity.
  INSERT INTO admin_audit (admin_user_id, admin_email, action, target_business_id, detail)
  VALUES (p_admin_user_id, p_admin_email, 'delete_business', p_business_id,
          jsonb_build_object('name', v_name));

  -- The hard delete — cascades across every tenant table.
  DELETE FROM businesses WHERE id = p_business_id;

  RETURN v_name;
END
$$;

REVOKE ALL    ON FUNCTION admin_delete_business(text, text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION admin_delete_business(text, text, uuid) TO app_role;
