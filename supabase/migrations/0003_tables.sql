-- ============================================================================
-- 0003_tables.sql — the 9 tables (Bizz_up MVP data model)
-- ----------------------------------------------------------------------------
-- Source of truth: docs/spec/data-model.md (FINAL, 9 tables + Redis live chat).
-- Live chat is NOT a table — it lives in Redis (decision 0006). The old DRAFT's
-- `conversations`/`messages` tables are SUPERSEDED and intentionally not built.
--
-- Conventions:
--   * uuid PKs via gen_random_uuid() (pgcrypto), except `users` (Google `sub`).
--   * business_id uuid → businesses(id) ON DELETE CASCADE is the tenant key.
--   * 🔒 columns hold CIPHERTEXT only (encrypted in the app before insert):
--       leads.phone / contact_name / answers, whatsapp_connections.phone_number,
--       whatsapp_credentials.auth_state (bytea, 🔒🔒 crown jewel).
--   * Multi-lead (Omer's change): bot_settings.lead_steps is an OBJECT keyed by
--     lead name, and leads carries `lead_name` to say which questionnaire.
--   * RLS + grants are applied separately in 0004 (kept apart for clarity).
-- Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
-- ============================================================================

-- updated_at trigger helper (re-applied to the mutating tables below).
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END
$$;

-- 1) users — Google login identity. GLOBAL (no tenant key, no RLS).
CREATE TABLE IF NOT EXISTS users (
  id            text PRIMARY KEY,                  -- Google OpenID `sub`
  email         text UNIQUE NOT NULL,              -- login handle (stays queryable)
  name          text,
  picture       text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_login_at timestamptz
);

-- 2) businesses — the tenant. This row's `id` IS the business_id everywhere.
CREATE TABLE IF NOT EXISTS businesses (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  business_type text,
  created_by    text REFERENCES users(id) ON DELETE SET NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_businesses_created_by ON businesses(created_by);

-- 3) business_members — who may access a business (ownership check lives here).
CREATE TABLE IF NOT EXISTS business_members (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  user_id     text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role        text NOT NULL DEFAULT 'owner',
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (business_id, user_id)
);
CREATE INDEX IF NOT EXISTS ix_business_members_user ON business_members(user_id);

-- 4) whatsapp_connections — per-business connection state (holds NO secret key).
CREATE TABLE IF NOT EXISTS whatsapp_connections (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id        uuid NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE CASCADE,
  gateway_account_id text UNIQUE,                  -- bridges inbound to the business
  status             text NOT NULL DEFAULT 'disconnected',
  phone_number       text,                         -- 🔒 ciphertext (the linked number)
  last_connected_at  timestamptz,
  last_error         text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

-- 5) whatsapp_credentials — the Baileys session key. 🔒🔒 CROWN JEWEL.
CREATE TABLE IF NOT EXISTS whatsapp_credentials (
  business_id uuid PRIMARY KEY REFERENCES businesses(id) ON DELETE CASCADE,
  auth_state  bytea NOT NULL,                      -- 🔒🔒 envelope-encrypted bytes
  key_version int NOT NULL DEFAULT 1,              -- which KEK encrypted it (rotation)
  rotated_at  timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- 6) bot_settings — the bot's brain config (two jsonb). MULTI-LEAD lead_steps.
CREATE TABLE IF NOT EXISTS bot_settings (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id      uuid NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE CASCADE,
  -- Object keyed by lead name → several questionnaires per business, e.g.
  --   { "car_insurance": { "label": "...", "steps": [ {key,question,...} ] } }
  lead_steps       jsonb NOT NULL DEFAULT '{}'::jsonb,
  bot_profile      jsonb NOT NULL DEFAULT '{}'::jsonb,    -- name/system_prompt/tone
  handoff_keywords jsonb NOT NULL DEFAULT '["נציג","אדם","human","agent"]'::jsonb,
  is_published     boolean NOT NULL DEFAULT false,        -- try-me vs live
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);
-- Self-healing: an earlier build may have defaulted lead_steps to a flat '[]'
-- array; the multi-lead model is an object keyed by lead name → default '{}'.
ALTER TABLE bot_settings ALTER COLUMN lead_steps SET DEFAULT '{}'::jsonb;

-- 7) leads — collected leads + abandoned-follow-up record. PII 🔒.
CREATE TABLE IF NOT EXISTS leads (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id      uuid NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  lead_name        text,                           -- which questionnaire (key in lead_steps)
  phone            text,                           -- 🔒 ciphertext
  contact_name     text,                           -- 🔒 ciphertext
  answers          jsonb,                          -- 🔒 encrypted blob {"_":"<ct>"}
  status           text NOT NULL DEFAULT 'in_progress',  -- in_progress→new/abandoned→read/archived
  last_step_index  int,
  is_test          boolean NOT NULL DEFAULT false,
  key_version      int NOT NULL DEFAULT 1,
  cache_chat_ref   text,                           -- pointer to the live Redis key
  started_at       timestamptz NOT NULL DEFAULT now(),
  last_activity_at timestamptz NOT NULL DEFAULT now(),
  submitted_at     timestamptz
);
-- Self-healing: if an earlier build created `leads` without the multi-lead
-- column, add it (additive migrations beat "drop & recreate" once data exists).
ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_name text;
CREATE INDEX IF NOT EXISTS ix_leads_business_status   ON leads(business_id, status);
CREATE INDEX IF NOT EXISTS ix_leads_business_submitted ON leads(business_id, submitted_at DESC);
-- The abandoned-sweep index (M5): cheap scan of idle in_progress leads.
CREATE INDEX IF NOT EXISTS ix_leads_business_activity ON leads(business_id, last_activity_at);
CREATE INDEX IF NOT EXISTS ix_leads_business_leadname ON leads(business_id, lead_name);

-- 8) bot_builder_messages — AI-assist build-chat history (owner-facing). OPTIONAL.
CREATE TABLE IF NOT EXISTS bot_builder_messages (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id    uuid NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  author_user_id text REFERENCES users(id) ON DELETE SET NULL,
  role           text NOT NULL,                    -- user / assistant
  content        text,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_botbuilder_business_created
  ON bot_builder_messages(business_id, created_at);

-- 9) flow_events — lead funnel (started/step_completed/completed/abandoned).
CREATE TABLE IF NOT EXISTS flow_events (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id uuid NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  lead_id     uuid REFERENCES leads(id) ON DELETE CASCADE,
  flow_key    text,                                -- which questionnaire
  event       text NOT NULL,
  step_index  int,
  is_test     boolean NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_flow_events_business_created
  ON flow_events(business_id, created_at);
CREATE INDEX IF NOT EXISTS ix_flow_events_lead ON flow_events(lead_id);

-- updated_at triggers on the mutating tables (drop+create = idempotent).
DROP TRIGGER IF EXISTS trg_businesses_updated          ON businesses;
CREATE TRIGGER trg_businesses_updated          BEFORE UPDATE ON businesses
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_wa_connections_updated      ON whatsapp_connections;
CREATE TRIGGER trg_wa_connections_updated      BEFORE UPDATE ON whatsapp_connections
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_wa_credentials_updated      ON whatsapp_credentials;
CREATE TRIGGER trg_wa_credentials_updated      BEFORE UPDATE ON whatsapp_credentials
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_bot_settings_updated        ON bot_settings;
CREATE TRIGGER trg_bot_settings_updated        BEFORE UPDATE ON bot_settings
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
