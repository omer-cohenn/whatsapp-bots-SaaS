"""M5 (part B) — the lead-memory RUNTIME, strict pytest (the CI version).

m5_full_test.py + test_bot_tryme.py cover the no-save "try-me" sandbox. THIS
suite covers the OTHER half of M5: the real `bot_runtime` that PERSISTS — leads,
funnel events, encryption at rest, handoff-silence, the abandoned sweep — and
proves the tenant wall holds for all of it.

It runs IN-PROCESS against the real ASGI app over httpx ASGITransport (so the
deny-by-default /api gate, the session dependency, and tenant_connection/RLS are
all real) and also calls bot_runtime.run_turn / abandoned_sweep directly where a
test needs exact control of Redis state.

Every persisted row here is is_test=true, and the fixtures delete the test leads
they create. Nothing prints a secret, a token, or PII.
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

from app.core import crypto
from app.db.session import tenant_connection
from app.main import app
from app.services import abandoned_sweep, bot_runtime, conversation_state
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"

CUST_NAME = "דנה הבודקת"
CUST_PHONE = "052-1234567"
CUST_PHONE_DIGITS = "0521234567"
CUST_CHOICE_TEXT = "רכב"  # option #1 in Avi's seeded insurance_type step


# --- fixtures ---------------------------------------------------------------

@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=3)
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
async def cleanup_test_leads(pool):
    """Delete every is_test lead in BIZ_A after the test (events cascade)."""
    yield
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute(
            "DELETE FROM leads WHERE business_id = $1 AND is_test = true", BIZ_A
        )


@pytest_asyncio.fixture
async def lifespan_app():
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def http(lifespan_app):
    transport = ASGITransport(app=lifespan_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def _login(rds, user_id: str, business_id: str) -> str:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": f"{user_id}@example.com", "name": user_id,
        "picture": "", "business_id": business_id, "business_name": "x",
        "created_at": int(time.time()),
    }
    await rds.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    return sid


async def _fetch_lead(pool, business_id: str, lead_id: str):
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            "SELECT * FROM leads WHERE id = $1 AND business_id = $2",
            lead_id, business_id,
        )
    return dict(row) if row else None


async def _events(pool, business_id: str, lead_id: str):
    async with tenant_connection(pool, business_id) as conn:
        rows = await conn.fetch(
            "SELECT event FROM flow_events WHERE business_id = $1 AND lead_id = $2 "
            "ORDER BY created_at, id",
            business_id, lead_id,
        )
    return [r["event"] for r in rows]


def _answers_obj(raw):
    return raw if isinstance(raw, dict) else json.loads(raw)


# --- the gate ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_sim_requires_login(http):
    resp = await http.post("/api/bot/sim", json={"message": "1"})
    assert resp.status_code == 401


# --- the full lead lifecycle via /api/bot/sim --------------------------------

@pytest.mark.asyncio
async def test_lead_lifecycle_and_encryption(http, rds, pool, cleanup_test_leads):
    sid = await _login(rds, AVI_USER, BIZ_A)
    http.cookies.set(SESSION_COOKIE_NAME, sid)
    try:
        # start the flow → a fresh in_progress test lead + 'started'
        r = (await http.post("/api/bot/sim", json={"message": "1"})).json()
        conv = r["conversation_id"]
        lead_id = r["lead_id"]
        assert lead_id is not None
        lead = await _fetch_lead(pool, BIZ_A, lead_id)
        assert lead["status"] == "in_progress"
        assert lead["is_test"] is True
        assert lead["lead_name"] == "quote"
        assert lead["submitted_at"] is None
        assert await _events(pool, BIZ_A, lead_id) == ["started"]

        # answer name + phone → same lead grows, two 'step' events
        r2 = (await http.post("/api/bot/sim",
                              json={"message": CUST_NAME, "conversation_id": conv})).json()
        r3 = (await http.post("/api/bot/sim",
                              json={"message": CUST_PHONE, "conversation_id": conv})).json()
        assert r2["lead_id"] == lead_id and r3["lead_id"] == lead_id
        mid = await _fetch_lead(pool, BIZ_A, lead_id)
        assert mid["status"] == "in_progress"
        assert await _events(pool, BIZ_A, lead_id) == ["started", "step", "step"]

        # PII at rest is ciphertext, not plaintext — and round-trips with our key
        ans = _answers_obj(mid["answers"])
        blob = json.dumps(ans, ensure_ascii=False)
        assert mid["phone"] and CUST_PHONE_DIGITS not in mid["phone"]
        assert mid["contact_name"] and CUST_NAME not in mid["contact_name"]
        assert CUST_NAME not in blob and CUST_PHONE_DIGITS not in blob
        assert set(ans.keys()) == {"_"}
        assert crypto.decrypt_pii(mid["phone"]) == CUST_PHONE_DIGITS
        assert crypto.decrypt_pii(mid["contact_name"]) == CUST_NAME
        dec = crypto.decrypt_answers(ans)
        assert dec["phone"] == CUST_PHONE_DIGITS and dec["full_name"] == CUST_NAME

        # finish → status 'new' + submitted_at + 'completed'
        r4 = (await http.post("/api/bot/sim",
                              json={"message": "1", "conversation_id": conv})).json()
        assert r4["event"] == "lead_completed"
        done = await _fetch_lead(pool, BIZ_A, lead_id)
        assert done["status"] == "new"
        assert done["submitted_at"] is not None
        assert await _events(pool, BIZ_A, lead_id) == [
            "started", "step", "step", "completed"
        ]
        assert crypto.decrypt_answers(_answers_obj(done["answers"]))[
            "insurance_type"] == CUST_CHOICE_TEXT
    finally:
        await rds.delete(f"{_SESSION_KEY_PREFIX}{sid}")


# --- handoff silence ---------------------------------------------------------

@pytest.mark.asyncio
async def test_handoff_sets_human_and_bot_goes_silent(rds, pool, cleanup_test_leads):
    conv = f"sim:{secrets.token_hex(8)}"
    try:
        ho = await bot_runtime.run_turn(pool, rds, BIZ_A, conv,
                                        "אני רוצה לדבר עם נציג", is_test=True)
        assert ho["event"] == "handed_off"
        status = await conversation_state.get_status(rds, BIZ_A, conv)
        assert status == conversation_state.STATUS_HUMAN

        nxt = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "שלום?", is_test=True)
        assert nxt["silent"] is True
        assert nxt["replies"] == []
        assert nxt["event"] is None
    finally:
        await conversation_state.clear_state(rds, BIZ_A, conv)


# --- abandoned sweep ---------------------------------------------------------

@pytest.mark.asyncio
async def test_abandoned_sweep_flips_idle_lead(rds, pool, cleanup_test_leads):
    conv = f"sim:{secrets.token_hex(8)}"
    try:
        started = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "1", is_test=True)
        lead_id = started["lead_id"]
        assert lead_id is not None
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.execute(
                "UPDATE leads SET last_activity_at = now() - interval '120 minutes' "
                "WHERE id = $1 AND business_id = $2",
                lead_id, BIZ_A,
            )
        n = await abandoned_sweep.run_sweep_once(pool)
        assert n >= 1
        lead = await _fetch_lead(pool, BIZ_A, lead_id)
        assert lead["status"] == "abandoned"
        assert lead["is_test"] is True
        assert "abandoned" in await _events(pool, BIZ_A, lead_id)
    finally:
        await conversation_state.clear_state(rds, BIZ_A, conv)


# --- tenant isolation --------------------------------------------------------

@pytest.mark.asyncio
async def test_business_b_cannot_read_or_write_a_lead(rds, pool, cleanup_test_leads):
    conv = f"sim:{secrets.token_hex(8)}"
    try:
        started = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "1", is_test=True)
        lead_id = started["lead_id"]

        # B cannot read A's lead, even naming A's id / business_id explicitly.
        async with tenant_connection(pool, BIZ_B) as conn:
            assert await conn.fetchrow("SELECT id FROM leads WHERE id = $1", lead_id) is None
            assert await conn.fetchrow(
                "SELECT id FROM leads WHERE id = $1 AND business_id = $2", lead_id, BIZ_A
            ) is None
            # B cannot write A's lead either (RLS → 0 rows touched).
            res = await conn.execute(
                "UPDATE leads SET status = 'new' WHERE id = $1", lead_id
            )
        assert res.strip().endswith(" 0")
        still = await _fetch_lead(pool, BIZ_A, lead_id)
        assert still["status"] == "in_progress"
    finally:
        await conversation_state.clear_state(rds, BIZ_A, conv)


@pytest.mark.asyncio
async def test_sim_is_scoped_to_caller_only(http, rds, pool, cleanup_test_leads):
    sid = await _login(rds, AVI_USER, BIZ_A)
    http.cookies.set(SESSION_COOKIE_NAME, sid)
    try:
        async def count(bid):
            async with tenant_connection(pool, bid) as conn:
                return await conn.fetchval(
                    "SELECT count(*) FROM leads WHERE business_id = $1", bid
                )
        b_before = await count(BIZ_B)
        r = (await http.post("/api/bot/sim", json={"message": "1"})).json()
        new_lead = await _fetch_lead(pool, BIZ_A, r["lead_id"])
        assert new_lead is not None
        assert str(new_lead["business_id"]) == BIZ_A
        assert await count(BIZ_B) == b_before
    finally:
        await rds.delete(f"{_SESSION_KEY_PREFIX}{sid}")
