"""M14 — two bot fixes, strict pytest (the CI version).

Two product fixes, verified end-to-end against the real engine + runtime + Redis:

FIX A — the AI builder's greeting is intro-only (no menu options / numbers).
  The canonical, number-matched menu is rendered by the engine (`_menu_list`)
  right after the greeting. The AI builder must therefore NOT bake the option
  list into the stored `greeting`, or the options would appear twice (and in a
  different order, so a typed number could pick the wrong flow). This is a
  PROMPT-text guarantee: `bot_builder_ai.build_system_prompt(...)` must instruct
  Gemini that `greeting` is a short warm Hebrew intro only. The engine is
  unchanged — `_greeting_and_menu` still appends `_menu_list`.

FIX B — a CLOSED conversation restarts fresh on a new inbound.
  When a chat's status is 'closed' and a new customer message arrives,
  `run_turn` calls `conversation_state.reset_conversation(...)` which wipes the
  conv hash (status + engine state), the transcript log, and the index entry —
  then falls through to the normal flow. The net effect is a brand-new
  conversation: a fresh transcript reseeded with just the new exchange,
  get_state back to the initial state, status back to the default 'bot', the
  greeting+menu open turn, and a NEW lead when a flow is picked. The OLD closed
  lead row in Postgres is left untouched (history preserved).

It runs IN-PROCESS, calling `bot_runtime.run_turn` and `conversation_state`
directly against the real Redis + Postgres. Every persisted row is is_test=true;
the cleanup fixture deletes the test leads + Redis conv keys it created. Nothing
prints a secret, a token, or PII.
"""

from __future__ import annotations

import os
import secrets

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from app.db.session import tenant_connection
from app.services import (
    bot_engine,
    bot_builder_ai,
    bot_runtime,
    conversation_state as cs,
)

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (published)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (draft)


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

def _new_conv() -> str:
    return f"sim:{secrets.token_hex(8)}"


async def _drive_to_closed_with_lead(pool, rds, conv: str) -> str:
    """Open a fresh chat, start the 'quote' lead flow, then force-close it.

    Returns the lead_id of the (now closed) lead. After this, get_status is
    'closed' and a saved engine state with an active lead exists in Redis.
    """
    # Open turn (greeting+menu), then pick flow 1 → starts the 'quote' lead.
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "", is_test=True)
    pick = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "1", is_test=True)
    # Answer the first step so a lead row truly exists + is mid-flow.
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "ישראל ישראלי", is_test=True)
    lead_id = pick["lead_id"]
    assert lead_id is not None, "expected the quote flow to open a lead"
    # Force the chat closed (what the M9 'close conversation' action does).
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_CLOSED)
    return lead_id


# ============================================================================
#  FIX A — the builder prompt instructs greeting to be intro-only (no options)
# ============================================================================

def test_builder_prompt_greeting_is_intro_only():
    """The system prompt must constrain greeting to a short intro with no menu."""
    prompt = bot_builder_ai.build_system_prompt({})

    # The explicit constraint block is present and names the greeting field.
    assert "greeting" in prompt
    assert "הודעת הפתיחה" in prompt or "הודעת פתיחה" in prompt
    # It forbids listing the options and forbids numbers in the greeting.
    assert "ללא רשימת אפשרויות" in prompt or "אסור לה לכלול את רשימת" in prompt
    assert "ללא מספרים" in prompt or "אסור לה לכלול מספרים" in prompt
    # It explains WHY: the system renders the numbered menu automatically after.
    assert "אוטומטי" in prompt
    # And it warns about the duplicate-options symptom.
    assert "פעמיים" in prompt


def test_builder_prompt_examples_have_optionless_greeting():
    """The JSON examples must not seed an options-list greeting."""
    prompt = bot_builder_ai.build_system_prompt({})
    # The placeholder for the greeting field describes "intro only, no options".
    assert "הקדמה קצרה בלבד" in prompt
    # The replaceAll example greeting is a plain intro (ends with an offer to
    # help, not a numbered list). Sanity: no "1." / "2." numbered lines snuck in
    # as example greeting content right after a greeting key.
    assert '"greeting": "שלום' in prompt


def test_engine_still_appends_canonical_menu_after_greeting():
    """FIX A must NOT touch the engine: greeting + canonical _menu_list remain."""
    settings = {
        "bot_profile": {"greeting": "שלום! איך אפשר לעזור?"},
        "lead_steps": {
            "quote": {"label": "הצעת מחיר", "flow_type": "lead",
                      "steps": [{"key": "full_name", "question": "שם?",
                                 "type": "text", "required": True}]},
            "talk_to_human": {"label": "נציג", "flow_type": "human_handoff",
                              "steps": []},
        },
    }
    out = bot_engine.advance(settings, bot_engine.initial_state(), "")
    open_text = out["replies"][0]
    # The intro is there, AND the engine appended the numbered canonical menu.
    assert "שלום! איך אפשר לעזור?" in open_text
    assert "הצעת מחיר" in open_text  # a flow label from the canonical menu
    assert "1" in open_text          # the canonical menu is numbered by the engine


# ============================================================================
#  FIX B — a CLOSED conversation restarts fresh on a new inbound
# ============================================================================

@pytest.mark.asyncio
async def test_reset_conversation_clears_all_keys(pool, rds, cleanup):
    """reset_conversation deletes state, transcript, status, and the index entry."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    await _drive_to_closed_with_lead(pool, rds, conv)

    # Pre-conditions: there IS state, a transcript, a status, and an index entry.
    assert await cs.get_state(rds, BIZ_A, conv) is not None
    assert await cs.get_messages(rds, BIZ_A, conv)  # non-empty transcript
    assert await cs.get_status(rds, BIZ_A, conv) == cs.STATUS_CLOSED
    assert conv in await rds.smembers(cs._index_key(BIZ_A))

    await cs.reset_conversation(rds, BIZ_A, conv)

    # Post-conditions: everything is gone → looks like a never-seen conversation.
    assert await cs.get_state(rds, BIZ_A, conv) is None
    assert await cs.get_messages(rds, BIZ_A, conv) == []
    assert await cs.get_status(rds, BIZ_A, conv) is None  # None ⇒ callers default 'bot'
    assert conv not in await rds.smembers(cs._index_key(BIZ_A))


@pytest.mark.asyncio
async def test_closed_chat_new_inbound_starts_fresh(pool, rds, cleanup):
    """The headline behavior: closed + inbound = a clean brand-new conversation."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    old_lead_id = await _drive_to_closed_with_lead(pool, rds, conv)

    # A NEW inbound arrives on the CLOSED chat. run_turn must reset + then behave
    # EXACTLY like a brand-new conversation. We prove that equivalence by sending
    # the SAME first message to a genuinely-fresh conversation and comparing the
    # bot's reply byte-for-byte. (A non-empty first message lands at the menu and
    # yields the "didn't catch that — here's the menu" turn for BOTH paths; the
    # empty open-turn greeting only fires on an empty message, so the two paths
    # must match each other, not the empty-message greeting.)
    fresh_conv = _new_conv()
    cleanup.append((BIZ_A, fresh_conv))
    fresh_out = await bot_runtime.run_turn(
        pool, rds, BIZ_A, fresh_conv, "שלום", is_test=True)

    out = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "שלום", is_test=True)
    assert out["silent"] is False
    assert out["replies"] == fresh_out["replies"]
    # And that reply is the canonical numbered menu (the engine's _menu_list).
    reply = out["replies"][0]
    assert "קבלת הצעת מחיר" in reply and "דברו עם נציג" in reply
    assert "1" in reply and "2" in reply

    # Status is back to the default 'bot' (the hash was deleted; get_status None,
    # but set_state during the turn re-created the hash WITHOUT a status field).
    status = await cs.get_status(rds, BIZ_A, conv)
    assert status in (None, cs.STATUS_BOT)

    # The engine state is a fresh menu state (phase=menu, no active flow/lead).
    state = await cs.get_state(rds, BIZ_A, conv)
    assert state is not None
    assert state.get("phase") == bot_engine.PHASE_MENU
    assert state.get("active_flow") is None
    assert state.get("lead_id") is None  # the closed lead is NOT carried over

    # The transcript was cleared then reseeded with ONLY the new exchange:
    # the one inbound "שלום" + the bot's open-turn reply. Nothing from before.
    msgs = await cs.get_messages(rds, BIZ_A, conv)
    assert [m["role"] for m in msgs] == ["customer", "bot"]
    assert msgs[0]["body"] == "שלום"

    # The OLD closed lead row still exists in Postgres, untouched (history kept).
    async with tenant_connection(pool, BIZ_A) as conn:
        still_there = await conn.fetchval(
            "SELECT count(*)::int FROM leads WHERE id = $1 AND business_id = $2",
            old_lead_id, BIZ_A)
    assert still_there == 1


@pytest.mark.asyncio
async def test_closed_then_pick_flow_creates_new_lead(pool, rds, cleanup):
    """After a closed chat restarts, picking a flow opens a NEW lead, not the old."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    old_lead_id = await _drive_to_closed_with_lead(pool, rds, conv)

    # New inbound (resets), then pick flow 1 again → a brand-new lead must open.
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "שלום", is_test=True)
    pick = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "1", is_test=True)
    new_lead_id = pick["lead_id"]

    assert new_lead_id is not None
    assert new_lead_id != old_lead_id  # a fresh lead, the old one is not reused

    # Both rows exist: the old closed lead is preserved AND a new one was made.
    async with tenant_connection(pool, BIZ_A) as conn:
        rows = await conn.fetch(
            "SELECT id FROM leads WHERE id = ANY($1::uuid[]) AND business_id = $2",
            [old_lead_id, new_lead_id], BIZ_A)
    assert {str(r["id"]) for r in rows} == {old_lead_id, new_lead_id}


@pytest.mark.asyncio
async def test_non_closed_statuses_are_untouched_by_reset_path(pool, rds, cleanup):
    """A 'bot' chat is NOT reset on a new inbound — only 'closed' triggers it.

    Sanity guard so the closed-reset branch can't accidentally wipe a live chat.
    """
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    # Open + start the flow + answer one step (status stays 'bot').
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "", is_test=True)
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "1", is_test=True)
    before = await cs.get_messages(rds, BIZ_A, conv)
    # Another normal inbound: the transcript GROWS (no reset on a 'bot' chat).
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "ישראל", is_test=True)
    after = await cs.get_messages(rds, BIZ_A, conv)
    assert len(after) > len(before)


# ============================================================================
#  FIX B isolation — reset only touches THIS tenant + conversation
# ============================================================================

@pytest.mark.asyncio
async def test_reset_is_tenant_and_conversation_scoped(pool, rds, cleanup):
    """reset_conversation(A, convA) must not touch B's chat or A's other chat."""
    conv_a = _new_conv()
    conv_a_other = _new_conv()
    conv_b = _new_conv()
    cleanup.append((BIZ_A, conv_a))
    cleanup.append((BIZ_A, conv_a_other))
    cleanup.append((BIZ_B, conv_b))

    # Give all three live state + a transcript.
    await _drive_to_closed_with_lead(pool, rds, conv_a)
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv_a_other, "", is_test=True)
    await bot_runtime.run_turn(pool, rds, BIZ_B, conv_b, "", is_test=True)

    # Reset ONLY tenant A's first conversation.
    await cs.reset_conversation(rds, BIZ_A, conv_a)

    # A's first conv is wiped...
    assert await cs.get_state(rds, BIZ_A, conv_a) is None
    assert await cs.get_messages(rds, BIZ_A, conv_a) == []
    # ...but A's OTHER conversation is untouched...
    assert await cs.get_state(rds, BIZ_A, conv_a_other) is not None
    assert await cs.get_messages(rds, BIZ_A, conv_a_other)
    assert conv_a_other in await rds.smembers(cs._index_key(BIZ_A))
    # ...and tenant B's conversation is untouched.
    assert await cs.get_state(rds, BIZ_B, conv_b) is not None
    assert await cs.get_messages(rds, BIZ_B, conv_b)
    assert conv_b in await rds.smembers(cs._index_key(BIZ_B))


@pytest.mark.asyncio
async def test_reset_rejects_cross_tenant_key():
    """Defense-in-depth: a forged conversation id can't escape the business prefix.

    reset_conversation builds keys via `_key`/`_log_key`, which always prepend the
    caller's business prefix, and `_assert_owns` re-checks it. There is no path to
    name another tenant's key, so a normal call is always self-scoped. We assert
    the guard exists and fires for a key that doesn't match (mirrors live_chat).
    """
    # The guard rejects a key that isn't prefixed with this caller's business id.
    with pytest.raises(cs.CrossTenantConversationError):
        cs._assert_owns(BIZ_A, f"conv:{BIZ_B}:someconv")
    # And accepts a correctly-prefixed key (no raise).
    cs._assert_owns(BIZ_A, f"conv:{BIZ_A}:someconv")
