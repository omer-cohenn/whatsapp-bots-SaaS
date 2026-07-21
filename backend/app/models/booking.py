"""Pydantic models for the M11 booking API (admin + public).

These are the frozen request/response shapes the frontend + Google agents build
against. Two hard conventions, exactly like the dashboard models:

  * `business_id` is NEVER part of ANY model here. The tenant always comes from
    the server session (`current_business`) for admin routes, or from the
    verified slug for public routes — never from a body.
  * Decrypted client PII (name/phone/email/notes) appears ONLY in admin
    RESPONSES, served to the authenticated owner of the tenant. Public responses
    never echo another customer's PII.

`working_hours` is the SPLIT-hours shape (decision 0011): weekday "0".."6"
(Sun=0) → a LIST of {"s":"HH:MM","e":"HH:MM"} ranges, so a day can have e.g. a
morning + an evening block. Times are local Asia/Jerusalem wall-clock strings;
the slot algorithm converts to UTC.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- shared bounds + validators ---------------------------------------------

# A "HH:MM" 24-hour wall-clock time (e.g. "09:00", "18:30"). Used in working
# hours ranges and in the public slot/create payloads.
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# A "YYYY-MM-DD" calendar date (the public page picks a day, the slot algorithm
# resolves it against the business timezone).
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Field length bounds — generous but finite (guard oversized bodies / abuse).
MAX_NAME_CHARS = 120
MAX_PHONE_CHARS = 40
MAX_EMAIL_CHARS = 200
MAX_NOTES_CHARS = 1000
MAX_SERVICE_NAME_CHARS = 120
# Service blurb (public card) + the per-business public-page welcome message.
MAX_SERVICE_DESC_CHARS = 500
MAX_WELCOME_MESSAGE_CHARS = 600
# A booking-page slug is the public handle; bound it tightly.
SLUG_MAX = 64

# --- M20 business-page bounds (decision 0028) --------------------------------
# All owner-authored PUBLIC copy — bounded so a body can never become an abuse
# vector, generous enough for real Hebrew text.
MAX_TAGLINE_CHARS = 160
MAX_ABOUT_CHARS = 2000
MAX_ADDRESS_CHARS = 240
MAX_PAGE_PHONE_CHARS = 40
MAX_PAGE_URL_CHARS = 500
# One gallery caption ("תספורת פייד") — two words, not a paragraph.
MAX_CAPTION_CHARS = 120
# The gallery position. Bounded far above the 40-image cap so a re-order can use
# sparse values, but still finite.
MAX_SORT_ORDER = 10_000


def _valid_time(value: str) -> str:
    if not _TIME_RE.match(value):
        raise ValueError("time must be HH:MM (24h)")
    return value


def _valid_date(value: str) -> str:
    if not _DATE_RE.match(value):
        raise ValueError("date must be YYYY-MM-DD")
    return value


# --- working hours (a weekday → list of {s,e} ranges) ------------------------


class HoursRange(BaseModel):
    """One open block within a weekday, e.g. {"s":"09:00","e":"13:00"}."""

    model_config = ConfigDict(extra="forbid")

    s: str = Field(..., description="start time HH:MM (local Asia/Jerusalem)")
    e: str = Field(..., description="end time HH:MM (local Asia/Jerusalem)")

    @field_validator("s", "e")
    @classmethod
    def _check_time(cls, value: str) -> str:
        return _valid_time(value)

    @model_validator(mode="after")
    def _check_order(self) -> "HoursRange":
        # A zero/negative range can't hold any appointment — reject it early.
        if self.s >= self.e:
            raise ValueError("range start must be before end")
        return self


# weekday key "0".."6" (Sun=0). We keep the JSON object shape (not a list) so it
# matches the working_hours jsonb column exactly.
_WEEKDAY_KEYS = {"0", "1", "2", "3", "4", "5", "6"}


# --- booking_settings (admin: GET/PUT /api/booking/settings) -----------------


class BookingSettings(BaseModel):
    """The per-business booking config (admin GET response + PUT request body).

    `slug` and `timezone` are READ-ONLY from the API's point of view: the slug is
    auto-generated server-side on first save (non-guessable) and the timezone is
    fixed Asia/Jerusalem (decision 0011). They appear in the GET response but are
    IGNORED if sent in a PUT (the service never overwrites them from the body).
    """

    model_config = ConfigDict(extra="forbid")

    # Echoed on GET; ignored on PUT (server owns them).
    slug: str | None = Field(default=None, max_length=SLUG_MAX)
    timezone: str | None = Field(default=None, max_length=64)

    # weekday "0".."6" → list of {s,e}. Empty list = closed that day.
    working_hours: dict[str, list[HoursRange]] = Field(default_factory=dict)
    min_notice_minutes: int = Field(default=120, ge=0, le=60 * 24 * 30)
    buffer_minutes: int = Field(default=0, ge=0, le=240)
    max_days_ahead: int = Field(default=30, ge=1, le=365)
    meet_enabled: bool = False
    # Short Hebrew greeting shown atop the public booking page (owner-authored or
    # AI-generated). Public marketing copy — never PII. Persisted on PUT.
    welcome_message: str | None = Field(default=None, max_length=MAX_WELCOME_MESSAGE_CHARS)

    @field_validator("working_hours")
    @classmethod
    def _check_weekdays(
        cls, value: dict[str, list[HoursRange]]
    ) -> dict[str, list[HoursRange]]:
        for key in value:
            if key not in _WEEKDAY_KEYS:
                raise ValueError('working_hours keys must be weekday "0".."6" (Sun=0)')
        return value


# --- services (admin: GET/POST/PATCH/DELETE /api/services[/{id}]) ------------


class ServiceItem(BaseModel):
    """One bookable service (admin response)."""

    id: str
    name: str
    duration_minutes: int
    active: bool
    # description = a short public blurb; price = OPTIONAL ₪ whole shekels
    # (None => the UI shows "ללא עלות").
    description: str | None = None
    price: int | None = None
    created_at: str | None = None


class ServicesResponse(BaseModel):
    """GET /api/services response."""

    services: list[ServiceItem]


class ServiceCreateRequest(BaseModel):
    """POST /api/services body."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=MAX_SERVICE_NAME_CHARS)
    duration_minutes: int = Field(default=30, ge=5, le=8 * 60)
    active: bool = True
    description: str | None = Field(default=None, max_length=MAX_SERVICE_DESC_CHARS)
    # OPTIONAL price in ₪ (whole shekels). None => "ללא עלות" on the public page.
    price: int | None = Field(default=None, ge=0)


class ServiceUpdateRequest(BaseModel):
    """PATCH /api/services/{id} body — every field optional (partial update)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=MAX_SERVICE_NAME_CHARS)
    duration_minutes: int | None = Field(default=None, ge=5, le=8 * 60)
    active: bool | None = None
    description: str | None = Field(default=None, max_length=MAX_SERVICE_DESC_CHARS)
    price: int | None = Field(default=None, ge=0)


# --- bookings (admin: GET /api/bookings, PATCH /api/bookings/{id}) -----------

# Booking status vocabulary. The public create starts a booking 'pending';
# the owner confirms/completes/cancels; a customer cancels via cancel_token.
BOOKING_STATUSES = ("pending", "confirmed", "cancelled", "completed")
BookingStatus = Literal["pending", "confirmed", "cancelled", "completed"]


class BookingItem(BaseModel):
    """One booking, decrypted for the OWNER (admin response).

    `scheduled_at` is the UTC ISO-8601 instant; the frontend renders it in
    Asia/Jerusalem. Client PII is decrypted here for the owner only — never
    logged, never returned on a public route.
    """

    id: str
    service_id: str | None = None
    service_name: str | None = None
    lead_id: str | None = None
    client_name: str | None = None
    client_phone: str | None = None
    client_email: str | None = None
    scheduled_at: str  # UTC ISO-8601
    duration_minutes: int
    status: str
    notes: str | None = None
    google_event_id: str | None = None
    meet_link: str | None = None
    is_test: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class BookingsResponse(BaseModel):
    """GET /api/bookings response (newest first)."""

    bookings: list[BookingItem]


class BookingAlertItem(BaseModel):
    """One home notification: a customer cancelled/rescheduled their booking.

    Resolved for the owner — client_name/service_name/scheduled_at are decrypted
    from the linked booking; `at` is when the customer made the change.
    """

    booking_id: str
    kind: str  # "cancelled" | "rescheduled"
    at: str | None = None
    client_name: str | None = None
    service_name: str | None = None
    scheduled_at: str | None = None  # the booking's (new) time, UTC ISO-8601


class BookingAlertsResponse(BaseModel):
    """GET /api/bookings/alerts response (newest first)."""

    alerts: list[BookingAlertItem]


class BookingUpdateRequest(BaseModel):
    """PATCH /api/bookings/{id} body: set status and/or reschedule.

    At least one of (status) or (date+time) must be present. `date`+`time` are
    local Asia/Jerusalem wall-clock; the service converts to UTC. A reschedule
    re-checks slot availability (double-booking guard) before committing.
    """

    model_config = ConfigDict(extra="forbid")

    status: BookingStatus | None = None
    date: str | None = None  # YYYY-MM-DD (local) — present together with time
    time: str | None = None  # HH:MM (local) — present together with date

    @field_validator("date")
    @classmethod
    def _check_date(cls, value: str | None) -> str | None:
        return _valid_date(value) if value is not None else None

    @field_validator("time")
    @classmethod
    def _check_time(cls, value: str | None) -> str | None:
        return _valid_time(value) if value is not None else None

    @model_validator(mode="after")
    def _check_something(self) -> "BookingUpdateRequest":
        has_reschedule = self.date is not None or self.time is not None
        if has_reschedule and (self.date is None or self.time is None):
            raise ValueError("reschedule requires BOTH date and time")
        if self.status is None and not has_reschedule:
            raise ValueError("provide a status and/or a date+time to reschedule")
        return self


class BookingUpdateResponse(BaseModel):
    """Echo the booking + its new status/time after an admin change."""

    booking_id: str
    status: str
    scheduled_at: str  # UTC ISO-8601


# --- welcome-message generator (admin: POST /api/booking/welcome/generate) ----


class WelcomeGenerateRequest(BaseModel):
    """POST /api/booking/welcome/generate body — an OPTIONAL tone hint.

    `tone` nudges the generated greeting (e.g. "חם", "מקצועי", "קליל"); when
    omitted the generator picks a warm default. Bounded so it can't be abused.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    tone: str | None = Field(default=None, max_length=60)


class WelcomeGenerateResponse(BaseModel):
    """POST /api/booking/welcome/generate response: the suggested greeting.

    The owner previews/edits it before saving via PUT /api/booking/settings — we
    do NOT persist it here.
    """

    message: str


# --- PUBLIC shapes (NO session — resolved from the slug) ---------------------
#
# These power the customer-facing booking page. They expose the MINIMUM needed
# to book: the active services, the free slots for a chosen service+date, and a
# tiny create/cancel/reschedule surface. They NEVER expose another customer's
# PII, never carry a business_id, never echo internal ids beyond the new
# booking's own id + cancel_token.


class PublicServiceItem(BaseModel):
    """A bookable service as the public page sees it (no internal flags)."""

    id: str
    name: str
    duration_minutes: int
    # Public card extras: a short blurb + an OPTIONAL price in ₪ (None => the UI
    # renders "ללא עלות"). These are owner-authored, public — never PII.
    description: str | None = None
    price: int | None = None


class PublicServicesResponse(BaseModel):
    """GET /api/book/{slug}/services response (active services only).

    `welcome_message` is the per-business greeting shown atop the page (may be
    None when the owner hasn't set one — the UI shows a sensible default).
    """

    business_name: str
    welcome_message: str | None = None
    services: list[PublicServiceItem]


class PublicAvailabilityResponse(BaseModel):
    """GET /api/book/{slug}/availability response: which days have any free slot.

    `dates` are the "YYYY-MM-DD" days inside the requested [from,to] range that
    have >=1 bookable slot for the chosen service. The public page uses this to
    enable/disable calendar days before drilling into a single day's slots.
    """

    dates: list[str]


class PublicSlotsResponse(BaseModel):
    """GET /api/book/{slug}/slots response: bookable start times for a date.

    `slots` are local Asia/Jerusalem "HH:MM" start times the customer can pick;
    `date` echoes the requested day. Already-taken / out-of-window times are
    omitted.
    """

    date: str
    slots: list[str]


class PublicBookingCreateRequest(BaseModel):
    """POST /api/book/{slug} body — the customer's booking request.

    `date`+`time` are local Asia/Jerusalem wall-clock; the server converts to
    UTC. PII (name/phone/email/notes) is encrypted at rest by the service and is
    NEVER logged.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    service_id: str = Field(..., min_length=1, max_length=64)
    date: str
    time: str
    name: str = Field(..., min_length=1, max_length=MAX_NAME_CHARS)
    phone: str = Field(..., min_length=3, max_length=MAX_PHONE_CHARS)
    email: str | None = Field(default=None, max_length=MAX_EMAIL_CHARS)
    notes: str | None = Field(default=None, max_length=MAX_NOTES_CHARS)

    @field_validator("date")
    @classmethod
    def _check_date(cls, value: str) -> str:
        return _valid_date(value)

    @field_validator("time")
    @classmethod
    def _check_time(cls, value: str) -> str:
        return _valid_time(value)


class PublicBookingCreateResponse(BaseModel):
    """POST /api/book/{slug} response: the new booking + its cancel token.

    `cancel_token` is the non-guessable handle the customer uses to cancel or
    reschedule later (no login). `scheduled_at` is the UTC instant booked.
    """

    booking_id: str
    cancel_token: str
    scheduled_at: str  # UTC ISO-8601


class PublicRescheduleRequest(BaseModel):
    """POST /api/book/{slug}/reschedule/{token} body: a new date+time."""

    model_config = ConfigDict(extra="forbid")

    date: str
    time: str

    @field_validator("date")
    @classmethod
    def _check_date(cls, value: str) -> str:
        return _valid_date(value)

    @field_validator("time")
    @classmethod
    def _check_time(cls, value: str) -> str:
        return _valid_time(value)


class PublicMutationResponse(BaseModel):
    """Generic ack for a public cancel/reschedule (no PII)."""

    booking_id: str
    status: str
    scheduled_at: str  # UTC ISO-8601


# --- M20 business page (owner: /api/booking/page + /api/booking/images) -------
#
# The "business page" is the visual shell around the existing booking flow: a
# hero (logo, name, tagline, address, four contact buttons) plus a photo gallery.
# EVERY field here is owner-authored PUBLIC marketing content — including the
# address and phone, which are the BUSINESS's own details, not a customer's.
# That is a deliberate, documented exception to the encryption rule (decision
# 0028 / migration 0029), and it does not extend to anything else.
#
# Image BYTES never appear in these models: an image row carries a
# `storage_path`, and the browser fetches the file from `/media/{storage_path}`,
# which Caddy serves straight off disk without touching Python.


class BusinessImageItem(BaseModel):
    """One gallery image row (owner + public responses share this shape).

    `storage_path` is the relative path inside the images volume
    (`{business_id}/{uuid}.{ext}`). The public URL is `/media/{storage_path}` —
    the frontend builds it, the API never stores a full URL, so the origin can
    change without a data migration.
    """

    id: str
    storage_path: str
    caption: str | None = None
    sort_order: int = 0
    mime_type: str | None = None
    size_bytes: int | None = None
    created_at: str | None = None


class BusinessPageResponse(BaseModel):
    """GET /api/booking/page — the owner's view of the page + its gallery.

    `slug` is echoed so the wizard can show/copy the public link. `page_theme` is
    a free-form jsonb object the frontend owns (palette / radius / font); the
    backend stores and returns it without interpreting it, so C and D can evolve
    the theme shape without a backend change. `{}` means "the default look".
    """

    slug: str | None = None
    business_name: str = ""
    tagline: str | None = None
    about: str | None = None
    address: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    instagram_url: str | None = None
    waze_url: str | None = None
    logo_url: str | None = None
    page_theme: dict = Field(default_factory=dict)
    images: list[BusinessImageItem] = Field(default_factory=list)
    updated_at: str | None = None


class BusinessPageUpdateRequest(BaseModel):
    """PUT /api/booking/page — partial update; EVERY field is optional.

    Same house rule as the services PATCH: an OMITTED key leaves the column
    alone, while an EXPLICIT null CLEARS it (the route reads `model_fields_set`
    to tell the two apart). Clearing matters here because "empty field ⇒ the
    button is not rendered" is the product rule for the four contact buttons.

    `slug` is NOT accepted — it is server-owned.

    `business_name` IS accepted (M20 revision). The account is created from the
    Google profile at first login, so a solo owner's page is titled with their
    PERSONAL name until they change it. Unlike every other field here it may not
    be cleared to null: a page with no name has nothing to render, so an empty
    value is rejected rather than stored.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    business_name: str | None = Field(default=None, min_length=1, max_length=120)
    tagline: str | None = Field(default=None, max_length=MAX_TAGLINE_CHARS)
    about: str | None = Field(default=None, max_length=MAX_ABOUT_CHARS)
    address: str | None = Field(default=None, max_length=MAX_ADDRESS_CHARS)
    phone: str | None = Field(default=None, max_length=MAX_PAGE_PHONE_CHARS)
    whatsapp: str | None = Field(default=None, max_length=MAX_PAGE_PHONE_CHARS)
    instagram_url: str | None = Field(default=None, max_length=MAX_PAGE_URL_CHARS)
    waze_url: str | None = Field(default=None, max_length=MAX_PAGE_URL_CHARS)
    logo_url: str | None = Field(default=None, max_length=MAX_PAGE_URL_CHARS)
    page_theme: dict | None = None

    @field_validator("instagram_url", "waze_url", "logo_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        """Only http(s) links. Blocks `javascript:` / `data:` in an href we render.

        These three values are rendered as an `href`/`src` on a PUBLIC page, so a
        `javascript:` URL here would be stored XSS against every visitor. An
        empty string is normalized to None (the UI sends "" when the owner clears
        a field, and "" must mean "no button", not a link to the current page).
        """
        if value is None:
            return None
        if not value:
            return None
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("url must start with http:// or https://")
        return value

    @field_validator("tagline", "about", "address", "phone", "whatsapp")
    @classmethod
    def _empty_is_null(cls, value: str | None) -> str | None:
        """An empty string means "cleared", which is stored as NULL, not ""."""
        return value or None


class BusinessImageUpdateRequest(BaseModel):
    """PATCH /api/booking/images/{id} — caption and/or position.

    `caption` follows the omit-vs-null rule (explicit null clears the caption);
    `sort_order` is a plain optional int — there is no "no position", so an
    omitted key simply leaves the current one.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    caption: str | None = Field(default=None, max_length=MAX_CAPTION_CHARS)
    sort_order: int | None = Field(default=None, ge=0, le=MAX_SORT_ORDER)


class BusinessImagesResponse(BaseModel):
    """GET-style envelope for the gallery (display order)."""

    images: list[BusinessImageItem]


class PublicBusinessImageItem(BaseModel):
    """One gallery image as the PUBLIC page sees it: the path + the caption.

    No size, no mime, no created_at — a visitor has no use for them, and each is
    one more fact about the business we would be publishing for free.
    """

    id: str
    storage_path: str
    caption: str | None = None


class PublicBusinessPageResponse(BaseModel):
    """GET /api/book/{slug}/page — what an ANONYMOUS visitor may see.

    Deliberately a SEPARATE model from `BusinessPageResponse`: it carries only
    the fields the public hero + gallery render. No settings, no slug echo, no
    internal ids beyond each image's own id (which the UI needs as a list key),
    and — obviously — no customer data of any kind. A new owner-only column added
    to `booking_settings` later cannot leak here by accident, because adding it
    to this model is a separate, visible edit.
    """

    business_name: str = ""
    tagline: str | None = None
    about: str | None = None
    address: str | None = None
    phone: str | None = None
    whatsapp: str | None = None
    instagram_url: str | None = None
    waze_url: str | None = None
    logo_url: str | None = None
    page_theme: dict = Field(default_factory=dict)
    images: list[PublicBusinessImageItem] = Field(default_factory=list)
