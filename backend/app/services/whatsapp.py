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
    last_error: str | None = None,
) -> dict[str, str | None]:
    """Record/refresh this tenant's gateway mapping. Returns the saved (safe) shape.

    Inserts the row on first link, or updates it on a re-link. The linked phone is
    encrypted before it touches the DB (the 🔒 phone_number column); `key_version`
    is stamped for rotation. Alongside the ciphertext we store `phone_hmac` — a
    keyed deterministic hash (crypto.phone_hash) used ONLY for the
    one-number-one-business conflict probe (0027); no plaintext is stored.
    `business_id` is the verified session tenant and is included in the
    INSERT/WHERE so RLS's WITH CHECK matches — the write can only ever touch THIS
    tenant's row. `last_connected_at` is bumped whenever the status says we're
    connected, so the dashboard can show "last linked".

    `last_error`: when given, stamped on the row (e.g. 'phone_conflict' so the
    owner UI can explain a refused link). A clean CONNECTED report clears it.

    Returns {gateway_account_id, phone (plaintext echo for the caller), status} —
    NEVER the ciphertext, and the phone is never logged.
    """
    phone_ct = crypto.encrypt_pii(phone)
    phone_hmac = crypto.phone_hash(phone) if phone else None
    connected = status == "connected"

    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            """
            INSERT INTO whatsapp_connections
                (business_id, gateway_account_id, phone_number, phone_hmac,
                 status, last_connected_at, last_error)
            VALUES ($1, $2, $3, $4, $5,
                    CASE WHEN $6 THEN now() ELSE NULL END,
                    $7)
            ON CONFLICT (business_id) DO UPDATE SET
                gateway_account_id = EXCLUDED.gateway_account_id,
                phone_number       = EXCLUDED.phone_number,
                phone_hmac         = EXCLUDED.phone_hmac,
                status             = EXCLUDED.status,
                last_connected_at  = CASE
                    WHEN $6 THEN now()
                    ELSE whatsapp_connections.last_connected_at
                END,
                -- An explicit error wins; a clean CONNECTED report clears any old
                -- error; otherwise keep whatever was there.
                last_error = COALESCE(
                    $7,
                    CASE WHEN $6 THEN NULL ELSE whatsapp_connections.last_error END
                )
            """,
            business_id,
            gateway_account_id,
            phone_ct,
            phone_hmac,
            status,
            connected,
            last_error,
        )

    # Echo the saved values back to the caller (plaintext phone for the owner's
    # own number — never the stored ciphertext, never logged).
    return {
        "gateway_account_id": gateway_account_id,
        "phone": phone,
        "status": status,
    }


async def get_connection_state(
    pool: asyncpg.Pool, business_id: str
) -> dict[str, str | None] | None:
    """Read THIS tenant's connection row (RLS-scoped). None when unlinked.

    Returns a small safe shape {status, phone} for the owner dashboard: `status`
    is the raw connection status, `phone` is the DECRYPTED own number (owner's own
    — returned only to the authenticated owner, never logged). `business_id` is
    the verified session tenant; the read runs inside `tenant_connection` so RLS
    can only ever return this tenant's own row.
    """
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            "SELECT status, phone_number, last_error FROM whatsapp_connections "
            "WHERE business_id = $1",
            business_id,
        )
    if row is None:
        return None
    return {
        "status": row["status"],
        # Decrypt the own-number ciphertext for the owner (loud on failure).
        "phone": crypto.decrypt_pii(row["phone_number"]),
        # e.g. 'phone_conflict' — lets the owner UI explain a refused link.
        "last_error": row["last_error"],
    }


async def ensure_session(
    pool: asyncpg.Pool, business_id: str
) -> None:
    """Ensure a connection row exists so `wa_list_sessions()` includes this tenant.

    This is the owner's "start/ensure my session" action (POST /link in M6b). Its
    ONLY job is to make sure a `whatsapp_connections` row exists for this business
    (gateway_account_id = business_id): that row is what the gateway polls via
    wa_list_sessions() to know it should open a socket and produce a QR.

    It marks the row 'connecting' when there is no live session yet, but NEVER
    downgrades an already-'connected' row, and NEVER touches the encrypted phone.
    `business_id` is the verified session tenant; the write runs inside
    `tenant_connection` so RLS's WITH CHECK scopes it to this tenant only.
    """
    async with tenant_connection(pool, business_id) as conn:
        # $1 (uuid column) and $2 (text column) carry the SAME value — passing it
        # twice keeps asyncpg's type deduction unambiguous (uuid vs text on one
        # placeholder raises AmbiguousParameterError).
        await conn.execute(
            """
            INSERT INTO whatsapp_connections (business_id, gateway_account_id, status)
            VALUES ($1, $2, 'connecting')
            ON CONFLICT (business_id) DO UPDATE SET
                gateway_account_id = EXCLUDED.gateway_account_id,
                status = CASE
                    WHEN whatsapp_connections.status = 'connected'
                        THEN whatsapp_connections.status
                    ELSE 'connecting'
                END
            """,
            business_id,
            str(business_id),
        )


async def send_outbound(business_id: str, to: str, text: str) -> bool:
    """Send an owner/system message to a customer over WhatsApp (M6a.2 / M6b).

    Posts to the gateway's internal `/send-bot` endpoint over the Docker network,
    authenticated with the shared X-Gateway-Token header (the same constant the
    inbound webhook checks). M6b: the gateway runs ONE socket per business, so we
    MUST name the sending business — `business_id` selects the right socket.
    `to` is the customer's WhatsApp jid — which IS the conversation_id (e.g.
    '<num>@s.whatsapp.net', or the owner's '@lid' for the self-chat) — and `text`
    is the message body.

    Best-effort by design: the reply is ALWAYS already queued in the Redis outbox
    by the caller; this send is the on-top delivery attempt. Returns True ONLY on
    a 2xx response whose JSON says {"ok": true}; on ANY failure (gateway down,
    timeout, non-2xx, bad shape, that business not connected) we return False so
    the caller can report "queued but not delivered" instead of erroring.

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
                json={"business_id": business_id, "to": to, "text": text},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001 — best-effort; never leak details or PII.
        log.warning("gateway /send-bot send failed")
        return False

    return bool(isinstance(data, dict) and data.get("ok") is True)
