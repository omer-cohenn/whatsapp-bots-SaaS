"""M11.1 strict — SERVICES round-trip + SETTINGS welcome + AVAILABILITY.

Split out of the original test_m11_1.py (shared fixtures/helpers live in
_m11_1_helpers.py). Per decision 0012.

  G2 SERVICES ROUND-TRIP — POST/PATCH carry description + price; they persist and
     come back via GET /api/services AND the public services route; an omitted
     price stays null; an explicit null clears it.
  G3 SETTINGS — PUT welcome_message persists + GET returns it; the public services
     response includes welcome_message (None when unset).
  G4 AVAILABILITY — exactly the open days; an over-booked/closed day is OUT; range
     > 62 days → 422; inverted range → 422; unknown slug → 404.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

import pytest

from _m11_1_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    AVI_USER,
    BIZ_A,
    JLM,
    _ALL_DAYS_9_17,
    _login,
    _logout,
    _make_service_http,
    _real_future_date,
    _seed_settings,
    _wd_key,
    cleanup,
    http,
    lifespan_app,
    pool,
    rds,
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
