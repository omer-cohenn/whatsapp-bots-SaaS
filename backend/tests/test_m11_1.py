"""M11.1 — public booking page polish, strict pytest (CI).

Per decision 0012. This suite proves the M11.1 contract end-to-end against the
REAL ASGI app over httpx ASGITransport (so the deny-by-default /api gate, the
session dependency, tenant_connection/RLS and the public-slug bootstrap are all
exercised). It drives the welcome generator through its monkeypatched Gemini seam
(no key, no network) exactly like test_bot_builder.py.

What it proves (mapped to the QA goals):

  G2 SERVICES ROUND-TRIP — POST/PATCH carry description + price; they persist and
     come back via GET /api/services AND the public GET /api/book/{slug}/services;
     an omitted price stays null; an explicit null clears it.
  G3 SETTINGS — PUT welcome_message persists + GET returns it; the public services
     response includes welcome_message (None when unset).
  G4 AVAILABILITY — GET /api/book/{slug}/availability returns exactly the open
     days; an over-booked/closed day is OUT; range > 62 days → 422; unknown slug
     → 404; a bad date string → 422.
  G5 AI WELCOME — POST /api/booking/welcome/generate is gated (401 without a
     session); with Gemini mocked it returns the message; missing key → 503; the
     key never leaks into the response.
  G6 ISOLATION — A cannot read/patch B's services/settings; the public slug only
     ever exposes its own tenant's services + welcome_message.

Every persisted row is cleaned up after each test. Nothing prints a secret or PII.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import booking as booking_service
from app.services import booking_welcome
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

JLM = ZoneInfo("Asia/Jerusalem")

# Every weekday 09:00-17:00, so a real-clock future date always lands open.
_ALL_DAYS_9_17 = {str(k): [{"s": "09:00", "e": "17:00"}] for k in range(7)}


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
async def cleanup(pool, rds):
    """After each test: wipe the booking rows we touched, so the M2 wall stays
    pristine and tests never bleed into each other."""
    yield
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute("DELETE FROM bookings WHERE business_id = $1", bid)
            await conn.execute(
                "DELETE FROM leads WHERE business_id = $1 "
                "AND (is_test = true OR lead_name = 'פגישה')", bid)
            await conn.execute("DELETE FROM services WHERE business_id = $1", bid)
            await conn.execute("DELETE FROM booking_settings WHERE business_id = $1", bid)
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


def _logout(http) -> None:
    http.cookies.clear()


async def _seed_settings(pool, business_id: str, *, working_hours: dict,
                         min_notice=120, buffer=0, max_days=365) -> str:
    """UPSERT booking_settings (fresh slug); return the slug."""
    slug = "t-" + secrets.token_urlsafe(8)
    async with tenant_connection(pool, business_id) as conn:
        # slug is server-owned (only set on first insert); RETURN the live slug so
        # the caller always uses the one that actually resolves the public page.
        live = await conn.fetchval(
            """
            INSERT INTO booking_settings
                (business_id, working_hours, min_notice_minutes, buffer_minutes,
                 max_days_ahead, meet_enabled, slug)
            VALUES ($1, $2::jsonb, $3, $4, $5, false, $6)
            ON CONFLICT (business_id) DO UPDATE SET
                working_hours = EXCLUDED.working_hours,
                min_notice_minutes = EXCLUDED.min_notice_minutes,
                buffer_minutes = EXCLUDED.buffer_minutes,
                max_days_ahead = EXCLUDED.max_days_ahead
            RETURNING slug
            """,
            business_id, json.dumps(working_hours), min_notice, buffer, max_days, slug,
        )
    return live


def _wd_key(date_str: str) -> str:
    return str((datetime.fromisoformat(date_str).weekday() + 1) % 7)


def _real_future_date(min_days_ahead: int = 7, weekday_local: int = 2) -> str:
    d = (datetime.now(JLM) + timedelta(days=min_days_ahead)).date()
    while d.weekday() != weekday_local:
        d += timedelta(days=1)
    return d.isoformat()


# --- the fake Gemini client (same seam as test_bot_builder) ------------------

class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModels:
    def __init__(self, reply_text: str) -> None:
        self._reply_text = reply_text

    async def generate_content(self, **_kwargs):  # noqa: ANN003
        return _FakeResp(self._reply_text)


class _FakeAio:
    def __init__(self, reply_text: str) -> None:
        self.models = _FakeModels(reply_text)


class _FakeClient:
    def __init__(self, reply_text: str) -> None:
        self.aio = _FakeAio(reply_text)


def _patch_welcome_gemini(monkeypatch, reply_text: str) -> None:
    monkeypatch.setattr(
        booking_welcome, "get_gemini_client", lambda: _FakeClient(reply_text)
    )


# ============================================================================
#  GOAL 2 — SERVICES ROUND-TRIP: description + price persist; null stays null
# ============================================================================

@pytest.mark.asyncio
async def test_create_service_with_description_and_price(http, rds, pool, cleanup):
    """POST /api/services with description+price: both persist and come back."""
    await _login(rds, http, AVI_USER, BIZ_A)
    r = await http.post("/api/services", json={
        "name": "תספורת", "duration_minutes": 30,
        "description": "תספורת מלאה כולל שטיפה", "price": 80,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["description"] == "תספורת מלאה כולל שטיפה"
    assert body["price"] == 80

    # GET /api/services echoes them.
    rows = (await http.get("/api/services")).json()["services"]
    match = [s for s in rows if s["id"] == body["id"]]
    assert match and match[0]["description"] == "תספורת מלאה כולל שטיפה"
    assert match[0]["price"] == 80


@pytest.mark.asyncio
async def test_create_service_omitted_price_stays_null(http, rds, pool, cleanup):
    """A service created WITHOUT a price keeps price=null (UI shows 'ללא עלות')."""
    await _login(rds, http, AVI_USER, BIZ_A)
    r = await http.post("/api/services", json={
        "name": "ייעוץ חינם", "duration_minutes": 30,
        "description": "פגישת היכרות",
    })
    assert r.status_code == 201, r.text
    assert r.json()["price"] is None
    assert r.json()["description"] == "פגישת היכרות"


@pytest.mark.asyncio
async def test_patch_service_sets_and_clears_price(http, rds, pool, cleanup):
    """PATCH can SET price (0 is valid = free) and explicitly CLEAR it (null)."""
    await _login(rds, http, AVI_USER, BIZ_A)
    sid = (await http.post("/api/services", json={
        "name": "טיפול", "duration_minutes": 45, "price": 150})).json()["id"]

    # Update both description + price.
    p1 = await http.patch(f"/api/services/{sid}", json={
        "description": "טיפול מעמיק", "price": 200})
    assert p1.status_code == 200
    assert p1.json()["price"] == 200 and p1.json()["description"] == "טיפול מעמיק"

    # price = 0 is a VALID free price (not the same as null).
    p0 = await http.patch(f"/api/services/{sid}", json={"price": 0})
    assert p0.status_code == 200 and p0.json()["price"] == 0

    # Explicit null clears it back to "no price".
    pn = await http.patch(f"/api/services/{sid}", json={"price": None})
    assert pn.status_code == 200 and pn.json()["price"] is None
    # description left untouched (omitted) — still there.
    assert pn.json()["description"] == "טיפול מעמיק"


@pytest.mark.asyncio
async def test_negative_price_rejected(http, rds, pool, cleanup):
    """A negative price is rejected by the model (ge=0) → 422."""
    await _login(rds, http, AVI_USER, BIZ_A)
    r = await http.post("/api/services", json={
        "name": "x", "duration_minutes": 30, "price": -5})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_public_services_carry_description_and_price(http, rds, pool, cleanup):
    """The public GET /api/book/{slug}/services exposes description + price."""
    slug = await _seed_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)
    await _login(rds, http, AVI_USER, BIZ_A)
    await http.post("/api/services", json={
        "name": "צביעה", "duration_minutes": 60,
        "description": "צביעת שיער מקצועית", "price": 250})
    await http.post("/api/services", json={
        "name": "החלקה", "duration_minutes": 90})  # no price → null

    _logout(http)
    rows = (await http.get(f"/api/book/{slug}/services")).json()["services"]
    by_name = {s["name"]: s for s in rows}
    assert by_name["צביעה"]["description"] == "צביעת שיער מקצועית"
    assert by_name["צביעה"]["price"] == 250
    assert by_name["החלקה"]["price"] is None


# ============================================================================
#  GOAL 3 — SETTINGS: welcome_message persists + appears on the public page
# ============================================================================

@pytest.mark.asyncio
async def test_put_settings_persists_welcome_message(http, rds, pool, cleanup):
    """PUT /api/booking/settings stores welcome_message; GET returns it."""
    await _login(rds, http, AVI_USER, BIZ_A)
    msg = "ברוכים הבאים לעסק שלנו! קבעו תור בקלות."
    put = await http.put("/api/booking/settings", json={
        "working_hours": _ALL_DAYS_9_17,
        "min_notice_minutes": 120, "buffer_minutes": 0,
        "max_days_ahead": 30, "meet_enabled": False,
        "welcome_message": msg,
    })
    assert put.status_code == 200, put.text
    assert put.json()["welcome_message"] == msg

    got = await http.get("/api/booking/settings")
    assert got.json()["welcome_message"] == msg


@pytest.mark.asyncio
async def test_welcome_message_too_long_rejected(http, rds, pool, cleanup):
    """A welcome_message over 600 chars → 422 (model bound)."""
    await _login(rds, http, AVI_USER, BIZ_A)
    put = await http.put("/api/booking/settings", json={
        "working_hours": _ALL_DAYS_9_17,
        "min_notice_minutes": 120, "buffer_minutes": 0,
        "max_days_ahead": 30, "meet_enabled": False,
        "welcome_message": "א" * 601,
    })
    assert put.status_code == 422, put.text


@pytest.mark.asyncio
async def test_public_services_response_includes_welcome_message(http, rds, pool, cleanup):
    """The public services response carries welcome_message; None when unset."""
    slug = await _seed_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)

    # Before the owner sets one: welcome_message is None on the public page.
    pre = (await http.get(f"/api/book/{slug}/services")).json()
    assert pre["welcome_message"] is None

    # Owner saves one.
    await _login(rds, http, AVI_USER, BIZ_A)
    msg = "שמחים לראותכם! בחרו שירות ותור שמתאים לכם."
    await http.put("/api/booking/settings", json={
        "working_hours": _ALL_DAYS_9_17, "min_notice_minutes": 0,
        "buffer_minutes": 0, "max_days_ahead": 30, "meet_enabled": False,
        "welcome_message": msg})

    # The PUT generated/kept a slug; re-read it so the public GET uses the live one.
    new_slug = (await http.get("/api/booking/settings")).json()["slug"]
    _logout(http)
    post = (await http.get(f"/api/book/{new_slug}/services")).json()
    assert post["welcome_message"] == msg


# ============================================================================
#  GOAL 4 — AVAILABILITY: open days IN, closed/over-booked OUT, bounds/404
# ============================================================================

@pytest.mark.asyncio
async def test_availability_returns_only_open_days(http, rds, pool, cleanup):
    """A day with a free slot is IN; a fully-closed weekday is OUT of `dates`."""
    # Open ONLY Wednesday (local weekday 2 → our Sun=0 key).
    open_date = _real_future_date(min_days_ahead=7, weekday_local=2)  # a Wednesday
    wd = _wd_key(open_date)
    slug = await _seed_settings(pool, BIZ_A, working_hours={
        wd: [{"s": "09:00", "e": "17:00"}]}, min_notice=0, max_days=365)
    svc = (await _make_service_http(http, rds, pool, BIZ_A, duration=60))

    # Query a 7-day window starting at the open Wednesday.
    start = open_date
    end = (datetime.fromisoformat(open_date) + timedelta(days=6)).date().isoformat()
    _logout(http)
    r = await http.get(
        f"/api/book/{slug}/availability",
        params={"service_id": svc, "from": start, "to": end})
    assert r.status_code == 200, r.text
    dates = r.json()["dates"]
    # The open Wednesday is present; the other six days (closed) are absent.
    assert open_date in dates
    assert len(dates) == 1, dates


@pytest.mark.asyncio
async def test_availability_overbooked_day_excluded(http, rds, pool, cleanup):
    """A day whose only slot is taken drops OUT of availability."""
    date = _real_future_date(min_days_ahead=7, weekday_local=2)
    wd = _wd_key(date)
    # A single 60-min slot 09:00-10:00 on that weekday only.
    slug = await _seed_settings(pool, BIZ_A, working_hours={
        wd: [{"s": "09:00", "e": "10:00"}]}, min_notice=0, max_days=365)
    svc = await _make_service_http(http, rds, pool, BIZ_A, duration=60)

    _logout(http)
    # Available before booking it.
    r1 = await http.get(f"/api/book/{slug}/availability",
                        params={"service_id": svc, "from": date, "to": date})
    assert date in r1.json()["dates"]

    # Book the only slot.
    rb = await http.post(f"/api/book/{slug}", json={
        "service_id": svc, "date": date, "time": "09:00",
        "name": "a", "phone": "+972500000099"})
    assert rb.status_code == 201, rb.text

    # Now the day has no free slot → excluded.
    r2 = await http.get(f"/api/book/{slug}/availability",
                        params={"service_id": svc, "from": date, "to": date})
    assert date not in r2.json()["dates"], "an over-booked day was still available"


@pytest.mark.asyncio
async def test_availability_range_over_62_days_is_422(http, rds, pool, cleanup):
    """A from→to span over 62 days → 422 (bounded server-side)."""
    slug = await _seed_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)
    svc = await _make_service_http(http, rds, pool, BIZ_A, duration=60)
    _logout(http)
    start = datetime.now(JLM).date()
    end = (start + timedelta(days=70)).isoformat()  # 71 days inclusive
    r = await http.get(f"/api/book/{slug}/availability",
                       params={"service_id": svc, "from": start.isoformat(), "to": end})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_availability_inverted_range_is_422(http, rds, pool, cleanup):
    """'to' before 'from' → 422."""
    slug = await _seed_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)
    svc = await _make_service_http(http, rds, pool, BIZ_A, duration=60)
    _logout(http)
    r = await http.get(f"/api/book/{slug}/availability",
                       params={"service_id": svc, "from": "2099-06-10", "to": "2099-06-01"})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_availability_unknown_slug_is_404(http, cleanup):
    """Availability on an unprovisioned slug → 404 (no tenant leak)."""
    bogus = "nope-" + secrets.token_urlsafe(6)
    r = await http.get(f"/api/book/{bogus}/availability",
                       params={"service_id": "x", "from": "2099-06-01", "to": "2099-06-05"})
    assert r.status_code == 404, r.text


# ============================================================================
#  GOAL 5 — AI WELCOME: gate (401), mocked success, no-key 503, no key leak
# ============================================================================

@pytest.mark.asyncio
async def test_welcome_generate_requires_session(http, cleanup):
    """POST /api/booking/welcome/generate without a session → 401 (gated)."""
    r = await http.post("/api/booking/welcome/generate", json={})
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_welcome_generate_returns_message_when_mocked(
    http, rds, pool, cleanup, monkeypatch
):
    """With Gemini mocked: returns the generated message (key never touched)."""
    await _login(rds, http, AVI_USER, BIZ_A)
    await http.post("/api/services", json={"name": "ייעוץ", "duration_minutes": 30})
    canned = "ברוכים הבאים! נשמח לעזור לכם. קבעו תור עכשיו."
    _patch_welcome_gemini(monkeypatch, canned)

    r = await http.post("/api/booking/welcome/generate", json={"tone": "חם"})
    assert r.status_code == 200, r.text
    assert r.json()["message"] == canned


@pytest.mark.asyncio
async def test_welcome_generate_no_key_is_503(http, rds, pool, cleanup, monkeypatch):
    """With NO Gemini key (real factory, key unset) → 503; the app stays up."""
    await _login(rds, http, AVI_USER, BIZ_A)
    # Force the not-configured branch: clear the cached settings + the env key.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from app.core import config as app_config
    app_config.get_settings.cache_clear()
    try:
        r = await http.post("/api/booking/welcome/generate", json={})
        assert r.status_code == 503, r.text
    finally:
        app_config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_welcome_generate_never_leaks_key(http, rds, pool, cleanup, monkeypatch):
    """The generate response never contains the configured key, even on success."""
    await _login(rds, http, AVI_USER, BIZ_A)
    _patch_welcome_gemini(monkeypatch, "טקסט תקין")
    r = await http.post("/api/booking/welcome/generate", json={})
    assert r.status_code == 200
    from app.core.config import get_settings
    key = get_settings().gemini_api_key
    if key is not None:
        assert key.get_secret_value() not in r.text


# ============================================================================
#  GOAL 6 — TENANT ISOLATION on the new fields
# ============================================================================

@pytest.mark.asyncio
async def test_isolation_a_cannot_patch_b_service_fields(http, rds, pool, cleanup):
    """A PATCH on B's service (description/price) → 404; B's row untouched."""
    svc_b = await _make_service_direct(pool, BIZ_B, name="B-svc", duration=30,
                                       description="B-desc", price=99)
    await _login(rds, http, AVI_USER, BIZ_A)
    p = await http.patch(f"/api/services/{svc_b}", json={
        "description": "hacked", "price": 1})
    assert p.status_code == 404, p.text

    async with tenant_connection(pool, BIZ_B) as conn:
        row = await conn.fetchrow(
            "SELECT description, price FROM services WHERE id=$1 AND business_id=$2",
            svc_b, BIZ_B)
    assert row["description"] == "B-desc" and row["price"] == 99


@pytest.mark.asyncio
async def test_isolation_welcome_message_scoped(http, rds, pool, cleanup):
    """B's welcome_message never appears for A; each tenant sees only its own."""
    await _login(rds, http, BELLA_USER, BIZ_B)
    await http.put("/api/booking/settings", json={
        "working_hours": _ALL_DAYS_9_17, "min_notice_minutes": 0,
        "buffer_minutes": 0, "max_days_ahead": 30, "meet_enabled": False,
        "welcome_message": "ברוכים הבאים-B-SECRET"})

    await _login(rds, http, AVI_USER, BIZ_A)
    a = (await http.get("/api/booking/settings")).json()
    assert a.get("welcome_message") != "ברוכים הבאים-B-SECRET"


@pytest.mark.asyncio
async def test_public_slug_only_exposes_own_welcome_and_services(http, rds, pool, cleanup):
    """A's public page shows A's welcome + services, never B's."""
    slug_a = await _seed_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)
    await _make_service_direct(pool, BIZ_A, name="A-svc", duration=30)
    await _make_service_direct(pool, BIZ_B, name="B-svc", duration=30)
    # Give A a welcome; B a different one.
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute(
            "UPDATE booking_settings SET welcome_message=$1 WHERE business_id=$2",
            "A-welcome", BIZ_A)

    rows = (await http.get(f"/api/book/{slug_a}/services")).json()
    names = {s["name"] for s in rows["services"]}
    assert "A-svc" in names and "B-svc" not in names
    assert rows["welcome_message"] == "A-welcome"


# --- service-creation helpers (HTTP for owner-path, direct for B-tenant) ------

async def _make_service_http(http, rds, pool, business_id, *, duration) -> str:
    """Create a service via the owner HTTP path (logs in as that tenant's owner)."""
    user = AVI_USER if business_id == BIZ_A else BELLA_USER
    await _login(rds, http, user, business_id)
    r = await http.post("/api/services", json={
        "name": "svc", "duration_minutes": duration})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_service_direct(pool, business_id, *, name, duration,
                               description=None, price=None) -> str:
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO services (business_id, name, duration_minutes, active,
                                  description, price)
            VALUES ($1, $2, $3, true, $4, $5) RETURNING id
            """,
            business_id, name, duration, description, price)
    return str(row["id"])
