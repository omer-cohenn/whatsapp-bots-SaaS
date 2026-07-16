-- ============================================================================
-- 0001_roles_extensions.sql — Bizz_up M2 (the tenant wall): roles + extensions
-- ----------------------------------------------------------------------------
-- Runs as the Postgres SUPERUSER (the compose POSTGRES_USER) via the migrate
-- runner. Creates:
--   1. pgcrypto       — for gen_random_uuid() on every uuid PK.
--   2. app_role       — the dashboard/API login role. NON-superuser, so RLS
--                       actually applies to it (the old system's #1 bug was
--                       connecting with a service key that BYPASSED RLS).
--   3. gateway_role   — the ONLY role allowed to touch the crown-jewel
--                       whatsapp_credentials table (least privilege).
--
-- Passwords are injected by the migrate runner as psql variables (:'app_pw',
-- :'gw_pw') so NO secret is ever committed to this file. Idempotent: safe to
-- re-run (CREATE only when missing; ALTER refreshes the password each run).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- app_role: tenant-scoped, subject to RLS. Created once, then its password is
-- (re)set from the injected variable every run so it always matches .env.
SELECT 'CREATE ROLE app_role LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_role')
\gexec
ALTER ROLE app_role LOGIN PASSWORD :'app_pw';

-- gateway_role: crown-jewel only. Same create-once / refresh-password pattern.
SELECT 'CREATE ROLE gateway_role LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gateway_role')
\gexec
ALTER ROLE gateway_role LOGIN PASSWORD :'gw_pw';

-- Note: CONNECT (on the database) and USAGE (on schema public) are already
-- granted to PUBLIC by default in Postgres 16, so both roles can connect and
-- see the schema. The actual TABLE privileges are granted explicitly — and
-- minimally — in 0004. Nothing else is granted here.
