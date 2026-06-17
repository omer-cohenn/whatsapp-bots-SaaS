-- ============================================================================
-- seed.sql — DEV fixtures (run by `make seed`, applied as the SUPERUSER).
-- ----------------------------------------------------------------------------
-- Two fake tenants used by the isolation demo + tests. Fixed UUIDs so the demo
-- can reference them by name. Idempotent (ON CONFLICT DO NOTHING) so re-seeding
-- is safe. This is DEV-ONLY data — it is NOT part of the schema migrations and
-- never runs in production.
--
--   🅰️  Avi Insurance   id = aaaaaaaa-... user = google-sub-avi
--   🅱️  Bella Barber    id = bbbbbbbb-... user = google-sub-bella
--
-- Seeded as the superuser, so RLS is bypassed here (that is how a brand-new
-- business gets created — the app path for signup lands in M3).
-- ============================================================================

INSERT INTO users (id, email, name) VALUES
  ('google-sub-avi',   'avi@example.com',   'Avi'),
  ('google-sub-bella', 'bella@example.com', 'Bella')
ON CONFLICT (id) DO NOTHING;

INSERT INTO businesses (id, name, business_type, created_by) VALUES
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'Avi Insurance', 'insurance',  'google-sub-avi'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'Bella Barber',  'service_pro','google-sub-bella')
ON CONFLICT (id) DO NOTHING;

INSERT INTO business_members (business_id, user_id, role) VALUES
  ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'google-sub-avi',   'owner'),
  ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', 'google-sub-bella', 'owner')
ON CONFLICT (business_id, user_id) DO NOTHING;
