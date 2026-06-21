"""PUBLIC booking router — the customer-facing page (M11, NO session gate).

This is the ONE router that is NOT under the `/api` session gate: a customer has
no login. It is mounted directly on the app (see app/main.py) under the same
`/api/book/...` path family the contract froze. Security here rests on three
legs (decision 0011, fixing last_bo's C4 cross-tenant IDOR):

  1. SLUG, not business_id. The tenant is resolved from the public, non-guessable
     `slug` via `booking_service.resolve_slug(...)` (a SECURITY DEFINER lookup,
     migration 0010). A slug that maps to no provisioned business → 404. The
     business_id is NEVER taken from the path/query/body.
  2. RLS still applies. After resolving the slug we open a NORMAL
     `tenant_connection(pool, business_id)`, so every public read/write is
     RLS-scoped exactly like an authenticated request — the public path can only
     ever touch the resolved tenant's rows.
  3. Hardened create. POST is rate-limited per (IP, slug) in Redis, re-checks the
     slot (double-booking guard → 409), generates a non-guessable cancel_token,
     and creates the lead+booking in ONE transaction with all PII encrypted.

We NEVER log PII (name/phone/email/notes), the cancel_token, or the slug body.
Errors are generic.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from app.core.logging import get_logger
from app.db.session import tenant_connection
from app.models.booking import (
    PublicAvailabilityResponse,
    PublicBookingCreateRequest,
    PublicBookingCreateResponse,
    PublicMutationResponse,
    PublicRescheduleRequest,
    PublicServiceItem,
    PublicServicesResponse,
    PublicSlotsResponse,
    SLUG_MAX,
)
from app.services import booking as booking_service
from app.services import booking_alerts

# Mounted at the app root (NOT under the gated /api router) so it stays public.
router = APIRouter(prefix="/api/book", tags=["public-booking"])
log = get_logger("app.api.public_booking")

# A cancel_token in the path is the customer's unguessable handle; bound length.
_TOKEN_MAX = 128

# Rate limit for the public create: at most N booking attempts per (IP, slug)
# inside the window. A SaaS booking page should never see legitimate bursts; this
# blunts scripted abuse / spam without hurting a real customer.
_RATE_LIMIT_MAX = 8
_RATE_LIMIT_WINDOW_SECONDS = 60 * 10  # 10 minutes


async def _resolve_or_404(request: Request, slug: str) -> str:
    """Resolve a slug → business_id, or raise 404. Never echoes the slug."""
    business_id = await booking_service.resolve_slug(request.app.state.pg_pool, slug)
    if business_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="page not found")
    return business_id


def _client_ip(request: Request) -> str:
    """Best-effort client IP for rate-limiting (proxy header first, then peer).

    Used ONLY as a rate-limit bucket key, never logged. Falls back to "unknown"
    so a missing peer can't crash the limiter.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # First hop is the original client when behind a trusted proxy.
        return fwd.split(",")[0].strip()
    client = request.client
    return client.host if client else "unknown"


async def _check_rate_limit(request: Request, slug: str) -> None:
    """Increment + enforce the per-(IP, slug) create limiter in Redis (429).

    A fixed-window counter: first hit sets the TTL; subsequent hits increment.
    Over the cap inside the window → 429. The IP is only ever a bucket key here.
    """
    redis = request.app.state.redis
    key = f"ratelimit:book:{slug}:{_client_ip(request)}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, _RATE_LIMIT_WINDOW_SECONDS)
    if count > _RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many requests, please try again later",
        )


# --- public reads ------------------------------------------------------------


@router.get("/{slug}/services", response_model=PublicServicesResponse)
async def public_services(
    request: Request,
    slug: str = Path(..., min_length=1, max_length=SLUG_MAX),
) -> PublicServicesResponse:
    """The active services bookable on this public page + the welcome message.

    Each service carries its public blurb + optional ₪ price; the page header
    shows the per-business welcome_message (None when the owner hasn't set one).
    """
    business_id = await _resolve_or_404(request, slug)
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        rows = await booking_service.list_services(conn, business_id, active_only=True)
        name = await booking_service.business_display_name(conn, business_id)
        settings = await booking_service.get_settings(conn, business_id)
    return PublicServicesResponse(
        business_name=name,
        welcome_message=settings.get("welcome_message"),
        services=[
            PublicServiceItem(
                id=r["id"],
                name=r["name"],
                duration_minutes=r["duration_minutes"],
                description=r.get("description"),
                price=r.get("price"),
            )
            for r in rows
        ],
    )


@router.get("/{slug}/availability", response_model=PublicAvailabilityResponse)
async def public_availability(
    request: Request,
    slug: str = Path(..., min_length=1, max_length=SLUG_MAX),
    service_id: str = Query(..., min_length=1, max_length=64),
    date_from: str = Query(..., min_length=10, max_length=10, alias="from"),
    date_to: str = Query(..., min_length=10, max_length=10, alias="to"),
) -> PublicAvailabilityResponse:
    """Which days in [from,to] have >=1 free slot for this service.

    Slug-resolved like the other public routes; RLS-scoped. The range is bounded
    server-side (<=62 days) — an invalid or oversized range → 422. No PII here.
    """
    business_id = await _resolve_or_404(request, slug)
    try:
        async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
            dates = await booking_service.compute_availability(
                conn,
                business_id,
                service_id=service_id,
                from_str=date_from,
                to_str=date_to,
            )
    except booking_service.InvalidDateRange:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid date range",
        ) from None
    return PublicAvailabilityResponse(dates=dates)


@router.get("/{slug}/slots", response_model=PublicSlotsResponse)
async def public_slots(
    request: Request,
    slug: str = Path(..., min_length=1, max_length=SLUG_MAX),
    service_id: str = Query(..., min_length=1, max_length=64),
    date: str = Query(..., min_length=10, max_length=10),
) -> PublicSlotsResponse:
    """Bookable LOCAL start times for a chosen service + date (taken slots gone)."""
    business_id = await _resolve_or_404(request, slug)
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        slots = await booking_service.compute_slots(
            conn, business_id, service_id=service_id, date_str=date
        )
    return PublicSlotsResponse(date=date, slots=slots)


# --- public create -----------------------------------------------------------


@router.post(
    "/{slug}",
    response_model=PublicBookingCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def public_create_booking(
    body: PublicBookingCreateRequest,
    request: Request,
    slug: str = Path(..., min_length=1, max_length=SLUG_MAX),
) -> PublicBookingCreateResponse:
    """Create a booking (+ its unified lead) from the public page.

    Rate-limited per (IP, slug). The service re-checks the slot is still offered +
    free (double-booking → 409), generates a non-guessable cancel_token, and
    creates the lead + booking in ONE tenant transaction with all PII encrypted.
    The Google hook fires AFTER commit (best-effort). NEVER logs PII/token.
    """
    business_id = await _resolve_or_404(request, slug)
    await _check_rate_limit(request, slug)

    try:
        async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
            result = await booking_service.create_public_booking(
                conn,
                business_id,
                service_id=body.service_id,
                date_str=body.date,
                time_str=body.time,
                name=body.name,
                phone=body.phone,
                email=body.email,
                notes=body.notes,
            )
    except booking_service.SlotTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="slot no longer available"
        ) from None
    except booking_service.InvalidBookingRequest:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid booking request"
        ) from None

    # Decoupled Google sync AFTER the booking committed (create the event).
    await booking_service.run_google_hook(business_id, result["booking_id"], "created")

    return PublicBookingCreateResponse(
        booking_id=result["booking_id"],
        cancel_token=result["cancel_token"],
        scheduled_at=result["scheduled_at"],
    )


# --- public cancel / reschedule (via cancel_token) ---------------------------


@router.post("/{slug}/cancel/{cancel_token}", response_model=PublicMutationResponse)
async def public_cancel_booking(
    request: Request,
    slug: str = Path(..., min_length=1, max_length=SLUG_MAX),
    cancel_token: str = Path(..., min_length=1, max_length=_TOKEN_MAX),
) -> PublicMutationResponse:
    """Customer-cancel via the cancel_token. 404 if the token isn't this page's.

    Frees the slot for others; fires the Google hook to DELETE the event after
    commit (best-effort). The token is matched together with the resolved tenant,
    so it can only ever touch this business's row. Never logs the token.
    """
    business_id = await _resolve_or_404(request, slug)
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        result = await booking_service.cancel_booking_by_token(
            conn, business_id, cancel_token
        )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="booking not found")

    await booking_service.run_google_hook(business_id, result["booking_id"], "cancelled")
    # Notify the owner's home that a CUSTOMER cancelled (PII-free alert).
    await booking_alerts.push_alert(
        request.app.state.redis, business_id, result["booking_id"], "cancelled"
    )
    return PublicMutationResponse(**result)


@router.post("/{slug}/reschedule/{cancel_token}", response_model=PublicMutationResponse)
async def public_reschedule_booking(
    body: PublicRescheduleRequest,
    request: Request,
    slug: str = Path(..., min_length=1, max_length=SLUG_MAX),
    cancel_token: str = Path(..., min_length=1, max_length=_TOKEN_MAX),
) -> PublicMutationResponse:
    """Customer-reschedule via the cancel_token to a new date+time.

    Re-validates the new slot is offered + free (double-booking → 409). 404 if the
    token isn't this page's. Fires the Google hook to UPDATE the event after
    commit (best-effort). Never logs the token.
    """
    business_id = await _resolve_or_404(request, slug)
    try:
        async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
            result = await booking_service.reschedule_booking_by_token(
                conn, business_id, cancel_token, date_str=body.date, time_str=body.time
            )
    except booking_service.SlotTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="slot no longer available"
        ) from None
    except booking_service.InvalidBookingRequest:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid slot"
        ) from None

    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="booking not found")

    await booking_service.run_google_hook(business_id, result["booking_id"], "rescheduled")
    # Notify the owner's home that a CUSTOMER moved their appointment (PII-free).
    await booking_alerts.push_alert(
        request.app.state.redis, business_id, result["booking_id"], "rescheduled"
    )
    return PublicMutationResponse(**result)
