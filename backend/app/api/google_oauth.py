"""Protected /api/google/* router — connect the OWNER's Google Calendar (M11).

Mounted under the gated `/api` group (see app/api/me.py), so every route here
inherits the deny-by-default session gate — INCLUDING the callback. That's
intentional: the owner is logged in when Google redirects back (same-site browser
navigation carries the session cookie), so the callback is reachable only by an
authenticated owner. Routes (decision 0011):

  GET  /api/google/connect    → the Google consent URL (calendar.events scope).
  GET  /api/google/callback   → verify state, exchange code, store the KEK-
                                encrypted refresh token, redirect back to the app.
  GET  /api/google/status     → connected? + which account (NEVER the token).
  POST /api/google/disconnect → delete the stored credentials/token.

Tenant safety on EVERY route:
  * the business id comes from `current_business` (server session) ONLY;
  * the callback ALSO binds the OAuth state → the business that started the flow
    and refuses a state that doesn't match the session (defense in depth), so a
    callback can only ever write the tenant that began the connect;
  * the refresh token is stored KEK-encrypted and is NEVER logged or returned.

VALIDATE-AT-USE: if GOOGLE_CALENDAR_REDIRECT_URI is not configured, connect/
callback raise GoogleConfigError → 503 "calendar connect not configured". The
feature is simply unavailable; the app still boots + runs without it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from app.core.config import get_settings
from app.core.deps import current_business
from app.core.logging import get_logger
from app.db.session import tenant_connection
from app.models.google import (
    GoogleConnectResponse,
    GoogleDisconnectResponse,
    GoogleStatusResponse,
)
from app.services import google_oauth

router = APIRouter(prefix="/google", tags=["google"])
log = get_logger("app.api.google_oauth")

# Where to send the owner's browser AFTER the connect round-trip (success or
# handled failure). The SPA shows the connect state from GET /api/google/status.
_RETURN_PATH = "/settings/calendar"


@router.get("/connect", response_model=GoogleConnectResponse)
async def google_connect(
    request: Request,
    business_id: str = Depends(current_business),
) -> GoogleConnectResponse:
    """Build the Google consent URL for calendar access (state bound to this tenant).

    Returns the URL as JSON; the SPA drives the redirect. 503 if the calendar
    feature isn't configured (no redirect URI) — validate-at-use, never at boot.
    """
    try:
        url = await google_oauth.build_connect_url(request.app.state.redis, business_id)
    except google_oauth.GoogleConfigError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="calendar connect not configured",
        ) from None
    return GoogleConnectResponse(auth_url=url)


@router.get("/callback")
async def google_callback(
    request: Request,
    business_id: str = Depends(current_business),
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    """Handle Google's redirect back: verify state, exchange code, store the token.

    On success the KEK-encrypted refresh token is saved for this tenant and the
    browser is redirected back into the app. On a handled failure we still
    redirect back (with ?google=error) so the SPA can show a friendly message —
    we never dump an error to the raw browser. NEVER logs the code/token.
    """
    redis = request.app.state.redis

    # Google can redirect back with ?error=access_denied (owner declined). Bail
    # cleanly back into the app — this is a normal user action, not a server error.
    if error or not code:
        log.info(
            "calendar callback without a usable code",
            extra={"has_code": bool(code), "has_state": bool(state), "google_error": error or ""},
        )
        return _back("error")

    # 1) CSRF: the state must be one we issued AND it must be bound to THIS tenant.
    #    consume_state is single-use; the bound business id defends against a
    #    cross-tenant callback even if a session somehow differed.
    bound_business = await google_oauth.consume_state(redis, state)
    if bound_business is None or bound_business != business_id:
        log.warning("calendar callback with invalid/mismatched state")
        return _back("error")

    # 2) Exchange the code for tokens (must include a refresh token).
    try:
        token = await google_oauth.exchange_code(code)
    except google_oauth.GoogleConfigError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="calendar connect not configured",
        ) from None
    except google_oauth.GoogleConnectError:
        # Already logged the class generically; keep the user message friendly.
        return _back("error")

    # 3) Store the credentials (KEK-encrypted refresh token), tenant-scoped.
    try:
        async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
            await google_oauth.store_credentials(conn, business_id, token=token)
    except Exception:  # noqa: BLE001 — never leak DB internals / the token
        log.warning("calendar credential store failed")
        return _back("error")

    return _back("connected")


@router.get("/status", response_model=GoogleStatusResponse)
async def google_status(
    request: Request,
    business_id: str = Depends(current_business),
) -> GoogleStatusResponse:
    """Is Google Calendar connected for this tenant? (Never returns the token.)"""
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        data = await google_oauth.get_status(conn, business_id)
    return GoogleStatusResponse(**data)


@router.post("/disconnect", response_model=GoogleDisconnectResponse)
async def google_disconnect(
    request: Request,
    business_id: str = Depends(current_business),
) -> GoogleDisconnectResponse:
    """Delete this tenant's stored Google credentials (idempotent)."""
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        await google_oauth.disconnect(conn, business_id)
    return GoogleDisconnectResponse(connected=False)


def _back(result: str) -> RedirectResponse:
    """Redirect the owner's browser back into the SPA with a result flag.

    Uses PUBLIC_BASE_URL (the app origin) so the redirect lands on the frontend,
    not the API. `result` is "connected" | "error" — the SPA reads it to show a
    toast, then refreshes GET /api/google/status for the real state.
    """
    base = get_settings().public_base_url.rstrip("/")
    return RedirectResponse(
        url=f"{base}{_RETURN_PATH}?google={result}",
        status_code=status.HTTP_302_FOUND,
    )
