-- ============================================================================
-- 0022_pricing_tiers_update.sql — adopt the approved 3-tier pricing model
-- ----------------------------------------------------------------------------
-- Source of truth: docs/decisions/0020-pricing-tiers.md (approved 2026-06-25).
-- 0015 seeded a placeholder catalog (free/basic/pro @ ₪0/49/149). This migration
-- rewrites that catalog into the LOCKED launch pricing of three tiers:
--
--   free     → 'חינמי'    ₪0     (trial / "see it work")
--   pro      → 'מקצועי'   ₪149   (small biz collecting leads)        [renamed]
--   business → 'עסקי'     ₪299   (biz with a booking calendar)       [NEW]
--   basic    → RETIRED    (any subscription on it moves to 'free')
--
-- WHY the column choices:
--   * plans.price = the CHARGED launch price (what the customer actually pays
--     today). The struck-through "regular" price and the annual price are
--     display-only, so they live inside limits as regular_price / annual_price.
--   * Feature caps live in plans.limits jsonb:
--       lead_flows, leads_per_month, ai_actions_per_month,
--       handoff_numbers (null = unlimited), booking (bool), whatsapp_numbers.
--
-- All prices include 18% VAT (Israeli market). Cap ENFORCEMENT in the engine is
-- explicitly out of scope here — this is catalog + landing-display data only.
--
-- plans is a GLOBAL catalog (no business_id, no RLS) — touching its rows is safe
-- and does not cross any tenant wall. We do NOT change any grant/RLS/policy.
--
-- Idempotent: plain UPDATEs (re-running just rewrites the same values), an
-- INSERT ... ON CONFLICT (code) DO UPDATE for the new 'business' row, and a
-- guarded reassign+DELETE for the retired 'basic' row (safe if already gone).
-- Safe to run twice.
-- ============================================================================

-- 1) free → 'חינמי'. Trial tier: 1 flow, 30 leads/mo, up to 5 handoff numbers,
--    no booking, single WhatsApp number. No regular/annual price (it is free).
UPDATE plans
SET name       = 'חינמי',
    price      = 0,
    sort_order = 0,
    limits     = '{"lead_flows":1,"leads_per_month":30,"ai_actions_per_month":10,"handoff_numbers":5,"booking":false,"whatsapp_numbers":1}'::jsonb
WHERE code = 'free';

-- 2) pro → 'מקצועי'. Launch ₪149 (regular ₪200, annual ₪1,490). Unlimited
--    handoff numbers (handoff_numbers = null), still no booking.
UPDATE plans
SET name       = 'מקצועי',
    price      = 149,
    sort_order = 2,
    limits     = '{"lead_flows":5,"leads_per_month":600,"ai_actions_per_month":50,"handoff_numbers":null,"booking":false,"whatsapp_numbers":1,"regular_price":200,"annual_price":1490}'::jsonb
WHERE code = 'pro';

-- 3) business → 'עסקי' (NEW). Launch ₪299 (regular ₪349, annual ₪2,990). Adds
--    the appointment booking calendar (booking = true). ON CONFLICT DO UPDATE so
--    a re-run refreshes the row instead of failing on the PK.
INSERT INTO plans (code, name, price, sort_order, limits) VALUES
  ('business', 'עסקי', 299, 3,
   '{"lead_flows":9,"leads_per_month":2000,"ai_actions_per_month":100,"handoff_numbers":null,"booking":true,"whatsapp_numbers":1,"regular_price":349,"annual_price":2990}'::jsonb)
ON CONFLICT (code) DO UPDATE
  SET name       = EXCLUDED.name,
      price      = EXCLUDED.price,
      sort_order = EXCLUDED.sort_order,
      limits     = EXCLUDED.limits;

-- 4) Retire 'basic'. First move any subscription still pointing at it to 'free'
--    (otherwise the FK subscriptions.plan_code → plans(code) would block the
--    DELETE). Both statements are no-ops once 'basic' is gone, so re-runs are safe.
UPDATE subscriptions SET plan_code = 'free' WHERE plan_code = 'basic';
DELETE FROM plans WHERE code = 'basic';
