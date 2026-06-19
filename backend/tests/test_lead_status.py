"""M7 polish — PATCH /api/leads/{id}/status + dashboard 'orders' — strict pytest.

This is the CI gate for the M7 "polish" surface that the owner uses to work a
lead through to a sale:

  * PATCH /api/leads/{id}/status — owner sets a lead to 'deal' / 'closed' (and the
    other settable statuses); GET /api/leads reflects the change.
      - rejects an INVALID status (422),
      - 404 for an UNKNOWN lead id,
      - 401 with NO session (deny-by-default gate),
      - TENANT-SCOPED: business A cannot change business B's lead (404 / no-op).
  * GET /api/dashboard — "orders" = count of status='deal' leads:
      - marking a lead 'deal' via PATCH INCREMENTS orders,
      - the is_test filter is respected (default excludes test 'deal' leads),
      - the period filter is respected.

It drives the real bot door (POST /api/bot/sim, is_test=true) to SEED genuine
leads, then exercises the endpoints in-process against the real ASGI app over
httpx ASGITransport — so the gate, the session dependency, and
tenant_connection/RLS are all real. Everything seeded is is_test=true and is
cleaned up. Nothing prints a secret, a token, or PII.
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
from app.services import conversation_state
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

A_NAME = "דנה כהן"
A_PHONE = "052-1234567"
B_NAME = "שרה בלה-לקוחה"
B_PHONE = "050-9999999"


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
    """After each test: delete is_test leads for both tenants + made conv keys."""
    made: list[tuple[str, str]] = []
    yield made
    for bid, cid in made:
        await conversation_state.clear_state(rds, bid, cid)
        await rds.delete(f"conv:{bid}:{cid}:outbox")
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute(
                "DELETE FROM leads WHERE business_id = $1 AND is_test = true", bid)


# --- helpers ----------------------------------------------------------------

async def _login(rds, client, user_id: str, business_id: str) -> str:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": f"{user_id}@example.com", "name": user_id,
        "picture": "", "business_id": business_id, "business_name": "x",
        "created_at": int(time.time()),
    }
    await rds.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    client.cookies.set(SESSION_COOKIE_NAME, sid)
    return sid


async def _sim(client, conv_id, msg):
    return (await client.post(
        "/api/bot/sim", json={"message": msg, "conversation_id": conv_id})).json()


async def _seed_quote(client, made, conv_id, name, phone):
    """Drive Avi's full quote flow to completion (is_test lead). Returns lead_id."""
    made.append((BIZ_A, conv_id))
    s = await _sim(client, conv_id, "1")
    await _sim(client, conv_id, name)
    await _sim(client, conv_id, phone)
    done = await _sim(client, conv_id, "1")
    return done.get("lead_id") or s.get("lead_id")


async def _lead_status(client, lead_id) -> str | None:
    leads = (await client.get("/api/leads?include_test=true")).json()["leads"]
    for l in leads:
        if l["id"] == lead_id:
            return l["status"]
    return None


# ============================================================================
#  THE GATE
# ============================================================================

@pytest.mark.asyncio
async def test_patch_status_requires_session(http):
    r = await http.patch("/api/leads/some-id/status", json={"status": "deal"})
    assert r.status_code == 401


# ============================================================================
#  PATCH /api/leads/{id}/status — happy path (deal, closed) reflected by GET
# ============================================================================

@pytest.mark.asyncio
async def test_patch_status_to_deal_then_closed(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = f"sim:{secrets.token_hex(8)}"
    lead_id = await _seed_quote(http, cleanup, conv, A_NAME, A_PHONE)
    # fresh completed lead starts at 'new'.
    assert await _lead_status(http, lead_id) == "new"

    r1 = await http.patch(f"/api/leads/{lead_id}/status", json={"status": "deal"})
    assert r1.status_code == 200
    assert r1.json() == {"lead_id": lead_id, "status": "deal"}
    assert await _lead_status(http, lead_id) == "deal"

    r2 = await http.patch(f"/api/leads/{lead_id}/status", json={"status": "closed"})
    assert r2.status_code == 200
    assert r2.json()["status"] == "closed"
    assert await _lead_status(http, lead_id) == "closed"


# ============================================================================
#  PATCH validation: invalid status (422), unknown id (404)
# ============================================================================

@pytest.mark.asyncio
async def test_patch_status_invalid_is_422(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = f"sim:{secrets.token_hex(8)}"
    lead_id = await _seed_quote(http, cleanup, conv, A_NAME, A_PHONE)

    bad = await http.patch(f"/api/leads/{lead_id}/status", json={"status": "banana"})
    assert bad.status_code == 422
    # extra fields are forbidden by the model too.
    extra = await http.patch(
        f"/api/leads/{lead_id}/status", json={"status": "deal", "x": 1})
    assert extra.status_code == 422
    # ...and the lead was NOT changed by either rejected call.
    assert await _lead_status(http, lead_id) == "new"


@pytest.mark.asyncio
async def test_patch_status_unknown_id_is_404(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    ghost = "00000000-0000-0000-0000-000000000000"
    r = await http.patch(f"/api/leads/{ghost}/status", json={"status": "deal"})
    assert r.status_code == 404


# ============================================================================
#  TENANT ISOLATION: A cannot change B's lead (404 / no-op)
# ============================================================================

@pytest.mark.asyncio
async def test_patch_status_cross_tenant_is_404_noop(http, lifespan_app, rds, pool, cleanup):
    # Bella (B) seeds a real-but-test lead on her own client.
    transport = ASGITransport(app=lifespan_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as bhttp:
        await _login(rds, bhttp, BELLA_USER, BIZ_B)
        b_conv = f"sim:{secrets.token_hex(8)}"
        cleanup.append((BIZ_B, b_conv))
        await _sim(bhttp, b_conv, "1")
        await _sim(bhttp, b_conv, B_NAME)
        await _sim(bhttp, b_conv, B_PHONE)
        b_done = await _sim(bhttp, b_conv, "1")
        b_lead = b_done.get("lead_id")
        assert b_lead, "expected Bella's lead to be created"
        b_status_before = await _lead_status(bhttp, b_lead)

        # Avi (A) — logged in on the main client — tries to flip Bella's lead.
        await _login(rds, http, AVI_USER, BIZ_A)
        attack = await http.patch(
            f"/api/leads/{b_lead}/status", json={"status": "deal"})
        assert attack.status_code == 404, "A must not touch B's lead"

        # Bella's lead is unchanged (no-op for the cross-tenant attempt).
        b_status_after = await _lead_status(bhttp, b_lead)
        assert b_status_after == b_status_before

    # And the raw DB confirms it is NOT 'deal'.
    async with tenant_connection(pool, BIZ_B) as conn:
        raw = await conn.fetchval(
            "SELECT status FROM leads WHERE id=$1 AND business_id=$2", b_lead, BIZ_B)
    assert raw != "deal"


# ============================================================================
#  GET /api/dashboard — orders = count of status='deal'
# ============================================================================

@pytest.mark.asyncio
async def test_dashboard_orders_increments_on_deal(http, rds, pool, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = f"sim:{secrets.token_hex(8)}"
    lead_id = await _seed_quote(http, cleanup, conv, A_NAME, A_PHONE)

    # include_test=true so our seeded test lead is counted in this assertion.
    before = (await http.get("/api/dashboard?period=all&include_test=true")).json()
    assert "orders" in before
    orders_before = before["orders"]

    r = await http.patch(f"/api/leads/{lead_id}/status", json={"status": "deal"})
    assert r.status_code == 200

    after = (await http.get("/api/dashboard?period=all&include_test=true")).json()
    assert after["orders"] == orders_before + 1

    # orders must equal the raw DB truth for status='deal' (is_test included here).
    async with tenant_connection(pool, BIZ_A) as conn:
        raw_deals = await conn.fetchval(
            "SELECT count(*)::int FROM leads WHERE business_id=$1 AND status='deal'",
            BIZ_A)
    assert after["orders"] == raw_deals


@pytest.mark.asyncio
async def test_dashboard_orders_respects_is_test_filter(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = f"sim:{secrets.token_hex(8)}"
    lead_id = await _seed_quote(http, cleanup, conv, A_NAME, A_PHONE)
    await http.patch(f"/api/leads/{lead_id}/status", json={"status": "deal"})

    default = (await http.get("/api/dashboard?period=all")).json()
    with_test = (await http.get("/api/dashboard?period=all&include_test=true")).json()
    # The deal we just made is on a TEST lead, so it must NOT show by default,
    # but must appear when include_test=true.
    assert with_test["orders"] >= default["orders"] + 1


@pytest.mark.asyncio
async def test_dashboard_orders_respects_period_filter(http, rds, pool, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = f"sim:{secrets.token_hex(8)}"
    lead_id = await _seed_quote(http, cleanup, conv, A_NAME, A_PHONE)
    await http.patch(f"/api/leads/{lead_id}/status", json={"status": "deal"})

    # back-date this deal's started_at ~40 days so 'week' excludes it.
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute(
            "UPDATE leads SET started_at = now() - interval '40 days' "
            "WHERE id=$1 AND business_id=$2", lead_id, BIZ_A)

    all_q = (await http.get("/api/dashboard?period=all&include_test=true")).json()
    week_q = await http.get("/api/dashboard?period=week&include_test=true")
    assert week_q.status_code == 200
    week = week_q.json()
    # the 40-day-old deal counts in 'all' but is excluded from 'week'.
    assert all_q["orders"] >= 1
    assert week["orders"] == all_q["orders"] - 1
