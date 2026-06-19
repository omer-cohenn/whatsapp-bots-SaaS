-- ============================================================================
-- 0007_outcome_note.sql — owner's encrypted "what happened" note on a lead
-- ----------------------------------------------------------------------------
-- M10 (decision 0010): when the owner marks a lead as `deal` or `closed`, the
-- UI requires them to record a short outcome note ("what happened"). That note
-- is PII/business-sensitive, so the app encrypts it before insert — this column
-- holds CIPHERTEXT only, exactly like leads.phone / contact_name / answers.
--
-- Purely additive: no new table, no RLS change. `leads` already has RLS
-- (p_tenant_isolation) + app_role CRUD grants in 0004, both of which cover any
-- new column automatically. Idempotent via ADD COLUMN IF NOT EXISTS.
-- ============================================================================

ALTER TABLE leads ADD COLUMN IF NOT EXISTS outcome_note text;  -- 🔒 ciphertext (owner's outcome note)
