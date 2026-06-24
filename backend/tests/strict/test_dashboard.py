"""M7 — the owner DASHBOARD / back-office, strict pytest (the CI version).

m7_full_test.py is the narrated story; THIS is the strict gate CI runs. It drives
the real bot door (POST /api/bot/sim, is_test=true) to SEED genuine leads + a
funnel + a live conversation, then exercises every M7 read/back-office endpoint
in-process against the real ASGI app over httpx ASGITransport — so the
deny-by-default /api gate, the session dependency, and tenant_connection/RLS are
all real.

Covered:
  * GET  /api/leads          — decrypt, status/flow filters, is_test exclusion, gate.
  * GET  /api/dashboard      — funnel counts match DB truth, gate.
  * GET  /api/conversations  — lists only this tenant's chats, gate.
  * POST .../status, .../reply — flip status / queue reply, validation, gate.
  * PUT  /api/bot/publish     — toggles is_published, reflected by GET /api/bot/settings.
  * TENANT ISOLATION         — A never sees B's leads / dashboard / conversations.

period=week|month now works: app/services/leads._PERIOD_INTERVALS holds
datetime.timedelta values so asyncpg binds them natively to the $N::interval
param (an earlier str like '7 days' raised a DataError). The two period tests
below assert a hard 200.

Everything seeded here is is_test=true; the fixture deletes those leads + the
Redis conv keys it created. Nothing prints a secret, a token, or PII.
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
from app.services import bot_settings as bot_settings_service, conversation_state
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (published)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (draft)
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

# Avi's 'quote' flow: full_name → phone → insurance_type(choice).
A_NAME = "דנה כהן"
A_PHONE = "052-1234567"
A_PHONE_DIGITS = "0521234567"
A_CHOICE = "רכב"
# Bella's 'appointment' flow: full_name → phone.
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
    # raise_app_exceptions=False so an in-process 500 surfaces as an HTTP 500
    # response (what a real client sees) instead of re-raising into the test.
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
    # restore seed publish states (a publish test may have toggled them).
    await bot_settings_service.set_published(pool, BIZ_A, True)
    await bot_settings_service.set_published(pool, BIZ_B, False)


# --- helpers ----------------------------------------------------------------

async def _login(rds, http, user_id: str, business_id: str) -> str:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": f"{user_id}@example.com", "name": user_id,
        "picture": "", "business_id": business_id, "business_name": "x",
        "created_at": int(time.time()),
    }
    await rds.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)
    return sid


async def _sim(http, conv_id, msg):
    return (await http.post(
        "/api/bot/sim", json={"message": msg, "conversation_id": conv_id})).json()


async def _seed_quote(http, made, conv_id, name, phone):
    """Drive Avi's full quote flow to completion (is_test lead). Returns lead_id."""
    made.append((BIZ_A, conv_id))
    s = await _sim(http, conv_id, "1")
    await _sim(http, conv_id, name)
    await _sim(http, conv_id, phone)
    done = await _sim(http, conv_id, "1")
    return done.get("lead_id") or s.get("lead_id")


# ============================================================================
#  THE GATE — every M7 door is 401 without a session
# ============================================================================

@pytest.mark.asyncio
async def test_all_m7_routes_require_session(http):
    assert (await http.get("/api/leads")).status_code == 401
    assert (await http.get("/api/dashboard")).status_code == 401
    assert (await http.get("/api/conversations")).status_code == 401
    assert (await http.post(
        "/api/conversations/x/status", json={"status": "bot"})).status_code == 401
    assert (await http.post(
        "/api/conversations/x/reply", json={"text": "hi"})).status_code == 401
    assert (await http.put(
        "/api/bot/publish", json={"is_published": True})).status_code == 401


# ============================================================================
#  GET /api/leads
# ============================================================================

@pytest.mark.asyncio
async def test_leads_decrypted_full_detail(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = f"sim:{secrets.token_hex(8)}"
    lead_id = await _seed_quote(http, cleanup, conv, A_NAME, A_PHONE)

    leads = (await http.get("/api/leads?include_test=true")).json()["leads"]
    lead = next(l for l in leads if l["id"] == lead_id)
    assert lead["phone"] == A_PHONE_DIGITS
    assert lead["contact_name"] == A_NAME
    assert lead["lead_name"] == "quote"
    assert lead["status"] == "new"
    assert lead["answers"]["full_name"] == A_NAME
    assert lead["answers"]["phone"] == A_PHONE_DIGITS
    assert lead["answers"]["insurance_type"] == A_CHOICE


@pytest.mark.asyncio
async def test_leads_is_test_excluded_by_default(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = f"sim:{secrets.token_hex(8)}"
    await _seed_quote(http, cleanup, conv, A_NAME, A_PHONE)

    default = (await http.get("/api/leads")).json()["leads"]
    with_test = (await http.get("/api/leads?include_test=true")).json()["leads"]
    assert all(not l["is_test"] for l in default)
    assert any(l["is_test"] for l in with_test)
    assert len(with_test) > len(default)


@pytest.mark.asyncio
async def test_leads_status_filters_including_open(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    # one completed (status new) + one partial (status in_progress).
    done_conv = f"sim:{secrets.token_hex(8)}"
    done_id = await _seed_quote(http, cleanup, done_conv, A_NAME, A_PHONE)
    open_conv = f"sim:{secrets.token_hex(8)}"
    cleanup.append((BIZ_A, open_conv))
    s = await _sim(http, open_conv, "1")
    await _sim(http, open_conv, "יוסי לוי")
    open_id = s["lead_id"]

    q = "include_test=true"
    new_only = (await http.get(f"/api/leads?status=new&{q}")).json()["leads"]
    inprog = (await http.get(f"/api/leads?status=in_progress&{q}")).json()["leads"]
    open_b = (await http.get(f"/api/leads?status=open&{q}")).json()["leads"]

    assert all(l["status"] == "new" for l in new_only)
    assert any(l["id"] == done_id for l in new_only)
    assert all(l["status"] == "in_progress" for l in inprog)
    assert any(l["id"] == open_id for l in inprog)
    # synthetic 'open' = new + in_progress, and contains BOTH our leads.
    assert all(l["status"] in ("new", "in_progress") for l in open_b)
    open_ids = {l["id"] for l in open_b}
    assert done_id in open_ids and open_id in open_ids


@pytest.mark.asyncio
async def test_leads_flow_filter(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = f"sim:{secrets.token_hex(8)}"
    await _seed_quote(http, cleanup, conv, A_NAME, A_PHONE)

    quote = (await http.get("/api/leads?flow=quote&include_test=true")).json()["leads"]
    none = (await http.get("/api/leads?flow=__nope__&include_test=true")).json()["leads"]
    assert quote and all(l["lead_name"] == "quote" for l in quote)
    assert none == []


@pytest.mark.asyncio
async def test_leads_period_filter_week(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = f"sim:{secrets.token_hex(8)}"
    await _seed_quote(http, cleanup, conv, A_NAME, A_PHONE)
    resp = await http.get("/api/leads?period=week")
    assert resp.status_code == 200


# ============================================================================
#  GET /api/dashboard
# ============================================================================

@pytest.mark.asyncio
async def test_dashboard_counts_match_db_truth(http, rds, pool, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    # is_test leads must NOT count; include_test=true on the dashboard counts them.
    conv = f"sim:{secrets.token_hex(8)}"
    await _seed_quote(http, cleanup, conv, A_NAME, A_PHONE)

    dash = (await http.get("/api/dashboard?period=all")).json()
    dash_t = (await http.get("/api/dashboard?period=all&include_test=true")).json()

    async with tenant_connection(pool, BIZ_A) as conn:
        ev = {r["event"]: r["n"] for r in await conn.fetch(
            "SELECT event, count(*)::int n FROM flow_events "
            "WHERE business_id=$1 AND is_test=false GROUP BY event", BIZ_A)}
        real_total = await conn.fetchval(
            "SELECT count(*)::int FROM leads WHERE business_id=$1 AND is_test=false",
            BIZ_A)
    assert dash["started"] == ev.get("started", 0)
    assert dash["completed"] == ev.get("completed", 0)
    assert dash["abandoned"] == ev.get("abandoned", 0)
    assert dash["total_leads"] == real_total
    # include_test=true must see MORE (our seeded test lead).
    assert dash_t["total_leads"] > dash["total_leads"]


@pytest.mark.asyncio
async def test_dashboard_period_filter_week(http, rds):
    await _login(rds, http, AVI_USER, BIZ_A)
    resp = await http.get("/api/dashboard?period=week")
    assert resp.status_code == 200


# ============================================================================
#  GET /api/conversations + status + reply
# ============================================================================

@pytest.mark.asyncio
async def test_conversations_list_status_reply(http, rds, pool, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = f"sim:{secrets.token_hex(8)}"
    cleanup.append((BIZ_A, conv))
    await _sim(http, conv, "שלום")  # one live conversation now exists

    convs = (await http.get("/api/conversations")).json()["conversations"]
    assert conv in {c["conversation_id"] for c in convs}

    # status: bot|human|closed flips and sticks; invalid -> 422.
    r_h = await http.post(f"/api/conversations/{conv}/status", json={"status": "human"})
    assert r_h.json()["status"] == "human"
    assert await conversation_state.get_status(rds, BIZ_A, conv) == "human"
    r_c = await http.post(f"/api/conversations/{conv}/status", json={"status": "closed"})
    assert r_c.json()["status"] == "closed"
    assert await conversation_state.get_status(rds, BIZ_A, conv) == "closed"
    assert (await http.post(
        f"/api/conversations/{conv}/status", json={"status": "nope"})).status_code == 422

    # reply: queued, becomes preview, lands in the outbox; empty -> 422.
    text = "תודה, נחזור אליך בהקדם"
    r = await http.post(f"/api/conversations/{conv}/reply", json={"text": text})
    assert r.json()["queued"] is True
    convs2 = (await http.get("/api/conversations")).json()["conversations"]
    live = next(c for c in convs2 if c["conversation_id"] == conv)
    assert text in live["preview"]
    assert await rds.llen(f"conv:{BIZ_A}:{conv}:outbox") >= 1
    assert (await http.post(
        f"/api/conversations/{conv}/reply", json={"text": ""})).status_code == 422


# ============================================================================
#  PUT /api/bot/publish  (reflected by GET /api/bot/settings)
# ============================================================================

@pytest.mark.asyncio
async def test_publish_toggle_reflected_in_settings(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)

    off = (await http.put("/api/bot/publish", json={"is_published": False})).json()
    assert off["is_published"] is False
    assert (await http.get("/api/bot/settings")).json()["is_published"] is False

    on = (await http.put("/api/bot/publish", json={"is_published": True})).json()
    assert on["is_published"] is True
    assert (await http.get("/api/bot/settings")).json()["is_published"] is True


# ============================================================================
#  TENANT ISOLATION across every M7 read
# ============================================================================

@pytest.mark.asyncio
async def test_isolation_leads_dashboard_conversations(http, lifespan_app, rds, pool, cleanup):
    # Seed Avi (a completed lead + a live chat).
    await _login(rds, http, AVI_USER, BIZ_A)
    a_conv = f"sim:{secrets.token_hex(8)}"
    await _seed_quote(http, cleanup, a_conv, A_NAME, A_PHONE)
    a_live = f"sim:{secrets.token_hex(8)}"
    cleanup.append((BIZ_A, a_live))
    await _sim(http, a_live, "שלום")

    # Seed Bella (a completed lead + a live chat) on a SEPARATE client.
    transport = ASGITransport(app=lifespan_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as bhttp:
        await _login(rds, bhttp, BELLA_USER, BIZ_B)
        b_conv = f"sim:{secrets.token_hex(8)}"
        cleanup.append((BIZ_B, b_conv))
        await _sim(bhttp, b_conv, "1")
        await _sim(bhttp, b_conv, B_NAME)
        await _sim(bhttp, b_conv, B_PHONE)

        bella_leads = (await bhttp.get("/api/leads?include_test=true")).json()["leads"]
        bella_convs = (await bhttp.get("/api/conversations")).json()["conversations"]
        bella_dash = (await bhttp.get("/api/dashboard?period=all&include_test=true")).json()

    avi_leads = (await http.get("/api/leads?include_test=true")).json()["leads"]
    avi_convs = (await http.get("/api/conversations")).json()["conversations"]

    # Leads: no shared ids; Avi's data never contains Bella's plaintext.
    avi_ids = {l["id"] for l in avi_leads}
    bella_ids = {l["id"] for l in bella_leads}
    assert avi_ids.isdisjoint(bella_ids)
    blob = json.dumps(avi_leads, ensure_ascii=False)
    assert B_NAME not in blob and "0509999999" not in blob

    # Conversations: neither tenant's chat ids appear in the other's board.
    avi_conv_ids = {c["conversation_id"] for c in avi_convs}
    bella_conv_ids = {c["conversation_id"] for c in bella_convs}
    assert avi_conv_ids.isdisjoint(bella_conv_ids)
    assert a_live not in bella_conv_ids
    assert b_conv not in avi_conv_ids

    # Dashboard: Bella's funnel matches Bella's own DB truth only.
    async with tenant_connection(pool, BIZ_B) as conn:
        b_total = await conn.fetchval(
            "SELECT count(*)::int FROM leads WHERE business_id=$1", BIZ_B)
    assert bella_dash["total_leads"] == b_total
