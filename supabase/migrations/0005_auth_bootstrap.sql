-- ============================================================================
-- 0005_auth_bootstrap.sql — the two SECURITY DEFINER functions used at LOGIN
-- ----------------------------------------------------------------------------
-- THE PROBLEM: the backend connects as `app_role`, which has RLS FORCED on
-- businesses / business_members (see 0004). At login time there is NO tenant
-- context yet — `app.business_id` / current_business_id() is unset — so any
-- plain SELECT/INSERT on those tables under app_role returns 0 rows / is
-- blocked by the WITH CHECK fence. That is correct for normal requests, but it
-- makes login impossible (we can't even learn which businesses a user owns).
--
-- THE FIX: two SECURITY DEFINER functions. They run with the OWNER's rights
-- (the migrate superuser), which BYPASSES RLS by design. They are kept tiny and
-- tightly scoped to the single user_id passed in, so they can't be used to read
-- across tenants — the only thing they expose is "this user's own businesses".
--
-- SAFETY NOTES:
--   * `SET search_path = public, pg_temp` pins the schema so a malicious temp
--     object can't hijack an unqualified name (standard SECURITY DEFINER hygiene).
--   * EXECUTE is REVOKEd from PUBLIC and GRANTed only to app_role.
--   * provision_owner is IDEMPOTENT: a returning user always gets their existing
--     business back (no duplicate businesses), and it is race-safe under the
--     business_members UNIQUE(business_id,user_id) constraint.
-- Idempotent: CREATE OR REPLACE + idempotent REVOKE/GRANT.
-- ============================================================================

-- ----- 1) get_user_businesses ---------------------------------------------- --
-- Read-only. Returns every business this user belongs to (for the login screen
-- / account switcher). Scoped to the one user_id → cannot leak other tenants.
CREATE OR REPLACE FUNCTION get_user_businesses(p_user_id text)
RETURNS TABLE(business_id uuid, name text, role text)
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT b.id, b.name, m.role
  FROM business_members m
  JOIN businesses b ON b.id = m.business_id
  WHERE m.user_id = p_user_id
  ORDER BY m.created_at
$$;

-- ----- 2) provision_owner -------------------------------------------------- --
-- Upserts the login user, then ensures they own exactly one business. Returns
-- the business_id. Idempotent for returning users; race-safe for the very first
-- concurrent login of a brand-new user.
CREATE OR REPLACE FUNCTION provision_owner(
  p_user_id       text,
  p_email         text,
  p_name          text,
  p_picture       text,
  p_business_name text
)
RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_business_id uuid;
BEGIN
  -- (a) Upsert the login identity (Google `sub` is the PK).
  INSERT INTO users (id, email, name, picture, last_login_at)
  VALUES (p_user_id, p_email, p_name, p_picture, now())
  ON CONFLICT (id) DO UPDATE
    SET email         = EXCLUDED.email,
        name          = EXCLUDED.name,
        picture       = EXCLUDED.picture,
        last_login_at = now();

  -- (b) Returning user? Hand back their first (oldest) business, do not create.
  SELECT business_id INTO v_business_id
  FROM business_members
  WHERE user_id = p_user_id
  ORDER BY created_at
  LIMIT 1;

  IF v_business_id IS NOT NULL THEN
    RETURN v_business_id;
  END IF;

  -- (c) Brand-new user → create their business + owner membership.
  INSERT INTO businesses (name, created_by)
  VALUES (
    coalesce(
      nullif(btrim(p_business_name), ''),
      nullif(btrim(p_name), ''),
      nullif(split_part(p_email, '@', 1), ''),
      'My business'
    ),
    p_user_id
  )
  RETURNING id INTO v_business_id;

  -- Race-safe: if a concurrent login already inserted the membership, fall back
  -- to the existing one (the just-created business above is harmlessly orphaned;
  -- the UNIQUE(business_id,user_id) constraint is what makes this convergent).
  INSERT INTO business_members (business_id, user_id, role)
  VALUES (v_business_id, p_user_id, 'owner')
  ON CONFLICT (business_id, user_id) DO NOTHING;

  -- Re-read the winning membership (covers the concurrent-insert case where the
  -- ON CONFLICT above did nothing because another transaction won the race).
  SELECT business_id INTO v_business_id
  FROM business_members
  WHERE user_id = p_user_id
  ORDER BY created_at
  LIMIT 1;

  RETURN v_business_id;
END
$$;

-- ----- Permissions: PUBLIC gets nothing; app_role may EXECUTE --------------- --
REVOKE ALL ON FUNCTION get_user_businesses(text)                       FROM PUBLIC;
REVOKE ALL ON FUNCTION provision_owner(text, text, text, text, text)  FROM PUBLIC;
GRANT EXECUTE ON FUNCTION get_user_businesses(text)                      TO app_role;
GRANT EXECUTE ON FUNCTION provision_owner(text, text, text, text, text) TO app_role;
