"""M11.2 — service card image (image_url) round-trip, strict pytest (CI).

Per the M11.2 contract. Proves the new `services.image_url` field end-to-end
against the REAL ASGI app over httpx ASGITransport, so the deny-by-default /api
gate, the session dependency, tenant_connection/RLS and the public-slug bootstrap
are all exercised exactly like a real request.

What it proves (mapped to the QA goals):

  G2 ROUND-TRIP — POST sets image_url (an http(s) URL AND a long data: URL up to
     ~1 MB); it persists + comes back via GET /api/services AND the public
     GET /api/book/{slug}/services. PATCH sets a new value, an EXPLICIT null
     CLEARS it, an OMITTED field LEAVES IT UNCHANGED. A too-long value (over the
     2 MB model bound) → 422.
  G3 ISOLATION — A cannot PATCH B's service image (foreign id → 404, B's row
     untouched); the public slug only ever exposes its own tenant's images.

Every persisted row is cleaned up after each test. Nothing prints a secret/PII;
image_url here is owner-authored public marketing content (not PII/ciphertext).
"""

from __future__ import annotations

import json
import os
import secrets
import time

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.models.booking import MAX_SERVICE_IMAGE_CHARS
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

# A small public http(s) URL is acceptable in the same field.
HTTP_IMG = "https://cdn.example.com/avatar/haircut.png"

# A realistic client-resized data: URL. ~1 MB of base64 payload to prove the
# field carries a big resized image without truncation/422 (bound is 2 MB).
_DATA_PREFIX = "data:image/jpeg;base64,"
ONE_MB_DATA_URL = _DATA_PREFIX + ("A" * 1_000_000)

# Every weekday 09:00-17:00 so the public page resolves cleanly.
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
    """After each test: wipe the booking/service rows we touched, so the M2 wall
    stays pristine and tests never bleed into each other."""
    yield
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute("DELETE FROM bookings WHERE business_id = $1", bid)
            await conn.execute(
                "DELETE FROM leads WHERE business_id = $1 "
                "AND (is_test = true OR lead_name = 'פגישה')", bid)
            await conn.execute("DELETE FROM services WHERE business_id = $1", bid)
            await conn.execute("DELETE FROM booking_settings WHERE business_id = $1", bid)


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


async def _seed_settings(pool, business_id: str, *, working_hours: dict) -> str:
    """UPSERT booking_settings (fresh slug); return the LIVE slug (server-owned)."""
    slug = "t-" + secrets.token_urlsafe(8)
    async with tenant_connection(pool, business_id) as conn:
        live = await conn.fetchval(
            """
            INSERT INTO booking_settings
                (business_id, working_hours, min_notice_minutes, buffer_minutes,
                 max_days_ahead, meet_enabled, slug)
            VALUES ($1, $2::jsonb, 120, 0, 365, false, $3)
            ON CONFLICT (business_id) DO UPDATE SET
                working_hours = EXCLUDED.working_hours
            RETURNING slug
            """,
            business_id, json.dumps(working_hours), slug,
        )
    return live


async def _make_service_direct(pool, business_id, *, name, duration,
                               image_url=None) -> str:
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO services (business_id, name, duration_minutes, active,
                                  image_url)
            VALUES ($1, $2, $3, true, $4) RETURNING id
            """,
            business_id, name, duration, image_url)
    return str(row["id"])


# ============================================================================
#  GOAL 2 — image_url ROUND-TRIP: create / get / public read
# ============================================================================

@pytest.mark.asyncio
async def test_create_service_with_http_image_url(http, rds, pool, cleanup):
    """POST /api/services with an http(s) image_url: it persists and comes back."""
    await _login(rds, http, AVI_USER, BIZ_A)
    r = await http.post("/api/services", json={
        "name": "תספורת", "duration_minutes": 30, "image_url": HTTP_IMG})
    assert r.status_code == 201, r.text
    assert r.json()["image_url"] == HTTP_IMG

    # GET /api/services echoes it.
    rows = (await http.get("/api/services")).json()["services"]
    match = [s for s in rows if s["id"] == r.json()["id"]]
    assert match and match[0]["image_url"] == HTTP_IMG


@pytest.mark.asyncio
async def test_create_service_with_large_data_url(http, rds, pool, cleanup):
    """A ~1 MB resized data: URL is accepted and round-trips byte-for-byte."""
    await _login(rds, http, AVI_USER, BIZ_A)
    r = await http.post("/api/services", json={
        "name": "צביעה", "duration_minutes": 60, "image_url": ONE_MB_DATA_URL})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["image_url"] == ONE_MB_DATA_URL
    assert len(r.json()["image_url"]) > 1_000_000

    # And it survives a fresh read (the full payload, not truncated).
    rows = (await http.get("/api/services")).json()["services"]
    got = [s for s in rows if s["id"] == sid][0]["image_url"]
    assert got == ONE_MB_DATA_URL


@pytest.mark.asyncio
async def test_create_service_omitted_image_url_is_null(http, rds, pool, cleanup):
    """A service created WITHOUT image_url keeps image_url=null (placeholder)."""
    await _login(rds, http, AVI_USER, BIZ_A)
    r = await http.post("/api/services", json={
        "name": "ייעוץ", "duration_minutes": 30})
    assert r.status_code == 201, r.text
    assert r.json()["image_url"] is None


@pytest.mark.asyncio
async def test_patch_image_url_set_clear_and_leave_untouched(http, rds, pool, cleanup):
    """PATCH can SET image_url, EXPLICIT null CLEARS it, OMIT leaves it unchanged."""
    await _login(rds, http, AVI_USER, BIZ_A)
    sid = (await http.post("/api/services", json={
        "name": "טיפול", "duration_minutes": 45})).json()["id"]
    assert (await http.get("/api/services")).json()  # warm

    # SET it.
    p1 = await http.patch(f"/api/services/{sid}", json={"image_url": HTTP_IMG})
    assert p1.status_code == 200 and p1.json()["image_url"] == HTTP_IMG

    # OMIT image_url (change something else) → image_url LEFT UNCHANGED.
    p2 = await http.patch(f"/api/services/{sid}", json={"name": "טיפול מעודכן"})
    assert p2.status_code == 200
    assert p2.json()["name"] == "טיפול מעודכן"
    assert p2.json()["image_url"] == HTTP_IMG, "omitted image_url must be untouched"

    # EXPLICIT null CLEARS it back to placeholder.
    p3 = await http.patch(f"/api/services/{sid}", json={"image_url": None})
    assert p3.status_code == 200 and p3.json()["image_url"] is None
    # name stays (it was omitted this time).
    assert p3.json()["name"] == "טיפול מעודכן"


@pytest.mark.asyncio
async def test_patch_replace_data_url_with_http(http, rds, pool, cleanup):
    """PATCH can swap a big data: URL for a plain http URL (both valid in the field)."""
    await _login(rds, http, AVI_USER, BIZ_A)
    sid = (await http.post("/api/services", json={
        "name": "x", "duration_minutes": 30, "image_url": ONE_MB_DATA_URL})).json()["id"]
    p = await http.patch(f"/api/services/{sid}", json={"image_url": HTTP_IMG})
    assert p.status_code == 200 and p.json()["image_url"] == HTTP_IMG


@pytest.mark.asyncio
async def test_image_url_over_bound_is_422(http, rds, pool, cleanup):
    """An image_url longer than the 2 MB model bound → 422 (not a DB error)."""
    await _login(rds, http, AVI_USER, BIZ_A)
    too_big = _DATA_PREFIX + ("A" * (MAX_SERVICE_IMAGE_CHARS + 10))
    r = await http.post("/api/services", json={
        "name": "x", "duration_minutes": 30, "image_url": too_big})
    assert r.status_code == 422, f"expected 422, got {r.status_code}"


@pytest.mark.asyncio
async def test_public_services_carry_image_url(http, rds, pool, cleanup):
    """The public GET /api/book/{slug}/services exposes image_url (and null)."""
    slug = await _seed_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)
    await _login(rds, http, AVI_USER, BIZ_A)
    await http.post("/api/services", json={
        "name": "עם-תמונה", "duration_minutes": 30, "image_url": HTTP_IMG})
    await http.post("/api/services", json={
        "name": "בלי-תמונה", "duration_minutes": 30})  # no image → null

    _logout(http)
    rows = (await http.get(f"/api/book/{slug}/services")).json()["services"]
    by_name = {s["name"]: s for s in rows}
    assert by_name["עם-תמונה"]["image_url"] == HTTP_IMG
    assert by_name["בלי-תמונה"]["image_url"] is None


@pytest.mark.asyncio
async def test_public_services_carry_large_data_url(http, rds, pool, cleanup):
    """A resized data: URL also flows out intact on the public page."""
    slug = await _seed_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)
    await _login(rds, http, AVI_USER, BIZ_A)
    await http.post("/api/services", json={
        "name": "תמונה-גדולה", "duration_minutes": 30, "image_url": ONE_MB_DATA_URL})
    _logout(http)
    rows = (await http.get(f"/api/book/{slug}/services")).json()["services"]
    got = {s["name"]: s for s in rows}["תמונה-גדולה"]["image_url"]
    assert got == ONE_MB_DATA_URL


# ============================================================================
#  GOAL 3 — TENANT ISOLATION on image_url
# ============================================================================

@pytest.mark.asyncio
async def test_isolation_a_cannot_patch_b_service_image(http, rds, pool, cleanup):
    """A PATCH on B's service image → 404; B's image_url is untouched."""
    svc_b = await _make_service_direct(pool, BIZ_B, name="B-svc", duration=30,
                                       image_url=HTTP_IMG)
    await _login(rds, http, AVI_USER, BIZ_A)
    p = await http.patch(f"/api/services/{svc_b}", json={
        "image_url": "https://attacker.example/evil.png"})
    assert p.status_code == 404, p.text

    async with tenant_connection(pool, BIZ_B) as conn:
        row = await conn.fetchrow(
            "SELECT image_url FROM services WHERE id=$1 AND business_id=$2",
            svc_b, BIZ_B)
    assert row["image_url"] == HTTP_IMG, "B's image must be unchanged"


@pytest.mark.asyncio
async def test_isolation_foreign_service_invisible_in_list(http, rds, pool, cleanup):
    """B's service (a foreign id) never appears in A's GET /api/services list.

    There's no GET /api/services/{id} route (list/POST/PATCH/DELETE only), so the
    read-side isolation check is that A's list never carries B's service or image.
    A PATCH on that foreign id → 404 is covered separately.
    """
    svc_b = await _make_service_direct(pool, BIZ_B, name="B-svc", duration=30,
                                       image_url=HTTP_IMG)
    await _login(rds, http, AVI_USER, BIZ_A)
    rows = (await http.get("/api/services")).json()["services"]
    ids = {s["id"] for s in rows}
    assert svc_b not in ids, "A must not see B's service id"


@pytest.mark.asyncio
async def test_public_slug_only_exposes_own_images(http, rds, pool, cleanup):
    """A's public page shows A's image, never B's service/image."""
    slug_a = await _seed_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)
    await _make_service_direct(pool, BIZ_A, name="A-svc", duration=30,
                               image_url=HTTP_IMG)
    await _make_service_direct(pool, BIZ_B, name="B-svc", duration=30,
                               image_url="https://b.example/b.png")

    rows = (await http.get(f"/api/book/{slug_a}/services")).json()["services"]
    names = {s["name"] for s in rows}
    assert "A-svc" in names and "B-svc" not in names
    imgs = {s["image_url"] for s in rows}
    assert "https://b.example/b.png" not in imgs
