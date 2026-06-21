-- ============================================================================
-- 0012_service_image.sql — service card image (M11.2)
-- ----------------------------------------------------------------------------
-- One additive column so each service card can carry a picture:
--   services.image_url — OPTIONAL. Holds either a public http(s) URL OR a
--                        client-side-resized, compressed `data:` URL (the
--                        frontend shrinks the upload on a canvas). NULL =>
--                        the card shows a placeholder frame. Owner-authored,
--                        public marketing content — no PII/ciphertext.
--
-- Purely additive: no new table, no RLS/grant change. `services` already has
-- RLS + app_role grants (0009), which cover any new column automatically.
-- Idempotent via ADD COLUMN IF NOT EXISTS.
-- ============================================================================

ALTER TABLE services ADD COLUMN IF NOT EXISTS image_url text;  -- http(s) URL or resized data: URL, NULL=>placeholder
