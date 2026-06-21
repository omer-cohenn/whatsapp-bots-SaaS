"""M11 — public booking + per-business Google Calendar, strict pytest (CI).

Per decision 0011. This suite proves the M11 contract end-to-end against the
REAL ASGI app over httpx ASGITransport (so the deny-by-default /api gate, the
session dependency, tenant_connection/RLS and the public-slug bootstrap are all
exercised), and drives the slot algorithm + crypto + the Google hook directly
where a test needs exact control.

What it proves (mapped to the QA goals):

  2. SLOT ALGORITHM — split working-hours ranges (e.g. 09-13 + 16-19) yield
     exactly the right slots; two services with different durations differ.
  3. RULES — min_notice / max_days_ahead / buffer filter correctly; computed in
     Asia/Jerusalem, stored UTC.
  4. PUBLIC BOOKING — creates a LEAD + a booking; the RAW client PII columns are
     NOT plaintext (encrypted at rest) and decrypt for the owner.
  5. GUARDS — double-booking → 409; unknown slug → 404; junk fields rejected.
  6. CANCEL / RESCHEDULE — via cancel_token AND via owner PATCH both work.
  7. TENANT ISOLATION (incl. C4) — A cannot read/list/PATCH B's
     bookings/services/settings (foreign PATCH → 404); admin routes 401 without a
     session; public routes never expose another tenant.
  8. GOOGLE (MOCK) — the create hook is called with the right params; Meet only
     when meet_enabled; a Google failure does NOT break the booking; the
     refresh_token never appears in any response.

Every persisted row is is_test=true; the cleanup fixture deletes the test
bookings/leads/services/settings/credentials and Redis keys it created. Nothing
prints a secret, a token, or PII.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import booking as booking_service
from app.services import google_calendar
from app.services import google_oauth
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

JLM = ZoneInfo("Asia/Jerusalem")

# A FIXED "now" far in the future on a quiet weekday so notice/max-days math is
# deterministic and the test never collides with a real-clock boundary. We pick a
# Wednesday (2099-06-10) at 06:00 UTC (= 09:00 local in summer DST).
FIXED_NOW = datetime(2099, 6, 10, 6, 0, tzinfo=timezone.utc)


# --- fixtures ---------------------------------------------------------------

@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=4)
    try:
        yield p
    finally:
        await p.close()


@pytest_asyncio.fixture
async def rds():
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        yield r
    finally:
        await r.aclose()


@pytest_asyncio.fixture
async def lifespan_app():
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def http(lifespan_app):
    transport = ASGITransport(app=lifespan_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def google_hook(pool):
    """Register the real Google-calendar sync hook against the TEST pool.

    The hook is normally wired in the app lifespan (main.py). The Google-direct
    tests don't spin up the lifespan, so they register it here against their own
    pool; the calendar client itself is still the injected fake. Unregistered on
    teardown so it can't leak into another test."""
    google_calendar.register(pool)
    yield
    booking_service.register_google_hook(None)


@pytest_asyncio.fixture
async def cleanup(pool, rds):
    """After each test: delete every is_test booking + lead and any settings /
    services / google_credentials we touched, plus rate-limit Redis keys.

    We always reset the Google hook + calendar factory + any in-DB google creds so
    one test's mock can never leak into the next.
    """
    yield
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute(
                "DELETE FROM bookings WHERE business_id = $1 AND is_test = true", bid)
            # Booking-created leads use lead_name='פגישה'. The PUBLIC HTTP path
            # always creates them is_test=false (the route has no test flag), so we
            # must clean BOTH is_test leads AND those booking leads to leave a
            # pristine slate for the M2 wall (which expects no stray rows).
            await conn.execute(
                "DELETE FROM leads WHERE business_id = $1 "
                "AND (is_test = true OR lead_name = 'פגישה')", bid)
            await conn.execute("DELETE FROM services WHERE business_id = $1", bid)
            await conn.execute("DELETE FROM booking_settings WHERE business_id = $1", bid)
            await conn.execute("DELETE FROM google_credentials WHERE business_id = $1", bid)
    # Reset the Google seam so the real client + no hook side effects remain.
    google_calendar.set_calendar_client_factory(None)
    # Clear rate-limit buckets created by public POSTs.
    keys = await rds.keys("ratelimit:book:*")
    if keys:
        await rds.delete(*keys)


# --- helpers ----------------------------------------------------------------

async def _login(rds, http, user_id: str, business_id: str) -> None:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": f"{user_id}@example.com", "name": user_id,
        "picture": "", "business_id": business_id, "business_name": "x",
        "created_at": int(time.time()),
    }
    await rds.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)


async def _set_settings(pool, business_id: str, *, working_hours: dict,
                        min_notice=120, buffer=0, max_days=365, meet=False) -> str:
    """UPSERT booking_settings for a tenant with a fresh slug; return the slug."""
    slug = "t-" + secrets.token_urlsafe(8)
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            """
            INSERT INTO booking_settings
                (business_id, working_hours, min_notice_minutes, buffer_minutes,
                 max_days_ahead, meet_enabled, slug)
            VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7)
            ON CONFLICT (business_id) DO UPDATE SET
                working_hours = EXCLUDED.working_hours,
                min_notice_minutes = EXCLUDED.min_notice_minutes,
                buffer_minutes = EXCLUDED.buffer_minutes,
                max_days_ahead = EXCLUDED.max_days_ahead,
                meet_enabled = EXCLUDED.meet_enabled
            """,
            business_id, json.dumps(working_hours), min_notice, buffer, max_days,
            meet, slug,
        )
    return slug


async def _make_service(pool, business_id: str, *, name="ייעוץ",
                        duration=30, active=True) -> str:
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO services (business_id, name, duration_minutes, active)
            VALUES ($1, $2, $3, $4) RETURNING id
            """,
            business_id, name, duration, active,
        )
    return str(row["id"])


def _future_date(days_from_now: int, weekday_local: int | None = None) -> str:
    """A local YYYY-MM-DD `days_from_now` after FIXED_NOW (optionally a weekday).

    weekday_local uses Python Mon=0..Sun=6 if given (we step forward to it).
    Used ONLY by pure compute_slots(now=FIXED_NOW) tests, where the date math is
    anchored to the SAME injected FIXED_NOW so it's fully deterministic.
    """
    d = (FIXED_NOW.astimezone(JLM) + timedelta(days=days_from_now)).date()
    if weekday_local is not None:
        while d.weekday() != weekday_local:
            d += timedelta(days=1)
    return d.isoformat()


def _real_future_date(min_days_ahead: int = 7, weekday_local: int = 2) -> str:
    """A local YYYY-MM-DD at least `min_days_ahead` after the REAL clock, on a given
    weekday (Python Mon=0..Sun=6; default Wed=2).

    The HTTP / create_public_booking paths call compute_slots WITHOUT an injected
    `now`, so they use the real server clock. These tests must pick a date relative
    to REAL now (with generous max_days_ahead) so the slot survives notice/max-days.
    """
    d = (datetime.now(JLM) + timedelta(days=min_days_ahead)).date()
    while d.weekday() != weekday_local:
        d += timedelta(days=1)
    return d.isoformat()


def _wd_key(date_str: str) -> str:
    """Our working_hours weekday key (Sun=0..Sat=6) for a YYYY-MM-DD date."""
    return str((datetime.fromisoformat(date_str).weekday() + 1) % 7)


# Every weekday 09:00–17:00 — used by the HTTP / create-path tests so a real-clock
# future date always lands on an OPEN day regardless of which weekday it is.
_ALL_DAYS_9_17 = {str(k): [{"s": "09:00", "e": "17:00"}] for k in range(7)}


# ============================================================================
#  GOAL 2 — SLOT ALGORITHM: split ranges + multi-service durations
# ============================================================================

@pytest.mark.asyncio
async def test_split_ranges_yield_exact_slots(pool, cleanup):
    """A weekday with TWO ranges 09-13 + 16-19 and a 60-min service yields exactly
    the morning starts 09..12 and the evening starts 16..18 (no buffer)."""
    # Use a date far enough out that min_notice never trims it, and a weekday that
    # is OPEN. We open only Wednesday (local weekday 2) with the split ranges.
    date = _future_date(7, weekday_local=2)  # a Wednesday
    wd = str((datetime.fromisoformat(date).weekday() + 1) % 7)  # our Sun=0 key
    await _set_settings(pool, BIZ_A, working_hours={
        wd: [{"s": "09:00", "e": "13:00"}, {"s": "16:00", "e": "19:00"}]
    }, min_notice=0, buffer=0)
    svc = await _make_service(pool, BIZ_A, duration=60)

    async with tenant_connection(pool, BIZ_A) as conn:
        slots = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=date, now=FIXED_NOW)

    assert slots == ["09:00", "10:00", "11:00", "12:00",
                     "16:00", "17:00", "18:00"], slots


@pytest.mark.asyncio
async def test_multi_service_durations_differ(pool, cleanup):
    """Two services with different durations produce different slot grids on the
    same day/hours: a 30-min service has twice as many starts as a 60-min one."""
    date = _future_date(7, weekday_local=2)
    wd = str((datetime.fromisoformat(date).weekday() + 1) % 7)
    await _set_settings(pool, BIZ_A, working_hours={
        wd: [{"s": "09:00", "e": "12:00"}]
    }, min_notice=0, buffer=0)
    svc30 = await _make_service(pool, BIZ_A, name="קצר", duration=30)
    svc60 = await _make_service(pool, BIZ_A, name="ארוך", duration=60)

    async with tenant_connection(pool, BIZ_A) as conn:
        s30 = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc30, date_str=date, now=FIXED_NOW)
        s60 = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc60, date_str=date, now=FIXED_NOW)

    assert s30 == ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30"], s30
    assert s60 == ["09:00", "10:00", "11:00"], s60


@pytest.mark.asyncio
async def test_closed_weekday_returns_no_slots(pool, cleanup):
    """A weekday with no ranges configured → [] (the day is closed)."""
    date = _future_date(7, weekday_local=2)  # Wednesday
    # Only open MONDAY (local weekday 0 → our key); the requested Wed is closed.
    await _set_settings(pool, BIZ_A, working_hours={
        "1": [{"s": "09:00", "e": "17:00"}]  # our "1" = Monday
    }, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=30)

    async with tenant_connection(pool, BIZ_A) as conn:
        slots = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=date, now=FIXED_NOW)
    assert slots == []


# ============================================================================
#  GOAL 3 — RULES: min_notice / max_days_ahead / buffer (Asia/Jerusalem → UTC)
# ============================================================================

@pytest.mark.asyncio
async def test_min_notice_trims_early_slots(pool, cleanup):
    """With now=09:00 local and min_notice=120, slots before 11:00 local on TODAY
    are removed; 11:00 onward survive."""
    # FIXED_NOW is 06:00 UTC = 09:00 local (summer DST). Book TODAY (same local day).
    today_local = FIXED_NOW.astimezone(JLM).date().isoformat()
    wd = str((datetime.fromisoformat(today_local).weekday() + 1) % 7)
    await _set_settings(pool, BIZ_A, working_hours={
        wd: [{"s": "09:00", "e": "14:00"}]
    }, min_notice=120, buffer=0)
    svc = await _make_service(pool, BIZ_A, duration=60)

    async with tenant_connection(pool, BIZ_A) as conn:
        slots = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=today_local, now=FIXED_NOW)

    # earliest bookable = 09:00 + 120min = 11:00 local. So 09:00/10:00 are gone.
    assert "09:00" not in slots and "10:00" not in slots
    assert slots[0] == "11:00", slots


@pytest.mark.asyncio
async def test_max_days_ahead_excludes_far_future(pool, cleanup):
    """A date beyond max_days_ahead yields [] even though the weekday is open."""
    await _set_settings(pool, BIZ_A, working_hours={
        "0": [{"s": "09:00", "e": "17:00"}],
        "1": [{"s": "09:00", "e": "17:00"}],
        "2": [{"s": "09:00", "e": "17:00"}],
        "3": [{"s": "09:00", "e": "17:00"}],
        "4": [{"s": "09:00", "e": "17:00"}],
        "5": [{"s": "09:00", "e": "17:00"}],
        "6": [{"s": "09:00", "e": "17:00"}],
    }, min_notice=0, max_days=7)
    svc = await _make_service(pool, BIZ_A, duration=60)

    far = _future_date(30)  # well beyond the 7-day window
    near = _future_date(3)
    async with tenant_connection(pool, BIZ_A) as conn:
        far_slots = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=far, now=FIXED_NOW)
        near_slots = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=near, now=FIXED_NOW)
    assert far_slots == []
    assert near_slots, "a within-window day should have slots"


@pytest.mark.asyncio
async def test_buffer_widens_step_and_blocks_neighbours(pool, cleanup):
    """A 30-min service with a 30-min buffer steps every 60 min (duration+buffer):
    the grid is 09:00/10:00/11:00/12:00. Booking 10:00 then removes ONLY 10:00 —
    the neighbours 09:00 and 11:00 sit exactly the buffer gap away and survive
    (back-to-back-with-gap is allowed; that's the point of the buffer)."""
    date = _future_date(7, weekday_local=2)
    wd = _wd_key(date)
    await _set_settings(pool, BIZ_A, working_hours={
        wd: [{"s": "09:00", "e": "13:00"}]
    }, min_notice=0, buffer=30)
    svc = await _make_service(pool, BIZ_A, duration=30)

    async with tenant_connection(pool, BIZ_A) as conn:
        before = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=date, now=FIXED_NOW)
        # step = 30 (dur) + 30 (buffer) = 60 → 09:00,10:00,11:00,12:00
        assert before == ["09:00", "10:00", "11:00", "12:00"], before

        # Book 10:00. Its buffer-padded block is [09:30, 11:00]; the 09:00 and
        # 11:00 candidates touch that edge but do not OVERLAP it → they survive.
        start_utc = booking_service.local_to_utc(date, "10:00")
        await conn.execute(
            """
            INSERT INTO bookings
              (business_id, service_id, scheduled_at, duration_minutes, status,
               cancel_token, is_test)
            VALUES ($1, $2, $3, 30, 'confirmed', $4, true)
            """,
            BIZ_A, svc, start_utc, secrets.token_urlsafe(8))

        after = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=date, now=FIXED_NOW)
    assert "10:00" not in after, "the booked slot was still offered"
    assert after == ["09:00", "11:00", "12:00"], after


@pytest.mark.asyncio
async def test_local_to_utc_dst_offset(pool, cleanup):
    """09:00 local on a summer date == 06:00 UTC (Asia/Jerusalem DST = +3)."""
    date = _future_date(7, weekday_local=2)  # June → IDT (+3)
    start_utc = booking_service.local_to_utc(date, "09:00")
    assert start_utc.tzinfo == timezone.utc
    assert start_utc.hour == 6 and start_utc.minute == 0, start_utc


# ============================================================================
#  GOAL 4 — PUBLIC BOOKING: creates a lead + booking; PII encrypted at rest
# ============================================================================

@pytest.mark.asyncio
async def test_public_booking_creates_lead_and_encrypts_pii(http, rds, pool, cleanup):
    """POST /api/book/{slug} creates a lead + a booking; the RAW client_* DB
    columns are NOT plaintext, and the owner reads them back decrypted."""
    date = _real_future_date()
    slug = await _set_settings(pool, BIZ_A, working_hours={
        _wd_key(date): [{"s": "09:00", "e": "17:00"}],
    }, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)

    name = "ישראל ישראלי"
    phone = "+972500000001"
    email = "israel@example.com"
    notes = "מבקש פגישה בהקדם"

    r = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": date, "time": "09:00",
        "name": name, "phone": phone, "email": email, "notes": notes,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    booking_id = body["booking_id"]
    assert body["cancel_token"] and body["scheduled_at"]

    # Mark the created rows is_test so the cleanup fixture removes them.
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute(
            "UPDATE bookings SET is_test = true WHERE id = $1 AND business_id = $2",
            booking_id, BIZ_A)
        # The booking must link a LEAD.
        row = await conn.fetchrow(
            """SELECT lead_id, client_name, client_phone, client_email, notes
               FROM bookings WHERE id = $1 AND business_id = $2""",
            booking_id, BIZ_A)
        assert row["lead_id"] is not None, "booking did not link a lead"
        await conn.execute(
            "UPDATE leads SET is_test = true WHERE id = $1 AND business_id = $2",
            row["lead_id"], BIZ_A)
        lead = await conn.fetchrow(
            "SELECT id, status FROM leads WHERE id = $1", row["lead_id"])
        assert lead is not None, "linked lead row missing"

        # RAW columns must be ciphertext — NOT the plaintext PII.
        assert name not in (row["client_name"] or "")
        assert phone not in (row["client_phone"] or "")
        assert email not in (row["client_email"] or "")
        assert notes not in (row["notes"] or "")

    # The OWNER reads it back decrypted via the admin list.
    await _login(rds, http, AVI_USER, BIZ_A)
    rows = (await http.get("/api/bookings?include_test=true")).json()["bookings"]
    match = [b for b in rows if b["id"] == booking_id]
    assert match, "owner did not see the booking"
    b = match[0]
    assert b["client_name"] == name
    assert b["client_phone"] == phone
    assert b["client_email"] == email
    assert b["notes"] == notes


# ============================================================================
#  GOAL 5 — GUARDS: 409 double-booking, 404 unknown slug, junk-field rejection
# ============================================================================

@pytest.mark.asyncio
async def test_double_booking_returns_409(http, rds, pool, cleanup):
    """Booking the same free slot twice: the second attempt → 409."""
    date = _real_future_date()
    slug = await _set_settings(pool, BIZ_A, working_hours={
        _wd_key(date): [{"s": "09:00", "e": "17:00"}],
    }, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)

    base = {"service_id": svc, "date": date, "time": "10:00",
            "name": "א", "phone": "+972500000002"}
    r1 = await http.post(f"/api/book/{slug}", json=base)
    assert r1.status_code == 201, r1.text
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute(
            "UPDATE bookings SET is_test=true WHERE id=$1", r1.json()["booking_id"])
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_A)

    r2 = await http.post(f"/api/book/{slug}", json=base)
    assert r2.status_code == 409, r2.text


@pytest.mark.asyncio
async def test_unknown_slug_returns_404(http, cleanup):
    """An unprovisioned slug → 404 on every public route (no tenant leak)."""
    bogus = "does-not-exist-" + secrets.token_urlsafe(6)
    assert (await http.get(f"/api/book/{bogus}/services")).status_code == 404
    assert (await http.get(
        f"/api/book/{bogus}/slots?service_id=x&date=2099-06-10")).status_code == 404
    r = await http.post(f"/api/book/{bogus}", json={
        "service_id": "x", "date": "2099-06-10", "time": "09:00",
        "name": "a", "phone": "+972500000000"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_field_validation_rejects_junk(http, pool, cleanup):
    """Malformed date/time/phone in the public create body → 422 (Pydantic)."""
    slug = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)

    bad_date = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": "10/06/2099", "time": "09:00",
        "name": "a", "phone": "+972500000000"})
    assert bad_date.status_code == 422

    bad_time = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": "2099-06-10", "time": "9am",
        "name": "a", "phone": "+972500000000"})
    assert bad_time.status_code == 422

    empty_name = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": "2099-06-10", "time": "09:00",
        "name": "", "phone": "+972500000000"})
    assert empty_name.status_code == 422


@pytest.mark.asyncio
async def test_off_grid_time_rejected(http, pool, cleanup):
    """A well-formed time that is NOT an offered slot (off the grid) is rejected —
    never silently booked. The service re-derives the offered grid and refuses a
    time that isn't on it: a still-in-the-future off-grid time maps to 409 ("slot
    no longer available"), a past/closed one to 422. Either way: NOT 201, and no
    row is created."""
    slug = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)
    date = _real_future_date()
    # 09:17 is well-formed but never an offered start for a 60-min grid.
    r = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": date, "time": "09:17",
        "name": "a", "phone": "+972500000000"})
    assert r.status_code in (409, 422), r.text
    assert r.status_code != 201, "an off-grid time was silently booked!"
    async with tenant_connection(pool, BIZ_A) as conn:
        cnt = await conn.fetchval(
            "SELECT count(*) FROM bookings WHERE business_id=$1", BIZ_A)
    assert cnt == 0, "an off-grid booking row was created"


# ============================================================================
#  GOAL 6 — CANCEL / RESCHEDULE: via cancel_token AND via owner PATCH
# ============================================================================

@pytest.mark.asyncio
async def test_cancel_via_token_frees_slot(http, pool, cleanup):
    """Public cancel via cancel_token sets status=cancelled and frees the slot."""
    slug = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)
    date = _real_future_date()

    r = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": date, "time": "11:00",
        "name": "a", "phone": "+972500000003"})
    token = r.json()["cancel_token"]
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute(
            "UPDATE bookings SET is_test=true WHERE id=$1", r.json()["booking_id"])
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_A)
        # 11:00 is now taken (real-clock date → use the real now in compute_slots).
        taken = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=date)
        assert "11:00" not in taken

    c = await http.post(f"/api/book/{slug}/cancel/{token}")
    assert c.status_code == 200 and c.json()["status"] == "cancelled"

    async with tenant_connection(pool, BIZ_A) as conn:
        freed = await booking_service.compute_slots(
            conn, BIZ_A, service_id=svc, date_str=date)
    assert "11:00" in freed, "cancelling did not free the slot"


@pytest.mark.asyncio
async def test_reschedule_via_token_moves_time(http, pool, cleanup):
    """Public reschedule via cancel_token moves scheduled_at to the new slot."""
    slug = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)
    date = _real_future_date()

    r = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": date, "time": "09:00",
        "name": "a", "phone": "+972500000004"})
    token = r.json()["cancel_token"]
    bid = r.json()["booking_id"]
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", bid)
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_A)

    rs = await http.post(f"/api/book/{slug}/reschedule/{token}",
                         json={"date": date, "time": "14:00"})
    assert rs.status_code == 200, rs.text
    new_utc = booking_service.local_to_utc(date, "14:00")
    assert rs.json()["scheduled_at"].startswith(new_utc.isoformat()[:16])


@pytest.mark.asyncio
async def test_owner_patch_status_and_reschedule(http, rds, pool, cleanup):
    """Owner PATCH /api/bookings/{id} sets status and reschedules the time."""
    slug = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc = await _make_service(pool, BIZ_A, duration=60)
    date = _real_future_date()
    r = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": date, "time": "09:00",
        "name": "a", "phone": "+972500000005"})
    bid = r.json()["booking_id"]
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", bid)
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_A)

    await _login(rds, http, AVI_USER, BIZ_A)
    # Confirm it.
    p1 = await http.patch(f"/api/bookings/{bid}", json={"status": "confirmed"})
    assert p1.status_code == 200 and p1.json()["status"] == "confirmed"
    # Reschedule it to 15:00.
    p2 = await http.patch(f"/api/bookings/{bid}", json={"date": date, "time": "15:00"})
    assert p2.status_code == 200
    new_utc = booking_service.local_to_utc(date, "15:00")
    assert p2.json()["scheduled_at"].startswith(new_utc.isoformat()[:16])


@pytest.mark.asyncio
async def test_cancel_unknown_token_404(http, pool, cleanup):
    """A cancel_token that isn't this page's → 404 (never touches a row)."""
    slug = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    r = await http.post(f"/api/book/{slug}/cancel/nope-{secrets.token_urlsafe(6)}")
    assert r.status_code == 404


# ============================================================================
#  GOAL 7 — TENANT ISOLATION (incl. C4) + admin gate
# ============================================================================

@pytest.mark.asyncio
async def test_admin_routes_require_session(http):
    """All admin booking routes are 401 without a session (deny-by-default)."""
    assert (await http.get("/api/booking/settings")).status_code == 401
    assert (await http.get("/api/services")).status_code == 401
    assert (await http.get("/api/bookings")).status_code == 401
    assert (await http.patch("/api/bookings/x", json={"status": "confirmed"})).status_code == 401
    assert (await http.get("/api/google/status")).status_code == 401


@pytest.mark.asyncio
async def test_isolation_a_cannot_list_b_bookings(http, rds, pool, cleanup):
    """A's GET /api/bookings never includes B's booking (C4 list isolation)."""
    slug_b = await _set_settings(pool, BIZ_B, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc_b = await _make_service(pool, BIZ_B, duration=60)
    date = _real_future_date()
    rb = await http.post(f"/api/book/{slug_b}", json={
        "service_id": svc_b, "date": date, "time": "09:00",
        "name": "bella-customer", "phone": "+972500000006"})
    b_booking = rb.json()["booking_id"]
    async with tenant_connection(pool, BIZ_B) as conn:
        await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", b_booking)
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_B)

    await _login(rds, http, AVI_USER, BIZ_A)
    rows = (await http.get("/api/bookings?include_test=true")).json()["bookings"]
    assert all(b["id"] != b_booking for b in rows), "A saw B's booking!"


@pytest.mark.asyncio
async def test_isolation_a_cannot_patch_b_booking(http, rds, pool, cleanup):
    """A PATCH on B's booking id → 404 (RLS hid it); B's row untouched (C4)."""
    slug_b = await _set_settings(pool, BIZ_B, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc_b = await _make_service(pool, BIZ_B, duration=60)
    date = _real_future_date()
    rb = await http.post(f"/api/book/{slug_b}", json={
        "service_id": svc_b, "date": date, "time": "09:00",
        "name": "bella-customer", "phone": "+972500000007"})
    b_booking = rb.json()["booking_id"]
    async with tenant_connection(pool, BIZ_B) as conn:
        await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", b_booking)
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_B)

    await _login(rds, http, AVI_USER, BIZ_A)
    r = await http.patch(f"/api/bookings/{b_booking}", json={"status": "cancelled"})
    assert r.status_code == 404, r.text

    async with tenant_connection(pool, BIZ_B) as conn:
        st = await conn.fetchval(
            "SELECT status FROM bookings WHERE id=$1 AND business_id=$2",
            b_booking, BIZ_B)
    assert st == "pending", "A's PATCH mutated B's booking!"


@pytest.mark.asyncio
async def test_isolation_a_cannot_patch_b_service(http, rds, pool, cleanup):
    """A PATCH/DELETE on B's service id → 404; the service is untouched (C4)."""
    svc_b = await _make_service(pool, BIZ_B, name="B-service", duration=45)
    await _login(rds, http, AVI_USER, BIZ_A)

    p = await http.patch(f"/api/services/{svc_b}", json={"name": "hacked"})
    assert p.status_code == 404
    d = await http.delete(f"/api/services/{svc_b}")
    assert d.status_code == 404

    async with tenant_connection(pool, BIZ_B) as conn:
        nm = await conn.fetchval(
            "SELECT name FROM services WHERE id=$1 AND business_id=$2", svc_b, BIZ_B)
    assert nm == "B-service", "A mutated/deleted B's service!"


@pytest.mark.asyncio
async def test_isolation_settings_scoped_per_tenant(http, rds, pool, cleanup):
    """Each tenant's GET /api/booking/settings returns its OWN slug, never the
    other's; A's slug != B's slug and neither leaks across."""
    slug_b = await _set_settings(pool, BIZ_B, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)

    await _login(rds, http, AVI_USER, BIZ_A)
    a_settings = (await http.get("/api/booking/settings")).json()
    assert a_settings["slug"] != slug_b, "A's settings exposed B's slug"

    await _login(rds, http, BELLA_USER, BIZ_B)
    b_settings = (await http.get("/api/booking/settings")).json()
    assert b_settings["slug"] == slug_b


@pytest.mark.asyncio
async def test_public_slug_only_exposes_its_own_services(http, pool, cleanup):
    """The public services for A's slug never include B's services (slug→tenant)."""
    slug_a = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    await _make_service(pool, BIZ_A, name="A-only-service", duration=30)
    await _make_service(pool, BIZ_B, name="B-only-service", duration=30)

    rows = (await http.get(f"/api/book/{slug_a}/services")).json()["services"]
    names = {s["name"] for s in rows}
    assert "A-only-service" in names
    assert "B-only-service" not in names, "A's public page exposed B's service!"


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
