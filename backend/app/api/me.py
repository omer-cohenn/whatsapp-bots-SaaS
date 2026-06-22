"""Protected /api/* router — the deny-by-default tenant surface.

The router-level `dependencies=[Depends(current_session)]` IS the enforced
gate: EVERY route under `/api` requires a valid session (401 otherwise). New
protected routes added to this router inherit the gate automatically — no
per-route opt-in to forget.

GET /api/me returns who-am-I + the tenant + the WhatsApp connection status,
matching the frozen contract.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.admin import router as admin_router
from app.api.booking import router as booking_router
from app.api.bot_builder import router as bot_builder_router
from app.api.dashboard import router as dashboard_router
from app.api.google_oauth import router as google_router
from app.api.whatsapp import router as whatsapp_router
from app.core.config import get_settings
from app.core.deps import current_admin, current_business, current_session, current_user
from app.db.session import tenant_connection
from app.models.auth import MeBusiness, MeConnection, MeResponse, MeUser

# The router-level dependency is the gate: no /api/* route is reachable without
# a valid session.
api = APIRouter(prefix="/api", tags=["api"], dependencies=[Depends(current_session)])

# Mount the M4 bot-builder routes under /api/bot/* — they inherit the gate above
# (deny-by-default; no per-route opt-in to forget).
api.include_router(bot_builder_router)

# Mount the M7 dashboard / back-office READ routes (/api/leads, /api/dashboard,
# /api/conversations/*, /api/bot/publish). Same gate, deny-by-default.
api.include_router(dashboard_router)

# Mount the M11 booking ADMIN routes (/api/booking/settings, /api/services/*,
# /api/bookings/*). Same gate, deny-by-default. The PUBLIC booking routes
# (/api/book/*) are mounted separately on the app root — they are NOT gated.
api.include_router(booking_router)

# Mount the M11 Google Calendar connect routes (/api/google/connect|callback|
# status|disconnect). Same gate, deny-by-default — the OAuth callback is reached
# by the already-logged-in owner (the browser carries the session cookie).
api.include_router(google_router)

# Mount the M6a owner WhatsApp admin routes (/api/whatsapp/status|link|qr). Same
# gate, deny-by-default — the tenant is always the verified session business.
api.include_router(whatsapp_router)

# Mount the M12 platform-operator back-office (/api/admin/*). The admin router
# carries its OWN router-level dependency `[Depends(current_admin)]`, so mounting
# it here stacks BOTH gates: the session gate (from `api`) AND the admin gate —
# deny-by-default. This is the one surface that crosses the tenant wall, and
# current_admin (ADMIN_EMAILS) is its only guard.
api.include_router(admin_router)


async def _connection_status(request: Request, business_id: str) -> str:
    """Read the tenant's WhatsApp connection status, defaulting to disconnected.

    Uses a tenant_connection so RLS scopes the read to this business. QR connect
    is a later milestone, so a missing row simply means "disconnected".
    """
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        status_value = await conn.fetchval(
            "SELECT status FROM whatsapp_connections WHERE business_id = $1",
            business_id,
        )
    return status_value or "disconnected"


@api.get("/me", response_model=MeResponse)
async def me(
    request: Request,
    session: dict[str, Any] = Depends(current_session),
    user: dict[str, str] = Depends(current_user),
    business_id: str = Depends(current_business),
) -> MeResponse:
    """Return the authenticated user, their tenant, WhatsApp status + admin flag."""
    status_value = await _connection_status(request, business_id)
    # is_admin is computed LIVE against ADMIN_EMAILS (same rule as current_admin),
    # never read from a stored session flag.
    is_admin = get_settings().is_admin_email(user.get("email"))
    return MeResponse(
        user=MeUser(**user),
        business=MeBusiness(id=business_id, name=session.get("business_name", "")),
        connection=MeConnection(status=status_value),
        is_admin=is_admin,
    )
