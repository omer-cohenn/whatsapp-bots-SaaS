"""
============================================================================
  STATUS MODEL (decision 0021) — EXPLAINED LIKE YOU'RE FIVE
============================================================================

WHAT IS THIS FILE?
  The bot now has ONE clear story for every conversation, and a WhatsApp-style
  unread badge. This file checks that story end-to-end, in plain language.

  THE STORY:
    A customer writes. No open chat yet → the bot says hello + shows the menu.
    They pick something; the bot asks questions. A chat ENDS one of 3 ways, and
    we write down WHY on the lead ("close_reason"):
      • "completed" — they finished giving all the details.
      • "abandoned" — they went quiet for 60 minutes.
      • "answered"  — a human handled it and the owner pressed "done".
    After a chat closes, the NEXT message starts a brand-new chat (hello again).

  THE BIG BUG WE FIXED (the clock):
    When a HUMAN is chatting with the customer, the bot stays silent. The old
    code only reset the "60-minute quiet timer" when the BOT answered — so a
    customer talking to a real person for an hour got wrongly marked "abandoned"!
    Now EVERY incoming message resets that timer, even on the silent human path.

  THE BADGE:
    Every incoming customer message bumps an "unread" counter for that chat.
    The owner opening the chat clears it. The dashboard shows the grand total.

  Each check prints:  🧪 WHAT we try · 💡 WHY it matters · ✅/❌ the result.
  A scoreboard prints at the end. Run it via tests/test_status_model_0021.bat.
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
    abandoned_sweep,
    bot_runtime,
    conversation_state as cs,
    leads as leads_service,
)

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (published)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (draft)

_passed = 0
_total = 0


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


def new_conv() -> str:
    return f"sim:{secrets.token_hex(8)}"


async def seed_lead(pool, business_id, *, status, conversation_id, idle_minutes=0):
    ref = f"conv:{business_id}:{conversation_id}" if conversation_id else None
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO leads (business_id, lead_name, status, is_test,
                               cache_chat_ref, started_at, last_activity_at)
            VALUES ($1, 'test-flow', $2, true, $3,
                    now() - make_interval(mins => $4),
                    now() - make_interval(mins => $4))
            RETURNING id
            """,
            business_id, status, ref, idle_minutes,
        )
    return str(row["id"])


async def fetch_lead(pool, business_id, lead_id):
    async with tenant_connection(pool, business_id) as conn:
        return await conn.fetchrow(
            "SELECT status, close_reason FROM leads WHERE id=$1 AND business_id=$2",
            lead_id, business_id,
        )


async def cleanup(pool, rds, convs):
    for bid, cid in convs:
        await cs.reset_conversation(rds, bid, cid)
        await rds.delete(f"conv:{bid}:{cid}:outbox")
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute(
                "DELETE FROM leads WHERE business_id=$1 AND is_test=true", bid)


async def main() -> int:
    print(__doc__)
    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=4)
    rds = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    convs: list[tuple[str, str]] = []

    try:
        # ── 1 — the migration is really applied ─────────────────────────────
        banner("1", "The database actually has the new column + sweep shape")
        explain("look at the leads table + the sweep function in Postgres",
                "the whole milestone rests on close_reason existing and the "
                "sweep returning which chats to close")
        async with pool.acquire() as conn:
            col = await conn.fetchval(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name='leads' AND column_name='close_reason'")
            ret = await conn.fetchval(
                "SELECT pg_get_function_result(oid) FROM pg_proc "
                "WHERE proname='sweep_abandoned_leads'")
        result(col == "text", f"leads.close_reason is a {col} column")
        result(ret == "TABLE(lead_id uuid, conversation_id text)",
               f"sweep returns: {ret}")

        # ── 2 — THE CLOCK FIX (the headline bug) ────────────────────────────
        banner("2", "A customer talking to a HUMAN is NOT wrongly abandoned")
        explain("put a lead in a 'human' chat, make it look 2 hours idle, then "
                "have the customer send ONE new message, then run the sweep",
                "the new message must reset the 60-min timer — a real person is "
                "on the line, we must not declare it abandoned")
        conv = new_conv(); convs.append((BIZ_A, conv))
        lead = await seed_lead(pool, BIZ_A, status="in_progress",
                               conversation_id=conv, idle_minutes=120)
        await cs.set_status(rds, BIZ_A, conv, cs.STATUS_HUMAN)
        out = await bot_runtime.run_turn(pool, rds, BIZ_A, conv, "עוד שאלה", is_test=True)
        await abandoned_sweep.run_sweep_once(pool, rds)
        row = await fetch_lead(pool, BIZ_A, lead)
        result(out["silent"] is True, "the bot stayed silent (a human is handling it)")
        result(row["status"] == "in_progress",
               f"after the new message the lead is still '{row['status']}' (not abandoned)")

        # ── 2b — NEGATIVE CONTROL: a truly idle lead DOES get abandoned ─────
        banner("2b", "NEGATIVE CONTROL — a lead that really went quiet IS abandoned")
        explain("same setup but the customer sends NOTHING, then run the sweep",
                "if the sweep DIDN'T fire here, the whole feature would be broken — "
                "we prove it still catches a real abandonment")
        conv2 = new_conv(); convs.append((BIZ_A, conv2))
        lead2 = await seed_lead(pool, BIZ_A, status="in_progress",
                                conversation_id=conv2, idle_minutes=120)
        await cs.set_status(rds, BIZ_A, conv2, cs.STATUS_HUMAN)
        await abandoned_sweep.run_sweep_once(pool, rds)
        row2 = await fetch_lead(pool, BIZ_A, lead2)
        result(row2["status"] == "abandoned" and row2["close_reason"] == "abandoned",
               f"the quiet lead became '{row2['status']}' with reason '{row2['close_reason']}'")
        result(await cs.get_status(rds, BIZ_A, conv2) == cs.STATUS_CLOSED,
               "and its live chat was auto-closed in Redis")

        # ── 3 — a NULL conversation row doesn't crash the sweep ─────────────
        banner("3", "A lead with no chat link doesn't crash the sweep")
        explain("abandon a lead that has NO conversation pointer",
                "some leads never had a live chat; the close-loop must skip them "
                "safely, never blowing up the whole pass")
        lead3 = await seed_lead(pool, BIZ_A, status="in_progress",
                                conversation_id=None, idle_minutes=120)
        n = await abandoned_sweep.run_sweep_once(pool, rds)
        row3 = await fetch_lead(pool, BIZ_A, lead3)
        result(row3["status"] == "abandoned", "the no-chat lead was abandoned cleanly")
        result(n >= 1, "the sweep finished without crashing")

        # ── 4 — completed stamps the reason + closes the chat ───────────────
        banner("4", "Finishing the questionnaire writes reason='completed' + closes")
        explain("drive Avi's quote flow all the way to the end",
                "a finished lead should say WHY it closed (completed) and the "
                "chat should close so the next message starts fresh")
        conv4 = new_conv(); convs.append((BIZ_A, conv4))
        for m in ("שלום", "1", "דנה כהן", "052-1234567", "רכב"):
            await bot_runtime.run_turn(pool, rds, BIZ_A, conv4, m, is_test=True)
        async with tenant_connection(pool, BIZ_A) as conn:
            r = await conn.fetchrow(
                "SELECT status, close_reason FROM leads WHERE business_id=$1 "
                "AND cache_chat_ref=$2 ORDER BY last_activity_at DESC LIMIT 1",
                BIZ_A, f"conv:{BIZ_A}:{conv4}")
        result(r is not None and r["close_reason"] == "completed",
               f"the lead's close_reason is '{r['close_reason'] if r else None}'")
        result(await cs.get_status(rds, BIZ_A, conv4) == cs.STATUS_CLOSED,
               "the chat is now closed")

        # ── 5 — owner closing a HUMAN chat writes reason='answered' ─────────
        banner("5", "Owner pressing 'done' on a human chat writes reason='answered'")
        explain("a lead in a 'human' chat, then the owner sets it to 'closed'",
                "we want to tell apart 'a person handled this' (answered) from "
                "'the bot finished it' (completed) or 'they vanished' (abandoned)")
        conv5 = new_conv(); convs.append((BIZ_A, conv5))
        lead5 = await seed_lead(pool, BIZ_A, status="in_progress",
                                conversation_id=conv5, idle_minutes=0)
        await cs.set_status(rds, BIZ_A, conv5, cs.STATUS_HUMAN)
        conv_id = await _close_via_service(pool, rds, BIZ_A, lead5)
        row5 = await fetch_lead(pool, BIZ_A, lead5)
        result(row5["status"] == "closed" and row5["close_reason"] == "answered",
               f"status='{row5['status']}', close_reason='{row5['close_reason']}'")

        # ── 6 — the unread badge counts + clears ────────────────────────────
        banner("6", "The unread badge counts incoming messages and clears on open")
        explain("send messages on a bot chat AND a silent human chat, check the "
                "totals, then 'open' one chat to clear it",
                "the owner needs a WhatsApp-style badge for chats they haven't read")
        cb = new_conv(); ch = new_conv()
        convs.append((BIZ_A, cb)); convs.append((BIZ_A, ch))
        await bot_runtime.run_turn(pool, rds, BIZ_A, cb, "שלום", is_test=True)
        await bot_runtime.run_turn(pool, rds, BIZ_A, cb, "1", is_test=True)
        await seed_lead(pool, BIZ_A, status="in_progress", conversation_id=ch)
        await cs.set_status(rds, BIZ_A, ch, cs.STATUS_HUMAN)
        await bot_runtime.run_turn(pool, rds, BIZ_A, ch, "היי", is_test=True)
        result(await cs.get_unread(rds, BIZ_A, cb) == 2,
               "bot-chat unread = 2 (two messages)")
        result(await cs.get_unread(rds, BIZ_A, ch) == 1,
               "silent human-chat unread = 1 (counted even though the bot was silent)")
        total = await cs.unread_total(rds, BIZ_A)
        result(total >= 3, f"the tenant's total unread is {total} (≥3)")
        await cs.mark_read(rds, BIZ_A, cb)
        result(await cs.get_unread(rds, BIZ_A, cb) == 0,
               "opening the bot chat reset ITS badge to 0")
        await cs.reset_conversation(rds, BIZ_A, ch)
        result(await rds.exists(cs._unread_key(BIZ_A, ch)) == 0,
               "resetting a conversation also wiped its unread key")

        # ── 7 — closed → fresh hello ────────────────────────────────────────
        banner("7", "A closed chat starts brand-new on the next message")
        explain("close a chat, then send a new message — compare to a brand-new chat",
                "each visit should feel like its own conversation (hello + menu)")
        c7 = new_conv(); convs.append((BIZ_A, c7))
        await bot_runtime.run_turn(pool, rds, BIZ_A, c7, "", is_test=True)
        await bot_runtime.run_turn(pool, rds, BIZ_A, c7, "1", is_test=True)
        await cs.set_status(rds, BIZ_A, c7, cs.STATUS_CLOSED)
        fresh = new_conv(); convs.append((BIZ_A, fresh))
        fresh_out = await bot_runtime.run_turn(pool, rds, BIZ_A, fresh, "שלום", is_test=True)
        reopened = await bot_runtime.run_turn(pool, rds, BIZ_A, c7, "שלום", is_test=True)
        result(reopened["replies"] == fresh_out["replies"],
               "the reopened chat greets exactly like a brand-new one")

        # ── 8 — tenant isolation ────────────────────────────────────────────
        banner("8", "Business B can never see A's close_reason or A's unread")
        explain("give A a closed lead + an unread message, then read everything as B",
                "the #1 rule: one business must NEVER see another's data")
        ca = new_conv(); convs.append((BIZ_A, ca))
        a_lead = await seed_lead(pool, BIZ_A, status="abandoned",
                                 conversation_id=ca, idle_minutes=0)
        async with tenant_connection(pool, BIZ_A) as conn:
            await leads_service.set_lead_status(
                conn, BIZ_A, a_lead, "closed",
                close_reason=leads_service.CLOSE_REASON_ANSWERED)
        await bot_runtime.run_turn(pool, rds, BIZ_A, ca, "הודעה", is_test=True)
        async with tenant_connection(pool, BIZ_B) as conn:
            b_sees = await conn.fetchrow("SELECT id FROM leads WHERE id=$1", a_lead)
        result(b_sees is None, "B's database read cannot see A's closed lead at all")
        b_total = await cs.unread_total(rds, BIZ_B)
        a_total = await cs.unread_total(rds, BIZ_A)
        result(a_total >= 1, f"A's own unread total counts A's message ({a_total})")
        # B's total must not include A's conversation — prove the key is rejected.
        guard_ok = False
        try:
            cs._assert_owns(BIZ_B, cs._unread_key(BIZ_A, ca))
        except cs.CrossTenantConversationError:
            guard_ok = True
        result(guard_ok, "the unread key guard rejects a cross-tenant key")

    finally:
        await cleanup(pool, rds, convs)
        await rds.aclose()
        await pool.close()

    print()
    print("=" * 74)
    print(f"  SCOREBOARD: {_passed}/{_total} checks passed")
    print("=" * 74)
    return 0 if _passed == _total else 1


async def _close_via_service(pool, rds, business_id, lead_id):
    """Mirror the API close path: find the chat, see it's human, stamp 'answered'."""
    async with tenant_connection(pool, business_id) as conn:
        conv_id = await leads_service.get_conversation_id_for_lead(
            conn, business_id, lead_id)
        close_reason = None
        if conv_id is not None:
            st = await cs.get_status(rds, business_id, conv_id)
            if st in (cs.STATUS_HUMAN, cs.STATUS_WAITING):
                close_reason = leads_service.CLOSE_REASON_ANSWERED
        await leads_service.set_lead_status(
            conn, business_id, lead_id, "closed", close_reason=close_reason)
    return conv_id


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
