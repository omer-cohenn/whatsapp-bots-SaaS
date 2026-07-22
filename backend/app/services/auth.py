"""Google OAuth + opaque server-side sessions (the auth engine).

This module ports the SHAPE of the old `last_bo/bot/auth.py` login flow but
fixes its three real bugs:

  1. OAuth `state` is no longer kept in a process-RAM `set` (which loses every
     pending login on restart and doesn't survive >1 worker). It lives in Redis
     with a short TTL, keyed `oauth:state:{state}`, and is single-use.
  2. The session is NOT signed-cookie-with-user-payload. The cookie carries
     only an opaque, high-entropy id; all real data lives server-side in Redis
     under `session:{sid}`. Logout truly destroys it.
  3. The tenant is a real `business_id` (from `provision_owner`), never the
     user's email.

SECURITY: we never log the OAuth `code`, the access token, or the session id.
Errors raised here are generic on purpose — the API layer turns them into
client-safe responses (no `str(e)` to the user).
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("app.auth")

# --- Cookie + key/TTL constants -------------------------------------------
SESSION_COOKIE_NAME = "bizzup_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60  # ~7 days, sliding (refreshed on each load)
STATE_TTL_SECONDS = 600  # 10 minutes for the OAuth round-trip

_SESSION_KEY_PREFIX = "session:"
_STATE_KEY_PREFIX = "oauth:state:"

# --- Google endpoints ------------------------------------------------------
_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

_HTTP_TIMEOUT = 10.0  # seconds — Google calls should be fast; fail rather than hang.


class AuthError(Exception):
    """Generic auth failure. The API layer maps this to a client-safe error."""


# --- OAuth state (CSRF protection, single-use, Redis-backed) ---------------

async def build_google_auth_url(redis: aioredis.Redis) -> tuple[str, str]:
    """Build the Google consent URL and persist a single-use `state` in Redis.

    Returns (url, state). The state defends against CSRF on the callback: only
    a callback whose `state` we previously issued (and haven't consumed yet)
    is honored.
    """
    settings = get_settings()
    state = secrets.token_urlsafe(32)
    # Store the state with a short TTL; value is a marker, the key IS the token.
    await redis.set(f"{_STATE_KEY_PREFIX}{state}", "1", ex=STATE_TTL_SECONDS)

    params = urlencode(
        {
            "client_id": settings.google_client_id.get_secret_value(),
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
    )
    return f"{_GOOGLE_AUTH_URL}?{params}", state


async def consume_state(redis: aioredis.Redis, state: str) -> bool:
    """Atomically verify+delete an OAuth state. True only if it existed."""
    if not state:
        return False
    # DEL returns the number of keys removed → 1 means it was present & is now
    # consumed (single-use); 0 means unknown/expired/replayed.
    removed = await redis.delete(f"{_STATE_KEY_PREFIX}{state}")
    return removed == 1


# --- Google token + userinfo exchange --------------------------------------

async def exchange_code(code: str) -> dict[str, Any]:
    """Exchange an authorization `code` for Google tokens. Never logs the code."""
    settings = get_settings()
    data = {
        "code": code,
        "client_id": settings.google_client_id.get_secret_value(),
        "client_secret": settings.google_client_secret.get_secret_value(),
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(_GOOGLE_TOKEN_URL, data=data)
            resp.raise_for_status()
            token = resp.json()
    except Exception as exc:  # noqa: BLE001 — log class only, no token/code
        log.warning("oauth token exchange failed", extra={"error": type(exc).__name__})
        raise AuthError("token exchange failed") from exc

    if "access_token" not in token:
        raise AuthError("token response missing access_token")
    return token


async def fetch_userinfo(access_token: str) -> dict[str, Any]:
    """Fetch the user's Google profile. Returns {id(sub), email, name, picture}."""
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            info = resp.json()
    except Exception as exc:  # noqa: BLE001 — never log the token
        log.warning("oauth userinfo fetch failed", extra={"error": type(exc).__name__})
        raise AuthError("userinfo fetch failed") from exc

    # v3 userinfo uses `sub` as the stable Google id.
    sub = info.get("sub")
    email = info.get("email")
    if not sub or not email:
        raise AuthError("userinfo missing required fields")
    return {
        "id": sub,
        "email": email,
        "name": info.get("name", ""),
        "picture": info.get("picture", ""),
    }


# --- Server-side sessions (opaque id in Redis) -----------------------------

async def create_session(
    redis: aioredis.Redis,
    user: dict[str, Any],
    business: dict[str, Any],
    *,
    is_demo: bool = False,
) -> str:
    """Create a server-side session and return its opaque id (the cookie value).

    `user` carries the verified profile (id/email/name/picture). `business`
    carries the verified {id, name}. Only this is persisted — no tokens.

    `is_demo` marks a session minted by the public "המשך בתור דמו" button, which
    has NO credential behind it — anyone on the internet can create one. The flag
    is stamped SERVER-SIDE into the Redis payload, never taken from the client,
    and `app/core/demo_guard.py` reads it to refuse every write. The frontend
    also fakes edits locally so the demo feels alive, but that is UX only: the
    browser is not a security boundary, and a visitor can call the API directly
    with their own cookie. The guard is the control.
    """
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user["id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "picture": user.get("picture", ""),
        "business_id": str(business["id"]),
        "business_name": business.get("name", ""),
        "is_demo": bool(is_demo),
        "created_at": int(time.time()),
    }
    await redis.set(
        f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=SESSION_TTL_SECONDS
    )
    return sid


async def load_session(redis: aioredis.Redis, sid: str | None) -> dict[str, Any] | None:
    """Load a session by id and slide its TTL. None if missing/expired."""
    if not sid:
        return None
    raw = await redis.get(f"{_SESSION_KEY_PREFIX}{sid}")
    if raw is None:
        return None
    # Sliding window: every authenticated request extends the session.
    await redis.expire(f"{_SESSION_KEY_PREFIX}{sid}", SESSION_TTL_SECONDS)
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        # Corrupt session blob — treat as no session.
        return None


async def destroy_session(redis: aioredis.Redis, sid: str | None) -> None:
    """Delete a session server-side (idempotent)."""
    if not sid:
        return
    await redis.delete(f"{_SESSION_KEY_PREFIX}{sid}")


# --- Cookie flag helper ----------------------------------------------------

def cookie_is_secure() -> bool:
    """Secure flag on everywhere EXCEPT dev (so http://localhost works in dev)."""
    return get_settings().app_env != "dev"
