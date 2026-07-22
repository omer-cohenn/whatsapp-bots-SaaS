"""Public /auth/* router — Google login, callback, logout.

Flow (frozen contract):
  GET  /auth/google    -> 302 to Google consent (state stored in Redis)
  GET  /auth/callback  -> verify state, exchange code, provision owner+business,
                          create session, set cookie, 302 to "/"
  POST /auth/logout    -> destroy session + clear cookie, 204

These routes are PUBLIC (no session gate) — they are how a session is created.
Provisioning/lookup call the SECURITY DEFINER SQL functions on a plain
app_role connection (granted to app_role): provision_owner(...) and
get_user_businesses(...). Those functions are owned by the auth-bootstrap
migration; we only call them.

SECURITY: never log the OAuth `code`, tokens, or the session id. All failures
return a generic message to the client (no `str(e)`).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse

from app.core.logging import get_logger
from app.db.session import tenant_connection
from app.services import usage as usage_service
from app.services.auth import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    AuthError,
    build_google_auth_url,
    consume_state,
    cookie_is_secure,
    create_session,
    destroy_session,
    exchange_code,
    fetch_userinfo,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger("app.api.auth")


@router.get("/google")
async def auth_google(request: Request) -> RedirectResponse:
    """Kick off Google OAuth: store a fresh state, 302 to the consent screen."""
    url, _state = await build_google_auth_url(request.app.state.redis)
    # 302 (temporary) redirect to Google.
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
async def auth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
) -> RedirectResponse:
    """Handle Google's redirect back: verify state, log the user in, set cookie."""
    redis = request.app.state.redis

    # Google can redirect back with ?error=access_denied etc. Bail cleanly.
    if error or not code:
        # Diagnostic (safe: booleans + Google's non-secret error code, never the code itself).
        log.warning(
            "oauth callback without a usable code",
            extra={"has_code": bool(code), "has_state": bool(state), "google_error": error or ""},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="login failed")

    # 1) CSRF: the state MUST be one we issued (single-use, consumed here).
    if not await consume_state(redis, state):
        log.warning("oauth callback with invalid/expired state", extra={"has_state": bool(state)})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid state")

    # 2) Exchange the code + fetch the profile.
    try:
        token = await exchange_code(code)
        user = await fetch_userinfo(token["access_token"])
    except AuthError:
        # AuthError already logged the class; keep the client message generic.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="login failed"
        ) from None

    # 3) Provision the owner + auto-create their business on first login.
    #    SECURITY DEFINER function, granted to app_role; returns the business id.
    pool = request.app.state.pg_pool
    try:
        async with pool.acquire() as conn:
            business_id = await conn.fetchval(
                "SELECT provision_owner($1, $2, $3, $4, $5)",
                user["id"],
                user["email"],
                user["name"],
                user["picture"],
                "",
            )
            # Look up the business name for the session/UI.
            rows = await conn.fetch("SELECT * FROM get_user_businesses($1)", user["id"])
    except Exception:  # noqa: BLE001 — never leak DB internals to the client
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="login failed"
        ) from None

    business_name = ""
    for row in rows:
        if str(row.get("id") or row.get("business_id")) == str(business_id):
            business_name = row.get("name") or row.get("business_name") or ""
            break

    # 4) Create the server-side session + set the opaque cookie.
    sid = await create_session(
        redis, user, {"id": business_id, "name": business_name}
    )

    # M12 usage: count a successful login for this tenant. The provision step above
    # used a PLAIN app_role connection (no tenant context), but usage_daily is an
    # RLS table whose WITH CHECK needs current_business_id() set — so we open our
    # OWN short tenant_connection scoped to the just-provisioned business. The
    # business_id comes from provision_owner (server-side), never the client.
    # Best-effort: a counter failure must never break login.
    async with tenant_connection(pool, str(business_id)) as conn:
        await usage_service.bump_safe(conn, str(business_id), usage_service.METRIC_LOGIN)
    redirect = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sid,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=cookie_is_secure(),
        path="/",
    )
    return redirect


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def auth_logout(request: Request, response: Response) -> Response:
    """Destroy the session server-side and clear the cookie."""
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    await destroy_session(request.app.state.redis, sid)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


# --- public demo login -------------------------------------------------------

# The slug of the demo tenant. Resolved SERVER-SIDE: the client never names a
# business, so this route cannot be pointed at a real customer's data by editing
# a request. If the row is missing the route 404s rather than falling back to
# "some business", which is how a demo button turns into a data leak.
DEMO_BUSINESS_SLUG = "chocolate-kingdom-demo"


@router.get("/demo")
async def demo_login(request: Request) -> RedirectResponse:
    """Log the visitor into the read-only demo tenant. NO credential required.

    This is deliberately an open door — it is what the "המשך בתור דמו" button on
    the login screen calls, so anyone can walk in. Three things keep that safe:

      1. The tenant is hard-coded here by slug, never supplied by the caller.
      2. The session is stamped `is_demo`, and `DemoReadOnlyMiddleware` refuses
         every write from it. The visitor can click anything; nothing persists.
      3. The demo user's email is NOT in ADMIN_EMAILS, so `current_admin` keeps
         the platform back-office closed to it. That check reads the live env on
         every request, so this cannot drift out of sync.

    Deliberately NOT rate-limited: the only thing a flood creates is Redis keys
    that expire on their own, and the tenant is fixed, so there is nothing to
    enumerate. If that changes, this is where a limit belongs.
    """
    pool = request.app.state.pg_pool
    redis = request.app.state.redis

    # `businesses` is RLS-protected and there is no tenant context yet — that is
    # precisely what this call is deciding — so a plain SELECT sees nothing.
    # resolve_demo_business is the same minimal SECURITY DEFINER pattern as
    # resolve_booking_slug: it answers one question and exposes nothing else.
    row = await pool.fetchrow(
        "SELECT id, name FROM resolve_demo_business($1)", DEMO_BUSINESS_SLUG
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="demo is not available"
        )

    sid = await create_session(
        redis,
        {
            "id": f"demo:{DEMO_BUSINESS_SLUG}",
            # A non-routable example.com address so this can never collide with a
            # real Google account, and never match an ADMIN_EMAILS entry.
            "email": "demo@example.com",
            "name": "אורח/ת דמו",
            "picture": "",
        },
        {"id": str(row["id"]), "name": row["name"]},
        is_demo=True,
    )

    redirect = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sid,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=cookie_is_secure(),
        path="/",
    )
    return redirect
