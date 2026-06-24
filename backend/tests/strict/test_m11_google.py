"""M11 strict — GOOGLE Calendar in MOCK: hook params, Meet toggle, no token leak.

Split out of the original test_m11.py (shared fixtures/helpers live in
_m11_helpers.py). Per decision 0011.

  8. GOOGLE (MOCK) — the create hook is called with the right params; Meet only
     when meet_enabled; a Google failure does NOT break the booking; the
     refresh_token never appears in any response; creds are tenant-scoped.
"""

from __future__ import annotations

import secrets

import pytest

from _m11_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    AVI_USER,
    BIZ_A,
    BIZ_B,
    _ALL_DAYS_9_17,
    _login,
    _make_service,
    _real_future_date,
    _set_settings,
    cleanup,
    google_hook,
    http,
    lifespan_app,
    pool,
    rds,
)
from app.db.session import tenant_connection
from app.services import booking as booking_service
from app.services import google_calendar
from app.services import google_oauth


# ============================================================================
#  GOAL 8 — GOOGLE in MOCK: hook params, Meet toggle, graceful failure, no token
# ============================================================================

class _FakeCalendar:
    """A fake calendar client recording the calls + bodies (no network)."""

    instances: list["_FakeCalendar"] = []

    def __init__(self, refresh_token: str):
        self.refresh_token = refresh_token
        self.created: list[tuple[dict, bool]] = []
        self.patched: list[tuple[str, dict]] = []
        self.deleted: list[str] = []
        _FakeCalendar.instances.append(self)

    def create_event(self, body, *, with_meet):
        self.created.append((body, with_meet))
        ev = {"id": "evt-" + secrets.token_hex(4)}
        if with_meet:
            ev["hangoutLink"] = "https://meet.google.com/fake-abc-def"
        return ev

    def patch_event(self, event_id, body):
        self.patched.append((event_id, body))
        return {"id": event_id}

    def delete_event(self, event_id):
        self.deleted.append(event_id)


class _BoomCalendar:
    """A fake client whose create_event raises — to prove graceful degradation."""

    def __init__(self, refresh_token: str):
        pass

    def create_event(self, body, *, with_meet):
        raise RuntimeError("google is down")


async def _connect_google(pool, business_id: str, *, meet: bool) -> None:
    """Store a (fake) KEK-encrypted refresh token + set the meet toggle."""
    await _set_settings(pool, business_id, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0, meet=meet)
    async with tenant_connection(pool, business_id) as conn:
        await google_oauth.store_credentials(
            conn, business_id, token={
                "refresh_token": "fake-refresh-token-SECRET",
                "scope": google_oauth.CALENDAR_SCOPE,
                "id_token": "",
            })


async def _connect_google_and_slug(pool, business_id: str, *, meet: bool) -> str:
    """Like _connect_google but returns the slug (settings + creds in one go)."""
    slug = await _set_settings(pool, business_id, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0, meet=meet)
    async with tenant_connection(pool, business_id) as conn:
        await google_oauth.store_credentials(
            conn, business_id, token={
                "refresh_token": "fake-refresh-token-SECRET",
                "scope": google_oauth.CALENDAR_SCOPE, "id_token": ""})
    return slug


@pytest.mark.asyncio
async def test_google_hook_called_with_right_params_no_meet(pool, google_hook, cleanup):
    """When connected + meet OFF: the create hook fires with attendee=email and
    NO conferenceData; the event id is written back; no meet_link stored."""
    _FakeCalendar.instances = []
    google_calendar.set_calendar_client_factory(_FakeCalendar)
    await _connect_google(pool, BIZ_A, meet=False)
    svc = await _make_service(pool, BIZ_A, name="ייעוץ", duration=60)
    date = _real_future_date()

    async with tenant_connection(pool, BIZ_A) as conn:
        res = await booking_service.create_public_booking(
            conn, BIZ_A, service_id=svc, date_str=date, time_str="09:00",
            name="דנה", phone="+972500000010", email="dana@example.com",
            notes=None, is_test=True)
    booking_id = res["booking_id"]

    # Fire the hook the way the route does (after commit).
    await booking_service.run_google_hook(BIZ_A, booking_id, "created")

    assert _FakeCalendar.instances, "calendar client was never built"
    fake = _FakeCalendar.instances[-1]
    assert fake.refresh_token == "fake-refresh-token-SECRET"
    assert len(fake.created) == 1, "create_event not called exactly once"
    body, with_meet = fake.created[0]
    assert with_meet is False
    assert "conferenceData" not in body, "Meet attached although meet_enabled=false"
    assert body["attendees"] == [{"email": "dana@example.com"}]
    # The event carries the FIXED business timeZone so Google renders the correct
    # local wall-clock; the instant itself is the UTC one we stored. 09:00 local on
    # a summer date == 06:00Z, which is exactly what the booking start equals.
    assert body["start"]["timeZone"] == "Asia/Jerusalem"
    expected_utc = booking_service.local_to_utc(date, "09:00")
    assert body["start"]["dateTime"] == expected_utc.isoformat()
    assert body["start"]["dateTime"].startswith(f"{date}T06:00")  # 09:00 IDT = 06:00Z

    # The event id was persisted; no meet link (meet off).
    async with tenant_connection(pool, BIZ_A) as conn:
        row = await conn.fetchrow(
            "SELECT google_event_id, meet_link FROM bookings WHERE id=$1", booking_id)
    assert row["google_event_id"] and row["google_event_id"].startswith("evt-")
    assert row["meet_link"] is None


@pytest.mark.asyncio
async def test_google_meet_only_when_enabled(pool, google_hook, cleanup):
    """meet_enabled=true → create requests Meet (conferenceData) and the link is
    stored; the body carries a unique conference createRequest."""
    _FakeCalendar.instances = []
    google_calendar.set_calendar_client_factory(_FakeCalendar)
    await _connect_google(pool, BIZ_A, meet=True)
    svc = await _make_service(pool, BIZ_A, duration=60)
    date = _real_future_date()

    async with tenant_connection(pool, BIZ_A) as conn:
        res = await booking_service.create_public_booking(
            conn, BIZ_A, service_id=svc, date_str=date, time_str="10:00",
            name="עוז", phone="+972500000011", email="oz@example.com",
            notes=None, is_test=True)
    await booking_service.run_google_hook(BIZ_A, res["booking_id"], "created")

    fake = _FakeCalendar.instances[-1]
    body, with_meet = fake.created[0]
    assert with_meet is True
    assert "conferenceData" in body
    assert body["conferenceData"]["createRequest"]["requestId"]

    async with tenant_connection(pool, BIZ_A) as conn:
        link = await conn.fetchval(
            "SELECT meet_link FROM bookings WHERE id=$1", res["booking_id"])
    assert link == "https://meet.google.com/fake-abc-def"


@pytest.mark.asyncio
async def test_google_failure_does_not_break_booking(http, pool, cleanup):
    """A Google create that RAISES must NOT break the booking: the row stands,
    google_event_id stays null, and the public POST still returns 201."""
    google_calendar.set_calendar_client_factory(_BoomCalendar)
    slug = await _connect_google_and_slug(pool, BIZ_A, meet=False)
    svc = await _make_service(pool, BIZ_A, duration=60)
    date = _real_future_date()

    r = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": date, "time": "09:00",
        "name": "גיל", "phone": "+972500000012", "email": "gil@example.com"})
    assert r.status_code == 201, "a Google failure broke the booking!"
    booking_id = r.json()["booking_id"]
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", booking_id)
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_A)
        row = await conn.fetchrow(
            "SELECT status, google_event_id FROM bookings WHERE id=$1", booking_id)
    assert row["status"] == "pending"
    assert row["google_event_id"] is None, "a failed Google call wrote an event id"


@pytest.mark.asyncio
async def test_no_google_connected_is_noop(pool, google_hook, cleanup):
    """A business with NO google_credentials: the create hook is a clean no-op
    (no client built, booking unaffected)."""
    _FakeCalendar.instances = []
    google_calendar.set_calendar_client_factory(_FakeCalendar)
    # settings only — NO credentials stored.
    await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)
    date = _real_future_date()
    async with tenant_connection(pool, BIZ_A) as conn:
        res = await booking_service.create_public_booking(
            conn, BIZ_A, service_id=svc, date_str=date, time_str="09:00",
            name="נ", phone="+972500000013", email=None, notes=None, is_test=True)
    await booking_service.run_google_hook(BIZ_A, res["booking_id"], "created")
    assert _FakeCalendar.instances == [], "built a calendar client with no creds"


@pytest.mark.asyncio
async def test_refresh_token_never_in_status_response(http, rds, pool, cleanup):
    """GET /api/google/status reports connected + email but NEVER the token, and
    the response text contains no trace of the stored refresh token."""
    await _connect_google(pool, BIZ_A, meet=False)
    await _login(rds, http, AVI_USER, BIZ_A)
    r = await http.get("/api/google/status")
    assert r.status_code == 200
    data = r.json()
    assert data["connected"] is True
    assert "refresh_token" not in data
    assert "token" not in r.text.lower() or "refresh-token-SECRET" not in r.text
    assert "fake-refresh-token-SECRET" not in r.text


@pytest.mark.asyncio
async def test_google_creds_isolated_per_tenant(http, rds, pool, cleanup):
    """B connects Google; A's status stays disconnected (creds are tenant-scoped)."""
    await _connect_google(pool, BIZ_B, meet=False)
    await _login(rds, http, AVI_USER, BIZ_A)
    r = await http.get("/api/google/status")
    assert r.json()["connected"] is False, "A saw B's Google connection!"
