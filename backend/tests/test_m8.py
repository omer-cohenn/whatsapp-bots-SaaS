"""M8 — in-app human-handoff chat, strict pytest (the CI version).

m8_full_test.py is the narrated story; THIS is the strict gate CI runs. It mixes
two layers:

  * the SERVICE layer (`conversation_state` + `bot_runtime`) directly against the
    real Redis + Postgres — the cheapest place to prove the transcript model,
    the LTRIM-200 trim, tenant isolation on the `:log` key, the bot's silence in
    'waiting' AND 'human', and the handoff funnel event; and
  * the API layer in-process against the real ASGI app over httpx ASGITransport —
    so the deny-by-default `/api` gate, the session dependency, and
    tenant_connection/RLS are all real for the GET conversation-detail /messages
    endpoints and the cross-tenant 404/empty check.

Everything seeded here is is_test=true or uses throwaway conv ids; the cleanup
fixture deletes those leads + the Redis conv keys it created. Nothing prints a
secret, a token, or PII.
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
    """After each test: drop the conv keys we made + any is_test leads."""
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


# ============================================================================
#  SERVICE: append_message + get_messages — order, roles, trim, isolation
# ============================================================================

@pytest.mark.asyncio
async def test_append_and_get_messages_in_order_and_roles(rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))

    await cs.append_message(rds, BIZ_A, conv, "customer", "שלום")
    await cs.append_message(rds, BIZ_A, conv, "bot", "היי, איך אפשר לעזור?")
    await cs.append_message(rds, BIZ_A, conv, "owner", "אני הנציג, מדבר")

    msgs = await cs.get_messages(rds, BIZ_A, conv)
    assert [m["role"] for m in msgs] == ["customer", "bot", "owner"]
    assert [m["body"] for m in msgs] == [
        "שלום", "היי, איך אפשר לעזור?", "אני הנציג, מדבר",
    ]
    # Every line carries an `at` timestamp.
    assert all(m.get("at") for m in msgs)


@pytest.mark.asyncio
async def test_append_message_rejects_bad_role(rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    with pytest.raises(ValueError):
        await cs.append_message(rds, BIZ_A, conv, "hacker", "x")
    # Nothing was written.
    assert await cs.get_messages(rds, BIZ_A, conv) == []


@pytest.mark.asyncio
async def test_transcript_trimmed_to_200(rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    # Push 250 lines; only the last 200 should survive (LTRIM bound).
    for i in range(250):
        await cs.append_message(rds, BIZ_A, conv, "customer", f"m{i}")

    msgs = await cs.get_messages(rds, BIZ_A, conv)
    assert len(msgs) == cs.TRANSCRIPT_MAX == 200
    # The oldest kept is m50, the newest m249 (the first 50 rolled off).
    assert msgs[0]["body"] == "m50"
    assert msgs[-1]["body"] == "m249"


@pytest.mark.asyncio
async def test_transcript_tenant_isolated_service_layer(rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    cleanup.append((BIZ_B, conv))  # same id, different tenant
    await cs.append_message(rds, BIZ_A, conv, "customer", "סוד-של-אבי")

    # B asking for the SAME conversation id sees nothing — different key.
    assert await cs.get_messages(rds, BIZ_B, conv) == []
    # A still sees its own.
    a_msgs = await cs.get_messages(rds, BIZ_A, conv)
    assert len(a_msgs) == 1 and a_msgs[0]["body"] == "סוד-של-אבי"


@pytest.mark.asyncio
async def test_forged_key_prefix_rejected(rds, cleanup):
    # A hand-built id that tries to escape its prefix can't reach another tenant:
    # the key is always derived from the verified business_id, so _assert_owns on
    # the derived key always matches. Prove the guard fires on a mismatched key.
    with pytest.raises(cs.CrossTenantConversationError):
        cs._assert_owns(BIZ_A, f"conv:{BIZ_B}:whatever:log")


# ============================================================================
#  SERVICE: status transitions + bot SILENCE in waiting AND human
# ============================================================================

@pytest.mark.asyncio
async def test_status_transitions_bot_waiting_human_closed(rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    for st in (cs.STATUS_BOT, cs.STATUS_WAITING, cs.STATUS_HUMAN, cs.STATUS_CLOSED):
        await cs.set_status(rds, BIZ_A, conv, st)
        assert await cs.get_status(rds, BIZ_A, conv) == st
    # An invalid status is rejected loudly.
    with pytest.raises(ValueError):
        await cs.set_status(rds, BIZ_A, conv, "nonsense")


@pytest.mark.asyncio
async def test_bot_silent_in_waiting_but_still_logs_customer(pool, rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_WAITING)

    result = await bot_runtime.run_turn(
        pool, rds, BIZ_A, conv, "אני עדיין מחכה", is_test=True)
    assert result["silent"] is True
    assert result["replies"] == []

    # The customer message IS still on the transcript (role=customer).
    msgs = await cs.get_messages(rds, BIZ_A, conv)
    assert any(m["role"] == "customer" and m["body"] == "אני עדיין מחכה" for m in msgs)
    # The bot said nothing → no bot line was appended for this turn.
    assert not any(m["role"] == "bot" for m in msgs)


@pytest.mark.asyncio
async def test_bot_silent_in_human_but_still_logs_customer(pool, rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_HUMAN)

    result = await bot_runtime.run_turn(
        pool, rds, BIZ_A, conv, "שאלה נוספת ללקוח", is_test=True)
    assert result["silent"] is True
    assert result["replies"] == []

    msgs = await cs.get_messages(rds, BIZ_A, conv)
    assert any(m["role"] == "customer" and m["body"] == "שאלה נוספת ללקוח" for m in msgs)
    assert not any(m["role"] == "bot" for m in msgs)


@pytest.mark.asyncio
async def test_bot_answers_and_logs_both_roles_when_status_bot(pool, rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    # No status set yet → defaults to bot driving → it should answer the menu.
    result = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "שלום", is_test=True)
    assert result["silent"] is False
    assert result["replies"]  # the bot greeted / showed the menu

    msgs = await cs.get_messages(rds, BIZ_A, conv)
    assert msgs[0]["role"] == "customer" and msgs[0]["body"] == "שלום"
    assert any(m["role"] == "bot" for m in msgs)


# ============================================================================
#  SERVICE: handoff → status 'waiting' + a 'handed_off' funnel event
# ============================================================================

@pytest.mark.asyncio
async def test_handoff_sets_waiting_and_logs_funnel_event(pool, rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))

    # Drive the bot to a human-handoff. Avi's menu offers "דבר עם נציג" as an
    # option; we discover which input triggers it by reading the live config-driven
    # menu, then send the handoff keyword the engine recognises.
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "שלום", is_test=True)
    # The engine recognises a handoff keyword; "נציג" is the canonical request.
    result = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "נציג", is_test=True)

    # If this tenant's config routes the handoff, status flips to waiting AND a
    # handed_off event is logged. (We assert on the event the runtime logs.)
    assert result["event"] == "handed_off", (
        "expected a handoff; engine returned event=%r" % result["event"])
    assert await cs.get_status(rds, BIZ_A, conv) == cs.STATUS_WAITING

    async with tenant_connection(pool, BIZ_A) as conn:
        n = await conn.fetchval(
            "SELECT count(*)::int FROM flow_events "
            "WHERE business_id=$1 AND event=$2 AND is_test=true",
            BIZ_A, leads_service.EVENT_HANDOFF)
    assert n >= 1


@pytest.mark.asyncio
async def test_bot_goes_silent_on_turn_after_handoff(pool, rds, cleanup):
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "שלום", is_test=True)
    handoff = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "נציג", is_test=True)
    assert handoff["event"] == "handed_off"
    # The NEXT customer message must be silent (status is now 'waiting').
    after = await bot_runtime.run_turn(
        pool, rds, BIZ_A, conv, "עוד הודעה אחרי הבקשה", is_test=True)
    assert after["silent"] is True and after["replies"] == []


# ============================================================================
#  API: GET /api/conversations/{id} (+ linked lead) and .../messages
# ============================================================================

async def _sim(http, conv_id, msg):
    return (await http.post(
        "/api/bot/sim", json={"message": msg, "conversation_id": conv_id})).json()


@pytest.mark.asyncio
async def test_get_conversation_detail_returns_status_lead_messages(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    # Drive Avi's quote flow to completion so a linked lead exists.
    await _sim(http, conv, "1")
    await _sim(http, conv, "דנה כהן")
    await _sim(http, conv, "052-1234567")
    await _sim(http, conv, "1")

    detail = (await http.get(f"/api/conversations/{conv}")).json()
    assert detail["conversation_id"] == conv
    assert detail["status"] in ("bot", "waiting", "human", "closed")
    # A linked lead is present and decrypted for the owner.
    assert detail["lead"] is not None
    assert detail["lead"]["contact_name"] == "דנה כהן"
    # The transcript carries both customer and bot lines, oldest first.
    roles = [m["role"] for m in detail["messages"]]
    assert "customer" in roles and "bot" in roles


@pytest.mark.asyncio
async def test_get_messages_endpoint_returns_log(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    await _sim(http, conv, "שלום")

    body = (await http.get(f"/api/conversations/{conv}/messages")).json()
    assert body["conversation_id"] == conv
    assert body["messages"]
    assert body["messages"][0]["role"] == "customer"
    assert body["messages"][0]["body"] == "שלום"


@pytest.mark.asyncio
async def test_reply_endpoint_appends_owner_to_transcript(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    await _sim(http, conv, "שלום")
    # Owner takes over and replies.
    await http.post(f"/api/conversations/{conv}/status", json={"status": "human"})
    text = "שלום, אני הנציג ואשמח לעזור"
    r = await http.post(f"/api/conversations/{conv}/reply", json={"text": text})
    assert r.json()["queued"] is True

    msgs = (await http.get(f"/api/conversations/{conv}/messages")).json()["messages"]
    assert any(m["role"] == "owner" and m["body"] == text for m in msgs)


@pytest.mark.asyncio
async def test_status_endpoint_accepts_waiting(http, rds, cleanup):
    await _login(rds, http, AVI_USER, BIZ_A)
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    await _sim(http, conv, "שלום")
    r = await http.post(f"/api/conversations/{conv}/status", json={"status": "waiting"})
    assert r.status_code == 200
    assert r.json()["status"] == "waiting"
    assert await cs.get_status(rds, BIZ_A, conv) == "waiting"


# ============================================================================
#  API: the gate — these M8 doors are 401 without a session
# ============================================================================

@pytest.mark.asyncio
async def test_m8_routes_require_session(http):
    assert (await http.get("/api/conversations/x")).status_code == 401
    assert (await http.get("/api/conversations/x/messages")).status_code == 401


# ============================================================================
#  API: TENANT ISOLATION — A cannot read B's conversation detail/messages
# ============================================================================

@pytest.mark.asyncio
async def test_isolation_conversation_detail_and_messages(http, lifespan_app, rds, cleanup):
    # Bella seeds a real conversation with a secret line on a SEPARATE client.
    transport = ASGITransport(app=lifespan_app, raise_app_exceptions=False)
    b_conv = _new_conv()
    cleanup.append((BIZ_B, b_conv))
    async with AsyncClient(transport=transport, base_url="http://test") as bhttp:
        await _login(rds, bhttp, BELLA_USER, BIZ_B)
        await _sim(bhttp, b_conv, "סוד-של-בלה-1234")
        # Bella herself CAN read it.
        bella_detail = (await bhttp.get(f"/api/conversations/{b_conv}")).json()
        assert bella_detail["messages"]

    # Avi, logged into BIZ_A, asks for Bella's conversation id by hand.
    await _login(rds, http, AVI_USER, BIZ_A)
    avi_detail = (await http.get(f"/api/conversations/{b_conv}")).json()
    avi_msgs = (await http.get(f"/api/conversations/{b_conv}/messages")).json()

    # Avi gets an EMPTY conversation under his own (A) namespace — never Bella's
    # transcript, lead, or non-default status.
    assert avi_detail["messages"] == []
    assert avi_detail["lead"] is None
    assert avi_detail["status"] == "bot"  # default; Bella's real status not leaked
    assert avi_msgs["messages"] == []
    # Bella's secret never appears anywhere in Avi's responses.
    blob = json.dumps(avi_detail, ensure_ascii=False) + json.dumps(avi_msgs, ensure_ascii=False)
    assert "סוד-של-בלה-1234" not in blob
