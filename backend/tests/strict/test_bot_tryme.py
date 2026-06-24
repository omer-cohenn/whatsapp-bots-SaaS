"""M5 — the "try-me" test chat, strict pytest (the CI version).

M4 let an owner DESIGN their bot. M5 lets the owner TRY it like a customer, in a
sandbox that NEVER writes anything. Two halves:

  * The PURE engine (`app.services.bot_engine`) — no DB/network/AI/clock/state.
    We assert EVERY branch deterministically with a hand-built config: the open
    menu; flow pick by number AND by label; text/phone/email/choice validation
    (good + bad); full lead completion → event 'lead_completed' + the exact
    collected lead; the human-handoff keyword AND a handoff flow → 'handed_off';
    the paused-after-handoff note; a booking flow → 'booking' with the demo link;
    the exact menu keyword '0' returning to the menu from inside a flow; the
    mandatory menu-hint footer on in-flow questions only; and that the engine
    mutates none of its inputs and reveals nothing but this chat's own answers.

  * The ENDPOINT POST /api/bot/tryme — runs IN-PROCESS against the real ASGI app
    over httpx ASGITransport (so the deny-by-default `/api` gate, the session
    dependency, and `tenant_connection`/RLS are all real). We assert: 401 without
    a session; the run is tenant-scoped to the caller's OWN seeded config; and a
    WHOLE simulated lead conversation leaves bot_builder_messages AND leads row
    counts unchanged (try-me persists NOTHING).

Nothing here prints a secret, a token, or PII.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from contextlib import asynccontextmanager

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import bot_engine
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (published bot)
AVI_USER = "google-sub-avi"


# ============================================================================
#  PART A — the PURE engine (no fixtures, no I/O at all)
# ============================================================================

# A hand-built config with one of every step type + each flow type.
SETTINGS = {
    "bot_profile": {
        "name": "בוט בדיקה",
        "system_prompt": "עזור.",
        "greeting": "שלום מהבוט!",
        "escalation_message": "מעביר לנציג…",
        "menu_keywords": ["תפריט", "menu", "0"],
    },
    "lead_steps": {
        "signup": {
            "label": "הרשמה",
            "flow_type": "lead",
            "message": "תודה! קיבלנו הכל.",
            "steps": [
                {"key": "full_name", "question": "מה השם?", "type": "text", "required": True},
                {"key": "phone", "question": "טלפון?", "type": "phone", "required": True,
                 "error_message": "טלפון לא תקין."},
                {"key": "email", "question": "אימייל?", "type": "email", "required": True},
                {"key": "topic", "question": "נושא?", "type": "choice", "required": True,
                 "options": ["רכב", "דירה"]},
            ],
        },
        "talk_to_human": {
            "label": "דברו עם נציג",
            "flow_type": "human_handoff",
            "message": "מעביר לנציג אנושי.",
            "steps": [],
        },
        "book": {
            "label": "קביעת תור",
            "flow_type": "booking",
            "message": "לקביעת תור: {link}",
            "steps": [],
        },
    },
    "handoff_keywords": ["נציג", "agent"],
    "is_published": True,
}


def _open():
    return bot_engine.advance(SETTINGS, bot_engine.initial_state(), "")


def test_open_turn_greeting_and_menu():
    r = _open()
    text = r["replies"][0]
    assert r["event"] is None and r["lead"] is None
    assert r["state"]["phase"] == "menu"
    assert "שלום מהבוט" in text
    assert "1. הרשמה" in text and "2. דברו עם נציג" in text and "3. קביעת תור" in text


def test_pick_flow_by_number():
    r = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "1")
    assert r["state"]["phase"] == "in_flow"
    assert r["state"]["active_flow"] == "signup"
    assert r["state"]["step_index"] == 0
    assert "מה השם?" in r["replies"][0]


def test_pick_flow_by_label():
    r = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "דברו עם נציג")
    assert r["event"] == "handed_off"
    assert r["state"]["phase"] == "handed_off"


def test_text_step_validation_good_and_bad():
    start = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "1")
    # A blank/whitespace message is the "open" turn by design → back to the menu;
    # the empty required answer is NOT stored.
    bad = bot_engine.advance(SETTINGS, start["state"], "   ")
    assert bad["state"]["phase"] == "menu"
    assert bad["state"]["active_flow"] is None
    assert bad["state"]["collected"] == {}
    # A real name is kept and advances to the next step.
    good = bot_engine.advance(SETTINGS, start["state"], "דנה")
    assert good["state"]["step_index"] == 1
    assert good["state"]["collected"]["full_name"] == "דנה"


def test_phone_step_validation_good_and_bad():
    st = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "1")["state"]
    st = bot_engine.advance(SETTINGS, st, "דנה")["state"]  # now at phone
    bad = bot_engine.advance(SETTINGS, st, "12")
    assert bad["state"]["step_index"] == 1
    assert "טלפון לא תקין" in bad["replies"][0]
    good = bot_engine.advance(SETTINGS, st, "050-123-4567")
    assert good["state"]["step_index"] == 2
    assert good["state"]["collected"]["phone"] == "0501234567"  # digits only


def test_email_step_validation_good_and_bad():
    st = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "1")["state"]
    st = bot_engine.advance(SETTINGS, st, "דנה")["state"]
    st = bot_engine.advance(SETTINGS, st, "0501234567")["state"]  # now at email
    bad = bot_engine.advance(SETTINGS, st, "not-an-email")
    assert bad["state"]["step_index"] == 2
    good = bot_engine.advance(SETTINGS, st, "dana@example.com")
    assert good["state"]["step_index"] == 3
    assert good["state"]["collected"]["email"] == "dana@example.com"


def test_choice_step_validation_number_and_text_and_bad():
    st = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "1")["state"]
    st = bot_engine.advance(SETTINGS, st, "דנה")["state"]
    st = bot_engine.advance(SETTINGS, st, "0501234567")["state"]
    st = bot_engine.advance(SETTINGS, st, "dana@example.com")["state"]  # at choice
    bad = bot_engine.advance(SETTINGS, st, "9")  # out of range
    assert bad["state"]["step_index"] == 3
    by_num = bot_engine.advance(SETTINGS, st, "1")
    assert by_num["event"] == "lead_completed" and by_num["lead"]["topic"] == "רכב"
    by_txt = bot_engine.advance(SETTINGS, st, "דירה")
    assert by_txt["event"] == "lead_completed" and by_txt["lead"]["topic"] == "דירה"


def test_full_lead_completion_event_and_collected():
    st = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "1")["state"]
    st = bot_engine.advance(SETTINGS, st, "דנה כהן")["state"]
    st = bot_engine.advance(SETTINGS, st, "050-123-4567")["state"]
    st = bot_engine.advance(SETTINGS, st, "dana@example.com")["state"]
    done = bot_engine.advance(SETTINGS, st, "1")
    assert done["event"] == "lead_completed"
    assert done["lead"] == {
        "full_name": "דנה כהן",
        "phone": "0501234567",
        "email": "dana@example.com",
        "topic": "רכב",
    }
    assert done["state"]["phase"] == "menu"
    assert "תודה! קיבלנו הכל" in done["replies"][0]


def test_handoff_keyword_anywhere():
    r = bot_engine.advance(SETTINGS, bot_engine.initial_state(),
                           "אפשר לדבר עם נציג בבקשה")
    assert r["event"] == "handed_off"
    assert r["state"]["phase"] == "handed_off"


def test_select_handoff_flow_from_menu():
    r = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "2")
    assert r["event"] == "handed_off"
    assert "מעביר לנציג אנושי" in r["replies"][0]


def test_paused_after_handoff():
    handed = {"phase": "handed_off", "active_flow": None,
              "step_index": 0, "collected": {}}
    r = bot_engine.advance(SETTINGS, handed, "שלום?")
    assert r["event"] is None
    assert r["state"]["phase"] == "handed_off"
    assert "הועברה לנציג" in r["replies"][0]


def test_select_booking_flow_gives_demo_link():
    r = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "3")
    assert r["event"] == "booking"
    assert "https://example.com/book/demo" in r["replies"][0]
    assert "{link}" not in r["replies"][0]
    assert r["state"]["phase"] == "menu"


def test_return_to_menu_keyword_from_inside_flow():
    st = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "1")["state"]
    st = bot_engine.advance(SETTINGS, st, "דנה")["state"]  # mid-flow at phone
    r = bot_engine.advance(SETTINGS, st, "0")  # exact menu keyword
    assert r["state"]["phase"] == "menu"
    assert r["state"]["active_flow"] is None
    assert "1. הרשמה" in r["replies"][0]


def test_menu_hint_footer_on_in_flow_questions_only():
    in_flow = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "1")
    menu = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "")
    handoff = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "2")
    booking = bot_engine.advance(SETTINGS, bot_engine.initial_state(), "3")
    assert in_flow["replies"][0].endswith(bot_engine.MENU_HINT)
    assert not menu["replies"][0].endswith(bot_engine.MENU_HINT)
    assert not handoff["replies"][0].endswith(bot_engine.MENU_HINT)
    assert not booking["replies"][0].endswith(bot_engine.MENU_HINT)


def test_engine_is_pure_no_mutation_no_foreign_data():
    settings_snapshot = json.loads(json.dumps(SETTINGS))
    state_in = {"phase": "in_flow", "active_flow": "signup", "step_index": 3,
                "collected": {"full_name": "דנה", "phone": "0501234567",
                              "email": "dana@example.com"}}
    state_snapshot = json.loads(json.dumps(state_in))
    out = bot_engine.advance(SETTINGS, state_in, "1")
    # inputs untouched (pure: no in-place mutation)
    assert SETTINGS == settings_snapshot
    assert state_in == state_snapshot
    # the lead is ONLY this chat's own answers — nothing foreign
    assert out["event"] == "lead_completed"
    assert set(out["lead"]) == {"full_name", "phone", "email", "topic"}


# ============================================================================
#  PART B — the /api/bot/tryme endpoint (needs the running stack)
# ============================================================================


@asynccontextmanager
async def _lifespan_app():
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def client():
    async with _lifespan_app():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def redis_client():
    c = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    yield c
    await c.aclose()


@pytest_asyncio.fixture
async def app_pool():
    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=2)
    yield pool
    await pool.close()


async def _inject_session(redis: aioredis.Redis, user_id: str, business_id: str,
                          business_name: str) -> str:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": f"{user_id}@example.com", "name": user_id,
        "picture": "", "business_id": business_id, "business_name": business_name,
        "created_at": int(time.time()),
    }
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    return sid


async def _count(pool, table: str, business_id: str) -> int:
    async with tenant_connection(pool, business_id) as conn:
        return await conn.fetchval(
            f"SELECT count(*) FROM {table} WHERE business_id = $1", business_id
        )


@pytest.mark.asyncio
async def test_tryme_requires_a_session(client: AsyncClient):
    """No login cookie → 401 (try-me sits behind the same wall as everything)."""
    resp = await client.post("/api/bot/tryme", json={"message": ""})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_tryme_runs_callers_own_config(
    client: AsyncClient, redis_client: aioredis.Redis
):
    """Logged-in Avi opens try-me → sees HIS own seeded bot (greeting + flows)."""
    sid = await _inject_session(redis_client, AVI_USER, BIZ_A, "Avi Insurance")
    client.cookies.set(SESSION_COOKIE_NAME, sid)
    try:
        resp = await client.post("/api/bot/tryme", json={"message": ""})
        assert resp.status_code == 200
        body = resp.json()
        text = body["replies"][0]
        assert "אבי" in text                 # Avi's seeded greeting
        assert "קבלת הצעת מחיר" in text       # Avi's 'quote' flow label
        assert "קביעת תור" not in text        # NOT Bella's 'appointment' flow
        assert body["state"]["phase"] == "menu"
        assert body["event"] is None
    finally:
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid}")


@pytest.mark.asyncio
async def test_tryme_persists_nothing(
    client: AsyncClient, redis_client: aioredis.Redis, app_pool
):
    """A whole simulated lead conversation leaves chat + lead row counts unchanged."""
    sid = await _inject_session(redis_client, AVI_USER, BIZ_A, "Avi Insurance")
    client.cookies.set(SESSION_COOKIE_NAME, sid)
    try:
        chat_before = await _count(app_pool, "bot_builder_messages", BIZ_A)
        leads_before = await _count(app_pool, "leads", BIZ_A)

        # Drive Avi's seeded 'quote' flow end-to-end over HTTP, echoing the state.
        state = None
        last = {}
        for msg in ["", "1", "אבי הבודק", "052-9999999", "1"]:
            r = await client.post("/api/bot/tryme",
                                  json={"message": msg, "state": state})
            assert r.status_code == 200
            last = r.json()
            state = last["state"]

        # The flow really finished a lead (in memory only)…
        assert last["event"] == "lead_completed"
        assert last["lead"]["full_name"] == "אבי הבודק"
        # …yet NOTHING was written to either table.
        assert await _count(app_pool, "bot_builder_messages", BIZ_A) == chat_before
        assert await _count(app_pool, "leads", BIZ_A) == leads_before
    finally:
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid}")
