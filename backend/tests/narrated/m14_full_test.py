"""
============================================================================
  M14 — TWO BOT FIXES — EXPLAINED LIKE YOU'RE FIVE
============================================================================

WHAT IS THIS FILE?
  Two small but important bot fixes, checked in plain language end-to-end.

  ── FIX A: the opening message shouldn't list the menu TWICE ──────────────
    The bot's "open" message is two parts glued together:
        (1) the GREETING  — a short warm hello the AI builder wrote, and
        (2) the MENU      — the numbered list of options, which the ENGINE
                            builds itself ("1. ...", "2. ...").
    The engine's numbered menu is the REAL one — it's what matches the
    number a customer types. The bug was that the AI builder sometimes baked
    its OWN list of options INTO the greeting too. Result: options showed up
    twice, in a different order — so typing "2" could pick the wrong thing!
    The fix: tell the AI builder, in its instructions, that the greeting is a
    SHORT hello ONLY — no option list, no numbers. The engine is unchanged.

  ── FIX B: a CLOSED chat should start FRESH when the customer writes again ─
    When a chat is marked 'closed' (finished) and the SAME customer sends a
    new message later, it should feel like a brand-new conversation: clean
    transcript, greeting+menu again, and a NEW lead if they pick something.
    The old finished lead stays saved in the database (history is kept) — we
    just don't keep dragging the old chat around. The fix: when run_turn sees
    a 'closed' chat get a new message, it WIPES that chat's short-term memory
    (reset_conversation) and then continues as if it were brand new.

  THE RULE THAT NEVER BREAKS: wiping business A's chat must NEVER touch
  business B's chats (or even A's OTHER chats). We re-check that here too.

  Every check prints:  🧪 WHAT we try · 💡 WHY it matters · ✅/❌ the result.
  A scoreboard prints at the end. Run it via tests/test_m14.bat (double-click).
============================================================================
"""

from __future__ import annotations

import asyncio
import os
import secrets

import asyncpg
import redis.asyncio as aioredis

from app.db.session import tenant_connection
from app.services import (
    bot_engine,
    bot_builder_ai,
    bot_runtime,
    conversation_state as cs,
)

# The two pretend businesses (fixed ids from supabase/seed.sql).
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (published)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (draft)

# Scoreboard.
_passed = 0
_total = 0


# --- tiny printing helpers ---------------------------------------------------

def banner(num: str, title: str) -> None:
    print()
    print("─" * 74)
    print(f"  TEST {num}: {title}")
    print("─" * 74)


def explain(what: str, why: str) -> None:
    print(f"  🧪 We try : {what}")
    print(f"  💡 Because: {why}")


def result(ok: bool, detail: str) -> None:
    global _passed, _total
    _total += 1
    if ok:
        _passed += 1
        print(f"  ✅ GOOD   : {detail}")
    else:
        print(f"  ❌ BAD    : {detail}   <-- THIS IS A PROBLEM!")


# --- helpers -----------------------------------------------------------------

def new_conv() -> str:
    return f"sim:{secrets.token_hex(8)}"


async def drive_to_closed_with_lead(pool, rds, conv: str) -> str:
    """Open a chat, start the quote flow (→ a lead), then mark it closed."""
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "", is_test=True)
    pick = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "1", is_test=True)
    await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "ישראל ישראלי", is_test=True)
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_CLOSED)
    return pick["lead_id"]


async def cleanup_test_data(pool, rds, convs):
    for bid, cid in convs:
        await cs.reset_conversation(rds, bid, cid)
        await rds.delete(f"conv:{bid}:{cid}:outbox")
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute(
                "DELETE FROM leads WHERE business_id = $1 AND is_test = true", bid)


# --- the test run ------------------------------------------------------------

async def main() -> int:
    print(__doc__)
    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=4)
    rds = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    convs: list[tuple[str, str]] = []

    try:
        # ── 1 — FIX A: the builder prompt forbids options inside the greeting
        banner("1", "FIX A — the AI builder is told: greeting = short hello, no options")
        explain("read the system prompt the builder sends to the AI",
                "if it doesn't forbid an option-list in the greeting, the AI "
                "will keep baking one in → the menu shows up twice")
        prompt = bot_builder_ai.build_system_prompt({})
        names_field = ("הודעת הפתיחה" in prompt) or ("הודעת פתיחה" in prompt)
        forbids_options = ("ללא רשימת אפשרויות" in prompt) or ("אסור לה לכלול את רשימת" in prompt)
        forbids_numbers = ("ללא מספרים" in prompt) or ("אסור לה לכלול מספרים" in prompt)
        explains_auto = "אוטומטי" in prompt          # "the system shows the menu automatically"
        warns_twice = "פעמיים" in prompt              # "...otherwise it appears twice"
        result(names_field and forbids_options and forbids_numbers and explains_auto and warns_twice,
               "the prompt names the greeting field AND forbids the option-list/"
               "numbers AND explains the menu is auto-rendered (so no duplicates)")

        # ── 2 — FIX A: the JSON examples also use an option-free greeting
        banner("2", "FIX A — the builder's EXAMPLES don't seed an option-list greeting")
        explain("check the example/placeholder greeting text in the prompt",
                "the AI copies the examples; if THEY list options, the fix leaks")
        good_placeholder = "הקדמה קצרה בלבד" in prompt   # "a short intro only"
        good_example = '"greeting": "שלום' in prompt     # plain hello, not a list
        result(good_placeholder and good_example,
               "the example greeting is a plain hello ('intro only — no options')")

        # ── 3 — FIX A did NOT touch the engine: greeting + canonical menu remain
        banner("3", "FIX A — the engine STILL builds greeting + its own numbered menu")
        explain("ask the engine for the open turn with a known greeting + 2 flows",
                "the engine's numbered menu is the REAL one; it must be unchanged")
        settings = {
            "bot_profile": {"greeting": "שלום! איך אפשר לעזור?"},
            "lead_steps": {
                "quote": {"label": "הצעת מחיר", "flow_type": "lead",
                          "steps": [{"key": "full_name", "question": "שם?",
                                     "type": "text", "required": True}]},
                "talk_to_human": {"label": "נציג", "flow_type": "human_handoff",
                                  "steps": []}},
        }
        open_text = bot_engine.advance(settings, bot_engine.initial_state(), "")["replies"][0]
        result("שלום! איך אפשר לעזור?" in open_text and "הצעת מחיר" in open_text and "1" in open_text,
               "open turn = the greeting THEN the engine's numbered canonical menu")

        # ── 4 — FIX B: reset_conversation wipes EVERYTHING for one chat
        banner("4", "FIX B — reset_conversation wipes state + transcript + status + index")
        explain("close a chat (with a lead + transcript), then reset it",
                "a closed chat that gets a new message must look brand-new again")
        conv = new_conv(); convs.append((BIZ_A, conv))
        await drive_to_closed_with_lead(pool, rds, conv)
        had_state = await cs.get_state(rds, BIZ_A, conv) is not None
        had_log = bool(await cs.get_messages(rds, BIZ_A, conv))
        had_status = await cs.get_status(rds, BIZ_A, conv) == cs.STATUS_CLOSED
        in_index = conv in await rds.smembers(cs._index_key(BIZ_A))
        await cs.reset_conversation(rds, BIZ_A, conv)
        gone_state = await cs.get_state(rds, BIZ_A, conv) is None
        gone_log = await cs.get_messages(rds, BIZ_A, conv) == []
        gone_status = await cs.get_status(rds, BIZ_A, conv) is None
        out_index = conv not in await rds.smembers(cs._index_key(BIZ_A))
        result(had_state and had_log and had_status and in_index
               and gone_state and gone_log and gone_status and out_index,
               "before: state+log+status+index all present — after: all gone "
               "(exactly a never-seen conversation)")

        # ── 5 — FIX B: closed + new message → a clean brand-new conversation
        banner("5", "FIX B — a CLOSED chat + new message behaves like a NEW chat")
        explain("close a chat, send a new message, AND send the same message to a "
                "genuinely-fresh chat — compare the bot's reply",
                "the reset path must produce IDENTICAL behavior to a new chat")
        conv = new_conv(); convs.append((BIZ_A, conv))
        old_lead_id = await drive_to_closed_with_lead(pool, rds, conv)
        fresh = new_conv(); convs.append((BIZ_A, fresh))
        fresh_out = await bot_runtime.run_turn(pool, rds, BIZ_A, fresh, "שלום", is_test=True)
        reopened = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "שלום", is_test=True)
        same_reply = reopened["replies"] == fresh_out["replies"]
        not_silent = reopened["silent"] is False
        shows_menu = "קבלת הצעת מחיר" in reopened["replies"][0] and "1" in reopened["replies"][0]
        result(same_reply and not_silent and shows_menu,
               "the reopened chat replies EXACTLY like a brand-new chat "
               "(the canonical numbered menu)")

        # ── 6 — FIX B: state reset to fresh menu + status back to default 'bot'
        banner("6", "FIX B — after reopen: fresh menu state, status back to 'bot'")
        explain("inspect the reopened chat's saved engine state + status",
                "a clean restart means phase=menu, no carried-over lead, status bot")
        st = await cs.get_state(rds, BIZ_A, conv)
        status = await cs.get_status(rds, BIZ_A, conv)
        result(st is not None and st.get("phase") == bot_engine.PHASE_MENU
               and st.get("active_flow") is None and st.get("lead_id") is None
               and status in (None, cs.STATUS_BOT),
               "phase=menu, no active flow, no carried lead, status defaults to 'bot'")

        # ── 7 — FIX B: transcript was cleared then reseeded with ONLY the new turn
        banner("7", "FIX B — transcript cleared, then reseeded with ONLY the new exchange")
        explain("read the reopened chat's transcript",
                "old finished lines must be gone; only the new in/out should remain")
        msgs = await cs.get_messages(rds, BIZ_A, conv)
        roles = [m["role"] for m in msgs]
        result(roles == ["customer", "bot"] and msgs[0]["body"] == "שלום",
               "transcript = just [customer 'שלום', bot menu] — nothing from before")

        # ── 8 — FIX B: the OLD closed lead row is preserved in Postgres
        banner("8", "FIX B — the OLD finished lead is kept in the database (history)")
        explain("look up the old lead id after the chat restarted",
                "restarting the chat must NOT delete the finished lead's record")
        async with tenant_connection(pool, BIZ_A) as conn:
            still = await conn.fetchval(
                "SELECT count(*)::int FROM leads WHERE id=$1 AND business_id=$2",
                old_lead_id, BIZ_A)
        result(still == 1, "the old closed lead row is still there, untouched")

        # ── 9 — FIX B: picking a flow after reopen opens a NEW lead (not the old)
        banner("9", "FIX B — after reopen, picking a flow opens a NEW lead")
        explain("on the reopened chat, pick flow 1 again",
                "a fresh conversation must start a fresh lead, not reuse the old")
        pick = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "1", is_test=True)
        new_lead_id = pick["lead_id"]
        result(new_lead_id is not None and new_lead_id != old_lead_id,
               "a brand-new lead was opened; the old finished lead is not reused")

        # ── 10 — FIX B isolation: reset(A,convA) leaves B + A's other chat alone
        banner("10", "FIX B ISOLATION — resetting one chat never touches the others")
        explain("give A two chats and B one chat, reset only A's first chat",
                "wiping one tenant's chat must NEVER bleed into another's data")
        a1 = new_conv(); a2 = new_conv(); b1 = new_conv()
        convs += [(BIZ_A, a1), (BIZ_A, a2), (BIZ_B, b1)]
        await drive_to_closed_with_lead(pool, rds, a1)
        await bot_runtime.run_turn(pool, rds, BIZ_A, a2, "", is_test=True)
        await bot_runtime.run_turn(pool, rds, BIZ_B, b1, "", is_test=True)
        await cs.reset_conversation(rds, BIZ_A, a1)
        a1_gone = await cs.get_state(rds, BIZ_A, a1) is None and await cs.get_messages(rds, BIZ_A, a1) == []
        a2_ok = await cs.get_state(rds, BIZ_A, a2) is not None and bool(await cs.get_messages(rds, BIZ_A, a2))
        b1_ok = await cs.get_state(rds, BIZ_B, b1) is not None and bool(await cs.get_messages(rds, BIZ_B, b1))
        result(a1_gone and a2_ok and b1_ok,
               "A's first chat is wiped; A's OTHER chat and B's chat are untouched")

        # ── 11 — FIX B isolation: a forged cross-tenant key is rejected
        banner("11", "FIX B ISOLATION — a forged cross-tenant key is rejected")
        explain("ask reset's guard to accept a key with the WRONG business prefix",
                "defense-in-depth: a key must never name another tenant's chat")
        rejected = False
        try:
            cs._assert_owns(BIZ_A, f"conv:{BIZ_B}:forged")
        except cs.CrossTenantConversationError:
            rejected = True
        accepted_own = True
        try:
            cs._assert_owns(BIZ_A, f"conv:{BIZ_A}:mine")
        except cs.CrossTenantConversationError:
            accepted_own = False
        result(rejected and accepted_own,
               "the guard rejects B's prefix for caller A, but accepts A's own key")

        # ── 12 — NEGATIVE CONTROL: prove the reset test can actually FAIL
        banner("12", "NEGATIVE CONTROL: break it on purpose, watch it get caught")
        explain("close a chat but SKIP the reset, then check it 'looks brand-new'",
                "a green test is only trustworthy if it can go red when broken")
        conv_bad = new_conv(); convs.append((BIZ_A, conv_bad))
        await drive_to_closed_with_lead(pool, rds, conv_bad)
        # Deliberately DO NOT reset. The "is it fresh?" check must now be False.
        looks_fresh_without_reset = await cs.get_state(rds, BIZ_A, conv_bad) is None
        # Now actually reset and confirm the SAME check flips to True.
        await cs.reset_conversation(rds, BIZ_A, conv_bad)
        looks_fresh_after_reset = await cs.get_state(rds, BIZ_A, conv_bad) is None
        result((not looks_fresh_without_reset) and looks_fresh_after_reset,
               "without reset the chat is NOT fresh (test would catch a missing "
               "reset); with reset it IS fresh — the check is live, not asleep")

    finally:
        await cleanup_test_data(pool, rds, convs)
        await rds.aclose()
        await pool.close()

    # Scoreboard.
    print("\n" + "=" * 74)
    print(f"  SCOREBOARD:  {_passed}/{_total} checks passed")
    print("=" * 74)
    if _passed == _total:
        print("  🎉 ALL GREEN — the greeting won't double the menu anymore, and a")
        print("     closed chat starts fresh on a new message while keeping the old")
        print("     lead's history — and one tenant's reset never touches another. 🔒")
    else:
        print("  ⚠️  Some checks failed — see the ❌ lines above.")
    return 0 if _passed == _total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
