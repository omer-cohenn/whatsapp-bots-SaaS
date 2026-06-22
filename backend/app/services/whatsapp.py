"""WhatsApp connection mapping — the tenant ↔ gateway-account bridge (M6a).

Two responsibilities, kept tiny and focused:

  1. `get_connection_by_account(pool, gateway_account_id)` — the INBOUND lookup.
     The webhook is PUBLIC (a shared service token, no user session), so there is
     no tenant context to scope a normal read. We resolve which business owns a
     gateway account via the `resolve_wa_account` SECURITY DEFINER function
     (migration 0013), exactly like booking's `resolve_slug`. It returns ONLY the
     business_id for that exact account (or None) — nothing else, no phone, no
     status. The webhook then opens a normal `tenant_connection(business_id)` so
     every subsequent read/write is RLS-scoped like an authenticated request.

  2. `upsert_connection(pool, business_id, gateway_account_id, phone, status)` —
     the OWNER's "link my number" write. `business_id` is the caller's already-
     verified session tenant (never a client value); the write runs inside
     `tenant_connection(...)` so RLS scopes it to this tenant only. The linked
     phone is PII → ENCRYPTED at rest via `app/core/crypto.py` (the 🔒
     phone_number column) and `key_version` is stamped for rotation. We NEVER log
     the phone, the account id is safe (a server-side routing key), and we never
     return the ciphertext.
"""

from __future__ import annotations

import asyncpg
import httpx

from app.core import crypto
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import tenant_connection

log = get_logger("app.services.whatsapp")

# Internal backend -> gateway send call. Same Docker network, but the gateway
# does a real WhatsApp send, so we allow a touch more than the status/QR proxy
# (which uses 5s). Fail (return False) rather than hang the owner's request.
_SEND_TIMEOUT = 8.0


async def get_connection_by_account(
    pool: asyncpg.Pool, gateway_account_id: str
) -> str | None:
    """Resolve a gateway account id → its owning business_id, or None.

    PUBLIC-path safe: uses the `resolve_wa_account` SECURITY DEFINER function so
    it works with NO tenant context set (the inbound webhook has no session). The
    function bypasses RLS but exposes ONLY the business_id for that exact account
    — never any other column or another tenant's data. Returns None when no
    business has linked that account (caller → "no business", replies=[]).
    """
    async with pool.acquire() as conn:
        business_id = await conn.fetchval(
            "SELECT resolve_wa_account($1)", gateway_account_id
        )
    return str(business_id) if business_id is not None else None


async def upsert_connection(
    pool: asyncpg.Pool,
    business_id: str,
    gateway_account_id: str,
    phone: str | None,
    status: str,
) -> dict[str, str | None]:
    """Record/refresh this tenant's gateway mapping. Returns the saved (safe) shape.

    Inserts the row on first link, or updates it on a re-link. The linked phone is
    encrypted before it touches the DB (the 🔒 phone_number column); `key_version`
    is stamped for rotation. `business_id` is the verified session tenant and is
    included in the INSERT/WHERE so RLS's WITH CHECK matches — the write can only
    ever touch THIS tenant's row. `last_connected_at` is bumped whenever the
    status says we're connected, so the dashboard can show "last linked".

    Returns {gateway_account_id, phone (plaintext echo for the caller), status} —
    NEVER the ciphertext, and the phone is never logged.
    """
    phone_ct = crypto.encrypt_pii(phone)
    connected = status == "connected"

    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            """
            INSERT INTO whatsapp_connections
                (business_id, gateway_account_id, phone_number, status,
                 last_connected_at)
            VALUES ($1, $2, $3, $4,
                    CASE WHEN $5 THEN now() ELSE NULL END)
            ON CONFLICT (business_id) DO UPDATE SET
                gateway_account_id = EXCLUDED.gateway_account_id,
                phone_number       = EXCLUDED.phone_number,
                status             = EXCLUDED.status,
                last_connected_at  = CASE
                    WHEN $5 THEN now()
                    ELSE whatsapp_connections.last_connected_at
                END
            """,
            business_id,
            gateway_account_id,
            phone_ct,
            status,
            connected,
        )

    # Echo the saved values back to the caller (plaintext phone for the owner's
    # own number — never the stored ciphertext, never logged).
    return {
        "gateway_account_id": gateway_account_id,
        "phone": phone,
        "status": status,
    }


async def send_outbound(to: str, text: str) -> bool:
    """Send the owner's manual reply to the customer over WhatsApp (M6a.2).

    Posts to the gateway's internal `/send-bot` endpoint over the Docker network,
    authenticated with the shared X-Gateway-Token header (the same constant the
    inbound webhook checks). `to` is the customer's WhatsApp jid — which IS the
    conversation_id (e.g. '<num>@s.whatsapp.net', or the owner's '@lid' for the
    self-chat) — and `text` is the reply body.

    Best-effort by design: the reply is ALWAYS already queued in the Redis outbox
    by the caller; this send is the on-top delivery attempt. Returns True ONLY on
    a 2xx response whose JSON says {"ok": true}; on ANY failure (gateway down,
    timeout, non-2xx, bad shape) we return False so the caller can report
    "queued but not delivered" instead of erroring the owner's request.

    SAFE logging only: we NEVER log `to` (a phone-derived jid) or `text` (the
    message body) or the token — only that a send failed, with no detail.
    """
    base = get_settings().gateway_base_url.rstrip("/")
    token = get_settings().gateway_api_token.get_secret_value()
    try:
        async with httpx.AsyncClient(timeout=_SEND_TIMEOUT) as client:
            resp = await client.post(
                f"{base}/send-bot",
                headers={"X-Gateway-Token": token},
                json={"to": to, "text": text},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001 — best-effort; never leak details or PII.
        log.warning("gateway /send-bot send failed")
        return False

    return bool(isinstance(data, dict) and data.get("ok") is True)
