"""Internal WhatsApp API — the gateway → backend control channel (M6b).

M6b makes WhatsApp multi-tenant: the Node gateway opens ONE Baileys socket per
business and must (a) discover which businesses to open a socket for, (b) load /
save each business's envelope-encrypted Baileys auth_state, and (c) report each
socket's live status back so the owner dashboard can show it. This router is that
control channel.

Trust model — mirrors the webhook, NOT the owner session gate:
  * These are PUBLIC-path routes (the gateway has no user session), mounted on the
    app root outside the gated /api group. They are protected by the SAME shared
    X-Gateway-Token header the inbound webhook checks (constant-time compare).
    Every route rejects with 401 BEFORE doing any work if the token is bad.
  * The `business_id` here is a PATH PARAM supplied by the TRUSTED gateway (unlike
    owner routes, where it comes from the verified session). We still validate it
    is a well-formed uuid, and every DB touch runs through `tenant_connection`, so
    RLS scopes each read/write to that single business's row.

Crown-jewel rule (the whole point of M6b):
  * `whatsapp_credentials.auth_state` is reachable ONLY as gateway_role. This
    router touches it EXCLUSIVELY through `app.state.gw_pool` (the gateway_role
    pool). The app_role pool (`pg_pool`) has ZERO grant on that table and is used
    here only for the non-secret `wa_list_sessions()` lookup.

Logging: we NEVER log auth_state, the phone, the QR, or the token — only
non-PII identifiers (business_id) and coarse status.
"""

from __future__ import annotations

import base64
import hmac
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core import crypto
from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import tenant_connection
from app.models.internal_wa import (
    WaCredsResponse,
    WaSessionsResponse,
    WaStatusRequest,
    WaCredsRequest,
)
from app.services import whatsapp as whatsapp_service

router = APIRouter(prefix="/internal/wa", tags=["internal-wa"])
log = get_logger("app.internal_wa")

# How long a freshly-produced QR lives in Redis before the owner must re-fetch a
# new one. Short by design: a QR is transient linking material, not state.
_QR_TTL_SECONDS = 120

# Sanity bound on the base64 auth_state payload the gateway may PUT. A Baileys
# session is small (tens of KB); this generous cap just stops an absurd body from
# ever reaching the encryptor. ~4 MB of base64.
_MAX_AUTH_STATE_B64 = 4 * 1024 * 1024


def _token_ok(provided: str | None) -> bool:
    """Constant-time compare the provided token against the configured one.

    Identical check to the webhook's — the gateway authenticates to every
    internal route with the same shared X-Gateway-Token. The token is NEVER
    logged or echoed.
    """
    if not provided:
        return False
    expected = get_settings().gateway_api_token.get_secret_value()
    return hmac.compare_digest(provided, expected)


def _require_token(x_gateway_token: str | None) -> None:
    """Reject with 401 before any work if the gateway token is missing/wrong."""
    if not _token_ok(x_gateway_token):
        log.warning("internal-wa auth failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid gateway token"
        )


def _valid_business_id(business_id: str) -> str:
    """Return the canonical uuid string, or 422 if it isn't a well-formed uuid.

    The gateway is trusted, but a malformed path param must never reach a DB
    query — 422 is the correct "bad input" signal here.
    """
    try:
        return str(UUID(business_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="business_id must be a valid uuid",
        )


def _qr_key(business_id: str) -> str:
    """Redis key holding this business's transient QR data URL (owner-facing)."""
    return f"wa:qr:{business_id}"


@router.get("/sessions", response_model=WaSessionsResponse)
async def list_sessions(
    request: Request,
    x_gateway_token: str | None = Header(default=None, alias="X-Gateway-Token"),
) -> WaSessionsResponse:
    """Every business_id that has a WhatsApp connection → the gateway's socket set.

    Cross-tenant by nature (the gateway needs the FULL list), so it goes through
    the `wa_list_sessions()` SECURITY DEFINER function on the app_role pool — the
    ONE place that read is allowed, exposing ONLY business ids (no phone, status,
    or auth_state). No tenant context needed.
    """
    _require_token(x_gateway_token)

    # app_role pool: wa_list_sessions() EXECUTE is granted to app_role (0026).
    async with request.app.state.pg_pool.acquire() as conn:
        rows = await conn.fetch("SELECT wa_list_sessions() AS business_id")

    sessions = [str(r["business_id"]) for r in rows]
    log.info("internal-wa sessions listed", extra={"session_count": len(sessions)})
    return WaSessionsResponse(sessions=sessions)


@router.get("/creds/{business_id}", response_model=WaCredsResponse)
async def get_creds(
    business_id: str,
    request: Request,
    x_gateway_token: str | None = Header(default=None, alias="X-Gateway-Token"),
) -> WaCredsResponse:
    """Load and decrypt this business's Baileys auth_state (crown jewel).

    Reads `whatsapp_credentials` via the gateway_role pool + a tenant connection
    (RLS scopes it to this ONE business). If a row exists we decrypt the envelope
    and base64-encode the plaintext bytes for JSON transport back to the gateway.
    Null when the business has no saved session yet. auth_state is NEVER logged.
    """
    _require_token(x_gateway_token)
    business_id = _valid_business_id(business_id)

    async with tenant_connection(request.app.state.gw_pool, business_id) as conn:
        row = await conn.fetchrow(
            "SELECT auth_state, key_version FROM whatsapp_credentials "
            "WHERE business_id = $1",
            business_id,
        )

    if row is None:
        return WaCredsResponse(auth_state=None, key_version=None)

    # Decrypt the crown-jewel envelope, then base64 for safe JSON transport. The
    # decrypted bytes never touch a log line.
    plaintext = crypto.decrypt_auth_state(row["auth_state"], row["key_version"])
    return WaCredsResponse(
        auth_state=base64.b64encode(plaintext).decode(),
        key_version=row["key_version"],
    )


@router.put("/creds/{business_id}")
async def put_creds(
    business_id: str,
    body: WaCredsRequest,
    request: Request,
    x_gateway_token: str | None = Header(default=None, alias="X-Gateway-Token"),
) -> dict[str, bool]:
    """Encrypt + persist this business's Baileys auth_state (crown jewel).

    The gateway sends the raw auth_state base64-encoded; we decode to bytes,
    envelope-encrypt with the crown KEK, and UPSERT into `whatsapp_credentials`
    via the gateway_role pool (RLS scopes the write to this business). key_version
    is stamped to the current KEK version for rotation. Nothing sensitive logged.
    """
    _require_token(x_gateway_token)
    business_id = _valid_business_id(business_id)

    # Bound the payload before touching the crypto layer, then decode base64 →
    # bytes. Any bad base64 is a client (gateway) error → 422, generic message.
    if len(body.auth_state) > _MAX_AUTH_STATE_B64:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="auth_state too large",
        )
    try:
        plaintext = base64.b64decode(body.auth_state, validate=True)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="auth_state must be valid base64",
        )

    ciphertext = crypto.encrypt_auth_state(plaintext)

    async with tenant_connection(request.app.state.gw_pool, business_id) as conn:
        await conn.execute(
            """
            INSERT INTO whatsapp_credentials (business_id, auth_state, key_version)
            VALUES ($1, $2, $3)
            ON CONFLICT (business_id) DO UPDATE SET
                auth_state  = EXCLUDED.auth_state,
                key_version = EXCLUDED.key_version,
                updated_at  = now()
            """,
            business_id,
            ciphertext,
            crypto.CURRENT_KEY_VERSION,
        )

    log.info("internal-wa creds saved", extra={"business_id": business_id})
    return {"ok": True}


@router.post("/status/{business_id}")
async def report_status(
    business_id: str,
    body: WaStatusRequest,
    request: Request,
    x_gateway_token: str | None = Header(default=None, alias="X-Gateway-Token"),
) -> dict[str, bool]:
    """The gateway reports this business's socket status (+ optional QR).

    Two side effects:
      1. Persist status/phone/last_connected_at on the `whatsapp_connections` row
         via the whatsapp service (phone encrypted at rest). We pass
         gateway_account_id = business_id: in M6b each business IS its own account.
      2. Stash the transient QR in Redis (`wa:qr:{business_id}`, short TTL) so the
         owner dashboard can fetch it. Cleared once connected (or when no QR is
         supplied) so a stale code never lingers.

    The phone and the QR are PII/linking material and are NEVER logged.

    ONE NUMBER = ONE BUSINESS (0027): when the gateway reports CONNECTED with a
    phone, we probe `wa_phone_conflict` — is that number already linked to a
    DIFFERENT business? If so we do NOT record the phone here; we stamp the row
    status='conflict' + last_error='phone_conflict' (so the owner UI explains
    it) and answer {"ok": true, "conflict": true} — the gateway then logs that
    session out (unlinking the device) and returns to a fresh QR.
    """
    _require_token(x_gateway_token)
    business_id = _valid_business_id(business_id)
    gw_pool = request.app.state.gw_pool

    # 0) Conflict probe (only meaningful on a CONNECTED report with a phone).
    if body.status == "connected" and body.phone:
        phone_hmac = crypto.phone_hash(body.phone)
        async with gw_pool.acquire() as conn:
            conflict_biz = await conn.fetchval(
                "SELECT wa_phone_conflict($1, $2)", business_id, phone_hmac
            )
        if conflict_biz is not None:
            # Refuse the link: never store the phone under this business. Mark
            # the row so the owner sees WHY, and tell the gateway to log out.
            await whatsapp_service.upsert_connection(
                gw_pool,
                business_id,
                gateway_account_id=business_id,
                phone=None,
                status="conflict",
                last_error="phone_conflict",
            )
            await request.app.state.redis.delete(_qr_key(business_id))
            # Log WHICH business hit a conflict — never the phone or the hmac.
            log.warning(
                "internal-wa phone conflict — link refused",
                extra={"business_id": business_id},
            )
            return {"ok": True, "conflict": True}

    # 1) Persist the connection state (phone encrypted inside the service). Use
    #    the gateway_role pool: the gateway owns this row in M6b.
    await whatsapp_service.upsert_connection(
        gw_pool,
        business_id,
        gateway_account_id=business_id,
        phone=body.phone,
        status=body.status,
    )

    # 2) Transient QR in Redis for the owner dashboard. Store while linking; clear
    #    it the moment we're connected or the gateway sends no QR, so the owner
    #    never sees a dead code.
    redis = request.app.state.redis
    qr_key = _qr_key(business_id)
    if body.status == "connected" or not body.qr_data_url:
        await redis.delete(qr_key)
    else:
        await redis.set(qr_key, body.qr_data_url, ex=_QR_TTL_SECONDS)

    log.info(
        "internal-wa status reported",
        extra={"business_id": business_id, "status": body.status},
    )
    return {"ok": True, "conflict": False}
