-- 0027 — "one WhatsApp number = one business" (M6b hardening).
--
-- WHY: nothing stopped an owner from scanning the SAME WhatsApp number into two
-- different businesses (WhatsApp happily links our gateway as another "linked
-- device"). The result is chaos: every message on that number reaches BOTH
-- businesses' sockets and BOTH bots react. This migration adds the pieces the
-- backend needs to DETECT that conflict at connect time so the gateway can
-- refuse the second link:
--
--   1. `whatsapp_connections.phone_hmac` — a keyed HMAC-SHA256 of the linked
--      number (crypto.phone_hash, PHONE_HMAC_KEY). The phone itself stays
--      ENCRYPTED in phone_number (randomized ciphertext — useless for equality
--      checks); the HMAC is deterministic, so equal numbers compare equal, yet
--      it cannot be reversed without the secret key. No plaintext is stored.
--
--   2. `wa_phone_conflict(p_business, p_hmac)` — a SECURITY DEFINER lookup
--      (modeled on resolve_wa_account, 0013): "does ANY OTHER business already
--      hold this phone?" It is cross-tenant BY DESIGN (that is the whole
--      question), but it exposes ONLY the conflicting business_id — never the
--      phone, status, or any other column. EXECUTE is granted to gateway_role
--      (the internal status-report path that runs the check) only.

-- 1) The deterministic lookup column (nullable — legacy rows backfill on the
--    next status report). Indexed for the equality probe.
ALTER TABLE whatsapp_connections ADD COLUMN IF NOT EXISTS phone_hmac text;
CREATE INDEX IF NOT EXISTS ix_whatsapp_connections_phone_hmac
  ON whatsapp_connections (phone_hmac);

-- 2) The conflict probe. STABLE (read-only), definer-owned, locked search_path.
DROP FUNCTION IF EXISTS wa_phone_conflict(uuid, text);
CREATE FUNCTION wa_phone_conflict(p_business uuid, p_hmac text)
RETURNS uuid
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public, pg_temp
AS $$
  SELECT business_id
  FROM whatsapp_connections
  WHERE p_hmac IS NOT NULL
    AND p_hmac <> ''
    AND phone_hmac = p_hmac
    AND business_id <> p_business
  LIMIT 1
$$;

REVOKE ALL ON FUNCTION wa_phone_conflict(uuid, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION wa_phone_conflict(uuid, text) TO gateway_role;
