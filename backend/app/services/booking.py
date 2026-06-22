"""Booking domain logic — settings, services, slots, bookings (M11).

This is the tenant-scoped engine behind both the owner's admin API and the
public booking page. Like `leads.py`, the functions here take an already-open,
tenant-bound `asyncpg.Connection` (from `tenant_connection`) so RLS scopes every
read/write and a multi-step write (lead + booking) commits in ONE transaction.

Non-negotiables baked in everywhere:

  1. RLS, always. `business_id` is the caller's already-verified id (the session
     for admin, the resolved slug for public) — never a raw client value. It is
     passed in the INSERT/UPDATE so RLS's WITH CHECK matches.
  2. Client PII encrypted at rest, never logged. client_name / client_phone /
     client_email / notes are encrypted via `app/core/crypto.py` before they
     touch the DB; `key_version` is stamped for rotation. We NEVER log a name,
     phone, email, or note.
  3. Time discipline (decision 0011). The business timezone is fixed
     Asia/Jerusalem; the owner edits LOCAL wall-clock working hours, but
     `scheduled_at` is stored + compared in UTC. We convert at the edges with
     `zoneinfo` (stdlib) — no pytz.

The slot algorithm (the heart of the public page) is documented inline at
`compute_slots`. Double-booking is enforced HERE (there's no DB-level uniqueness
on (business_id, scheduled_at) — see the schema note), both when listing slots
and again, defensively, at create/reschedule time.

GOOGLE SEAM (decoupled): every booking mutation calls a single async hook,
`run_google_hook(...)`, AFTER the row is committed. The Google agent registers a
real implementation via `register_google_hook`; until then it is a no-op. A hook
failure is swallowed (logged generically) so Google can NEVER break a booking
(decision 0011: degrade gracefully).
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, time, timedelta, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

import asyncpg

from app.core import crypto
from app.core.logging import get_logger
from app.services import leads as leads_service
from app.services import usage as usage_service

log = get_logger("app.services.booking")

# The fixed business timezone (decision 0011). Stored times are UTC; the owner's
# working hours + the public page speak this local wall-clock.
BUSINESS_TZ = ZoneInfo("Asia/Jerusalem")

# A booked slot that is NOT one of these is "live" and blocks its time. A
# cancelled booking frees its slot again.
_ACTIVE_BOOKING_STATUSES = ("pending", "confirmed", "completed")

# Sensible default working hours for a brand-new business (so the page isn't
# empty before the owner configures anything): Sun–Thu 09:00–17:00. The owner
# overrides this in settings. Weekday "0"=Sun .. "6"=Sat.
_DEFAULT_WORKING_HOURS = {
    "0": [{"s": "09:00", "e": "17:00"}],
    "1": [{"s": "09:00", "e": "17:00"}],
    "2": [{"s": "09:00", "e": "17:00"}],
    "3": [{"s": "09:00", "e": "17:00"}],
    "4": [{"s": "09:00", "e": "17:00"}],
}

# The slug is the public, non-guessable booking-page handle. token_urlsafe(9)
# gives ~12 url-safe chars — short enough to share, long enough to be unguessable.
_SLUG_BYTES = 9
# The cancel_token must be unguessable (a customer cancels with ONLY this token).
_CANCEL_TOKEN_BYTES = 24


# ============================================================================
# Google hook seam (registered by the Google agent; no-op until then)
# ============================================================================

# The action that just happened to a booking, passed to the hook so a single
# implementation can branch (create vs update vs delete the calendar event).
GoogleHookAction = str  # "created" | "rescheduled" | "cancelled"

# Signature the Google agent implements + registers. It receives the tenant id
# (already verified) and the booking id, NOT a connection — Google sync runs
# AFTER the booking transaction commits, opening its own tenant_connection as
# needed. It must never raise (failures degrade gracefully); we also guard it.
GoogleHook = Callable[[str, str, GoogleHookAction], Awaitable[None]]

_google_hook: GoogleHook | None = None


def register_google_hook(hook: GoogleHook | None) -> None:
    """Register (or clear) the Google-calendar sync hook. Called by the Google agent.

    Passing None disables it (the default state). Keeping this a module-level
    registration keeps the booking core free of any Google import/dependency.
    """
    global _google_hook
    _google_hook = hook


async def run_google_hook(business_id: str, booking_id: str, action: GoogleHookAction) -> None:
    """Fire the Google hook for a committed booking mutation — best-effort.

    Called AFTER the booking row is committed. If no hook is registered this is a
    no-op. Any error is swallowed + logged generically so Google can NEVER break
    a booking (decision 0011). Never logs PII/tokens.
    """
    hook = _google_hook
    if hook is None:
        return
    try:
        await hook(business_id, booking_id, action)
    except Exception:  # noqa: BLE001 — degrade gracefully; no str(e)/PII
        log.warning("google booking hook failed", extra={"action": action})


# ============================================================================
# booking_settings — get / update (auto-generate slug on first save)
# ============================================================================

async def get_settings(conn: asyncpg.Connection, business_id: str) -> dict[str, Any]:
    """Return this tenant's booking settings, creating a default row if missing.

    On first read we INSERT a default row (with a fresh non-guessable slug) so a
    business always has a usable public page. RLS-scoped via `conn`; business_id
    is the caller's verified id and is in the WHERE/VALUES so the policy matches.
    """
    row = await conn.fetchrow(
        """
        SELECT business_id, timezone, working_hours, min_notice_minutes,
               buffer_minutes, max_days_ahead, meet_enabled, welcome_message,
               slug, updated_at
        FROM booking_settings
        WHERE business_id = $1
        """,
        business_id,
    )
    if row is None:
        row = await _create_default_settings(conn, business_id)
    return _settings_to_dict(row)


async def _create_default_settings(
    conn: asyncpg.Connection, business_id: str
) -> asyncpg.Record:
    """Insert a default settings row with a fresh unique slug; return the row."""
    slug = await _unique_slug(conn)
    row = await conn.fetchrow(
        """
        INSERT INTO booking_settings
            (business_id, working_hours, slug)
        VALUES ($1, $2::jsonb, $3)
        ON CONFLICT (business_id) DO UPDATE SET updated_at = now()
        RETURNING business_id, timezone, working_hours, min_notice_minutes,
                  buffer_minutes, max_days_ahead, meet_enabled, welcome_message,
                  slug, updated_at
        """,
        business_id,
        json.dumps(_DEFAULT_WORKING_HOURS, ensure_ascii=False),
        slug,
    )
    return row


async def update_settings(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    working_hours: dict[str, Any],
    min_notice_minutes: int,
    buffer_minutes: int,
    max_days_ahead: int,
    meet_enabled: bool,
    welcome_message: str | None,
) -> dict[str, Any]:
    """UPSERT the editable booking settings for this tenant; return the saved row.

    The slug + timezone are SERVER-OWNED: a new row gets a fresh slug, and an
    existing row keeps its slug/timezone untouched (the body can't change them).
    `welcome_message` is owner-authored public copy (NOT PII) — persisted as-is.
    RLS-scoped; business_id is the verified id and is written from here only.
    """
    # Ensure a slug exists (first save creates the row + slug); then update the
    # editable fields. We do this as a single UPSERT so it's race-safe.
    slug = await _unique_slug(conn)
    row = await conn.fetchrow(
        """
        INSERT INTO booking_settings
            (business_id, working_hours, min_notice_minutes, buffer_minutes,
             max_days_ahead, meet_enabled, welcome_message, slug, updated_at)
        VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7, $8, now())
        ON CONFLICT (business_id) DO UPDATE SET
            working_hours      = EXCLUDED.working_hours,
            min_notice_minutes = EXCLUDED.min_notice_minutes,
            buffer_minutes     = EXCLUDED.buffer_minutes,
            max_days_ahead     = EXCLUDED.max_days_ahead,
            meet_enabled       = EXCLUDED.meet_enabled,
            welcome_message    = EXCLUDED.welcome_message,
            updated_at         = now()
        RETURNING business_id, timezone, working_hours, min_notice_minutes,
                  buffer_minutes, max_days_ahead, meet_enabled, welcome_message,
                  slug, updated_at
        """,
        business_id,
        json.dumps(working_hours, ensure_ascii=False),
        min_notice_minutes,
        buffer_minutes,
        max_days_ahead,
        meet_enabled,
        welcome_message,
        slug,
    )
    return _settings_to_dict(row)


async def _unique_slug(conn: asyncpg.Connection) -> str:
    """Generate a non-guessable slug not already in use (tiny retry loop).

    NOTE: the SELECT here runs under RLS as app_role, but the public uniqueness
    of slugs is enforced by the UNIQUE constraint on the column regardless. The
    check is best-effort to avoid a collision retry; the constraint is the real
    guarantee. Collisions on a 12-char url-safe token are astronomically rare.
    """
    for _ in range(5):
        candidate = secrets.token_urlsafe(_SLUG_BYTES)
        # The function bypasses RLS to check global uniqueness of the public slug.
        taken = await conn.fetchval("SELECT resolve_booking_slug($1)", candidate)
        if taken is None:
            return candidate
    # Extremely unlikely; fall back to a longer token.
    return secrets.token_urlsafe(_SLUG_BYTES * 2)


def _settings_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Map a booking_settings row → a JSON-able dict (working_hours normalized)."""
    return {
        "slug": row["slug"],
        "timezone": row["timezone"],
        "working_hours": _as_obj(row["working_hours"], {}),
        "min_notice_minutes": int(row["min_notice_minutes"]),
        "buffer_minutes": int(row["buffer_minutes"]),
        "max_days_ahead": int(row["max_days_ahead"]),
        "meet_enabled": bool(row["meet_enabled"]),
        "welcome_message": row["welcome_message"],
        "updated_at": _iso(row["updated_at"]),
    }


# ============================================================================
# services — CRUD
# ============================================================================

async def list_services(
    conn: asyncpg.Connection, business_id: str, *, active_only: bool = False
) -> list[dict[str, Any]]:
    """List this tenant's services (newest first). RLS-scoped via `conn`."""
    where = "business_id = $1"
    if active_only:
        where += " AND active = true"
    rows = await conn.fetch(
        f"""
        SELECT id, name, duration_minutes, active, description, price,
               image_url, created_at
        FROM services
        WHERE {where}
        ORDER BY created_at DESC
        """,
        business_id,
    )
    return [_service_to_dict(r) for r in rows]


async def get_service(
    conn: asyncpg.Connection, business_id: str, service_id: str
) -> dict[str, Any] | None:
    """Return one service for this tenant, or None (caller maps None → 404)."""
    row = await conn.fetchrow(
        """
        SELECT id, name, duration_minutes, active, description, price,
               image_url, created_at
        FROM services
        WHERE id = $1 AND business_id = $2
        """,
        service_id,
        business_id,
    )
    return _service_to_dict(row) if row is not None else None


async def create_service(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    name: str,
    duration_minutes: int,
    active: bool,
    description: str | None,
    price: int | None,
    image_url: str | None,
) -> dict[str, Any]:
    """Insert a new service for this tenant; return it. RLS WITH CHECK matches."""
    row = await conn.fetchrow(
        """
        INSERT INTO services
            (business_id, name, duration_minutes, active, description, price,
             image_url)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id, name, duration_minutes, active, description, price,
                  image_url, created_at
        """,
        business_id,
        name,
        duration_minutes,
        active,
        description,
        price,
        image_url,
    )
    return _service_to_dict(row)


async def update_service(
    conn: asyncpg.Connection,
    business_id: str,
    service_id: str,
    *,
    name: str | None,
    duration_minutes: int | None,
    active: bool | None,
    description: str | None,
    price: int | None,
    image_url: str | None,
    set_description: bool = False,
    set_price: bool = False,
    set_image_url: bool = False,
) -> dict[str, Any] | None:
    """Partial-update a service (only provided fields). None if no row matched.

    Builds a dynamic SET from just the supplied fields; the WHERE includes
    business_id so RLS scopes the write to this tenant. Returns the updated row,
    or None when the id doesn't exist for this tenant (caller → 404).

    description/price/image_url are nullable columns, so "set to NULL" (clear)
    must be distinguishable from "omitted". The caller passes `set_description` /
    `set_price` / `set_image_url` = True when the field was present in the PATCH
    body (even if its value is None), so an explicit null actually clears the
    column.
    """
    sets: list[str] = []
    params: list[Any] = [service_id, business_id]
    if name is not None:
        params.append(name)
        sets.append(f"name = ${len(params)}")
    if duration_minutes is not None:
        params.append(duration_minutes)
        sets.append(f"duration_minutes = ${len(params)}")
    if active is not None:
        params.append(active)
        sets.append(f"active = ${len(params)}")
    if set_description:
        params.append(description)
        sets.append(f"description = ${len(params)}")
    if set_price:
        params.append(price)
        sets.append(f"price = ${len(params)}")
    if set_image_url:
        params.append(image_url)
        sets.append(f"image_url = ${len(params)}")

    if not sets:
        # Nothing to change → just return the current row (or None if absent).
        return await get_service(conn, business_id, service_id)

    row = await conn.fetchrow(
        f"""
        UPDATE services SET {', '.join(sets)}
        WHERE id = $1 AND business_id = $2
        RETURNING id, name, duration_minutes, active, description, price,
                  image_url, created_at
        """,
        *params,
    )
    return _service_to_dict(row) if row is not None else None


async def delete_service(
    conn: asyncpg.Connection, business_id: str, service_id: str
) -> bool:
    """Delete a service for this tenant. Returns True if a row was removed.

    Existing bookings keep their history: the FK is ON DELETE SET NULL, so a
    deleted service simply nulls `bookings.service_id` (the booking row stays).
    """
    result = await conn.execute(
        "DELETE FROM services WHERE id = $1 AND business_id = $2",
        service_id,
        business_id,
    )
    return result.rsplit(" ", 1)[-1] != "0"


def _service_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "duration_minutes": int(row["duration_minutes"]),
        "active": bool(row["active"]),
        "description": row["description"],
        "price": int(row["price"]) if row["price"] is not None else None,
        "image_url": row["image_url"],
        "created_at": _iso(row["created_at"]),
    }


# ============================================================================
# slot algorithm — the bookable start times for a (service, date)
# ============================================================================

async def compute_slots(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    service_id: str,
    date_str: str,
    now: datetime | None = None,
) -> list[str]:
    """Return the bookable LOCAL "HH:MM" start times for a service on a date.

    The full algorithm (decision 0011):

      1. Load the service (must exist + be active for this tenant) → its
         duration; load settings → working_hours, buffer, min_notice, max_days.
      2. For the requested date, read THAT weekday's LIST of {s,e} ranges. For
         EACH range, generate candidate starts stepping by
         (duration + buffer) minutes, so a whole appointment (and its trailing
         buffer) fits inside the range.
      3. Convert each LOCAL candidate to a UTC instant (Asia/Jerusalem via
         zoneinfo). Drop any that fall before now()+min_notice_minutes or beyond
         now()+max_days_ahead.
      4. Subtract slots that overlap an existing NON-cancelled booking that day
         (overlap is computed INCLUDING the buffer on both sides), so taken
         times disappear.

    Returns the surviving starts as local "HH:MM" strings, ascending. An unknown
    /inactive service, a closed weekday, or a fully-booked day → []. RLS-scoped.
    """
    service = await get_service(conn, business_id, service_id)
    if service is None or not service["active"]:
        return []
    duration = int(service["duration_minutes"])

    settings = await get_settings(conn, business_id)
    buffer_min = int(settings["buffer_minutes"])
    min_notice = int(settings["min_notice_minutes"])
    max_days = int(settings["max_days_ahead"])
    working_hours = settings["working_hours"] or {}

    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return []

    # Python weekday(): Mon=0..Sun=6. Our keys use Sun=0..Sat=6, so remap.
    weekday_key = str((day.weekday() + 1) % 7)
    ranges = working_hours.get(weekday_key) or []
    if not ranges:
        return []

    now = now or datetime.now(timezone.utc)
    earliest = now + timedelta(minutes=min_notice)
    latest = now + timedelta(days=max_days)

    # Existing live bookings for that local day (to subtract taken slots). We
    # fetch a window covering the whole local day in UTC and overlap-check below.
    taken = await _bookings_on_local_day(conn, business_id, day)

    step = duration + buffer_min  # stride between consecutive candidate starts.
    out: list[str] = []
    for rng in ranges:
        start_local = _local_dt(day, rng.get("s"))
        end_local = _local_dt(day, rng.get("e"))
        if start_local is None or end_local is None:
            continue
        cursor = start_local
        # The appointment itself (NOT the trailing buffer) must fit before the
        # range end — buffer is padding between bookings, not bookable time.
        while cursor + timedelta(minutes=duration) <= end_local:
            start_utc = cursor.astimezone(timezone.utc)
            end_utc = start_utc + timedelta(minutes=duration)
            if earliest <= start_utc <= latest and not _overlaps_any(
                start_utc, end_utc, duration, buffer_min, taken
            ):
                out.append(cursor.strftime("%H:%M"))
            cursor += timedelta(minutes=step)

    return out


# The public availability range is bounded so the day-by-day loop can't be used
# to hammer the DB (62 days ≈ two months, comfortably above max_days_ahead=30).
AVAILABILITY_MAX_DAYS = 62


class InvalidDateRange(Exception):
    """Raised for a bad/oversized availability range (caller → 422)."""


async def compute_availability(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    service_id: str,
    from_str: str,
    to_str: str,
    now: datetime | None = None,
) -> list[str]:
    """Return the days in [from,to] that have >=1 free slot for a service.

    A thin loop over `compute_slots`: for each calendar day in the INCLUSIVE
    range we ask for that day's bookable slots and keep the day if any survive.
    The range is validated + BOUNDED to AVAILABILITY_MAX_DAYS days (a longer or
    inverted range raises InvalidDateRange → 422). RLS-scoped via `conn`; never
    logs PII (there is none here). An unknown/inactive service yields [].
    """
    try:
        start = datetime.strptime(from_str, "%Y-%m-%d").date()
        end = datetime.strptime(to_str, "%Y-%m-%d").date()
    except ValueError:
        raise InvalidDateRange("dates must be YYYY-MM-DD") from None
    if end < start:
        raise InvalidDateRange("'to' must be on or after 'from'")
    span_days = (end - start).days + 1  # inclusive
    if span_days > AVAILABILITY_MAX_DAYS:
        raise InvalidDateRange("range too large")

    now = now or datetime.now(timezone.utc)
    out: list[str] = []
    day = start
    while day <= end:
        date_str = day.strftime("%Y-%m-%d")
        slots = await compute_slots(
            conn, business_id, service_id=service_id, date_str=date_str, now=now
        )
        if slots:
            out.append(date_str)
        day += timedelta(days=1)
    return out


async def _bookings_on_local_day(
    conn: asyncpg.Connection, business_id: str, day: Any
) -> list[tuple[datetime, int]]:
    """Live bookings whose start falls on the given LOCAL day → [(start_utc, dur)].

    We bound the query by the local-day window converted to UTC (covers DST-safe
    edges with a small pad), then return each booking's UTC start + duration for
    overlap math. Only non-cancelled statuses count.
    """
    day_start_local = datetime.combine(day, time(0, 0), tzinfo=BUSINESS_TZ)
    day_end_local = day_start_local + timedelta(days=1)
    # Pad by a few hours so a slot whose buffer spills across midnight is caught.
    lo = (day_start_local - timedelta(hours=6)).astimezone(timezone.utc)
    hi = (day_end_local + timedelta(hours=6)).astimezone(timezone.utc)
    rows = await conn.fetch(
        """
        SELECT scheduled_at, duration_minutes
        FROM bookings
        WHERE business_id = $1
          AND status = ANY($2::text[])
          AND scheduled_at >= $3 AND scheduled_at < $4
        """,
        business_id,
        list(_ACTIVE_BOOKING_STATUSES),
        lo,
        hi,
    )
    return [(r["scheduled_at"], int(r["duration_minutes"])) for r in rows]


def _overlaps_any(
    start_utc: datetime,
    end_utc: datetime,
    duration: int,
    buffer_min: int,
    taken: list[tuple[datetime, int]],
) -> bool:
    """True if [start,end] (padded by buffer on both sides) overlaps a taken slot.

    Buffer is applied symmetrically: a candidate is blocked if it lands within
    `buffer_min` of an existing booking, so back-to-back bookings keep their gap.
    """
    pad = timedelta(minutes=buffer_min)
    cand_lo = start_utc - pad
    cand_hi = end_utc + pad
    for booked_start, booked_dur in taken:
        booked_end = booked_start + timedelta(minutes=booked_dur)
        # Standard interval overlap: A starts before B ends AND B starts before A ends.
        if cand_lo < booked_end and booked_start < cand_hi:
            return True
    return False


def _local_dt(day: Any, hhmm: str | None) -> datetime | None:
    """Combine a date + "HH:MM" into an aware local (Asia/Jerusalem) datetime."""
    if not hhmm:
        return None
    try:
        hh, mm = hhmm.split(":")
        return datetime.combine(day, time(int(hh), int(mm)), tzinfo=BUSINESS_TZ)
    except (ValueError, TypeError):
        return None


def local_to_utc(date_str: str, time_str: str) -> datetime | None:
    """Convert a local "YYYY-MM-DD" + "HH:MM" to a UTC aware datetime (or None)."""
    try:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None
    local = _local_dt(day, time_str)
    return local.astimezone(timezone.utc) if local is not None else None


# ============================================================================
# bookings — list (admin), create (public), cancel / reschedule
# ============================================================================

async def list_bookings(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    include_test: bool = False,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """List this tenant's bookings (newest first), decrypted for the OWNER.

    Filters (all optional): status (pending|confirmed|cancelled|completed),
    date_from / date_to as LOCAL "YYYY-MM-DD" days (inclusive, converted to a UTC
    window). `is_test` excluded unless include_test. Joins the service name for
    display. Client PII is decrypted here for the owner — NEVER logged.
    """
    params: list[Any] = [business_id]
    where = ["b.business_id = $1"]

    if not include_test:
        where.append("b.is_test = false")
    if status:
        params.append(status)
        where.append(f"b.status = ${len(params)}")
    if date_from:
        lo = local_to_utc(date_from, "00:00")
        if lo is not None:
            params.append(lo)
            where.append(f"b.scheduled_at >= ${len(params)}")
    if date_to:
        # Inclusive of the whole 'to' day → next local midnight.
        hi = local_to_utc(date_to, "00:00")
        if hi is not None:
            params.append(hi + timedelta(days=1))
            where.append(f"b.scheduled_at < ${len(params)}")

    params.append(int(limit))
    rows = await conn.fetch(
        f"""
        SELECT b.id, b.service_id, s.name AS service_name, b.lead_id,
               b.client_name, b.client_phone, b.client_email,
               b.scheduled_at, b.duration_minutes, b.status, b.notes,
               b.google_event_id, b.meet_link, b.is_test, b.key_version,
               b.created_at, b.updated_at
        FROM bookings b
        LEFT JOIN services s ON s.id = b.service_id
        WHERE {' AND '.join(where)}
        ORDER BY b.scheduled_at DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [_decrypt_booking_row(r) for r in rows]


async def get_booking(
    conn: asyncpg.Connection, business_id: str, booking_id: str
) -> dict[str, Any] | None:
    """Return one decrypted booking for this tenant, or None (caller → 404)."""
    row = await conn.fetchrow(
        """
        SELECT b.id, b.service_id, s.name AS service_name, b.lead_id,
               b.client_name, b.client_phone, b.client_email,
               b.scheduled_at, b.duration_minutes, b.status, b.notes,
               b.google_event_id, b.meet_link, b.is_test, b.key_version,
               b.created_at, b.updated_at
        FROM bookings b
        LEFT JOIN services s ON s.id = b.service_id
        WHERE b.id = $1 AND b.business_id = $2
        """,
        booking_id,
        business_id,
    )
    return _decrypt_booking_row(row) if row is not None else None


class SlotTakenError(Exception):
    """Raised when a chosen slot is no longer free (double-booking guard → 409)."""


class InvalidBookingRequest(Exception):
    """Raised for a bad service/date/time the customer chose (→ 400/422)."""


async def create_public_booking(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    service_id: str,
    date_str: str,
    time_str: str,
    name: str,
    phone: str,
    email: str | None,
    notes: str | None,
    conversation_id: str | None = None,
    is_test: bool = False,
) -> dict[str, Any]:
    """Create a LEAD + a BOOKING for a public request, in ONE transaction.

    Steps (all RLS-scoped via the shared tenant-bound `conn`):
      1. Validate the service (exists + active) → its duration.
      2. Convert the chosen LOCAL date+time to a UTC instant; re-verify it is a
         currently-OFFERED slot (in working hours + within notice/max-days) — a
         re-check, not trusting the client to send a real slot string.
      3. Double-booking guard: re-check the exact slot is still free; else raise
         SlotTakenError (→ 409).
      4. Create a lead (leads_service.create_lead, lead_name='פגישה') so the
         booking is unified with the lead pipeline (M9/M10), then insert the
         booking row linked to that lead. ALL client PII is encrypted at rest.

    Returns {booking_id, cancel_token, scheduled_at(UTC ISO)}. The caller fires
    `run_google_hook(...)` AFTER the transaction commits. NEVER logs PII.
    """
    service = await get_service(conn, business_id, service_id)
    if service is None or not service["active"]:
        raise InvalidBookingRequest("service not available")
    duration = int(service["duration_minutes"])

    start_utc = local_to_utc(date_str, time_str)
    if start_utc is None:
        raise InvalidBookingRequest("invalid date/time")

    # Re-derive the offered slots for that service+day and require the chosen
    # time to be among them (defends against a hand-crafted time off the grid /
    # outside hours / past the notice window).
    offered = await compute_slots(
        conn, business_id, service_id=service_id, date_str=date_str
    )
    if time_str not in offered:
        # Either the slot was taken between listing + submit, or it was never a
        # real slot. Treat a still-in-window-but-taken time as 409, else 400.
        if _is_future(start_utc):
            raise SlotTakenError("slot no longer available")
        raise InvalidBookingRequest("slot not offered")

    # Generate the customer's non-guessable cancel handle.
    cancel_token = secrets.token_urlsafe(_CANCEL_TOKEN_BYTES)

    # 1) The unified LEAD (consistent with M9/M10). lead_name is a generic,
    #    PII-free label; status defaults to 'in_progress' from create_lead.
    lead_id = await leads_service.create_lead(
        conn,
        business_id,
        lead_name="פגישה",
        conversation_id=conversation_id or f"booking:{cancel_token}",
        is_test=is_test,
    )

    # Enrich the lead with the customer's details + the booking summary so it shows
    # up meaningfully on the dashboard (a NAMED "booking request" — not a nameless,
    # half-filled lead). Hebrew keys map name→contact_name, phone→phone; status → 'new'.
    # A human-readable local date for the "מועד" answer (DD/MM/YYYY HH:MM), not raw
    # ISO — the customer picked date_str (YYYY-MM-DD) + time_str (HH:MM) in local time.
    _y, _m, _d = date_str.split("-")
    human_when = f"{_d}/{_m}/{_y} {time_str}"
    lead_details: dict[str, Any] = {
        "שם_מלא": name,
        "טלפון": phone,
        "שירות": service["name"],
        "מועד": human_when,
    }
    if email:
        lead_details["אימייל"] = email
    await leads_service.complete_lead(conn, business_id, lead_id, lead_details)

    # 2) The booking row — PII encrypted at rest, key_version stamped.
    row = await conn.fetchrow(
        """
        INSERT INTO bookings
            (business_id, service_id, lead_id, client_name, client_phone,
             client_email, scheduled_at, duration_minutes, status, notes,
             cancel_token, is_test, key_version)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending', $9, $10, $11, $12)
        RETURNING id, scheduled_at
        """,
        business_id,
        service_id,
        lead_id,
        crypto.encrypt_pii(name),
        crypto.encrypt_pii(phone),
        crypto.encrypt_pii(email),
        start_utc,
        duration,
        crypto.encrypt_pii(notes),
        cancel_token,
        is_test,
        crypto.CURRENT_KEY_VERSION,
    )

    # M12 usage: count a new booking for this tenant. Best-effort on the SAME
    # tenant-bound conn (RLS WITH CHECK passes); a counter failure must never break
    # booking creation. (create_lead above already bumped 'lead' for the unified
    # lead row.)
    await usage_service.bump_safe(conn, business_id, usage_service.METRIC_BOOKING)

    return {
        "booking_id": str(row["id"]),
        "cancel_token": cancel_token,
        "scheduled_at": _iso(row["scheduled_at"]),
        "lead_id": lead_id,
    }


def _is_future(start_utc: datetime) -> bool:
    """Cheap heuristic: is this instant in the future (not obviously past)?

    Used only to pick 409 vs 400 when a chosen time isn't in the offered list.
    Not a security check (the offered-list membership above is the real gate).
    """
    return start_utc > datetime.now(timezone.utc)


async def cancel_booking_by_token(
    conn: asyncpg.Connection, business_id: str, cancel_token: str
) -> dict[str, Any] | None:
    """Customer-cancel a booking via its cancel_token. None if no match.

    Sets status='cancelled' (which frees its slot for others). RLS-scoped; the
    cancel_token is the customer's unguessable handle and is matched together
    with business_id so it can only ever touch THIS tenant's row.
    """
    row = await conn.fetchrow(
        """
        UPDATE bookings
        SET status = 'cancelled'
        WHERE business_id = $1 AND cancel_token = $2
        RETURNING id, status, scheduled_at
        """,
        business_id,
        cancel_token,
    )
    if row is None:
        return None
    return {
        "booking_id": str(row["id"]),
        "status": row["status"],
        "scheduled_at": _iso(row["scheduled_at"]),
    }


async def reschedule_booking_by_token(
    conn: asyncpg.Connection,
    business_id: str,
    cancel_token: str,
    *,
    date_str: str,
    time_str: str,
) -> dict[str, Any] | None:
    """Customer-reschedule a booking via its cancel_token to a new date+time.

    Re-validates the new slot is offered + free (double-booking guard) before
    moving it. None if the token doesn't match a row for this tenant; raises
    SlotTakenError / InvalidBookingRequest like create. RLS-scoped.
    """
    existing = await conn.fetchrow(
        """
        SELECT id, service_id, duration_minutes
        FROM bookings
        WHERE business_id = $1 AND cancel_token = $2
        """,
        business_id,
        cancel_token,
    )
    if existing is None:
        return None

    new_start = await _validate_new_slot(
        conn,
        business_id,
        service_id=str(existing["service_id"]) if existing["service_id"] else None,
        date_str=date_str,
        time_str=time_str,
        exclude_booking_id=str(existing["id"]),
    )

    row = await conn.fetchrow(
        """
        UPDATE bookings
        SET scheduled_at = $3, status = 'pending'
        WHERE business_id = $1 AND cancel_token = $2
        RETURNING id, status, scheduled_at
        """,
        business_id,
        cancel_token,
        new_start,
    )
    return {
        "booking_id": str(row["id"]),
        "status": row["status"],
        "scheduled_at": _iso(row["scheduled_at"]),
    }


async def admin_update_booking(
    conn: asyncpg.Connection,
    business_id: str,
    booking_id: str,
    *,
    status: str | None,
    date_str: str | None,
    time_str: str | None,
) -> dict[str, Any] | None:
    """Owner update: set status and/or reschedule a booking. None if no match.

    A reschedule (date+time) re-validates the new slot is free (double-booking
    guard) before moving it. Status + reschedule can be combined. RLS-scoped via
    the WHERE on business_id. Returns {booking_id, status, scheduled_at}.
    """
    existing = await conn.fetchrow(
        """
        SELECT id, service_id, duration_minutes, scheduled_at, status
        FROM bookings
        WHERE id = $1 AND business_id = $2
        """,
        booking_id,
        business_id,
    )
    if existing is None:
        return None

    new_start: datetime | None = None
    if date_str is not None and time_str is not None:
        new_start = await _validate_new_slot(
            conn,
            business_id,
            service_id=str(existing["service_id"]) if existing["service_id"] else None,
            date_str=date_str,
            time_str=time_str,
            exclude_booking_id=booking_id,
        )

    sets: list[str] = []
    params: list[Any] = [booking_id, business_id]
    if status is not None:
        params.append(status)
        sets.append(f"status = ${len(params)}")
    if new_start is not None:
        params.append(new_start)
        sets.append(f"scheduled_at = ${len(params)}")
    if not sets:
        # Nothing to change → return the current shape.
        return {
            "booking_id": str(existing["id"]),
            "status": existing["status"],
            "scheduled_at": _iso(existing["scheduled_at"]),
        }

    row = await conn.fetchrow(
        f"""
        UPDATE bookings SET {', '.join(sets)}
        WHERE id = $1 AND business_id = $2
        RETURNING id, status, scheduled_at
        """,
        *params,
    )
    return {
        "booking_id": str(row["id"]),
        "status": row["status"],
        "scheduled_at": _iso(row["scheduled_at"]),
    }


async def _validate_new_slot(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    service_id: str | None,
    date_str: str,
    time_str: str,
    exclude_booking_id: str,
) -> datetime:
    """Validate a reschedule target slot is free; return its UTC start.

    Mirrors create's guard but EXCLUDES the booking being moved from the
    overlap set (so a booking doesn't collide with itself). Raises
    InvalidBookingRequest / SlotTakenError on failure.
    """
    new_start = local_to_utc(date_str, time_str)
    if new_start is None:
        raise InvalidBookingRequest("invalid date/time")

    # Re-derive offered slots for this service+day; the chosen time must be one.
    if service_id is None:
        raise InvalidBookingRequest("service unavailable")
    offered = await compute_slots(
        conn, business_id, service_id=service_id, date_str=date_str
    )
    if time_str in offered:
        return new_start

    # Not offered: distinguish "taken" (still future) → 409 vs "off-grid" → 400.
    # We re-check overlap excluding the moving booking, because compute_slots
    # counts the booking's OWN current time as taken.
    service = await get_service(conn, business_id, service_id)
    if service is None or not service["active"]:
        raise InvalidBookingRequest("service unavailable")
    duration = int(service["duration_minutes"])
    settings = await get_settings(conn, business_id)
    buffer_min = int(settings["buffer_minutes"])
    end_utc = new_start + timedelta(minutes=duration)

    # Re-check overlap EXCLUDING the moving booking precisely by id (compute_slots
    # above counts the booking's OWN current time as taken, which is why it fell
    # out of the offered list when the new time equals its old time).
    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    taken = await _bookings_on_local_day_excluding(
        conn, business_id, day, exclude_booking_id
    )
    if _overlaps_any(new_start, end_utc, duration, buffer_min, taken):
        raise SlotTakenError("slot no longer available")
    raise InvalidBookingRequest("slot not offered")


async def _bookings_on_local_day_excluding(
    conn: asyncpg.Connection, business_id: str, day: Any, exclude_booking_id: str
) -> list[tuple[datetime, int]]:
    """Like _bookings_on_local_day but excludes one booking id (the one moving)."""
    day_start_local = datetime.combine(day, time(0, 0), tzinfo=BUSINESS_TZ)
    day_end_local = day_start_local + timedelta(days=1)
    lo = (day_start_local - timedelta(hours=6)).astimezone(timezone.utc)
    hi = (day_end_local + timedelta(hours=6)).astimezone(timezone.utc)
    rows = await conn.fetch(
        """
        SELECT scheduled_at, duration_minutes
        FROM bookings
        WHERE business_id = $1
          AND status = ANY($2::text[])
          AND id <> $3
          AND scheduled_at >= $4 AND scheduled_at < $5
        """,
        business_id,
        list(_ACTIVE_BOOKING_STATUSES),
        exclude_booking_id,
        lo,
        hi,
    )
    return [(r["scheduled_at"], int(r["duration_minutes"])) for r in rows]


# ============================================================================
# public page helpers (resolve slug → business; public service/slot reads)
# ============================================================================

async def resolve_slug(pool: asyncpg.Pool, slug: str) -> str | None:
    """Resolve a public booking slug → business_id, or None (caller → 404).

    Uses the `resolve_booking_slug` SECURITY DEFINER function (migration 0010),
    which bypasses RLS to look up the slug→business mapping when there is NO
    tenant context yet (the public page has no session). It exposes ONLY the
    business id for that exact slug — nothing else. The caller then opens a
    normal tenant_connection bound to that id so EVERY subsequent read/write is
    RLS-scoped exactly like an authenticated request.
    """
    async with pool.acquire() as conn:
        business_id = await conn.fetchval("SELECT resolve_booking_slug($1)", slug)
    return str(business_id) if business_id is not None else None


async def business_display_name(conn: asyncpg.Connection, business_id: str) -> str:
    """Best-effort business display name for the public page header.

    Read RLS-scoped; businesses has RLS, so this returns the name only because
    the tenant context is set on `conn`. Never raises — falls back to "".
    """
    try:
        name = await conn.fetchval(
            "SELECT name FROM businesses WHERE id = $1", business_id
        )
        return name or ""
    except Exception:  # noqa: BLE001 — header is cosmetic; never break the page
        return ""


# ============================================================================
# decryption + small helpers
# ============================================================================

def _decrypt_booking_row(row: asyncpg.Record) -> dict[str, Any]:
    """Map one bookings row → a readable dict with client PII decrypted (owner)."""
    key_version = row["key_version"] or crypto.CURRENT_KEY_VERSION
    return {
        "id": str(row["id"]),
        "service_id": str(row["service_id"]) if row["service_id"] else None,
        "service_name": row["service_name"],
        "lead_id": str(row["lead_id"]) if row["lead_id"] else None,
        "client_name": crypto.decrypt_pii(row["client_name"], key_version),
        "client_phone": crypto.decrypt_pii(row["client_phone"], key_version),
        "client_email": crypto.decrypt_pii(row["client_email"], key_version),
        "scheduled_at": _iso(row["scheduled_at"]),
        "duration_minutes": int(row["duration_minutes"]),
        "status": row["status"],
        "notes": crypto.decrypt_pii(row["notes"], key_version),
        "google_event_id": row["google_event_id"],
        "meet_link": row["meet_link"],
        "is_test": bool(row["is_test"]),
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
    }


def _as_obj(value: Any, default: Any) -> Any:
    """asyncpg returns jsonb as a str; normalize to a Python object."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _iso(value: Any) -> str | None:
    """ISO-8601 a timestamptz (or None passes through)."""
    return value.isoformat() if value is not None else None
