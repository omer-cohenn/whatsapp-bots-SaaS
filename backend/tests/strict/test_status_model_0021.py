"""Decision 0021 — conversation/lead status model, strict pytest (CI version).

Verifies the unified status machine + close reasons + unread badge end-to-end
against the REAL Redis + Postgres + ASGI app (no mocks). Covers QA goal 10:

  * MIGRATION  — leads.close_reason exists; sweep fn returns the TABLE shape.
  * CLOCK FIX  — an inbound on a human/waiting chat bumps the active lead's
                 last_activity_at so it is NOT swept at 60 min; an idle lead IS.
  * ABANDON    — sweep flips idle in_progress → abandoned + close_reason +
                 PII-free funnel event + closes the Redis conversation; a NULL
                 conversation_id row does not crash the sweep.
  * COMPLETED  — a lead_completed turn stamps close_reason='completed' + closes.
  * ANSWERED   — owner PATCH closing a human/waiting chat stamps 'answered'.
  * UNREAD     — bot path + silent human path both increment; total summed;
                 GET /conversations/{id} resets to 0; reset wipes; TTL honored.
  * GREETING   — closed→reset→greeting + brand-new number greet (goal 7).
  * ISOLATION  — B cannot read A's close_reason / unread; keys are tenant-scoped;
                 sweep stays the single SECURITY DEFINER doorway; no PII leaks.

Every persisted row is is_test=true; the cleanup fixture deletes the test leads
and Redis conv keys it created. Nothing prints a secret, a token, or PII.
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
    abandoned_sweep,
    bot_runtime,
    conversation_state as cs,
    leads as leads_service,
)
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (published)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (draft)
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

IDLE_MIN = abandoned_sweep.ABANDONED_AFTER_MINUTES  # 60


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
        await cs.reset_conversation(rds, bid, cid)
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


async def _seed_lead(pool, business_id, *, status, conversation_id, idle_minutes=0):
    """Insert a minimal is_test lead with a given status, conv link, and age.

    idle_minutes pushes last_activity_at into the past so the sweep can act on it.
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
            VALUES ($1, $2, $3, true, $4,
                    now() - make_interval(mins => $5),
                    now() - make_interval(mins => $5))
            RETURNING id
            """,
            business_id, "test-flow", status, cache_chat_ref, idle_minutes,
        )
    return str(row["id"])


async def _fetch_lead(pool, business_id, lead_id):
    async with tenant_connection(pool, business_id) as conn:
        return await conn.fetchrow(
            "SELECT status, close_reason, is_test FROM leads "
            "WHERE id = $1 AND business_id = $2",
            lead_id, business_id,
        )


async def _events(pool, business_id, lead_id):
    async with tenant_connection(pool, business_id) as conn:
        rows = await conn.fetch(
            "SELECT event, step_index, is_test FROM flow_events "
            "WHERE lead_id = $1 AND business_id = $2",
            lead_id, business_id,
        )
    return rows


async def _set_lead_idle(pool, business_id, lead_id, minutes):
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            "UPDATE leads SET last_activity_at = now() - make_interval(mins => $3) "
            "WHERE id = $1 AND business_id = $2",
            lead_id, business_id, minutes,
        )


# ============================================================================
#  CHECK 1 — migration applied (column + sweep TABLE return shape)
# ============================================================================

@pytest.mark.asyncio
async def test_close_reason_column_exists(pool):
    async with pool.acquire() as conn:
        dt = await conn.fetchval(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name = 'leads' AND column_name = 'close_reason'"
        )
    assert dt == "text"


@pytest.mark.asyncio
async def test_sweep_fn_returns_table_shape_and_is_security_definer(pool):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT pg_get_function_result(oid) AS ret, prosecdef AS secdef "
            "FROM pg_proc WHERE proname = 'sweep_abandoned_leads'"
        )
    assert row["ret"] == "TABLE(lead_id uuid, conversation_id text)"
    assert row["secdef"] is True


# ============================================================================
#  CHECK 2 — the clock fix (THE key bug)
# ============================================================================

@pytest.mark.asyncio
async def test_inbound_on_human_chat_bumps_clock_not_abandoned(pool, rds, cleanup):
    """A human-handled chat: a fresh inbound resets the lead's clock, so a lead
    that WAS idle >60 min is no longer swept after the customer messages."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    # A lead in a 'human' conversation, idle for 120 min (would be swept).
    lead_id = await _seed_lead(pool, BIZ_A, status="in_progress",
                               conversation_id=conv, idle_minutes=120)
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_HUMAN)

    # Customer sends a new inbound on the silent human path → clock must bump.
    out = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "עוד שאלה", is_test=True)
    assert out["silent"] is True

    # Now run the sweep with the 60-min threshold: the lead is fresh → NOT swept.
    await abandoned_sweep.run_sweep_once(pool, rds)
    lead = await _fetch_lead(pool, BIZ_A, lead_id)
    assert lead["status"] == "in_progress"
    assert lead["close_reason"] is None


@pytest.mark.asyncio
async def test_inbound_on_waiting_chat_bumps_clock(pool, rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    lead_id = await _seed_lead(pool, BIZ_A, status="in_progress",
                               conversation_id=conv, idle_minutes=120)
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_WAITING)
    out = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "מישהו שם?", is_test=True)
    assert out["silent"] is True
    await abandoned_sweep.run_sweep_once(pool, rds)
    lead = await _fetch_lead(pool, BIZ_A, lead_id)
    assert lead["status"] == "in_progress"


@pytest.mark.asyncio
async def test_negative_control_idle_lead_is_abandoned(pool, rds, cleanup):
    """NEGATIVE CONTROL: an idle in_progress lead with NO new inbound for >60 min
    DOES get abandoned — proving the sweep still fires when it should."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    lead_id = await _seed_lead(pool, BIZ_A, status="in_progress",
                               conversation_id=conv, idle_minutes=120)
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_HUMAN)
    # No inbound — go straight to the sweep.
    n = await abandoned_sweep.run_sweep_once(pool, rds)
    assert n >= 1
    lead = await _fetch_lead(pool, BIZ_A, lead_id)
    assert lead["status"] == "abandoned"
    assert lead["close_reason"] == "abandoned"


# ============================================================================
#  CHECK 3 — abandon → close + reason + funnel + Redis close
# ============================================================================

@pytest.mark.asyncio
async def test_sweep_abandons_closes_redis_and_writes_funnel(pool, rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    lead_id = await _seed_lead(pool, BIZ_A, status="in_progress",
                               conversation_id=conv, idle_minutes=120)
    # Give it a live Redis conversation in 'human' (so the sweep must close it).
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_HUMAN)
    assert await cs.get_status(rds, BIZ_A, conv) == cs.STATUS_HUMAN

    await abandoned_sweep.run_sweep_once(pool, rds)

    # Lead flipped + close_reason stamped.
    lead = await _fetch_lead(pool, BIZ_A, lead_id)
    assert lead["status"] == "abandoned"
    assert lead["close_reason"] == "abandoned"
    # Redis conversation closed.
    assert await cs.get_status(rds, BIZ_A, conv) == cs.STATUS_CLOSED
    # PII-free 'abandoned' funnel event written under this tenant + is_test.
    events = await _events(pool, BIZ_A, lead_id)
    abandoned_evts = [e for e in events if e["event"] == "abandoned"]
    assert len(abandoned_evts) == 1
    assert abandoned_evts[0]["is_test"] is True


@pytest.mark.asyncio
async def test_sweep_null_conversation_does_not_crash(pool, rds, cleanup):
    """A lead with NO cache_chat_ref (NULL conversation_id) must be abandoned
    without the Redis-close loop crashing the pass."""
    lead_id = await _seed_lead(pool, BIZ_A, status="in_progress",
                               conversation_id=None, idle_minutes=120)
    # No cleanup conv to register; just clean the lead via the fixture's DELETE.
    cleanup.append((BIZ_A, "noop"))
    n = await abandoned_sweep.run_sweep_once(pool, rds)
    assert n >= 1
    lead = await _fetch_lead(pool, BIZ_A, lead_id)
    assert lead["status"] == "abandoned"
    assert lead["close_reason"] == "abandoned"


# ============================================================================
#  CHECK 4 — completed stamps close_reason + closes the chat
# ============================================================================

@pytest.mark.asyncio
async def test_completed_lead_stamps_completed_and_closes(pool, rds, http, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    # Drive Avi's quote flow to completion. The FIRST inbound on a never-seen
    # conversation is consumed by the greeting+menu open turn (commit 0dd58ad), so
    # we send a leading message, THEN pick flow 1 → name → phone → choice "רכב".
    for msg in ("שלום", "1", "דנה כהן", "052-1234567", "רכב"):
        await bot_runtime.run_turn(pool, rds, BIZ_A, conv, msg, is_test=True)

    # The conversation is now closed (next inbound would greet fresh).
    assert await cs.get_status(rds, BIZ_A, conv) == cs.STATUS_CLOSED

    # The newest lead for this conversation carries close_reason='completed'.
    async with tenant_connection(pool, BIZ_A) as conn:
        lead_id = await leads_service.get_active_lead_id_by_conversation(
            conn, BIZ_A, conv)
        # active id may be None (state cleared on close); fall back to ref lookup.
    async with tenant_connection(pool, BIZ_A) as conn:
        row = await conn.fetchrow(
            "SELECT status, close_reason FROM leads "
            "WHERE business_id = $1 AND cache_chat_ref = $2 "
            "ORDER BY last_activity_at DESC LIMIT 1",
            BIZ_A, f"conv:{BIZ_A}:{conv}",
        )
    assert row is not None
    assert row["close_reason"] == "completed"
    assert row["status"] == "new"


# ============================================================================
#  CHECK 5 — answered: owner manual close of a human/waiting chat
# ============================================================================

@pytest.mark.asyncio
async def test_owner_close_human_chat_stamps_answered(pool, rds, http, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    lead_id = await _seed_lead(pool, BIZ_A, status="in_progress",
                               conversation_id=conv, idle_minutes=0)
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_HUMAN)

    resp = await http.patch(f"/api/leads/{lead_id}/status",
                            json={"status": "closed"})
    assert resp.status_code == 200
    lead = await _fetch_lead(pool, BIZ_A, lead_id)
    assert lead["status"] == "closed"
    assert lead["close_reason"] == "answered"


@pytest.mark.asyncio
async def test_owner_close_non_human_chat_no_answered(pool, rds, http, cleanup):
    """Closing a lead whose chat is NOT human/waiting (e.g. bot) must NOT stamp
    'answered' — answered is reserved for the human-handling close."""
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    lead_id = await _seed_lead(pool, BIZ_A, status="in_progress",
                               conversation_id=conv, idle_minutes=0)
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_BOT)
    resp = await http.patch(f"/api/leads/{lead_id}/status",
                            json={"status": "closed"})
    assert resp.status_code == 200
    lead = await _fetch_lead(pool, BIZ_A, lead_id)
    assert lead["status"] == "closed"
    assert lead["close_reason"] is None


@pytest.mark.asyncio
async def test_owner_deal_does_not_stamp_close_reason(pool, rds, http, cleanup):
    """A 'deal' outcome is a pure owner outcome — close_reason stays untouched."""
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    lead_id = await _seed_lead(pool, BIZ_A, status="new",
                               conversation_id=conv, idle_minutes=0)
    resp = await http.patch(f"/api/leads/{lead_id}/status",
                            json={"status": "deal"})
    assert resp.status_code == 200
    lead = await _fetch_lead(pool, BIZ_A, lead_id)
    assert lead["status"] == "deal"
    assert lead["close_reason"] is None


# ============================================================================
#  CHECK 6 — unread counter
# ============================================================================

@pytest.mark.asyncio
async def test_unread_increments_bot_path(pool, rds, http, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    # Two inbound customer messages on the bot path.
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "שלום", is_test=True)
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "1", is_test=True)
    assert await cs.get_unread(rds, BIZ_A, conv) == 2


@pytest.mark.asyncio
async def test_unread_increments_silent_human_path(pool, rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    await _seed_lead(pool, BIZ_A, status="in_progress",
                     conversation_id=conv, idle_minutes=0)
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_HUMAN)
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "היי", is_test=True)
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "עוד הודעה", is_test=True)
    assert await cs.get_unread(rds, BIZ_A, conv) == 2


@pytest.mark.asyncio
async def test_unread_total_and_open_resets(pool, rds, http, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv1 = _new_conv()
    conv2 = _new_conv()
    cleanup.append((BIZ_A, conv1))
    cleanup.append((BIZ_A, conv2))
    # Baseline first — other tests in the same session may leave their own
    # unread keys in this tenant's index until their fixture teardown runs, so
    # we assert on the DELTA these two conversations contribute, not an absolute.
    base_total = (await http.get("/api/conversations")).json()["unread_total"]
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv1, "שלום", is_test=True)
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv2, "שלום", is_test=True)
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv2, "1", is_test=True)

    # GET /api/conversations returns the per-conversation unread counts, and the
    # total rose by exactly these two conversations' contribution (1 + 2 = 3).
    resp = await http.get("/api/conversations")
    assert resp.status_code == 200
    body = resp.json()
    by_id = {c["conversation_id"]: c["unread"] for c in body["conversations"]}
    assert by_id.get(conv1) == 1
    assert by_id.get(conv2) == 2
    assert body["unread_total"] == base_total + 3

    # Opening conv2 resets ITS counter to 0; conv1 untouched.
    detail = await http.get(f"/api/conversations/{conv2}")
    assert detail.status_code == 200
    assert await cs.get_unread(rds, BIZ_A, conv2) == 0
    assert await cs.get_unread(rds, BIZ_A, conv1) == 1
    # The total dropped by conv2's 2 (only conv1's 1 remains of our delta).
    resp2 = await http.get("/api/conversations")
    assert resp2.json()["unread_total"] == base_total + 1


@pytest.mark.asyncio
async def test_unread_key_wiped_by_reset(pool, rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "שלום", is_test=True)
    assert await cs.get_unread(rds, BIZ_A, conv) >= 1
    await cs.reset_conversation(rds, BIZ_A, conv)
    assert await rds.exists(cs._unread_key(BIZ_A, conv)) == 0
    assert await cs.get_unread(rds, BIZ_A, conv) == 0


@pytest.mark.asyncio
async def test_unread_ttl_persists_for_human_expires_for_bot(pool, rds, cleanup):
    conv_bot = _new_conv()
    conv_human = _new_conv()
    cleanup.append((BIZ_A, conv_bot))
    cleanup.append((BIZ_A, conv_human))
    # Bot chat: unread key has a finite sliding TTL.
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv_bot, "שלום", is_test=True)
    ttl_bot = await rds.ttl(cs._unread_key(BIZ_A, conv_bot))
    assert 0 < ttl_bot <= cs.CONVERSATION_TTL_SECONDS

    # Human chat: unread key persists (no expiry, ttl == -1).
    await _seed_lead(pool, BIZ_A, status="in_progress",
                     conversation_id=conv_human, idle_minutes=0)
    await cs.set_status(rds, BIZ_A, conv_human, cs.STATUS_HUMAN)
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv_human, "היי", is_test=True)
    assert await rds.ttl(cs._unread_key(BIZ_A, conv_human)) == -1


# ============================================================================
#  CHECK 7 — no-conversation → greeting (closed→reset; brand-new number)
# ============================================================================

@pytest.mark.asyncio
async def test_brand_new_number_greets(pool, rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    # An empty open-turn on a never-seen conversation → greeting + menu.
    out = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "", is_test=True)
    assert out["silent"] is False
    assert out["replies"]
    reply = out["replies"][0]
    assert "1" in reply  # the canonical numbered menu the engine appends


@pytest.mark.asyncio
async def test_closed_chat_resets_and_greets(pool, rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    # Open + pick a flow, then force closed.
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "", is_test=True)
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "1", is_test=True)
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_CLOSED)

    # A genuinely-fresh conversation gets the same first-turn reply for the same
    # inbound — proving the closed chat reset to a brand-new conversation.
    fresh = _new_conv()
    cleanup.append((BIZ_A, fresh))
    fresh_out = await bot_runtime.run_turn(pool, rds, BIZ_A, fresh, "שלום", is_test=True)
    out = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "שלום", is_test=True)
    assert out["replies"] == fresh_out["replies"]
    # The transcript was wiped + reseeded with just the new exchange.
    msgs = await cs.get_messages(rds, BIZ_A, conv)
    assert [m["role"] for m in msgs] == ["customer", "bot"]
    assert msgs[0]["body"] == "שלום"


# ============================================================================
#  CHECK 9 — security / isolation
# ============================================================================

@pytest.mark.asyncio
async def test_b_cannot_read_a_close_reason(pool, rds, http, cleanup):
    """B's GET /api/leads must never surface A's lead or its close_reason."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    a_lead = await _seed_lead(pool, BIZ_A, status="abandoned",
                              conversation_id=conv, idle_minutes=0)
    async with tenant_connection(pool, BIZ_A) as conn:
        await leads_service.set_lead_status(
            conn, BIZ_A, a_lead, "closed",
            close_reason=leads_service.CLOSE_REASON_ANSWERED)

    # B logs in and lists leads — A's lead must not appear.
    await _login(rds, http, BELLA_USER, BIZ_B)
    resp = await http.get("/api/leads?include_test=true&status=closed")
    assert resp.status_code == 200
    ids = {l["id"] for l in resp.json()["leads"]}
    assert a_lead not in ids

    # And a direct RLS read as B returns nothing for A's id.
    async with tenant_connection(pool, BIZ_B) as conn:
        assert await conn.fetchrow(
            "SELECT id FROM leads WHERE id = $1", a_lead) is None


@pytest.mark.asyncio
async def test_unread_total_is_tenant_scoped(pool, rds, http, cleanup):
    """A's inbound must not show up in B's unread_total."""
    conv_a = _new_conv()
    cleanup.append((BIZ_A, conv_a))
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv_a, "שלום", is_test=True)
    assert await cs.get_unread(rds, BIZ_A, conv_a) >= 1

    await _login(rds, http, BELLA_USER, BIZ_B)
    resp = await http.get("/api/conversations")
    body = resp.json()
    assert conv_a not in {c["conversation_id"] for c in body["conversations"]}
    # B's total counts only B's conversations (A's conv_a not included).
    assert body["unread_total"] == await cs.unread_total(rds, BIZ_B)


@pytest.mark.asyncio
async def test_unread_key_rejects_cross_tenant():
    """The unread key guard fires for a forged cross-tenant key."""
    with pytest.raises(cs.CrossTenantConversationError):
        cs._assert_owns(BIZ_A, cs._unread_key(BIZ_B, "someconv"))
    # And accepts a correctly-prefixed unread key (no raise).
    cs._assert_owns(BIZ_A, cs._unread_key(BIZ_A, "someconv"))


@pytest.mark.asyncio
async def test_app_role_cannot_call_sweep_outside_grant(pool):
    """app_role CAN execute the sweep (the single SD doorway) — but the function
    is SECURITY DEFINER and only app_role/owner hold EXECUTE; PUBLIC has none."""
    async with pool.acquire() as conn:
        grantees = await conn.fetch(
            "SELECT grantee FROM information_schema.role_routine_grants "
            "WHERE routine_name = 'sweep_abandoned_leads'"
        )
    names = {g["grantee"] for g in grantees}
    assert "app_role" in names
    assert "PUBLIC" not in names


@pytest.mark.asyncio
async def test_app_role_cannot_bypass_rls_on_leads(pool):
    """Confirm RLS is still FORCED: app_role with A's context cannot read B rows.

    Seed a B lead, then with A's app.business_id context a direct SELECT for B's
    id returns nothing — RLS is not bypassable by the app role.
    """
    b_lead = await _seed_lead(pool, BIZ_B, status="new",
                              conversation_id=None, idle_minutes=0)
    try:
        async with tenant_connection(pool, BIZ_A) as conn:
            row = await conn.fetchrow("SELECT id FROM leads WHERE id = $1", b_lead)
        assert row is None
    finally:
        async with tenant_connection(pool, BIZ_B) as conn:
            await conn.execute(
                "DELETE FROM leads WHERE id = $1 AND business_id = $2", b_lead, BIZ_B)
