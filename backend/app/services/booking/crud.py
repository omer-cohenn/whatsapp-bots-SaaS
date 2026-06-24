# לוגיקת התורים — יצירה/ביטול/שינוי תור + הליד המקושר + פענוח לבעלים
"""Booking rows: list (admin), create (public), cancel / reschedule (M11).

The tenant-scoped CRUD for `bookings`. `create_public_booking` writes a unified
LEAD + BOOKING in ONE transaction (PII encrypted at rest), and the cancel /
reschedule / admin-update paths re-validate the slot is still free (the
double-booking guard lives here AND in `slots.py`). Owner reads decrypt the
client PII; we NEVER log a name, phone, email, or note. Moved VERBATIM from the
old single-file `booking.py` — no logic change.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.core import crypto
from app.services import leads as leads_service
from app.services import usage as usage_service
from app.services.booking._helpers import _CANCEL_TOKEN_BYTES, _iso
from app.services.booking.settings import get_service, get_settings
from app.services.booking.slots import (
    _bookings_on_local_day_excluding,
    _overlaps_any,
    compute_slots,
    local_to_utc,
)


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


# ============================================================================
# decryption helper
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
