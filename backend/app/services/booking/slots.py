# לוגיקת התורים — חישוב הזמנים הפנויים (slot algorithm) + המרות זמן
"""The slot algorithm: bookable start times for a (service, date) (M11).

This is the heart of the public booking page. `compute_slots` derives the free
LOCAL "HH:MM" starts for a service on one day (working hours + buffer + notice +
max-days windows, minus times that overlap a live booking), and
`compute_availability` loops it over a bounded date range. The overlap math +
LOCAL↔UTC conversions (Asia/Jerusalem via zoneinfo, decision 0011) live here too.
Moved VERBATIM from the old single-file `booking.py` — no logic change.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

import asyncpg

from app.services.booking._helpers import _ACTIVE_BOOKING_STATUSES, BUSINESS_TZ
from app.services.booking.settings import get_service, get_settings


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
