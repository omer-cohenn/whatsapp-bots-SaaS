# לוגיקת התורים — חבילת הזמנות: מאחדת את settings/slots/crud/google לממשק אחד
"""Booking domain logic — settings, services, slots, bookings (M11).

This package was split out of the old single-file `booking.py` for readability
(M15 cleanup) WITHOUT any behavior change. The code now lives in four focused
sub-modules, and this `__init__` re-exports the FULL public surface so every
existing caller keeps working unchanged — both
`from app.services import booking; booking.X()` and
`from app.services.booking import X`.

Sub-modules:
  * settings.py — booking_settings + services CRUD + slug + public-page helpers
  * slots.py    — the slot algorithm (compute_slots / compute_availability) + tz
  * crud.py     — bookings list/create/cancel/reschedule + the linked lead
  * google.py   — the Google-calendar sync hook seam (no-op until registered)
  * page.py     — M20: the business-page fields + the gallery image rows

Non-negotiables (unchanged, documented in the sub-modules): RLS always; client
PII encrypted at rest + never logged; time stored/compared in UTC, edited in the
fixed business timezone (Asia/Jerusalem); the Google hook can never break a
booking (best-effort, swallowed). See decision 0011.
"""

from __future__ import annotations

from app.services.booking._helpers import BUSINESS_TZ
from app.services.booking.crud import (
    InvalidBookingRequest,
    SlotTakenError,
    admin_update_booking,
    cancel_booking_by_token,
    create_public_booking,
    get_booking,
    list_bookings,
    reschedule_booking_by_token,
)
from app.services.booking.google import (
    GoogleHook,
    GoogleHookAction,
    register_google_hook,
    run_google_hook,
)
from app.services.booking.page import (
    count_images,
    create_image,
    delete_image_row,
    get_image,
    get_page,
    list_images,
    rename_business,
    update_image,
    update_page,
)
from app.services.booking.settings import (
    business_display_name,
    create_service,
    delete_service,
    get_service,
    get_settings,
    list_services,
    resolve_slug,
    update_service,
    update_settings,
)
from app.services.booking.slots import (
    AVAILABILITY_MAX_DAYS,
    InvalidDateRange,
    compute_availability,
    compute_slots,
    local_to_utc,
)

__all__ = [
    # google hook seam
    "GoogleHook",
    "GoogleHookAction",
    "register_google_hook",
    "run_google_hook",
    # settings + services + public-page helpers
    "get_settings",
    "update_settings",
    "list_services",
    "get_service",
    "create_service",
    "update_service",
    "delete_service",
    "resolve_slug",
    "business_display_name",
    "rename_business",
    # M20 business page: the page fields + the gallery rows
    "get_page",
    "update_page",
    "list_images",
    "count_images",
    "create_image",
    "get_image",
    "update_image",
    "delete_image_row",
    # slot algorithm + time helpers
    "compute_slots",
    "compute_availability",
    "AVAILABILITY_MAX_DAYS",
    "InvalidDateRange",
    "local_to_utc",
    # bookings CRUD
    "list_bookings",
    "get_booking",
    "create_public_booking",
    "cancel_booking_by_token",
    "reschedule_booking_by_token",
    "admin_update_booking",
    "SlotTakenError",
    "InvalidBookingRequest",
    # constants
    "BUSINESS_TZ",
]
