"""Google Calendar + Meet sync — the booking hook implementation (M11).

This is the concrete implementation of the decoupled hook that `booking.py`
fires AFTER every booking mutation commits. The booking core knows NOTHING about
Google; it just calls `run_google_hook(business_id, booking_id, action)`. Here we:

  * "created"     → create an event on the OWNER's primary calendar, invite the
                    customer by email, optionally attach a Google Meet link, and
                    write `google_event_id` + `meet_link` back onto the booking.
  * "rescheduled" → patch the existing event's start/end (by google_event_id).
  * "cancelled"   → delete the existing event.

RESILIENCE (decision 0011 — degrade gracefully):
  * If the business hasn't connected Google → no-op (the booking stands).
  * If ANY Google call fails → we log a GENERIC warning (no token, no PII) and
    leave google_event_id/meet_link as they were. A calendar failure must NEVER
    break a booking. The booking-core hook runner ALSO wraps us, so even an
    unexpected raise is swallowed — but we still defend in depth here.

WIRING (decoupled, no Google import in booking.py):
  At startup, `register(pool)` builds a closure that captures the app's asyncpg
  pool and registers it with `booking.register_google_hook(...)`. The hook then
  opens its OWN `tenant_connection(pool, business_id)` to read/decrypt the
  booking and the refresh token (both RLS-scoped to the verified tenant).

QA / MOCK PATH:
  The actual Google API calls go through a single seam, `_calendar_client(...)`,
  and the event-build math is a pure function, `build_event_body(...)`. A test
  can call `build_event_body` directly to assert params (summary/attendees/Meet/
  RFC3339 times) with NO network, and can register a fake client via
  `set_calendar_client_factory(...)` to assert the create/patch/delete calls.

SECURITY: the refresh token + access token are never logged or returned. Client
PII (name/email) is decrypted just-in-time only to build the invite and is never
logged. All errors to the operator are generic (no str(e) with secrets/PII).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import asyncpg

from app.core import crypto
from app.core.logging import get_logger
from app.db.session import tenant_connection
from app.services import booking as booking_service
from app.services import google_oauth

log = get_logger("app.services.google_calendar")

# The owner's default calendar. We always act on "primary" (no calendar picker in
# the MVP) — events land on the connected account's main calendar.
_PRIMARY_CALENDAR = "primary"

# Google's RFC3339 expects an explicit timezone. We send the FIXED business tz so
# Google renders the local wall-clock correctly; the instant itself is unambiguous.
_BUSINESS_TZ_NAME = "Asia/Jerusalem"


# ============================================================================
# Calendar client seam (real Google client by default; swappable for QA)
# ============================================================================

# A CalendarClient is any object exposing create_event / patch_event /
# delete_event. The real one wraps google-api-python-client; tests inject a fake.
class CalendarClient:
    """Thin async-friendly wrapper around the Google Calendar v3 events API.

    google-api-python-client is synchronous, so each call is run in a thread via
    asyncio.to_thread by the hook (we keep the wrapper itself plain-sync here and
    let the caller offload it). The wrapper is built from a refresh token →
    short-lived credentials; the token is never logged.
    """

    def __init__(self, refresh_token: str) -> None:
        # Import inside the constructor so the heavy Google libs are only loaded
        # when calendar sync actually runs (validate-at-use; keeps boot light and
        # lets the feature be absent without import errors).
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        settings = _google_settings()
        creds = Credentials(
            token=None,  # no access token yet; refreshed on first use by the lib
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings["client_id"],
            client_secret=settings["client_secret"],
            scopes=[google_oauth.CALENDAR_SCOPE],
        )
        # cache_discovery=False avoids a noisy file-cache warning in containers.
        self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    def create_event(self, body: dict[str, Any], *, with_meet: bool) -> dict[str, Any]:
        """Insert an event; conferenceDataVersion=1 only when requesting Meet."""
        return (
            self._service.events()
            .insert(
                calendarId=_PRIMARY_CALENDAR,
                body=body,
                conferenceDataVersion=1 if with_meet else 0,
                sendUpdates="all",  # email the attendee (the customer) the invite
            )
            .execute()
        )

    def patch_event(self, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Patch an existing event (used for reschedule — start/end only)."""
        return (
            self._service.events()
            .patch(
                calendarId=_PRIMARY_CALENDAR,
                eventId=event_id,
                body=body,
                sendUpdates="all",
            )
            .execute()
        )

    def delete_event(self, event_id: str) -> None:
        """Delete an event (used for cancel). 410/404 are treated as already-gone."""
        from googleapiclient.errors import HttpError

        try:
            self._service.events().delete(
                calendarId=_PRIMARY_CALENDAR,
                eventId=event_id,
                sendUpdates="all",
            ).execute()
        except HttpError as exc:
            # Already deleted on Google's side → idempotent success, not a failure.
            if getattr(exc, "status_code", None) in (404, 410) or getattr(
                getattr(exc, "resp", None), "status", None
            ) in (404, 410):
                return
            raise


# The factory used to build a client from a refresh token. Tests swap this with
# `set_calendar_client_factory` to inject a fake (asserting create/patch/delete).
CalendarClientFactory = Callable[[str], Any]
_client_factory: CalendarClientFactory = CalendarClient


def set_calendar_client_factory(factory: CalendarClientFactory | None) -> None:
    """Override (or reset) the calendar-client factory — the QA/mock seam.

    Passing None restores the real Google client. A test passes a factory that
    returns a fake exposing create_event/patch_event/delete_event so the hook's
    behavior + the event body can be asserted with NO network.
    """
    global _client_factory
    _client_factory = factory or CalendarClient


def _google_settings() -> dict[str, str]:
    """The client id/secret reused from the login OAuth app (never logged)."""
    from app.core.config import get_settings

    s = get_settings()
    return {
        "client_id": s.google_client_id.get_secret_value(),
        "client_secret": s.google_client_secret.get_secret_value(),
    }


# ============================================================================
# pure event-body builder (no network — unit-testable)
# ============================================================================

def build_event_body(
    *,
    service_name: str | None,
    notes: str | None,
    client_name: str | None,
    client_email: str | None,
    start_utc: datetime,
    duration_minutes: int,
    with_meet: bool,
    meet_request_id: str | None = None,
) -> dict[str, Any]:
    """Build the Google Calendar v3 event body for a booking (pure function).

    start_utc is an aware UTC datetime; we emit RFC3339 with the FIXED business
    timezone so Google shows the correct local wall-clock. The customer is added
    as an attendee by email (so they get an email invite) only when an email was
    provided. When `with_meet` is set we attach a conferenceData.createRequest
    with a UNIQUE requestId (the caller passes one) — the caller must then send
    conferenceDataVersion=1 so Google actually provisions the Meet link.

    No PII is logged here; this only SHAPES the payload. The summary uses the
    service name (falling back to a generic label) + the customer name if present.
    """
    end_utc = start_utc + timedelta(minutes=duration_minutes)

    label = service_name or "פגישה"
    summary = f"{label} — {client_name}" if client_name else label

    description_parts = [f"שירות: {label}"]
    if notes:
        description_parts.append(f"הערות: {notes}")
    description_parts.append("נקבע דרך Bizz_up")

    body: dict[str, Any] = {
        "summary": summary,
        "description": "\n".join(description_parts),
        "start": {
            "dateTime": _rfc3339(start_utc),
            "timeZone": _BUSINESS_TZ_NAME,
        },
        "end": {
            "dateTime": _rfc3339(end_utc),
            "timeZone": _BUSINESS_TZ_NAME,
        },
    }

    # Invite the customer by email → they receive a Google Calendar invitation.
    if client_email:
        body["attendees"] = [{"email": client_email}]

    # Google Meet: a createRequest with a unique requestId; the caller passes
    # conferenceDataVersion=1 so Google provisions the link + returns hangoutLink.
    if with_meet:
        body["conferenceData"] = {
            "createRequest": {
                "requestId": meet_request_id or "",
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

    return body


def build_reschedule_patch(start_utc: datetime, duration_minutes: int) -> dict[str, Any]:
    """The minimal patch body to move an event to a new start/end (reschedule)."""
    end_utc = start_utc + timedelta(minutes=duration_minutes)
    return {
        "start": {"dateTime": _rfc3339(start_utc), "timeZone": _BUSINESS_TZ_NAME},
        "end": {"dateTime": _rfc3339(end_utc), "timeZone": _BUSINESS_TZ_NAME},
    }


def _rfc3339(dt: datetime) -> str:
    """Aware datetime → RFC3339 (ISO-8601 with offset). UTC stored, offset emitted."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def extract_meet_link(event: dict[str, Any]) -> str | None:
    """Pull the Meet link from a created event (hangoutLink or conferenceData)."""
    link = event.get("hangoutLink")
    if link:
        return link
    # Fallback: dig into conferenceData entryPoints for the video URI.
    conf = event.get("conferenceData") or {}
    for ep in conf.get("entryPoints") or []:
        if ep.get("entryPointType") == "video" and ep.get("uri"):
            return ep["uri"]
    return None


# ============================================================================
# the hook — registered with booking.register_google_hook at startup
# ============================================================================

def register(pool: asyncpg.Pool) -> None:
    """Wire the calendar sync into the booking core (call once at startup).

    Builds a closure capturing the asyncpg pool (the hook gets only ids, not a
    connection) and registers it. After this, every committed booking mutation
    fires `sync_booking` best-effort.
    """

    async def _hook(business_id: str, booking_id: str, action: str) -> None:
        await sync_booking(pool, business_id, booking_id, action)

    booking_service.register_google_hook(_hook)
    log.info("google calendar hook registered")


async def sync_booking(
    pool: asyncpg.Pool, business_id: str, booking_id: str, action: str
) -> None:
    """Sync ONE booking to Google Calendar for the given action. Best-effort.

    Opens its own tenant_connection (RLS-scoped to the verified business). Reads
    the booking + Meet toggle + refresh token; if the business hasn't connected
    Google, it's a clean no-op. ANY failure is swallowed + logged generically so
    a calendar problem can never break the booking. NEVER logs tokens/PII.
    """
    try:
        async with tenant_connection(pool, business_id) as conn:
            refresh_token = await google_oauth.load_refresh_token(conn, business_id)
            if not refresh_token:
                # Business hasn't connected Google → nothing to do (booking stands).
                return

            booking = await booking_service.get_booking(conn, business_id, booking_id)
            if booking is None:
                return

            if action == "cancelled":
                await _do_cancel(conn, business_id, booking, refresh_token)
            elif action == "rescheduled":
                await _do_reschedule(conn, business_id, booking, refresh_token)
            else:  # "created" (default)
                await _do_create(conn, business_id, booking, refresh_token)
    except Exception:  # noqa: BLE001 — degrade gracefully; no token/PII/str(e)
        log.warning("google calendar sync failed", extra={"action": action})


async def _do_create(
    conn: asyncpg.Connection,
    business_id: str,
    booking: dict[str, Any],
    refresh_token: str,
) -> None:
    """Create the calendar event for a new booking + persist event id/Meet link."""
    settings = await booking_service.get_settings(conn, business_id)
    with_meet = bool(settings.get("meet_enabled"))

    start_utc = _parse_iso(booking["scheduled_at"])
    if start_utc is None:
        return

    # A unique Meet requestId per booking so retries don't collide on Google.
    meet_request_id = f"bizzup-{booking['id']}" if with_meet else None
    body = build_event_body(
        service_name=booking.get("service_name"),
        notes=booking.get("notes"),
        client_name=booking.get("client_name"),
        client_email=booking.get("client_email"),
        start_utc=start_utc,
        duration_minutes=int(booking["duration_minutes"]),
        with_meet=with_meet,
        meet_request_id=meet_request_id,
    )

    client = _client_factory(refresh_token)
    event = await _run(client.create_event, body, with_meet=with_meet)

    event_id = event.get("id")
    meet_link = extract_meet_link(event) if with_meet else None
    if event_id:
        await conn.execute(
            """
            UPDATE bookings
            SET google_event_id = $3, meet_link = $4
            WHERE id = $1 AND business_id = $2
            """,
            booking["id"],
            business_id,
            event_id,
            meet_link,
        )


async def _do_reschedule(
    conn: asyncpg.Connection,
    business_id: str,
    booking: dict[str, Any],
    refresh_token: str,
) -> None:
    """Patch the event's time on reschedule. Creates one if none exists yet."""
    event_id = booking.get("google_event_id")
    start_utc = _parse_iso(booking["scheduled_at"])
    if start_utc is None:
        return

    # No prior event (e.g. connected AFTER the booking) → create it now instead.
    if not event_id:
        await _do_create(conn, business_id, booking, refresh_token)
        return

    patch = build_reschedule_patch(start_utc, int(booking["duration_minutes"]))
    client = _client_factory(refresh_token)
    await _run(client.patch_event, event_id, patch)


async def _do_cancel(
    conn: asyncpg.Connection,
    business_id: str,
    booking: dict[str, Any],
    refresh_token: str,
) -> None:
    """Delete the calendar event on cancel + clear the stored event id/link."""
    event_id = booking.get("google_event_id")
    if not event_id:
        return
    client = _client_factory(refresh_token)
    await _run(client.delete_event, event_id)
    # Clear our pointers so a later reschedule won't try to patch a dead event.
    await conn.execute(
        """
        UPDATE bookings
        SET google_event_id = NULL, meet_link = NULL
        WHERE id = $1 AND business_id = $2
        """,
        booking["id"],
        business_id,
    )


async def _run(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a (possibly blocking) Google client call off the event loop.

    The real google-api-python-client is synchronous, so we offload to a thread.
    A fake test client may be sync OR async — we await it if it returns an
    awaitable, otherwise thread-offload it. Keeps the hook non-blocking either way.
    """
    import asyncio
    import inspect

    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    result = await asyncio.to_thread(func, *args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 string (the booking's scheduled_at) → aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# Re-export so callers/tests can reference the crypto domain used for the token.
__all__ = [
    "register",
    "sync_booking",
    "build_event_body",
    "build_reschedule_patch",
    "extract_meet_link",
    "set_calendar_client_factory",
    "CalendarClient",
    "crypto",
]
