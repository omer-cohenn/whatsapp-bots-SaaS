"""Protected /api/* booking admin router — the owner's calendar back-office (M11).

Mounted under the gated `/api` group (see app/api/me.py), so every route here
inherits the deny-by-default session gate. Endpoints (decision 0011):

  GET  /api/booking/settings        → this tenant's booking config.
  PUT  /api/booking/settings        → update working hours + availability rules.
  GET  /api/services                → list this tenant's services.
  POST /api/services                → create a service.
  PATCH/DELETE /api/services/{id}   → update / delete a service.
  GET  /api/bookings                → list bookings (status + date filters, PII
                                       decrypted for the owner).
  PATCH /api/bookings/{id}          → set status and/or reschedule.

Tenant safety on EVERY route (mirrors dashboard.py):
  * business id comes from `current_business` (server session) ONLY;
  * Postgres reads/writes go through `tenant_connection(...)` so RLS scopes them;
  * client PII is decrypted for the OWNER in responses and is NEVER logged;
  * a foreign / unknown id returns 404 (RLS-scoped UPDATE/SELECT matched no row).

The Google agent's calendar routes live in their own router; booking mutations
here fire the decoupled `run_google_hook(...)` AFTER the row commits.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status

from app.core.crypto import DecryptionError
from app.core.deps import current_business
from app.core.logging import get_logger
from app.db.session import tenant_connection
from app.models.booking import (
    BookingItem,
    BookingsResponse,
    BookingSettings,
    BookingUpdateRequest,
    BookingUpdateResponse,
    HoursRange,
    ServiceCreateRequest,
    ServiceItem,
    ServicesResponse,
    ServiceUpdateRequest,
    BookingAlertItem,
    BookingAlertsResponse,
    WelcomeGenerateRequest,
    WelcomeGenerateResponse,
)
from app.services import booking as booking_service
from app.services import booking_alerts
from app.services import booking_reminders
from app.services import booking_welcome
from app.services import usage as usage_service

router = APIRouter(tags=["booking"])
log = get_logger("app.api.booking")

# A service/booking id is a UUID in the path; bound its length defensively (the
# service still scopes every query by business_id, so this is just hygiene).
_ID_MAX = 64


# --- booking settings --------------------------------------------------------


@router.get("/booking/settings", response_model=BookingSettings)
async def get_booking_settings(
    request: Request,
    business_id: str = Depends(current_business),
) -> BookingSettings:
    """This tenant's booking config (creates a default row + slug on first read)."""
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        data = await booking_service.get_settings(conn, business_id)
    return BookingSettings(**_settings_for_model(data))


@router.put("/booking/settings", response_model=BookingSettings)
async def put_booking_settings(
    body: BookingSettings,
    request: Request,
    business_id: str = Depends(current_business),
) -> BookingSettings:
    """Update working hours + availability rules. slug/timezone are server-owned.

    The request's `slug`/`timezone` (if any) are IGNORED — the service never
    overwrites them from the body. working_hours is the validated weekday→ranges
    shape; the service stores it as jsonb.
    """
    working_hours = {
        day: [r.model_dump() for r in ranges]
        for day, ranges in body.working_hours.items()
    }
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        data = await booking_service.update_settings(
            conn,
            business_id,
            working_hours=working_hours,
            min_notice_minutes=body.min_notice_minutes,
            buffer_minutes=body.buffer_minutes,
            max_days_ahead=body.max_days_ahead,
            meet_enabled=body.meet_enabled,
            welcome_message=body.welcome_message,
        )
    return BookingSettings(**_settings_for_model(data))


def _settings_for_model(data: dict) -> dict:
    """Shape a service settings dict into the BookingSettings model kwargs."""
    return {
        "slug": data.get("slug"),
        "timezone": data.get("timezone"),
        "working_hours": {
            day: [HoursRange(**r) for r in ranges]
            for day, ranges in (data.get("working_hours") or {}).items()
        },
        "min_notice_minutes": data["min_notice_minutes"],
        "buffer_minutes": data["buffer_minutes"],
        "max_days_ahead": data["max_days_ahead"],
        "meet_enabled": data["meet_enabled"],
        "welcome_message": data.get("welcome_message"),
    }


# --- AI welcome-message generator (preview only; not persisted here) ----------


@router.post("/booking/welcome/generate", response_model=WelcomeGenerateResponse)
async def generate_welcome_message(
    body: WelcomeGenerateRequest,
    request: Request,
    business_id: str = Depends(current_business),
) -> WelcomeGenerateResponse:
    """Generate a short warm Hebrew welcome for the public booking page.

    Uses the business display name + its ACTIVE service names (read RLS-scoped)
    and an optional tone hint. 503 if Gemini is unset, 502 if the call fails. The
    owner previews/edits the result, then saves it via PUT /api/booking/settings
    — we do NOT persist it here. Never logs the key or output.
    """
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        name = await booking_service.business_display_name(conn, business_id)
        services = await booking_service.list_services(conn, business_id, active_only=True)
    service_names = [s["name"] for s in services]

    try:
        message = await booking_welcome.generate_welcome(name, service_names, body.tone)
    except booking_welcome.WelcomeNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI is not configured",
        ) from None
    except booking_welcome.WelcomeGenerateError:
        log.warning("welcome generate ai call failed")  # no key / no output
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI is temporarily unavailable",
        ) from None

    # M13: count one successful AI call for this tenant (the Gemini call returned).
    # usage_daily is RLS-scoped, so open a short tenant_connection just for the
    # counter. Best-effort: bump_safe swallows any error — never break the request.
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        await usage_service.bump_safe(conn, business_id, usage_service.METRIC_AI_CALL)

    return WelcomeGenerateResponse(message=message)


# --- services CRUD -----------------------------------------------------------


@router.get("/services", response_model=ServicesResponse)
async def list_services(
    request: Request,
    business_id: str = Depends(current_business),
) -> ServicesResponse:
    """List this tenant's services (newest first)."""
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        rows = await booking_service.list_services(conn, business_id)
    return ServicesResponse(services=[ServiceItem(**r) for r in rows])


@router.post("/services", response_model=ServiceItem, status_code=status.HTTP_201_CREATED)
async def create_service(
    body: ServiceCreateRequest,
    request: Request,
    business_id: str = Depends(current_business),
) -> ServiceItem:
    """Create a service for this tenant."""
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        row = await booking_service.create_service(
            conn,
            business_id,
            name=body.name,
            duration_minutes=body.duration_minutes,
            active=body.active,
            description=body.description,
            price=body.price,
            image_url=body.image_url,
        )
    return ServiceItem(**row)


@router.patch("/services/{service_id}", response_model=ServiceItem)
async def update_service(
    body: ServiceUpdateRequest,
    request: Request,
    service_id: str = Path(..., min_length=1, max_length=_ID_MAX),
    business_id: str = Depends(current_business),
) -> ServiceItem:
    """Partial-update a service. 404 if the id isn't this tenant's.

    description/price/image_url are nullable: we forward whether each was PRESENT
    in the body (model_fields_set) so an explicit null clears the column, while an
    omitted field is left untouched.
    """
    sent = body.model_fields_set
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        row = await booking_service.update_service(
            conn,
            business_id,
            service_id,
            name=body.name,
            duration_minutes=body.duration_minutes,
            active=body.active,
            description=body.description,
            price=body.price,
            image_url=body.image_url,
            set_description="description" in sent,
            set_price="price" in sent,
            set_image_url="image_url" in sent,
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="service not found")
    return ServiceItem(**row)


@router.delete(
    "/services/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_service(
    request: Request,
    service_id: str = Path(..., min_length=1, max_length=_ID_MAX),
    business_id: str = Depends(current_business),
) -> Response:
    """Delete a service. 404 if not this tenant's. Past bookings keep their history."""
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        deleted = await booking_service.delete_service(conn, business_id, service_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="service not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- bookings (list + admin update) ------------------------------------------


@router.get("/bookings", response_model=BookingsResponse)
async def list_bookings(
    request: Request,
    business_id: str = Depends(current_business),
    status_filter: Literal["pending", "confirmed", "cancelled", "completed"] | None = Query(
        None, alias="status"
    ),
    date_from: str | None = Query(None, max_length=10, alias="from"),
    date_to: str | None = Query(None, max_length=10, alias="to"),
    include_test: bool = Query(False),
) -> BookingsResponse:
    """List this tenant's bookings (newest first), decrypted for the owner.

    Filters: status, from/to as LOCAL YYYY-MM-DD days (inclusive). `is_test`
    excluded unless include_test=true. A stored-PII decrypt mismatch fails
    loud-but-generic (no str(e), no plaintext) exactly like the leads list.
    """
    try:
        async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
            rows = await booking_service.list_bookings(
                conn,
                business_id,
                status=status_filter,
                date_from=date_from,
                date_to=date_to,
                include_test=include_test,
            )
    except DecryptionError:
        log.error("booking decryption failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="could not read bookings",
        ) from None
    return BookingsResponse(bookings=[BookingItem(**r) for r in rows])


@router.patch("/bookings/{booking_id}", response_model=BookingUpdateResponse)
async def update_booking(
    body: BookingUpdateRequest,
    request: Request,
    booking_id: str = Path(..., min_length=1, max_length=_ID_MAX),
    business_id: str = Depends(current_business),
) -> BookingUpdateResponse:
    """Owner update: set status and/or reschedule a booking.

    A reschedule re-checks slot availability (double-booking guard → 409). 404 if
    the id isn't this tenant's. On success the Google hook fires AFTER commit
    (create/update/delete the calendar event) — best-effort, never breaks here.
    """
    try:
        async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
            result = await booking_service.admin_update_booking(
                conn,
                business_id,
                booking_id,
                status=body.status,
                date_str=body.date,
                time_str=body.time,
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

    # Decoupled Google sync AFTER the row committed. A cancelled status deletes
    # the calendar event; status/time changes update it. Best-effort — a failure
    # is swallowed inside the hook runner (decision 0011: degrade gracefully).
    action = "cancelled" if body.status == "cancelled" else "rescheduled"
    await booking_service.run_google_hook(business_id, result["booking_id"], action)

    # When the OWNER confirms a booking, queue a confirmation message so the
    # customer hears about it from the business's WhatsApp number. It waits in the
    # booking outbox and is delivered for real once M6 (WhatsApp) is connected.
    if body.status == "confirmed":
        await booking_reminders.queue_booking_message(
            request.app.state.redis,
            business_id,
            result["booking_id"],
            "approved",
            result["scheduled_at"],
        )

    return BookingUpdateResponse(**result)


@router.get("/bookings/alerts", response_model=BookingAlertsResponse)
async def booking_alerts_feed(
    request: Request,
    business_id: str = Depends(current_business),
) -> BookingAlertsResponse:
    """Home notifications: bookings a CUSTOMER cancelled/rescheduled (newest first).

    The PII-free alerts come from this tenant's Redis inbox; each is resolved back
    to its booking under RLS so the owner sees the (decrypted) name + service +
    time. Alerts whose booking no longer exists are skipped. PII is never logged.
    """
    raw = await booking_alerts.list_alerts(request.app.state.redis, business_id)
    if not raw:
        return BookingAlertsResponse(alerts=[])

    items: list[BookingAlertItem] = []
    try:
        async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
            for a in raw:
                booking = await booking_service.get_booking(conn, business_id, a["booking_id"])
                if booking is None:
                    continue  # the booking was deleted; drop the stale alert
                items.append(
                    BookingAlertItem(
                        booking_id=a["booking_id"],
                        kind=a.get("kind", "cancelled"),
                        at=a.get("at"),
                        client_name=booking.get("client_name"),
                        service_name=booking.get("service_name"),
                        scheduled_at=booking.get("scheduled_at"),
                    )
                )
    except DecryptionError:
        log.error("booking alert decryption failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="could not read alerts",
        ) from None

    return BookingAlertsResponse(alerts=items)
