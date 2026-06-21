"""Google Calendar OAuth connect — incremental auth for the OWNER's calendar (M11).

This is SEPARATE from the login flow in `app/services/auth.py`:

  * `auth.py` logs the OWNER in (scopes: openid/email/profile) and creates the
    app session. It does NOT request calendar access.
  * THIS module does INCREMENTAL auth: once logged in, an owner can additionally
    grant `calendar.events` so the app can create/cancel/reschedule events on
    THEIR Google Calendar. It reuses the same GOOGLE_CLIENT_ID/SECRET but has its
    OWN redirect URI (GOOGLE_CALENDAR_REDIRECT_URI) and its own callback route.

What we persist (per business, tenant-scoped, RLS-enforced):
  google_credentials.refresh_token  — the long-lived refresh token, the crown
                                       jewel here. Stored KEK-ENVELOPE encrypted
                                       (same domain as the WhatsApp creds), NEVER
                                       logged or returned.
  google_credentials.scope          — the granted scopes (for display/debug).
  google_credentials.connected_email — which Google account is connected.

VALIDATE-AT-USE (decision 0011 + the agent brief): the stack MUST boot with NO
calendar redirect configured. If the redirect URI is missing we raise a typed
`GoogleConfigError` at the moment an owner tries to connect → the API maps it to
503 "calendar connect not configured". The feature simply isn't available; boot
never blocks.

SECURITY: we never log the OAuth `code`, access/refresh tokens, or the state. The
CSRF state lives in Redis (short TTL, single-use) and is bound to the business id
that started the flow, so a callback can only ever write the tenant that began it.
"""

from __future__ import annotations

import json
import secrets
from typing import Any
from urllib.parse import urlencode

import asyncpg
import httpx
import redis.asyncio as aioredis

from app.core import crypto
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("app.services.google_oauth")

# The single scope the calendar feature needs: create/update/delete events on the
# owner's calendars. We deliberately do NOT ask for full calendar or free/busy.
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"

# Google OAuth endpoints (same as auth.py — kept local so the modules stay
# independent; these are public, non-secret URLs).
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"

# The CSRF state for the calendar connect round-trip. Short-lived + single-use,
# stored under its own key prefix so it never collides with the login state.
_STATE_TTL_SECONDS = 600  # 10 minutes for the consent round-trip
_STATE_KEY_PREFIX = "google:calendar:state:"

_HTTP_TIMEOUT = 10.0  # seconds — Google calls should be fast; fail rather than hang.


class GoogleConfigError(Exception):
    """The calendar feature isn't configured (no redirect URI). → HTTP 503.

    Validate-at-USE: raised only when an owner actually tries to connect, so a
    missing GOOGLE_CALENDAR_REDIRECT_URI degrades the feature without blocking boot.
    """


class GoogleConnectError(Exception):
    """A generic connect/token failure. The API maps this to a client-safe error."""


def calendar_redirect_uri() -> str:
    """Return the configured calendar redirect URI, or raise GoogleConfigError.

    This is the validate-at-use gate: the env var is OPTIONAL at boot, so the
    feature only "exists" once it's set. Empty/blank counts as not configured.
    """
    uri = get_settings().google_calendar_redirect_uri
    if not uri or not uri.strip():
        raise GoogleConfigError("calendar connect not configured")
    return uri.strip()


# --- CSRF state (single-use, Redis-backed, bound to the business) ------------

async def build_connect_url(redis: aioredis.Redis, business_id: str) -> str:
    """Build the Google consent URL for calendar access + store a single-use state.

    The state maps back to the business that started the flow (so the callback
    writes only that tenant). `access_type=offline` + `prompt=consent` force a
    refresh token even on a re-connect. We request the calendar scope plus the
    base identity scopes so the granted credentials also expose the connected
    account's email at token time. Raises GoogleConfigError if not configured.
    """
    settings = get_settings()
    redirect_uri = calendar_redirect_uri()  # validate-at-use

    state = secrets.token_urlsafe(32)
    # Bind the state → business id so the callback can resolve the tenant safely
    # WITHOUT trusting anything from the client. Short TTL, single-use (DEL on read).
    await redis.set(
        f"{_STATE_KEY_PREFIX}{state}",
        str(business_id),
        ex=_STATE_TTL_SECONDS,
    )

    params = urlencode(
        {
            "client_id": settings.google_client_id.get_secret_value(),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            # calendar.events + identity so we also learn the connected email.
            "scope": f"openid email {CALENDAR_SCOPE}",
            "state": state,
            "access_type": "offline",   # we NEED a refresh token (long-lived access)
            "prompt": "consent",        # force the consent screen → guarantees a refresh token
            "include_granted_scopes": "true",  # incremental: keep the login grants too
        }
    )
    return f"{_GOOGLE_AUTH_URL}?{params}"


async def consume_state(redis: aioredis.Redis, state: str) -> str | None:
    """Atomically verify+delete a connect state → the bound business id, or None.

    Returns the business id that started the flow (single-use: the key is deleted
    here). None means unknown/expired/replayed → the callback must reject it.
    """
    if not state:
        return None
    key = f"{_STATE_KEY_PREFIX}{state}"
    # GETDEL is atomic single-use: read the bound business id and remove the key.
    business_id = await redis.getdel(key)
    return business_id or None


# --- token exchange ----------------------------------------------------------

async def exchange_code(code: str) -> dict[str, Any]:
    """Exchange a calendar-consent `code` for tokens. Never logs the code/tokens.

    Returns the raw token dict (access_token, refresh_token?, scope, id_token?).
    A refresh token is only returned when access_type=offline + a fresh consent
    were used (we force both above), so a re-connect always yields one.
    """
    settings = get_settings()
    data = {
        "code": code,
        "client_id": settings.google_client_id.get_secret_value(),
        "client_secret": settings.google_client_secret.get_secret_value(),
        "redirect_uri": calendar_redirect_uri(),
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(_GOOGLE_TOKEN_URL, data=data)
            resp.raise_for_status()
            token = resp.json()
    except Exception as exc:  # noqa: BLE001 — log class only, never the code/token
        log.warning("calendar token exchange failed", extra={"error": type(exc).__name__})
        raise GoogleConnectError("token exchange failed") from exc

    if "refresh_token" not in token:
        # No refresh token = we can't act on behalf of the owner later. This
        # happens if the user had previously consented without revoking; prompt=
        # consent above should prevent it, but fail loud (generic) if it slips.
        raise GoogleConnectError("no refresh token granted")
    return token


def _connected_email_from_token(token: dict[str, Any]) -> str | None:
    """Best-effort extract the connected account's email from the id_token.

    The id_token is a JWT (header.payload.signature). We only read the unsigned
    payload's `email` claim for DISPLAY — it's already from a verified TLS token
    exchange with Google, and it's never used as an auth decision. Returns None
    if absent/unparseable (the email column is optional).
    """
    id_token = token.get("id_token")
    if not id_token or id_token.count(".") != 2:
        return None
    import base64

    try:
        payload_b64 = id_token.split(".")[1]
        # JWT base64url with no padding — re-pad before decoding.
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded).decode())
        email = claims.get("email")
        return email if isinstance(email, str) else None
    except Exception:  # noqa: BLE001 — email is cosmetic; never break connect
        return None


# --- credential storage (KEK-encrypted refresh token, tenant-scoped) ---------

async def store_credentials(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    token: dict[str, Any],
) -> dict[str, Any]:
    """UPSERT this tenant's Google credentials from a token response. RLS-scoped.

    The refresh token is the crown jewel: it is KEK-ENVELOPE encrypted (same
    domain as the WhatsApp auth state) before it touches the DB, so a stolen DB
    dump is useless without the KEK. The column is `text`, so we store the
    envelope's utf-8 JSON. NEVER logs the token. Returns {connected, email, scope}.
    """
    refresh_token = token["refresh_token"]
    # Envelope-encrypt with the crown KEK (bytes in → utf-8 JSON envelope out).
    encrypted = crypto.encrypt_auth_state(refresh_token.encode()).decode()
    scope = token.get("scope") or CALENDAR_SCOPE
    email = _connected_email_from_token(token)

    await conn.execute(
        """
        INSERT INTO google_credentials
            (business_id, refresh_token, scope, connected_email, connected_at)
        VALUES ($1, $2, $3, $4, now())
        ON CONFLICT (business_id) DO UPDATE SET
            refresh_token   = EXCLUDED.refresh_token,
            scope           = EXCLUDED.scope,
            connected_email = EXCLUDED.connected_email,
            connected_at    = now()
        """,
        business_id,
        encrypted,
        scope,
        email,
    )
    return {"connected": True, "email": email, "scope": scope}


async def get_status(conn: asyncpg.Connection, business_id: str) -> dict[str, Any]:
    """Return this tenant's connection status (NEVER the token). RLS-scoped.

    {connected: bool, email: str|None, scope: str|None}. The refresh token is
    deliberately not selected here so it can never accidentally leak to a response.
    """
    row = await conn.fetchrow(
        """
        SELECT connected_email, scope, connected_at
        FROM google_credentials
        WHERE business_id = $1
        """,
        business_id,
    )
    if row is None:
        return {"connected": False, "email": None, "scope": None}
    return {
        "connected": True,
        "email": row["connected_email"],
        "scope": row["scope"],
    }


async def disconnect(conn: asyncpg.Connection, business_id: str) -> bool:
    """Delete this tenant's Google credentials (the row + token). RLS-scoped.

    Returns True if a row was removed. Idempotent: disconnecting when not
    connected is a no-op (returns False). Future events already created on the
    calendar are left untouched — we only drop our stored ability to act.
    """
    result = await conn.execute(
        "DELETE FROM google_credentials WHERE business_id = $1",
        business_id,
    )
    return result.rsplit(" ", 1)[-1] != "0"


async def load_refresh_token(conn: asyncpg.Connection, business_id: str) -> str | None:
    """Decrypt + return this tenant's refresh token, or None if not connected.

    Used ONLY by the calendar service (server-side, just-in-time) to mint an
    access token. RLS-scoped. The plaintext is returned to the caller in-process
    and is NEVER logged. Raises crypto.DecryptionError (loud) if the stored
    ciphertext can't be decrypted — we never silently hand back garbage.
    """
    row = await conn.fetchrow(
        "SELECT refresh_token FROM google_credentials WHERE business_id = $1",
        business_id,
    )
    if row is None or not row["refresh_token"]:
        return None
    # KEK-envelope decrypt (bytes out → utf-8 token string).
    return crypto.decrypt_auth_state(row["refresh_token"].encode()).decode()
