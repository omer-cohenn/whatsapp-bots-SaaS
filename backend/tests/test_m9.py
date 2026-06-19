"""M9 — lead outcomes unified around the LEAD, strict pytest (the CI version).

Per decision 0009. The lead status is the single source of truth for an outcome:

  * "בוצעה עסקה"  → lead status 'deal'   + conversation status 'closed'
  * "סגירת פנייה" → lead status 'closed' + conversation status 'closed'

Both reuse EXISTING endpoints (PATCH /api/leads/{id}/status, POST
/api/conversations/{id}/status) — no new endpoint. This suite proves:

  1. GET /api/leads?status=deal | ?status=closed return ONLY those leads, scoped.
  2. Each lead payload carries conversation_id derived from cache_chat_ref
     (and null when there is no ref).
  3. A handoff turn with NO prior lead now CREATES a minimal lead
     (lead_name "פנייה לנציג") linked to the conversation; the handed_off
     funnel event is attached to it; the chat status still flips to 'waiting'.
  4. The outcome flow: PATCH a lead to 'deal'/'closed' works and it then appears
     under that status filter; the conversation can be closed via POST status.
  5. TENANT ISOLATION: business A can never read/filter business B's leads.

It runs IN-PROCESS against the real ASGI app over httpx ASGITransport (so the
deny-by-default /api gate, the session dependency, and tenant_connection/RLS are
all real), and calls bot_runtime.run_turn directly where a test needs exact
control of Redis state. Every persisted row is is_test=true; the cleanup fixture
deletes the test leads + Redis conv keys it created. Nothing prints a secret, a
token, or PII.
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
from app.services import (
    bot_runtime,
    conversation_state as cs,
    leads as leads_service,
)
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (published)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (draft)
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

HANDOFF_LEAD_NAME = "פנייה לנציג"  # the minimal-lead label the runtime stamps.


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
    """After each test: drop the conv keys we made + any is_test leads in A and B."""
    made: list[tuple[str, str]] = []
    yield made
    for bid, cid in made:
        await cs.clear_state(rds, bid, cid)
        await rds.delete(f"conv:{bid}:{cid}:log")
        await rds.delete(f"conv:{bid}:{cid}:outbox")
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute(
                "DELETE FROM leads WHERE business_id = $1 AND is_test = true", bid)


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


def _new_conv() -> str:
    return f"sim:{secrets.token_hex(8)}"


async def _seed_test_lead(pool, business_id: str, *, status: str,
                          conversation_id: str | None) -> str:
    """Insert a minimal is_test lead with a given status (+ optional conv link).

    Tenant-scoped via tenant_connection so RLS WITH CHECK matches. Returns the id.
    """
    cache_chat_ref = (
        f"conv:{business_id}:{conversation_id}" if conversation_id else None
    )
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO leads
                (business_id, lead_name, status, is_test, cache_chat_ref,
                 started_at, last_activity_at)
            VALUES ($1, $2, $3, true, $4, now(), now())
            RETURNING id
            """,
            business_id, "test-flow", status, cache_chat_ref,
        )
    return str(row["id"])


# ============================================================================
#  1) GET /api/leads?status=deal and ?status=closed → ONLY those, scoped
# ============================================================================

@pytest.mark.asyncio
async def test_status_filter_deal_and_closed_return_only_those(http, rds, pool, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    # One lead of each outcome status (+ a 'new' that must be excluded).
    deal_id = await _seed_test_lead(pool, BIZ_A, status="deal", conversation_id=None)
    closed_id = await _seed_test_lead(pool, BIZ_A, status="closed", conversation_id=None)
    new_id = await _seed_test_lead(pool, BIZ_A, status="new", conversation_id=None)

    # ?status=deal returns the deal only.
    deal_rows = (await http.get("/api/leads?status=deal&include_test=true")).json()["leads"]
    deal_ids = {r["id"] for r in deal_rows}
    assert deal_id in deal_ids
    assert closed_id not in deal_ids and new_id not in deal_ids
    assert all(r["status"] == "deal" for r in deal_rows)

    # ?status=closed returns the closed only.
    closed_rows = (await http.get("/api/leads?status=closed&include_test=true")).json()["leads"]
    closed_ids = {r["id"] for r in closed_rows}
    assert closed_id in closed_ids
    assert deal_id not in closed_ids and new_id not in closed_ids
    assert all(r["status"] == "closed" for r in closed_rows)


@pytest.mark.asyncio
async def test_list_leads_service_filters_deal_and_closed(pool, cleanup):
    """The service-layer list_leads must also accept the two new stored statuses."""
    deal_id = await _seed_test_lead(pool, BIZ_A, status="deal", conversation_id=None)
    closed_id = await _seed_test_lead(pool, BIZ_A, status="closed", conversation_id=None)

    async with tenant_connection(pool, BIZ_A) as conn:
        deals = await leads_service.list_leads(
            conn, BIZ_A, status="deal", include_test=True)
        closeds = await leads_service.list_leads(
            conn, BIZ_A, status="closed", include_test=True)

    assert deal_id in {r["id"] for r in deals}
    assert all(r["status"] == "deal" for r in deals)
    assert closed_id in {r["id"] for r in closeds}
    assert all(r["status"] == "closed" for r in closeds)


# ============================================================================
#  2) conversation_id derived from cache_chat_ref (and null when absent)
# ============================================================================

@pytest.mark.asyncio
async def test_lead_payload_includes_conversation_id(http, rds, pool, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    linked_id = await _seed_test_lead(pool, BIZ_A, status="new", conversation_id=conv)
    unlinked_id = await _seed_test_lead(pool, BIZ_A, status="new", conversation_id=None)

    rows = (await http.get("/api/leads?status=new&include_test=true")).json()["leads"]
    by_id = {r["id"]: r for r in rows}

    # The linked lead exposes the derived conversation_id (prefix stripped).
    assert by_id[linked_id]["conversation_id"] == conv
    # The unlinked lead's conversation_id is null.
    assert by_id[unlinked_id]["conversation_id"] is None


# ============================================================================
#  3) Handoff with NO prior lead → minimal lead created + linked + event
# ============================================================================

@pytest.mark.asyncio
async def test_handoff_with_no_prior_lead_creates_minimal_lead(pool, rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))

    # Send a handoff keyword as the VERY FIRST message — no flow ever started, so
    # there is no active lead. Under M9 the runtime must still create one.
    result = await bot_runtime.run_turn(
        pool, rds, BIZ_A, conv, "אני רוצה לדבר עם נציג", is_test=True)

    assert result["event"] == "handed_off"
    # The chat status still flips to 'waiting' (customer asked, nobody picked up).
    assert await cs.get_status(rds, BIZ_A, conv) == cs.STATUS_WAITING

    # A minimal lead was created for this turn.
    lead_id = result["lead_id"]
    assert lead_id is not None

    async with tenant_connection(pool, BIZ_A) as conn:
        lead = await conn.fetchrow(
            "SELECT lead_name, status, cache_chat_ref FROM leads "
            "WHERE id = $1 AND business_id = $2",
            lead_id, BIZ_A)
        # The handed_off funnel event is attached to THIS lead.
        ev = await conn.fetchval(
            "SELECT count(*)::int FROM flow_events "
            "WHERE business_id = $1 AND lead_id = $2 AND event = $3",
            BIZ_A, lead_id, leads_service.EVENT_HANDOFF)

    assert lead["lead_name"] == HANDOFF_LEAD_NAME
    # Default status from create_lead is in_progress (the lead exists for follow-up).
    assert lead["status"] == leads_service.STATUS_IN_PROGRESS
    # The lead is linked back to the conversation via cache_chat_ref.
    assert lead["cache_chat_ref"] == f"conv:{BIZ_A}:{conv}"
    assert ev >= 1


@pytest.mark.asyncio
async def test_handoff_minimal_lead_shows_conversation_id_in_api(http, rds, pool, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))

    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "נציג", is_test=True)

    # The handoff lead is visible in the leads list with its conversation_id set.
    rows = (await http.get("/api/leads?include_test=true")).json()["leads"]
    match = [r for r in rows if r.get("conversation_id") == conv]
    assert match, "handoff lead not found linked to its conversation"
    assert match[0]["lead_name"] == HANDOFF_LEAD_NAME


# ============================================================================
#  4) Outcome flow: PATCH lead → deal/closed, then it filters; conv closes
# ============================================================================

@pytest.mark.asyncio
async def test_outcome_deal_flow(http, rds, pool, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    lead_id = await _seed_test_lead(pool, BIZ_A, status="new", conversation_id=conv)

    # "בוצעה עסקה" → lead status 'deal'.
    r = await http.patch(f"/api/leads/{lead_id}/status", json={"status": "deal"})
    assert r.status_code == 200 and r.json()["status"] == "deal"

    # It now appears under ?status=deal (and no longer under ?status=new).
    deal_ids = {x["id"] for x in
                (await http.get("/api/leads?status=deal&include_test=true")).json()["leads"]}
    new_ids = {x["id"] for x in
               (await http.get("/api/leads?status=new&include_test=true")).json()["leads"]}
    assert lead_id in deal_ids and lead_id not in new_ids

    # The conversation can be closed via the existing POST status endpoint.
    rc = await http.post(f"/api/conversations/{conv}/status", json={"status": "closed"})
    assert rc.status_code == 200 and rc.json()["status"] == "closed"
    assert await cs.get_status(rds, BIZ_A, conv) == cs.STATUS_CLOSED


@pytest.mark.asyncio
async def test_outcome_closed_flow(http, rds, pool, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    lead_id = await _seed_test_lead(pool, BIZ_A, status="new", conversation_id=conv)

    # "סגירת פנייה" → lead status 'closed'.
    r = await http.patch(f"/api/leads/{lead_id}/status", json={"status": "closed"})
    assert r.status_code == 200 and r.json()["status"] == "closed"

    closed_ids = {x["id"] for x in
                  (await http.get("/api/leads?status=closed&include_test=true")).json()["leads"]}
    assert lead_id in closed_ids

    rc = await http.post(f"/api/conversations/{conv}/status", json={"status": "closed"})
    assert rc.status_code == 200
    assert await cs.get_status(rds, BIZ_A, conv) == cs.STATUS_CLOSED


# ============================================================================
#  5) TENANT ISOLATION — A cannot read / filter B's deal/closed leads
# ============================================================================

@pytest.mark.asyncio
async def test_isolation_deal_closed_leads_not_visible_cross_tenant(http, rds, pool, cleanup):
    # Bella (B) has a deal and a closed lead.
    b_deal = await _seed_test_lead(pool, BIZ_B, status="deal", conversation_id=None)
    b_closed = await _seed_test_lead(pool, BIZ_B, status="closed", conversation_id=None)

    # Avi (A) logs in and filters by deal/closed — must never see B's leads.
    await _login(rds, http, AVI_USER, BIZ_A)
    a_deals = (await http.get("/api/leads?status=deal&include_test=true")).json()["leads"]
    a_closed = (await http.get("/api/leads?status=closed&include_test=true")).json()["leads"]
    a_all = (await http.get("/api/leads?include_test=true")).json()["leads"]

    seen = {r["id"] for r in a_deals} | {r["id"] for r in a_closed} | {r["id"] for r in a_all}
    assert b_deal not in seen
    assert b_closed not in seen


@pytest.mark.asyncio
async def test_isolation_cannot_patch_other_tenants_lead(http, rds, pool, cleanup):
    # B owns the lead; A tries to PATCH it by id → 404 (RLS hid the row).
    b_lead = await _seed_test_lead(pool, BIZ_B, status="new", conversation_id=None)
    await _login(rds, http, AVI_USER, BIZ_A)

    r = await http.patch(f"/api/leads/{b_lead}/status", json={"status": "deal"})
    assert r.status_code == 404

    # The lead's status is unchanged when read as its true owner.
    async with tenant_connection(pool, BIZ_B) as conn:
        st = await conn.fetchval(
            "SELECT status FROM leads WHERE id = $1 AND business_id = $2",
            b_lead, BIZ_B)
    assert st == "new"


# ============================================================================
#  The gate — the M9 doors are 401 without a session
# ============================================================================

@pytest.mark.asyncio
async def test_m9_routes_require_session(http):
    assert (await http.get("/api/leads?status=deal")).status_code == 401
    assert (await http.patch("/api/leads/x/status", json={"status": "deal"})).status_code == 401
