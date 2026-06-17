"""FastAPI auth dependencies — the deny-by-default gate.

`current_session` is attached at the router level to the whole `/api/*` group
(see app/api/me.py), so EVERY protected route requires a valid session by
default — no per-route opt-in (that was a bug in the old system). A route that
needs the user or the verified tenant id pulls `current_user` / `current_business`.

The business id returned by `current_business` comes from the SERVER-SIDE
session (set at login from `provision_owner`), so it is already verified to
belong to the authenticated user — it is never read from the client. Pass it
straight to `tenant_connection(pool, business_id)`.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status

from app.services.auth import SESSION_COOKIE_NAME, load_session


async def current_session(request: Request) -> dict[str, Any]:
    """Resolve the session from the cookie, or raise 401.

    This is the enforced gate: read the opaque cookie id, look the session up
    in Redis (refreshing its TTL). Missing or expired → 401.
    """
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    session = await load_session(request.app.state.redis, sid)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated"
        )
    return session


async def current_user(
    session: dict[str, Any] = Depends(current_session),
) -> dict[str, str]:
    """The authenticated user's public profile (from the session)."""
    return {
        "id": session["user_id"],
        "email": session["email"],
        "name": session.get("name", ""),
        "picture": session.get("picture", ""),
    }


async def current_business(
    session: dict[str, Any] = Depends(current_session),
) -> str:
    """The VERIFIED business id for the request (safe for tenant_connection)."""
    return str(session["business_id"])
