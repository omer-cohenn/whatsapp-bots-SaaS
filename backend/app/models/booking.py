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
# A booking-page slug is the public handle; bound it tightly.
SLUG_MAX = 64


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


class ServiceUpdateRequest(BaseModel):
    """PATCH /api/services/{id} body — every field optional (partial update)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=MAX_SERVICE_NAME_CHARS)
    duration_minutes: int | None = Field(default=None, ge=5, le=8 * 60)
    active: bool | None = None


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


class PublicServicesResponse(BaseModel):
    """GET /api/book/{slug}/services response (active services only)."""

    business_name: str
    services: list[PublicServiceItem]


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
