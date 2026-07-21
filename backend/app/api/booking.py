"""Protected /api/* booking admin router — the owner's calendar back-office (M11).

Mounted under the gated `/api` group (see app/api/me.py), so every route here
inherits the deny-by-default session gate. Endpoints (decision 0011):

  GET  /api/booking/settings        → this tenant's booking config.
  PUT  /api/booking/settings        → update working hours + availability rules.
  GET  /api/booking/page            → the M20 business-page fields + gallery.
  PUT  /api/booking/page            → partial-update the page fields.
  POST /api/booking/images          → upload one gallery image (multipart).
  PATCH/DELETE /api/booking/images/{id} → caption+order / delete row AND file.
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

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)

from app.core.crypto import DecryptionError
from app.core.deps import current_business
from app.core.logging import get_logger
from app.db.session import tenant_connection
from app.models.booking import (
    MAX_CAPTION_CHARS,
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
    BusinessImageItem,
    BusinessImageUpdateRequest,
    BusinessPageResponse,
    BusinessPageUpdateRequest,
    WelcomeGenerateRequest,
    WelcomeGenerateResponse,
)
from app.services import booking as booking_service
from app.services import business_images as image_storage
from app.services import booking_alerts
from app.services import booking_reminders
from app.services import booking_welcome
from app.services import usage as usage_service

router = APIRouter(tags=["booking"])
log = get_logger("app.api.booking")

# A service/booking id is a UUID in the path; bound its length defensively (the
# service still scopes every query by business_id, so this is just hygiene).
_ID_MAX = 64

# How many bytes we pull off an image upload per chunk while enforcing the size
# cap. 64 KiB keeps the loop cheap without adding a meaningful buffer of its own.
_UPLOAD_CHUNK = 64 * 1024


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


# --- M20 business page: the hero fields + the photo gallery -------------------
#
# Two resources, one tenant rule. `current_business` is the ONLY source of the
# business id on every route below; nothing reads one from a path, query or body.
# The page fields live on `booking_settings`; the gallery rows live in
# `business_images`; the image BYTES live on the server's disk and are served by
# Caddy at /media/{storage_path} — FastAPI never streams an image (the 1 GB box
# cannot afford it, and static files are what a reverse proxy is for).
#
# We never log a caption, an original filename, or a storage path (a path
# contains the business id).


def _page_response(page: dict, name: str, images: list[dict]) -> BusinessPageResponse:
    """Shape the page dict + gallery rows into the owner response model."""
    return BusinessPageResponse(
        slug=page.get("slug"),
        business_name=name,
        tagline=page.get("tagline"),
        about=page.get("about"),
        address=page.get("address"),
        phone=page.get("phone"),
        whatsapp=page.get("whatsapp"),
        instagram_url=page.get("instagram_url"),
        waze_url=page.get("waze_url"),
        logo_url=page.get("logo_url"),
        page_theme=page.get("page_theme") or {},
        images=[BusinessImageItem(**r) for r in images],
        updated_at=page.get("updated_at"),
    )


@router.get("/booking/page", response_model=BusinessPageResponse)
async def get_business_page(
    request: Request,
    business_id: str = Depends(current_business),
) -> BusinessPageResponse:
    """The owner's business-page settings + the full gallery, in display order.

    Creates the settings row (and its slug) on first read, exactly like
    GET /api/booking/settings does, so the wizard always has a public link to
    show even for a business that has never opened the booking tab.
    """
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        page = await booking_service.get_page(conn, business_id)
        name = await booking_service.business_display_name(conn, business_id)
        images = await booking_service.list_images(conn, business_id)
    return _page_response(page, name, images)


@router.put("/booking/page", response_model=BusinessPageResponse)
async def put_business_page(
    body: BusinessPageUpdateRequest,
    request: Request,
    business_id: str = Depends(current_business),
) -> BusinessPageResponse:
    """Partial-update the page fields. Omitted = untouched, explicit null = cleared.

    Follows the house pattern from PATCH /api/services/{id}: `model_fields_set`
    is what distinguishes "the key was absent" from "the key was sent as null".
    That distinction is the feature here — clearing `phone` is how the owner
    REMOVES the call button from the hero (empty field ⇒ no button, decision
    0028), and an omit-only implementation could never express it.

    `slug` is server-owned and not accepted (extra keys are a 422, not a silent
    no-op). `business_name` IS accepted and writes through to `businesses.name` —
    the account is named from the Google profile at signup, so a solo owner's
    public page carries their personal name until they rename it here.
    """
    sent = body.model_fields_set
    fields = {
        name: getattr(body, name)
        for name in (
            "tagline",
            "about",
            "address",
            "phone",
            "whatsapp",
            "instagram_url",
            "waze_url",
            "logo_url",
        )
        if name in sent
    }

    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        # The name lives on `businesses`, so it is a separate write — done inside
        # the SAME tenant-bound connection so both land under one RLS context.
        if "business_name" in sent and body.business_name:
            await booking_service.rename_business(conn, business_id, body.business_name)
        page = await booking_service.update_page(
            conn,
            business_id,
            fields=fields,
            page_theme=body.page_theme,
            set_page_theme="page_theme" in sent,
        )
        name = await booking_service.business_display_name(conn, business_id)
        images = await booking_service.list_images(conn, business_id)

    if page is None:  # pragma: no cover — get_page bootstraps the row first
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="page not found"
        )
    return _page_response(page, name, images)


async def _read_capped_image(upload: UploadFile) -> bytes:
    """Read the upload into memory, aborting with 413 the moment it passes the cap.

    FastAPI has already spooled the body to a temp file, so the request never sat
    whole in RAM. We materialise it once, bounded — we stop reading at the first
    chunk that crosses `MAX_IMAGE_BYTES`, so an oversized upload never allocates
    past the limit even if the client lied about Content-Length.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > image_storage.MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    "התמונה גדולה מדי (עד "
                    f"{image_storage.MAX_IMAGE_BYTES // (1024 * 1024)}MB לתמונה)"
                ),
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="הקובץ ריק"
        )
    return b"".join(chunks)


@router.post("/booking/logo", response_model=BusinessPageResponse)
async def upload_business_logo(
    request: Request,
    file: UploadFile = File(...),
    business_id: str = Depends(current_business),
) -> BusinessPageResponse:
    """Upload the round hero logo (M20 revision).

    `logo_url` used to be a text field the owner had to paste a URL into, which
    assumed they host an image somewhere — most do not. The logo is now uploaded
    exactly like a gallery image and we store the resulting `/media/...` path.

    Deliberately NOT a `business_images` row: the logo is not part of the gallery
    and must never appear in it, so it is only referenced by `logo_url`. It also
    does NOT count against the 40-image cap, which is about the gallery.

    Same defences as the gallery upload — size streamed to a 413, content sniffed
    to a 415, uuid filename, extension from the magic bytes. The PREVIOUS logo
    file is deleted after the new one is saved, so replacing a logo repeatedly
    cannot quietly fill the disk.
    """
    payload = await _read_capped_image(file)

    try:
        storage_path, _mime, _size = image_storage.save_image(
            business_id, payload, file.content_type
        )
    except image_storage.ImageRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from None
    except image_storage.ImageStorageError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="שמירת הלוגו נכשלה. נסו שוב.",
        ) from None

    new_url = f"/media/{storage_path}"
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        previous = await booking_service.get_page(conn, business_id)
        page = await booking_service.update_page(
            conn, business_id, fields={"logo_url": new_url}
        )
        name = await booking_service.business_display_name(conn, business_id)
        images = await booking_service.list_images(conn, business_id)

    # Only now that the new path is committed, drop the old file. Best-effort:
    # an orphaned file is untidy, a failed request over it would be worse.
    old_url = (previous or {}).get("logo_url") or ""
    if old_url.startswith("/media/") and old_url != new_url:
        image_storage.delete_image(old_url[len("/media/"):])

    return _page_response(page, name, images)


@router.post(
    "/booking/images",
    response_model=BusinessImageItem,
    status_code=status.HTTP_201_CREATED,
)
async def upload_business_image(
    request: Request,
    file: UploadFile = File(...),
    caption: str | None = Form(default=None),
    business_id: str = Depends(current_business),
) -> BusinessImageItem:
    """Upload ONE gallery image (multipart/form-data).

    Defence order, cheapest and most dangerous checks first:
      1. the 40-image cap, counted in the DATABASE under RLS → 422. The UI's own
         limit is a courtesy; THIS is the control. A tenant cannot buy itself
         more disk by patching the frontend.
      2. the size cap, enforced while streaming → 413.
      3. the content sniff → 415. The declared type and the uploaded filename are
         BOTH ignored: the extension is derived from the magic bytes, and the
         name is a fresh uuid4. An .html file renamed photo.png is rejected here.
      4. write the file, then INSERT the row — and if the INSERT fails, unlink the
         file so we never leave bytes on disk that nothing references.

    `caption` is optional; `sort_order` is not accepted on upload — a new image
    always lands at the END of the gallery, and the owner re-orders with PATCH.
    """
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        existing = await booking_service.count_images(conn, business_id)
    if existing >= image_storage.MAX_IMAGES_PER_BUSINESS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"אפשר להעלות עד {image_storage.MAX_IMAGES_PER_BUSINESS} תמונות. "
                "מחקו תמונה קיימת כדי להוסיף חדשה."
            ),
        )

    payload = await _read_capped_image(file)

    try:
        storage_path, mime_type, size_bytes = image_storage.save_image(
            business_id, payload, file.content_type
        )
    except image_storage.ImageRejected as exc:
        # The Hebrew message from the service is safe to show: it never contains
        # anything the client sent.
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)
        ) from None
    except image_storage.ImageStorageError:
        log.error("gallery upload failed", extra={"business_id": business_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to store image",
        ) from None
    finally:
        del payload  # drop the bytes before the DB round-trip

    caption = (caption or None) and caption.strip()[:MAX_CAPTION_CHARS] or None

    try:
        async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
            row = await booking_service.create_image(
                conn,
                business_id,
                storage_path=storage_path,
                mime_type=mime_type,
                size_bytes=size_bytes,
                caption=caption,
                sort_order=None,
            )
    except Exception:
        # The bytes are on disk but the row failed — remove the file so the
        # volume never accumulates files nothing can reference or delete.
        try:
            image_storage.delete_image(storage_path)
        except Exception:  # noqa: BLE001 — best-effort cleanup, never mask the 500
            log.error("orphaned image cleanup failed", extra={"business_id": business_id})
        log.error("gallery row insert failed", extra={"business_id": business_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to record image",
        ) from None

    return BusinessImageItem(**row)


@router.patch("/booking/images/{image_id}", response_model=BusinessImageItem)
async def update_business_image(
    body: BusinessImageUpdateRequest,
    request: Request,
    image_id: str = Path(..., min_length=1, max_length=_ID_MAX),
    business_id: str = Depends(current_business),
) -> BusinessImageItem:
    """Set an image's caption and/or its position in the gallery.

    404 when the id isn't this tenant's — the UPDATE is scoped by business_id (on
    top of RLS), so a foreign id simply matches no row. We return 404 rather than
    403 on purpose: a 403 would confirm the id exists in someone else's gallery.
    """
    sent = body.model_fields_set
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        row = await booking_service.update_image(
            conn,
            business_id,
            image_id,
            caption=body.caption,
            sort_order=body.sort_order,
            set_caption="caption" in sent,
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="image not found")
    return BusinessImageItem(**row)


@router.delete(
    "/booking/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_business_image(
    request: Request,
    image_id: str = Path(..., min_length=1, max_length=_ID_MAX),
    business_id: str = Depends(current_business),
) -> Response:
    """Delete a gallery image: the ROW first, then the FILE from disk. 404 if foreign.

    Row-then-file is deliberate. The row is the source of truth, so if the unlink
    fails we are left with an invisible orphan file (clutter, costs a few KB)
    rather than a row rendering as a broken image on the public page. The unlink
    is therefore best-effort and never turns a successful delete into a 500.
    """
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        storage_path = await booking_service.delete_image_row(
            conn, business_id, image_id
        )
    if storage_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="image not found")

    try:
        image_storage.delete_image(storage_path)
    except Exception:  # noqa: BLE001 — the row is gone; an orphan file is inert
        log.error("gallery file delete failed", extra={"business_id": business_id})

    return Response(status_code=status.HTTP_204_NO_CONTENT)


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

    description/price are nullable: we forward whether each was PRESENT in the
    body (model_fields_set) so an explicit null clears the column, while an
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
            set_description="description" in sent,
            set_price="price" in sent,
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
