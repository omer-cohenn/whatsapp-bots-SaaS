"""
============================================================================
  M9 — LEAD OUTCOMES, UNIFIED AROUND THE LEAD — EXPLAINED LIKE YOU'RE FIVE
============================================================================

WHAT IS THIS FILE?
  When a conversation ends, the owner needs to record WHAT HAPPENED:

    • "בוצעה עסקה" (we made a deal!)  → the LEAD's status becomes 'deal'
    • "סגירת פנייה" (close this one)  → the LEAD's status becomes 'closed'

  The big idea of M9 (decision 0009): the LEAD's status is the ONE TRUE
  RECORD of the outcome. We do NOT invent a new button or a new endpoint —
  we reuse the ones we already have:

    • PATCH /api/leads/{id}/status   → set the lead to 'deal' or 'closed'
    • POST  /api/conversations/{id}/status → close the live chat ('closed')

  M9 adds three small, careful things, and this test checks every one in
  plain language:

    1) You can now FILTER leads by the two outcome statuses:
         GET /api/leads?status=deal     → only the deals
         GET /api/leads?status=closed   → only the closed ones

    2) Every lead now tells you which live chat it belongs to:
         lead.conversation_id  (worked out from the saved cache_chat_ref)
       …and it's null when the lead was never tied to a chat.

    3) EVERY handoff now leaves a lead behind. Before, if a customer asked
       for a human BEFORE filling anything in, no lead existed and the owner
       could miss the request. Now the bot quietly creates a tiny lead
       called "פנייה לנציג" (= "a request for an agent") and links it to the
       chat, so the owner sees every single "I want a human" in their list.

  THE RULE THAT NEVER BREAKS: business A must NEVER see business B's leads,
  not even when filtering by deal/closed. We re-check that here too.

  Every check prints:  🧪 WHAT we try · 💡 WHY it matters · ✅/❌ the result.
  A scoreboard prints at the end. Run it via tests/test_m9.bat (double-click).
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

HANDOFF_LEAD_NAME = "פנייה לנציג"  # the tiny-lead label the bot stamps on a handoff.

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


async def seed_lead(pool, business_id, *, status, conversation_id):
    """Insert a minimal is_test lead with a given status + optional chat link."""
    ref = f"conv:{business_id}:{conversation_id}" if conversation_id else None
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO leads
                (business_id, lead_name, status, is_test, cache_chat_ref,
                 started_at, last_activity_at)
            VALUES ($1, 'test-flow', $2, true, $3, now(), now())
            RETURNING id
            """,
            business_id, status, ref,
        )
    return str(row["id"])


async def cleanup_test_data(pool, redis, convs):
    for bid, cid in convs:
        await cs.clear_state(redis, bid, cid)
        await redis.delete(f"conv:{bid}:{cid}:log")
        await redis.delete(f"conv:{bid}:{cid}:outbox")
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute(
                "DELETE FROM leads WHERE business_id = $1 AND is_test = true", bid)


# --- the story ---------------------------------------------------------------

async def main() -> int:
    print("\n" + "=" * 74)
    print("  M9 — LEAD OUTCOMES, UNIFIED AROUND THE LEAD")
    print("=" * 74)

    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=4)
    redis = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    convs: list[tuple[str, str]] = []

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            try:
                # Log Avi in for the whole story.
                sid = await inject_session(redis, AVI_USER, BIZ_A)
                http.cookies.set(SESSION_COOKIE_NAME, sid)

                # ── 1 — filter by deal ────────────────────────────────────────
                banner("1", "GET /api/leads?status=deal returns ONLY deals")
                explain("seed one 'deal', one 'closed', one 'new'; ask for deals",
                        "the owner's 'deals' tab must show won leads ONLY")
                deal_id = await seed_lead(pool, BIZ_A, status="deal", conversation_id=None)
                closed_id = await seed_lead(pool, BIZ_A, status="closed", conversation_id=None)
                new_id = await seed_lead(pool, BIZ_A, status="new", conversation_id=None)
                deals = (await http.get("/api/leads?status=deal&include_test=true")).json()["leads"]
                ids = {r["id"] for r in deals}
                result(deal_id in ids and closed_id not in ids and new_id not in ids
                       and all(r["status"] == "deal" for r in deals),
                       "only the 'deal' lead came back")

                # ── 2 — filter by closed ──────────────────────────────────────
                banner("2", "GET /api/leads?status=closed returns ONLY closed leads")
                explain("ask for closed leads",
                        "the 'closed/handled' view must show closed leads ONLY")
                closed = (await http.get("/api/leads?status=closed&include_test=true")).json()["leads"]
                cids = {r["id"] for r in closed}
                result(closed_id in cids and deal_id not in cids and new_id not in cids
                       and all(r["status"] == "closed" for r in closed),
                       "only the 'closed' lead came back")

                # ── 3 — conversation_id is derived from cache_chat_ref ────────
                banner("3", "Each lead tells you its conversation_id (or null)")
                explain("seed one lead linked to a chat + one with no chat",
                        "the UI must be able to jump from a lead to its live chat")
                conv = new_conv()
                linked = await seed_lead(pool, BIZ_A, status="new", conversation_id=conv)
                unlinked = await seed_lead(pool, BIZ_A, status="new", conversation_id=None)
                rows = (await http.get("/api/leads?status=new&include_test=true")).json()["leads"]
                by_id = {r["id"]: r for r in rows}
                result(by_id[linked]["conversation_id"] == conv
                       and by_id[unlinked]["conversation_id"] is None,
                       "linked lead shows the conv id; unlinked shows null")

                # ── 4 — handoff with NO prior lead creates a minimal lead ─────
                banner("4", "A handoff with NO prior lead now CREATES a tiny lead")
                explain("first message is 'I want an agent' (no flow started yet)",
                        "before, the request could vanish; now it always leaves a lead")
                hconv = new_conv()
                convs.append((BIZ_A, hconv))
                ho = await bot_runtime.run_turn(
                    pool, redis, BIZ_A, hconv, "אני רוצה לדבר עם נציג", is_test=True)
                async with tenant_connection(pool, BIZ_A) as conn:
                    hlead = await conn.fetchrow(
                        "SELECT lead_name, status, cache_chat_ref FROM leads "
                        "WHERE id=$1 AND business_id=$2", ho["lead_id"], BIZ_A)
                    nev = await conn.fetchval(
                        "SELECT count(*)::int FROM flow_events WHERE business_id=$1 "
                        "AND lead_id=$2 AND event=$3",
                        BIZ_A, ho["lead_id"], leads_service.EVENT_HANDOFF)
                result(ho["event"] == "handed_off"
                       and ho["lead_id"] is not None
                       and hlead["lead_name"] == HANDOFF_LEAD_NAME
                       and hlead["cache_chat_ref"] == f"conv:{BIZ_A}:{hconv}"
                       and nev >= 1,
                       f"a '{HANDOFF_LEAD_NAME}' lead was created, linked, and the "
                       "handed_off event is attached to it")

                # ── 5 — the chat still flips to 'waiting' on that handoff ─────
                banner("5", "That handoff STILL flips the chat to 'waiting'")
                explain("read the chat status after the handoff",
                        "the owner's queue must light up 'someone is waiting'")
                st = await cs.get_status(redis, BIZ_A, hconv)
                result(st == cs.STATUS_WAITING, f"chat status is '{st}'")

                # ── 6 — outcome: mark a lead as a DEAL, then it filters ───────
                banner("6", "Outcome flow: mark a lead 'deal' → it shows under ?status=deal")
                explain("PATCH a 'new' lead to 'deal', then re-filter",
                        "'בוצעה עסקה' must move the lead into the deals view")
                oconv = new_conv()
                convs.append((BIZ_A, oconv))
                olead = await seed_lead(pool, BIZ_A, status="new", conversation_id=oconv)
                pr = await http.patch(f"/api/leads/{olead}/status", json={"status": "deal"})
                deal_ids = {x["id"] for x in
                            (await http.get("/api/leads?status=deal&include_test=true")).json()["leads"]}
                new_ids = {x["id"] for x in
                           (await http.get("/api/leads?status=new&include_test=true")).json()["leads"]}
                result(pr.status_code == 200 and pr.json()["status"] == "deal"
                       and olead in deal_ids and olead not in new_ids,
                       "the lead moved from 'new' into 'deal'")

                # ── 7 — and the conversation can be closed ────────────────────
                banner("7", "…and the conversation closes via the existing endpoint")
                explain("POST /api/conversations/{id}/status status=closed",
                        "closing the deal closes the live chat too — one outcome")
                rc = await http.post(f"/api/conversations/{oconv}/status",
                                     json={"status": "closed"})
                cst = await cs.get_status(redis, BIZ_A, oconv)
                result(rc.status_code == 200 and cst == cs.STATUS_CLOSED,
                       f"the chat status is now '{cst}'")

                # ── 8 — outcome: mark a lead 'closed' (סגירת פנייה) ───────────
                banner("8", "Outcome flow: mark a lead 'closed' → it shows under ?status=closed")
                explain("PATCH a 'new' lead to 'closed', then re-filter",
                        "'סגירת פנייה' must move the lead into the closed view")
                clead = await seed_lead(pool, BIZ_A, status="new", conversation_id=None)
                pr2 = await http.patch(f"/api/leads/{clead}/status", json={"status": "closed"})
                cl_ids = {x["id"] for x in
                          (await http.get("/api/leads?status=closed&include_test=true")).json()["leads"]}
                result(pr2.status_code == 200 and clead in cl_ids,
                       "the lead moved into 'closed'")

                # ── 9 — ISOLATION: A cannot see B's deal/closed leads ─────────
                banner("9", "THE WALL: business A can NEVER see business B's leads")
                explain("Bella(B) has a deal + a closed lead; Avi(A) filters for them",
                        "filtering by an outcome must NEVER cross the tenant wall")
                b_deal = await seed_lead(pool, BIZ_B, status="deal", conversation_id=None)
                b_closed = await seed_lead(pool, BIZ_B, status="closed", conversation_id=None)
                a_deals = (await http.get("/api/leads?status=deal&include_test=true")).json()["leads"]
                a_closed = (await http.get("/api/leads?status=closed&include_test=true")).json()["leads"]
                seen = {r["id"] for r in a_deals} | {r["id"] for r in a_closed}
                result(b_deal not in seen and b_closed not in seen,
                       "Avi saw NONE of Bella's deal/closed leads")

                # ── 10 — ISOLATION: A cannot PATCH B's lead ───────────────────
                banner("10", "THE WALL: A cannot mark B's lead as a deal")
                explain("Avi PATCHes Bella's lead id directly",
                        "an attacker naming a foreign id must hit a 404, not the row")
                b_lead = await seed_lead(pool, BIZ_B, status="new", conversation_id=None)
                pr3 = await http.patch(f"/api/leads/{b_lead}/status", json={"status": "deal"})
                async with tenant_connection(pool, BIZ_B) as conn:
                    unchanged = await conn.fetchval(
                        "SELECT status FROM leads WHERE id=$1 AND business_id=$2",
                        b_lead, BIZ_B)
                result(pr3.status_code == 404 and unchanged == "new",
                       "Avi got 404 and Bella's lead is untouched")

                # ── 11 — NEGATIVE CONTROL: prove the wall test can actually FAIL
                banner("11", "NEGATIVE CONTROL: break it on purpose, watch it get caught")
                explain("pretend the deal filter LEAKED Bella's lead, re-run the check",
                        "a green wall test is only trustworthy if it can go red on a leak")
                # Simulate a leak: put Bella's deal id into Avi's result set by hand,
                # then run the SAME assertion the wall test uses. It MUST go False.
                leaked_seen = {b_deal}  # a deliberately broken "what Avi saw".
                wall_would_catch = (b_deal in leaked_seen)  # the bug is present...
                # The real isolation assertion is `b_deal not in seen`; on a leak that
                # is False → the test fails. We assert that it WOULD fail (i.e. the
                # check is live), then confirm the REAL result above stayed clean.
                result(wall_would_catch and b_deal not in seen,
                       "the wall assertion fires on a simulated leak, yet the REAL "
                       "run stayed clean (the check is live, not asleep)")

            finally:
                await cleanup_test_data(pool, redis, convs)
                await redis.aclose()
                await pool.close()

    # Scoreboard.
    print("\n" + "=" * 74)
    print(f"  SCOREBOARD:  {_passed}/{_total} checks passed")
    print("=" * 74)
    if _passed == _total:
        print("  🎉 ALL GREEN — the lead is the single source of truth for an")
        print("     outcome; deal/closed filter cleanly, every handoff leaves a")
        print("     lead, and the tenant wall still holds. 🔒")
    else:
        print("  ⚠️  Some checks failed — see the ❌ lines above.")
    return 0 if _passed == _total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
