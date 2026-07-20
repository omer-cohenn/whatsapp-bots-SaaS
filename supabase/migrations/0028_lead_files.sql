-- ============================================================================
-- 0028_lead_files.sql — M16 data foundation: customer file/image uploads
-- ----------------------------------------------------------------------------
-- M16 lets a customer send an image / PDF / DOC / PPT through the WhatsApp bot.
-- The BYTES never live in Postgres: they are envelope-encrypted and pushed to
-- Cloudflare R2 (S3-compatible) under a TENANT-PREFIXED object key
-- ({business_id}/{file_id}). This table holds only the METADATA + the wrapped
-- data key needed to decrypt that object again.
--
-- WHY the bytes are not a bytea column:
--   * a 10 MB row bloats every backup, every WAL segment, and every SELECT *;
--   * the owner download path streams from object storage instead of dragging
--     the payload through the DB connection pool (1 GB server — see the memory
--     notes in app/services/file_storage.py).
--
-- ENVELOPE ENCRYPTION (identical shape to whatsapp_credentials.auth_state):
--   a FRESH per-file data key (DEK) encrypts the payload; the crown KEK wraps
--   the DEK; only the WRAPPED dek is stored here (`wrapped_dek`), stamped with
--   `key_version` so a future KEK rotation can still decrypt old rows. A stolen
--   R2 bucket is useless without the DB; a stolen DB dump is useless without the
--   KEK. Neither half alone yields a single customer file.
--
-- PII 🔒: `file_name` is stored as CIPHERTEXT (encrypt_pii) — a customer file is
-- routinely named "תעודת_זהות.pdf" / "invoice-Cohen.pdf", i.e. personal data. The
-- mime type, the size and the sha256 are NOT PII and stay plaintext so the owner
-- list view can render without a decrypt round-trip per row.
--
-- IDEMPOTENCY: Baileys re-emits a message on reconnect. The partial unique index
-- on (business_id, message_id) makes a re-delivered media message a no-op: the
-- upload endpoint looks the row up first and returns the EXISTING file_id
-- instead of pushing a second copy of the object to R2 (which would leak storage
-- and double-bill the tenant). message_id is nullable, hence the partial index.
--
-- lead_id is NULLABLE ON PURPOSE: a file can arrive mid-questionnaire, BEFORE the
-- `leads` row is finalized. The engine attaches it (UPDATE ... SET lead_id) once
-- the lead exists. Both FKs are ON DELETE CASCADE, so deleting a business or a
-- lead removes this metadata row — but NOTE: the cascade does NOT remove the R2
-- object. `file_storage.delete_object()` must be called by the deleting code
-- path; the object is otherwise orphaned (and undecryptable, since the wrapped
-- DEK dies with the row — so an orphan is inert, just wasted bytes).
--
-- ---------------------------------------------------------------------------
-- ROLE / POOL DECISION (the contract the API layer follows) — BOTH roles, split:
--
--   gateway_role → SELECT, INSERT.
--       The INTERNAL upload path (POST /internal/wa/media) is authenticated by
--       the shared X-Gateway-Token, not an owner session, and runs on
--       `app.state.gw_pool` — the same pool every other gateway-driven write
--       uses (see app/api/internal_wa.py). It needs SELECT for the idempotency
--       probe and INSERT for the new row. It gets NO UPDATE and NO DELETE: the
--       gateway must never be able to rewrite or erase a stored file record.
--
--   app_role → SELECT, INSERT, UPDATE, DELETE.
--       The OWNER download path (GET /api/leads/files/{file_id}) and the bot
--       engine both run as app_role on `app.state.pg_pool`. SELECT for the
--       download, UPDATE so the engine can attach `lead_id` once the lead row is
--       finalized, DELETE for owner-initiated file removal, INSERT so a future
--       owner-side upload does not need a migration.
--
-- Unlike whatsapp_credentials there is no crown-jewel wall here: the ciphertext
-- in this table is worthless without the KEK, and BOTH pools already hold the
-- KEK in process memory. Splitting the write verbs is the meaningful control.
-- RLS is the actual tenant wall on both pools — every query goes through
-- `tenant_connection`, so `current_business_id()` scopes it to one business.
-- ---------------------------------------------------------------------------
--
-- Idempotent (the migrate runner replays EVERY file on EVERY boot):
--   CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS /
--   DROP POLICY IF EXISTS before CREATE / idempotent REVOKE+GRANT /
--   plans.limits updated with a jsonb MERGE (`||`) so re-running just rewrites
--   the same keys and never clobbers the keys 0022 seeds.
-- ============================================================================

-- ----- (0) LEGACY-SHAPE GUARD ---------------------------------------------- --
-- A `lead_files` table with a DIFFERENT, earlier shape (kind / object_key /
-- content_type / expires_at, lead_id NOT NULL) exists in some environments. It
-- was created OUT OF BAND — no migration in this repo ever defined it — so a
-- plain CREATE TABLE IF NOT EXISTS below would silently no-op and leave the
-- schema wrong while the app fails at runtime on a missing `storage_key`.
--
-- We detect that legacy shape by the ABSENCE of `storage_key`, and:
--   * if the table is EMPTY  → DROP it, so the canonical CREATE below runs.
--     Nothing is lost: there are no rows, and the legacy table had no
--     wrapped_dek, so it could not have referenced an encrypted object anyway.
--   * if it has ANY rows     → RAISE, loudly. Data is never silently destroyed;
--     a human decides what to do with it.
-- On a clean database and on every replay after this has run once, both
-- branches are skipped entirely — this block is a no-op.
DO $$
DECLARE
  n bigint;
BEGIN
  IF to_regclass('public.lead_files') IS NOT NULL
     AND NOT EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public'
         AND table_name   = 'lead_files'
         AND column_name  = 'storage_key'
     )
  THEN
    EXECUTE 'SELECT count(*) FROM public.lead_files' INTO n;
    IF n > 0 THEN
      RAISE EXCEPTION
        'lead_files exists in a legacy shape and holds % row(s); refusing to '
        'drop it. Migrate or archive those rows, then re-run.', n;
    END IF;
    RAISE NOTICE 'dropping empty legacy lead_files table (pre-M16 shape)';
    DROP TABLE public.lead_files;
  END IF;
END
$$;

-- ----- (1) lead_files — one row per stored customer file -------------------- --
CREATE TABLE IF NOT EXISTS lead_files (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id      uuid NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  lead_id          uuid REFERENCES leads(id) ON DELETE CASCADE,  -- nullable: file may precede the lead
  conversation_id  text,                          -- the live chat this arrived on
  message_id       text,                          -- WhatsApp message id → idempotency key
  storage_key      text NOT NULL,                 -- R2 object key: {business_id}/{file_id}
  wrapped_dek      text NOT NULL,                 -- 🔒 per-file DEK, wrapped by the crown KEK
  key_version      int  NOT NULL DEFAULT 1,       -- which KEK version wrapped it (rotation)
  mime_type        text NOT NULL,                 -- CONTENT-SNIFFED type, not the declared one
  file_name        text,                          -- 🔒 ciphertext (PII)
  size_bytes       bigint NOT NULL,
  sha256           text,                          -- hex digest of the PLAINTEXT (integrity)
  created_at       timestamptz NOT NULL DEFAULT now()
);

-- Self-healing (additive) columns, in case an earlier build created the table.
ALTER TABLE lead_files ADD COLUMN IF NOT EXISTS conversation_id text;
ALTER TABLE lead_files ADD COLUMN IF NOT EXISTS message_id      text;
ALTER TABLE lead_files ADD COLUMN IF NOT EXISTS sha256          text;

-- IDEMPOTENCY: a Baileys re-emit of the same message must not store a 2nd copy.
-- Partial (WHERE message_id IS NOT NULL) so rows without a message id are free.
CREATE UNIQUE INDEX IF NOT EXISTS ux_lead_files_business_message
  ON lead_files (business_id, message_id)
  WHERE message_id IS NOT NULL;

-- The owner's "files for this business, newest first" list.
CREATE INDEX IF NOT EXISTS ix_lead_files_business_created
  ON lead_files (business_id, created_at DESC);

-- "all files attached to this lead" — the lead detail view + the engine's attach.
CREATE INDEX IF NOT EXISTS ix_lead_files_lead
  ON lead_files (lead_id);

-- ----- (2) RLS — the tenant wall (house style: ENABLE + FORCE + policy) ----- --
-- FORCE makes RLS apply even to the table owner (defense in depth). The migrate
-- runner is superuser and BYPASSES RLS — that is how this file can run at all;
-- the app connects as app_role / gateway_role where RLS is live.
ALTER TABLE lead_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE lead_files FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON lead_files;
CREATE POLICY p_tenant_isolation ON lead_files
  USING (business_id = current_business_id())        -- read: only my own files
  WITH CHECK (business_id = current_business_id());  -- write: only INTO my own tenant

-- ----- (3) Least-privilege grants (see the ROLE DECISION header above) ------ --
REVOKE ALL ON lead_files FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON lead_files TO app_role;
GRANT SELECT, INSERT                 ON lead_files TO gateway_role;

-- ----- (4) plans.limits — the M16 file quota keys --------------------------- --
-- Two NEW keys, merged into the limits blob 0022 seeds (`||` keeps every
-- existing key and overwrites only these two, so replay order 0022 → 0028 is
-- stable on every boot):
--
--   files_per_month : how many customer files a tenant may receive per month.
--   max_file_mb     : the per-file size cap SHOWN to the tenant. It is a soft,
--                     per-plan cap that must never exceed the HARD server cap
--                     `MAX_FILE_BYTES` (10 MB) in app/services/file_storage.py —
--                     that constant is the real 413 boundary and is enforced
--                     regardless of plan.
--
-- The numbers, and why:
--   free     →  20 files/mo,  5 MB  — enough to prove the feature works in the
--                                     trial without letting a free tenant park
--                                     GBs of R2 storage for nothing.
--   pro      → 300 files/mo, 10 MB  — ~half the plan's 600 leads/mo carry a file,
--                                     which matches the "photo of the problem"
--                                     use case this tier is sold on.
--   business →1000 files/mo, 10 MB  — half of its 2000 leads/mo, same ratio.
--
-- Enforcement of these caps lives in the engine (a later M16 slice); this
-- migration only publishes the catalog values.
UPDATE plans
SET limits = limits || '{"files_per_month":20,"max_file_mb":5}'::jsonb
WHERE code = 'free';

UPDATE plans
SET limits = limits || '{"files_per_month":300,"max_file_mb":10}'::jsonb
WHERE code = 'pro';

UPDATE plans
SET limits = limits || '{"files_per_month":1000,"max_file_mb":10}'::jsonb
WHERE code = 'business';
