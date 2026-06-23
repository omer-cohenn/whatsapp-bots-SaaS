"""M13 back-office analytics + CRM — a LIGHT smoke test (builder self-check).

This is NOT the full suite (the QA agent owns that). It proves, against the
in-process ASGI app + the real DB/Redis the container is wired to:

  (a) non-admin → 403 on every new route (the gate holds);
  (b) GET /overview returns avg_ltv AND stamps a platform_snapshots row;
  (c) each analytics endpoint returns sane JSON of the contracted shape;
  (d) PATCH .../crm moves a business' stage + writes admin_audit;
      bad stage → 422, unknown business → 404;
  (e) POST a note → 201 + GET notes returns it;
  (f) the ai_call bump increments usage_daily(metric='ai_call') for a business.

It cleans up after itself (CRM/audit/usage rows it wrote) via the superuser pool.
Run inside the backend container:  python -m pytest tests/m13_smoke.py -q
"""

from __future__ import annotations

import json
import os
import secrets
import time

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.db.session import tenant_connection
from app.services import usage as usage_service
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (seed, published)
UNKNOWN_BIZ = "00000000-0000-0000-0000-0000000000ff"  # matches no business

ADMIN_EMAIL = "oyc3333@gmail.com"
ADMIN_USER_ID_FALLBACK = "google-sub-m13-admin"
AVI_USER = "google-sub-avi"
NONADMIN_EMAIL = "avi@example.com"

NEW_GET_ROUTES = [
    "/api/admin/analytics/leads-by-type",
    "/api/admin/analytics/messages",
    "/api/admin/analytics/ai-ops",
    "/api/admin/analytics/by-plan?metric=ai_call",
    "/api/admin/analytics/trends",
    "/api/admin/crm",
    f"/api/admin/businesses/{BIZ_A}/crm/notes",
]


def _superuser_dsn() -> str:
    user = os.environ["POSTGRES_USER"]
    pw = os.environ["POSTGRES_PASSWORD"]
    db = os.environ["POSTGRES_DB"]
    return f"postgresql://{user}:{pw}@postgres:5432/{db}"


@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=4)
    try:
        yield p
    finally:
        await p.close()


@pytest_asyncio.fixture
async def su():
    p = await asyncpg.create_pool(dsn=_superuser_dsn(), min_size=1, max_size=2)
    try:
        yield p
    finally:
        await p.close()


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
async def redis(lifespan_app):
    return lifespan_app.state.redis


@pytest_asyncio.fixture
async def admin_user(su):
    async with su.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM users WHERE email = $1", ADMIN_EMAIL
        )
        if existing is None:
            await conn.execute(
                "INSERT INTO users (id, email, name) VALUES ($1, $2, 'M13 Admin')",
                ADMIN_USER_ID_FALLBACK,
                ADMIN_EMAIL,
            )
            existing = ADMIN_USER_ID_FALLBACK
    yield str(existing)


@pytest_asyncio.fixture
async def clean_m13(su):
    """Reset the CRM + audit + ai_call rows our test wrote (zero-grant tables)."""
    yield
    async with su.acquire() as conn:
        await conn.execute("DELETE FROM crm_notes WHERE business_id = $1", BIZ_A)
        await conn.execute("DELETE FROM business_crm WHERE business_id = $1", BIZ_A)
        await conn.execute(
            "DELETE FROM admin_audit WHERE target_business_id = $1", BIZ_A
        )
        await conn.execute(
            "DELETE FROM usage_daily WHERE business_id = $1 AND metric = 'ai_call'",
            BIZ_A,
        )


async def _login(redis, http, user_id: str, email: str, business_id: str) -> str:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id,
        "email": email,
        "name": user_id,
        "picture": "",
        "business_id": business_id,
        "business_name": "x",
        "created_at": int(time.time()),
    }
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)
    return sid


async def _logout(redis, http, sid: str) -> None:
    await redis.delete(f"{_SESSION_KEY_PREFIX}{sid}")
    http.cookies.clear()


# (a) gate -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_routes_require_session(http):
    for route in NEW_GET_ROUTES:
        assert (await http.get(route)).status_code == 401, route
    assert (
        await http.patch(
            f"/api/admin/businesses/{BIZ_A}/crm", json={"stage": "won"}
        )
    ).status_code == 401
    assert (
        await http.post(
            f"/api/admin/businesses/{BIZ_A}/crm/notes", json={"note": "x"}
        )
    ).status_code == 401


@pytest.mark.asyncio
async def test_nonadmin_forbidden_on_new_routes(http, redis):
    sid = await _login(redis, http, AVI_USER, NONADMIN_EMAIL, BIZ_A)
    try:
        for route in NEW_GET_ROUTES:
            assert (await http.get(route)).status_code == 403, route
        assert (
            await http.patch(
                f"/api/admin/businesses/{BIZ_A}/crm", json={"stage": "won"}
            )
        ).status_code == 403
        assert (
            await http.post(
                f"/api/admin/businesses/{BIZ_A}/crm/notes", json={"note": "x"}
            )
        ).status_code == 403
    finally:
        await _logout(redis, http, sid)


# (b) overview: avg_ltv + snapshot stamp -------------------------------------


@pytest.mark.asyncio
async def test_overview_has_ltv_and_stamps_snapshot(http, redis, su, admin_user):
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        r = await http.get("/api/admin/overview")
        assert r.status_code == 200
        body = r.json()
        assert "avg_ltv" in body and "total_ltv" in body
        # The view should have stamped today's snapshot row.
        async with su.acquire() as conn:
            stamped = await conn.fetchval(
                "SELECT count(*) FROM platform_snapshots WHERE day = current_date"
            )
        assert stamped == 1
    finally:
        await _logout(redis, http, sid)


# (c) analytics endpoints return sane JSON -----------------------------------


@pytest.mark.asyncio
async def test_analytics_endpoints_shape(http, redis, admin_user):
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        r = await http.get("/api/admin/analytics/leads-by-type?period=month&plan=all")
        assert r.status_code == 200
        assert {"booking", "lead", "handoff"} <= set(r.json())

        r = await http.get("/api/admin/analytics/messages?period=all")
        assert r.status_code == 200 and "businesses" in r.json()

        r = await http.get("/api/admin/analytics/ai-ops")
        assert r.status_code == 200 and "series" in r.json()

        r = await http.get("/api/admin/analytics/by-plan?metric=ai_call&period=month")
        assert r.status_code == 200
        b = r.json()
        assert b["metric"] == "ai_call" and "rows" in b

        r = await http.get("/api/admin/analytics/trends")
        assert r.status_code == 200 and "series" in r.json()

        # Validation: junk metric → 422; bad date → 422.
        assert (
            await http.get("/api/admin/analytics/by-plan?metric=bogus")
        ).status_code == 422
        assert (
            await http.get("/api/admin/analytics/ai-ops?from=not-a-date")
        ).status_code == 422

        # CRM board.
        r = await http.get("/api/admin/crm")
        assert r.status_code == 200 and "businesses" in r.json()
    finally:
        await _logout(redis, http, sid)


# (d) CRM stage + audit; bad stage 422; unknown business 404 -----------------


@pytest.mark.asyncio
async def test_crm_stage_audit_and_errors(http, redis, su, admin_user, clean_m13):
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        r = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/crm",
            json={"stage": "warming", "next_followup": "2026-07-01T09:00:00+00:00"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["stage"] == "warming" and body["next_followup_at"] is not None

        async with su.acquire() as conn:
            audited = await conn.fetchval(
                "SELECT count(*) FROM admin_audit WHERE target_business_id = $1", BIZ_A
            )
        assert audited >= 1

        # Bad stage (Literal rejects → 422 before the SD call).
        assert (
            await http.patch(
                f"/api/admin/businesses/{BIZ_A}/crm", json={"stage": "nope"}
            )
        ).status_code == 422
        # Unknown business → 404.
        assert (
            await http.patch(
                f"/api/admin/businesses/{UNKNOWN_BIZ}/crm", json={"stage": "won"}
            )
        ).status_code == 404
    finally:
        await _logout(redis, http, sid)


# (e) note round-trip --------------------------------------------------------


@pytest.mark.asyncio
async def test_crm_note_roundtrip(http, redis, admin_user, clean_m13):
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        r = await http.post(
            f"/api/admin/businesses/{BIZ_A}/crm/notes",
            json={"note": "called the owner; warm"},
        )
        assert r.status_code == 201, r.text
        note_id = r.json()["note_id"]
        assert note_id

        r = await http.get(f"/api/admin/businesses/{BIZ_A}/crm/notes")
        assert r.status_code == 200
        notes = r.json()["notes"]
        assert any(n["id"] == note_id for n in notes)
        assert any(n["note"] == "called the owner; warm" for n in notes)

        # Blank note → 422; unknown business → 404.
        assert (
            await http.post(
                f"/api/admin/businesses/{BIZ_A}/crm/notes", json={"note": "   "}
            )
        ).status_code == 422
        assert (
            await http.post(
                f"/api/admin/businesses/{UNKNOWN_BIZ}/crm/notes", json={"note": "x"}
            )
        ).status_code == 404
    finally:
        await _logout(redis, http, sid)


# (f) ai_call bump increments usage_daily ------------------------------------


@pytest.mark.asyncio
async def test_ai_call_bump_increments_usage(pool, su, clean_m13):
    """Prove the bump wiring: a bump_safe(ai_call) lands in usage_daily for BIZ_A."""
    async with tenant_connection(pool, BIZ_A) as conn:
        await usage_service.bump_safe(conn, BIZ_A, usage_service.METRIC_AI_CALL)
    async with su.acquire() as conn:
        n = await conn.fetchval(
            "SELECT count FROM usage_daily "
            "WHERE business_id = $1 AND metric = 'ai_call' AND day = current_date",
            BIZ_A,
        )
    assert n is not None and n >= 1
