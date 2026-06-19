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
--
-- M4 NOTE — the bot_settings rows below are wrapped in explicit per-tenant
-- transactions that SET LOCAL app.business_id first. The superuser bypasses RLS
-- anyway, so this isn't strictly required to insert — but it (a) makes the seed
-- mirror exactly how the app writes (tenant context set, then write, see
-- backend/app/db/session.py), and (b) means the inserts still satisfy the
-- WITH CHECK predicate (business_id = current_business_id()) instead of relying
-- on the bypass — i.e. RLS-correct by construction. SET LOCAL only persists
-- inside a transaction, so each block is BEGIN; set_config(...,true); ...; COMMIT;
-- The jsonb shapes match docs/spec/bot-config-contract.md (the M4 contract).
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

-- ----------------------------------------------------------------------------
-- 🅰️ Avi Insurance — a sample published bot: one "lead" flow (quote, 3 steps)
-- + one "human_handoff" flow + a filled bot_profile. Idempotent on business_id.
-- ----------------------------------------------------------------------------
BEGIN;
  -- Bind this transaction to Avi's tenant (mirrors the app's set_config call).
  SELECT set_config('app.business_id', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', true);

  INSERT INTO bot_settings (business_id, bot_profile, lead_steps, handoff_keywords, is_published)
  VALUES (
    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    -- bot_profile (contract §1)
    jsonb_build_object(
      'name',               'עוזר הביטוח של אבי',
      'system_prompt',      'אתה עוזר דיגיטלי מקצועי וסבלני של סוכנות ביטוח. עזור ללקוחות להשאיר פרטים לקבלת הצעת מחיר והעבר פניות דחופות לנציג. אל תמציא מידע — אם אינך יודע, הפנה לנציג.',
      'tone',               'מקצועי ואדיב',
      'language',           'he',
      'greeting',           'שלום וברוך הבא לסוכנות הביטוח של אבי! 🛡️ איך אפשר לעזור?',
      'escalation_message', 'תודה! נציג מהסוכנות יחזור אליך בהקדם 🙏',
      'auto_close_minutes', 60,
      'menu_keywords',      jsonb_build_array('תפריט', 'menu', '0')
    ),
    -- lead_steps (contract §2) — OBJECT keyed by flow name
    jsonb_build_object(
      'quote', jsonb_build_object(
        'label',     'קבלת הצעת מחיר',
        'flow_type', 'lead',
        'steps', jsonb_build_array(
          jsonb_build_object('key','full_name','question','מה השם המלא שלך?','type','text','required',true),
          jsonb_build_object('key','phone','question','מה מספר הטלפון שלך?','type','phone','required',true,
                             'error_message','לא הצלחתי לזהות מספר טלפון תקין, אפשר שוב?'),
          jsonb_build_object('key','insurance_type','question','איזה סוג ביטוח מעניין אותך?','type','choice','required',true,
                             'options', jsonb_build_array('רכב','דירה','בריאות','חיים'))
        )
      ),
      'talk_to_human', jsonb_build_object(
        'label',     'דברו עם נציג',
        'flow_type', 'human_handoff',
        'steps',     jsonb_build_array()
      )
    ),
    -- handoff_keywords (contract §3)
    jsonb_build_array('נציג', 'אדם', 'human', 'agent'),
    -- is_published (contract §4)
    true
  )
  ON CONFLICT (business_id) DO NOTHING;
COMMIT;

-- ----------------------------------------------------------------------------
-- 🅱️ Bella Barber — a sample DRAFT bot (is_published=false → try-me only):
-- one "lead" flow (booking-style intake, 2 steps) + one "human_handoff" flow.
-- ----------------------------------------------------------------------------
BEGIN;
  SELECT set_config('app.business_id', 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', true);

  INSERT INTO bot_settings (business_id, bot_profile, lead_steps, handoff_keywords, is_published)
  VALUES (
    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
    jsonb_build_object(
      'name',               'עוזר המספרה של בלה',
      'system_prompt',      'אתה עוזר דיגיטלי חברותי וקליל של מספרה. עזור ללקוחות להשאיר פרטים לקביעת תור והעבר פניות דחופות לנציג. אל תמציא מחירים או זמינות.',
      'tone',               'חברותי וקליל',
      'language',           'he',
      'greeting',           'שלום וברוך הבא למספרה של בלה! 💇 איך אפשר לעזור לך היום?',
      'escalation_message', 'תודה! ניצור איתך קשר בהקדם 🙏',
      'auto_close_minutes', 45,
      'menu_keywords',      jsonb_build_array('תפריט', 'menu', '0')
    ),
    jsonb_build_object(
      'appointment', jsonb_build_object(
        'label',     'קביעת תור',
        'flow_type', 'lead',
        'steps', jsonb_build_array(
          jsonb_build_object('key','full_name','question','בשמחה! מה השם המלא שלך?','type','text','required',true),
          jsonb_build_object('key','phone','question','מה מספר הטלפון שלך לתיאום?','type','phone','required',true,
                             'error_message','מספר לא תקין, אפשר לנסות שוב?')
        )
      ),
      'talk_to_human', jsonb_build_object(
        'label',     'דברו עם נציג',
        'flow_type', 'human_handoff',
        'steps',     jsonb_build_array()
      )
    ),
    jsonb_build_array('נציג', 'אדם', 'human', 'agent'),
    false
  )
  ON CONFLICT (business_id) DO NOTHING;
COMMIT;
