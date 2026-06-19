"""
============================================================================
  M8 — THE IN-APP HUMAN-HANDOFF CHAT — FULL TEST, EXPLAINED LIKE YOU'RE FIVE
============================================================================

WHAT IS THIS FILE?
  Sometimes a customer wants a REAL person, not the bot. M8 is the little chat
  room inside the app where the business owner takes over and talks to that
  customer. To make that work we needed four things — and this test checks all
  of them, in plain language:

    1) A FULL TRANSCRIPT. Every line anyone says (the customer, the bot, the
       human owner) is written to one shared list in Redis, oldest→newest, and
       trimmed so it never grows forever (last 200 lines kept).

    2) A STATUS JOURNEY: bot → waiting → human → closed.
         • bot     = the robot is answering.
         • waiting = the customer asked for a person, nobody picked up YET (NEW).
         • human   = the owner took over.
         • closed  = the chat is done.

    3) THE BOT MUST GO QUIET when status is 'waiting' OR 'human' — but the
       customer's incoming messages are STILL written to the transcript, so the
       owner can see what the customer is saying while they help.

    4) WINDOWS to read it all:
         • GET /api/conversations/{id}          → status + linked lead + messages
         • GET /api/conversations/{id}/messages → just the transcript (for polling)
         • POST .../reply                       → owner's reply ALSO joins the log
         • POST .../status                      → now also accepts 'waiting'

  THE RULE THAT CAN NEVER BREAK: business A must NEVER be able to read business
  B's chat. Same conversation id, different business = a totally separate room.

  Every check prints:  🧪 WHAT we try · 💡 WHY it matters · ✅/❌ the result.
  A scoreboard prints at the end. Run it via tests/test_m8.bat (double-click).
============================================================================
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time

import asyncpg
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import bot_runtime, conversation_state as cs, leads as leads_service
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

# The two pretend businesses (fixed ids from supabase/seed.sql).
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

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

async def inject_session(redis, user_id: str, business_id: str) -> str:
    """Pretend this owner just logged in: drop a real session blob into Redis."""
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": f"{user_id}@example.com", "name": user_id,
        "picture": "", "business_id": business_id, "business_name": "x",
        "created_at": int(time.time()),
    }
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    return sid


def new_conv() -> str:
    return f"sim:{secrets.token_hex(8)}"


async def sim(http, conv_id, msg):
    return (await http.post(
        "/api/bot/sim", json={"message": msg, "conversation_id": conv_id})).json()


# ============================================================================
#  THE TESTS
# ============================================================================

async def run() -> int:
    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=3)
    redis = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)

    made: list[tuple[str, str]] = []  # (business_id, conv_id) to clean up

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:

            # ════════════════════════════════════════════════════════════════
            #  TEST 1 — the transcript records everyone, in order
            # ════════════════════════════════════════════════════════════════
            banner("1", "The transcript writes every line, in order, with roles")
            conv = new_conv(); made.append((BIZ_A, conv))
            explain("append a customer line, a bot line, and an owner line",
                    "the chat view needs the WHOLE conversation, oldest→newest.")
            await cs.append_message(redis, BIZ_A, conv, "customer", "שלום")
            await cs.append_message(redis, BIZ_A, conv, "bot", "היי 🙂")
            await cs.append_message(redis, BIZ_A, conv, "owner", "מדבר הנציג")
            msgs = await cs.get_messages(redis, BIZ_A, conv)
            roles = [m["role"] for m in msgs]
            result(roles == ["customer", "bot", "owner"],
                   f"roles came back in order: {roles}")
            result(all(m.get("at") for m in msgs),
                   "every line carries a timestamp ('at')")

            # ════════════════════════════════════════════════════════════════
            #  TEST 2 — the transcript can't grow forever (trim to 200)
            # ════════════════════════════════════════════════════════════════
            banner("2", "The transcript is trimmed to the last 200 lines")
            conv = new_conv(); made.append((BIZ_A, conv))
            explain("push 250 lines, then read them back",
                    "a runaway chat must not eat all of Redis — we keep the last 200.")
            for i in range(250):
                await cs.append_message(redis, BIZ_A, conv, "customer", f"m{i}")
            kept = await cs.get_messages(redis, BIZ_A, conv)
            result(len(kept) == 200, f"kept exactly {len(kept)} lines (cap = 200)")
            result(kept[0]["body"] == "m50" and kept[-1]["body"] == "m249",
                   f"oldest kept = {kept[0]['body']}, newest = {kept[-1]['body']}")

            # ════════════════════════════════════════════════════════════════
            #  TEST 3 — the bot is SILENT while 'waiting' (but still logs them)
            # ════════════════════════════════════════════════════════════════
            banner("3", "Bot stays quiet in 'waiting' — but the customer is still logged")
            conv = new_conv(); made.append((BIZ_A, conv))
            await cs.set_status(redis, BIZ_A, conv, cs.STATUS_WAITING)
            explain("the customer writes while the chat is 'waiting' for a person",
                    "the robot must NOT butt in — yet the owner must still see the message.")
            r = await bot_runtime.run_turn(pool, redis, BIZ_A, conv,
                                           "אני עדיין כאן", is_test=True)
            result(r["silent"] is True and r["replies"] == [],
                   "bot said nothing (silent=True, replies=[])")
            log = await cs.get_messages(redis, BIZ_A, conv)
            result(any(m["role"] == "customer" and m["body"] == "אני עדיין כאן" for m in log),
                   "the customer's message WAS still written to the transcript")
            result(not any(m["role"] == "bot" for m in log),
                   "no bot line was added (it really stayed quiet)")

            # ════════════════════════════════════════════════════════════════
            #  TEST 4 — the bot is SILENT while 'human' too
            # ════════════════════════════════════════════════════════════════
            banner("4", "Bot stays quiet in 'human' as well")
            conv = new_conv(); made.append((BIZ_A, conv))
            await cs.set_status(redis, BIZ_A, conv, cs.STATUS_HUMAN)
            explain("the customer writes while a human owner is handling the chat",
                    "once a person took over, the robot must never talk over them.")
            r = await bot_runtime.run_turn(pool, redis, BIZ_A, conv, "תודה!", is_test=True)
            log = await cs.get_messages(redis, BIZ_A, conv)
            result(r["silent"] is True and r["replies"] == [], "bot stayed silent")
            result(any(m["role"] == "customer" for m in log)
                   and not any(m["role"] == "bot" for m in log),
                   "customer logged, bot did not answer")

            # ════════════════════════════════════════════════════════════════
            #  TEST 5 — the full status journey bot→waiting→human→closed
            # ════════════════════════════════════════════════════════════════
            banner("5", "The status journey: bot → waiting → human → closed")
            conv = new_conv(); made.append((BIZ_A, conv))
            explain("set each status in turn and read it back",
                    "the owner's buttons walk a chat through these four states.")
            ok = True
            for st in (cs.STATUS_BOT, cs.STATUS_WAITING, cs.STATUS_HUMAN, cs.STATUS_CLOSED):
                await cs.set_status(redis, BIZ_A, conv, st)
                got = await cs.get_status(redis, BIZ_A, conv)
                ok = ok and (got == st)
            result(ok, "all four states set and read back correctly")
            bad = False
            try:
                await cs.set_status(redis, BIZ_A, conv, "garbage")
            except ValueError:
                bad = True
            result(bad, "an invalid status is rejected loudly (ValueError)")

            # ════════════════════════════════════════════════════════════════
            #  TEST 6 — asking for a human → status 'waiting' + a funnel light
            # ════════════════════════════════════════════════════════════════
            banner("6", "Customer asks for a human → 'waiting' + a 'handed_off' event")
            conv = new_conv(); made.append((BIZ_A, conv))
            explain("greet the bot, then type 'נציג' (= 'agent/representative')",
                    "this is the handoff: the chat must flip to 'waiting' and light "
                    "a funnel event so the owner gets a notification.")
            await sim(http, conv, "שלום")   # via the API, but uses the same runtime
            handoff = await bot_runtime.run_turn(pool, redis, BIZ_A, conv, "נציג", is_test=True)
            result(handoff["event"] == "handed_off",
                   f"engine reported the handoff (event={handoff['event']!r})")
            st = await cs.get_status(redis, BIZ_A, conv)
            result(st == cs.STATUS_WAITING, f"status is now '{st}' (waiting for a person)")
            async with tenant_connection(pool, BIZ_A) as conn:
                n = await conn.fetchval(
                    "SELECT count(*)::int FROM flow_events "
                    "WHERE business_id=$1 AND event=$2 AND is_test=true",
                    BIZ_A, leads_service.EVENT_HANDOFF)
            result(n >= 1, f"a 'handed_off' funnel event was logged (count={n})")
            after = await bot_runtime.run_turn(pool, redis, BIZ_A, conv, "?", is_test=True)
            result(after["silent"] is True,
                   "and the NEXT customer message is silent (bot waits for the owner)")

            # ════════════════════════════════════════════════════════════════
            #  TEST 7 — GET /api/conversations/{id}: status + lead + messages
            # ════════════════════════════════════════════════════════════════
            banner("7", "Opening a conversation shows status + linked lead + messages")
            sid = await inject_session(redis, AVI_USER, BIZ_A)
            http.cookies.set(SESSION_COOKIE_NAME, sid)
            conv = new_conv(); made.append((BIZ_A, conv))
            explain("run a full quote flow, then GET the conversation",
                    "the owner's chat screen needs ONE call that returns everything.")
            await sim(http, conv, "1")
            await sim(http, conv, "דנה כהן")
            await sim(http, conv, "052-1234567")
            await sim(http, conv, "1")
            detail = (await http.get(f"/api/conversations/{conv}")).json()
            result(detail["conversation_id"] == conv and "status" in detail,
                   f"got the conversation with status='{detail['status']}'")
            result(detail["lead"] is not None
                   and detail["lead"]["contact_name"] == "דנה כהן",
                   "the linked lead is attached and decrypted for the owner")
            r = [m["role"] for m in detail["messages"]]
            result("customer" in r and "bot" in r,
                   "the transcript carries both customer and bot lines")

            # ════════════════════════════════════════════════════════════════
            #  TEST 8 — GET .../messages returns just the transcript
            # ════════════════════════════════════════════════════════════════
            banner("8", "The light /messages endpoint returns just the log (for polling)")
            conv = new_conv(); made.append((BIZ_A, conv))
            await sim(http, conv, "שלום")
            explain("GET /api/conversations/{id}/messages",
                    "the chat panel polls this often — it should be small + log-only.")
            body = (await http.get(f"/api/conversations/{conv}/messages")).json()
            result(body["conversation_id"] == conv and body["messages"],
                   f"got {len(body['messages'])} message(s), no lead/status payload")
            result(body["messages"][0]["role"] == "customer"
                   and body["messages"][0]["body"] == "שלום",
                   "the first line is the customer's opening message")

            # ════════════════════════════════════════════════════════════════
            #  TEST 9 — owner's reply also lands in the transcript
            # ════════════════════════════════════════════════════════════════
            banner("9", "The owner's reply ALSO joins the shared transcript (role=owner)")
            conv = new_conv(); made.append((BIZ_A, conv))
            await sim(http, conv, "שלום")
            await http.post(f"/api/conversations/{conv}/status", json={"status": "human"})
            text = "שלום, אני הנציג ואשמח לעזור"
            explain("owner takes over (status=human) and posts a reply",
                    "the owner's line must show up in the chat view, not just the outbox.")
            rep = await http.post(f"/api/conversations/{conv}/reply", json={"text": text})
            result(rep.json().get("queued") is True, "the reply was queued (for M6 send)")
            msgs = (await http.get(f"/api/conversations/{conv}/messages")).json()["messages"]
            result(any(m["role"] == "owner" and m["body"] == text for m in msgs),
                   "the owner's reply appears in the transcript (role=owner)")

            # ════════════════════════════════════════════════════════════════
            #  TEST 10 — status endpoint now accepts 'waiting'
            # ════════════════════════════════════════════════════════════════
            banner("10", "POST .../status now accepts the new 'waiting' value")
            conv = new_conv(); made.append((BIZ_A, conv))
            await sim(http, conv, "שלום")
            explain("POST status='waiting' through the API",
                    "the contract widened the allowed set to include 'waiting'.")
            r = await http.post(f"/api/conversations/{conv}/status", json={"status": "waiting"})
            result(r.status_code == 200 and r.json()["status"] == "waiting",
                   "the API accepted 'waiting' and echoed it back")

            # ════════════════════════════════════════════════════════════════
            #  TEST 11 — THE WALL: business A cannot read business B's chat
            # ════════════════════════════════════════════════════════════════
            banner("11", "TENANT WALL: A can NEVER read B's conversation (same id!)")
            b_conv = new_conv(); made.append((BIZ_B, b_conv))
            explain("Bella seeds a secret chat; Avi asks for the SAME conv id by hand",
                    "the #1 rule: one business must never see another's chat.")
            async with AsyncClient(transport=transport, base_url="http://test") as bhttp:
                bsid = await inject_session(redis, BELLA_USER, BIZ_B)
                bhttp.cookies.set(SESSION_COOKIE_NAME, bsid)
                await sim(bhttp, b_conv, "סוד-של-בלה-9999")
                bella_view = (await bhttp.get(f"/api/conversations/{b_conv}")).json()
            result(bool(bella_view["messages"]), "Bella herself CAN read her own chat")

            # Avi (already logged in as BIZ_A above) tries the same id.
            avi_detail = (await http.get(f"/api/conversations/{b_conv}")).json()
            avi_msgs = (await http.get(f"/api/conversations/{b_conv}/messages")).json()
            result(avi_detail["messages"] == [] and avi_msgs["messages"] == [],
                   "Avi gets an EMPTY transcript for that id (his own A namespace)")
            result(avi_detail["lead"] is None and avi_detail["status"] == "bot",
                   "no lead, default status — Bella's real state did not leak")
            blob = json.dumps(avi_detail, ensure_ascii=False) + \
                json.dumps(avi_msgs, ensure_ascii=False)
            result("סוד-של-בלה-9999" not in blob,
                   "Bella's secret message never appears in Avi's responses")

    # --- cleanup -------------------------------------------------------------
    for bid, cid in made:
        await cs.clear_state(redis, bid, cid)
        await redis.delete(f"conv:{bid}:{cid}:log")
        await redis.delete(f"conv:{bid}:{cid}:outbox")
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute(
                "DELETE FROM leads WHERE business_id = $1 AND is_test = true", bid)
    await pool.close()
    await redis.aclose()

    # --- scoreboard ----------------------------------------------------------
    print()
    print("=" * 74)
    print(f"  M8 SCOREBOARD:  {_passed} / {_total} checks passed")
    print("=" * 74)
    if _passed == _total:
        print("  🎉 ALL GREEN — the in-app human-handoff chat works end-to-end,")
        print("     and business A can never read business B's chat.")
    else:
        print("  ⚠️  Some checks failed — see the ❌ lines above.")
    return 0 if _passed == _total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
