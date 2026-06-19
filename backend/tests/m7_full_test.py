"""
============================================================================
  M7 — THE OWNER DASHBOARD (back-office) — FULL TEST, EXPLAINED LIKE YOU'RE FIVE
============================================================================

WHAT IS THIS FILE?
  M5 made the bot REMEMBER (it writes leads + a funnel + a live conversation).
  M7 is the OWNER'S WINDOW into all of that — the back-office screens:

    * GET  /api/leads          → "show me everyone who wrote in", with their
                                  REAL (decrypted) phone / name / every answer,
                                  and filters (which week, which status, which
                                  questionnaire). Practice ('is_test') leads are
                                  hidden unless asked for.
    * GET  /api/dashboard      → the funnel numbers (how many started / finished
                                  / gave up / total) for a time window.
    * GET  /api/conversations  → the live chats happening right now, ONLY mine.
    * POST .../status          → flip a chat between bot / human / closed.
    * POST .../reply           → the owner types a manual reply (queued for M6).
    * PUT  /api/bot/publish     → the go-live switch (and GET /api/bot/settings
                                  must reflect it).

  THE RULE THAT CAN NEVER BREAK: business A's dashboard must NEVER show business
  B's leads, numbers, or chats — and every one of these doors is locked (401)
  to anyone without a login.

  HOW WE TEST IT FOR REAL:
    First we SEED REAL DATA by driving full conversations through the real
    endpoint POST /api/bot/sim (the same door the bot uses) — so genuine leads,
    funnel events, and a live conversation actually exist. Then we open the M7
    windows and check what the owner sees.

  Every check prints:  🧪 WHAT we try · 💡 WHY it matters · ✅/❌ the result.

  Run it with tests/test_m7.bat (double-click), or read HOW-TO at the bottom.
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
from app.services import bot_runtime, conversation_state
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

# The two pretend businesses (fixed ids from supabase/seed.sql).
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (published bot)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (draft bot)
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

# Avi's seeded 'quote' flow has 3 steps: full_name(text) → phone(phone)
# → insurance_type(choice of 4). What we'll type as a customer:
A_NAME = "דנה כהן"
A_PHONE = "052-1234567"
A_PHONE_DIGITS = "0521234567"     # the engine normalizes phones to digits-only
A_CHOICE = "רכב"                  # option #1 in Avi's insurance_type step

# A second, DIFFERENT customer for Avi (so we have >1 lead + a partial/abandon).
A2_NAME = "יוסי לוי"
A2_PHONE = "054-7654321"

# Bella's seeded 'appointment' flow: full_name(text) → phone(phone).
B_NAME = "שרה בלה-לקוחה"
B_PHONE = "050-9999999"

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

async def inject_session(redis, user_id: str, business_id: str, name: str) -> str:
    """Pretend this owner just logged in: drop a real session blob into Redis."""
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": f"{user_id}@example.com", "name": user_id,
        "picture": "", "business_id": business_id, "business_name": name,
        "created_at": int(time.time()),
    }
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    return sid


async def drive_quote(http, conv_id, name, phone) -> dict:
    """Drive Avi's full 3-step 'quote' flow to completion. Returns the start resp."""
    start = (await http.post("/api/bot/sim",
                             json={"message": "1", "conversation_id": conv_id})).json()
    await http.post("/api/bot/sim", json={"message": name, "conversation_id": conv_id})
    await http.post("/api/bot/sim", json={"message": phone, "conversation_id": conv_id})
    await http.post("/api/bot/sim", json={"message": "1", "conversation_id": conv_id})  # choice
    return start


# ============================================================================
#  THE TESTS
# ============================================================================

async def run() -> int:
    app_dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]
    pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=3)
    redis = aioredis.from_url(redis_url, decode_responses=True)

    made_conv_ids: list[tuple[str, str]] = []
    sids: list[str] = []

    async with app.router.lifespan_context(app):
        # raise_app_exceptions=False so an in-process 500 surfaces as an HTTP 500
        # response (what a real browser sees) instead of re-raising into the test
        # — lets us cleanly DETECT + report a server error rather than crash.
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:

            # ════════════════════════════════════════════════════════════════
            #  PART 0 — SEED REAL DATA via the real bot door (/api/bot/sim)
            # ════════════════════════════════════════════════════════════════
            #  NOTE: the sim path tags everything is_test=true, so to test the
            #  "is_test excluded by default" rule we ALSO need at least one REAL
            #  (is_test=false) lead. We create those by calling run_turn with
            #  is_test=False directly (same runtime the real WhatsApp path uses).
            #
            #  Plan of seeded REAL (is_test=false) data for Avi:
            #    * lead #1: a COMPLETED quote (Dana)       → status 'new'
            #    * lead #2: a PARTIAL  quote (Yossi, name only) → 'in_progress' ('open')
            #    * one LIVE conversation flipped to 'human'
            #  And for Bella: one COMPLETED appointment (Sara) — used to prove
            #  isolation (A must never see it).

            print("\n  ⏳ Seeding REAL conversations via the bot runtime ...")

            # --- Avi: a completed real lead (Dana) ---------------------------
            a_done_conv = f"sim:{secrets.token_hex(8)}"
            made_conv_ids.append((BIZ_A, a_done_conv))
            s1 = await bot_runtime.run_turn(pool, redis, BIZ_A, a_done_conv, "1")
            await bot_runtime.run_turn(pool, redis, BIZ_A, a_done_conv, A_NAME)
            await bot_runtime.run_turn(pool, redis, BIZ_A, a_done_conv, A_PHONE)
            done = await bot_runtime.run_turn(pool, redis, BIZ_A, a_done_conv, "1")
            a_done_lead = done["lead_id"] or s1["lead_id"]

            # --- Avi: a partial real lead (Yossi, name only → 'in_progress') -
            a_open_conv = f"sim:{secrets.token_hex(8)}"
            made_conv_ids.append((BIZ_A, a_open_conv))
            s2 = await bot_runtime.run_turn(pool, redis, BIZ_A, a_open_conv, "1")
            await bot_runtime.run_turn(pool, redis, BIZ_A, a_open_conv, A2_NAME)
            a_open_lead = s2["lead_id"]

            # --- Avi: a live conversation we will flip to 'human' ------------
            a_live_conv = f"sim:{secrets.token_hex(8)}"
            made_conv_ids.append((BIZ_A, a_live_conv))
            await bot_runtime.run_turn(pool, redis, BIZ_A, a_live_conv, "שלום")

            # --- Bella: a completed real lead (Sara) — for isolation ---------
            b_done_conv = f"sim:{secrets.token_hex(8)}"
            made_conv_ids.append((BIZ_B, b_done_conv))
            await bot_runtime.run_turn(pool, redis, BIZ_B, b_done_conv, "1")
            await bot_runtime.run_turn(pool, redis, BIZ_B, b_done_conv, B_NAME)
            await bot_runtime.run_turn(pool, redis, BIZ_B, b_done_conv, B_PHONE)
            await bot_runtime.run_turn(pool, redis, BIZ_B, b_done_conv, "1")  # ignored extra

            # --- Avi: a TEST (is_test=true) lead via the real /api/bot/sim ---
            # We log Avi in first; this also seeds the cookie for every check below.
            sid_a = await inject_session(redis, AVI_USER, BIZ_A, "Avi Insurance")
            sids.append(sid_a)
            http.cookies.set(SESSION_COOKIE_NAME, sid_a)
            a_test_conv = f"sim:{secrets.token_hex(8)}"
            made_conv_ids.append((BIZ_A, a_test_conv))
            await drive_quote(http, a_test_conv, "בודק טסט", "050-0000000")

            print("  ✅ Seed complete: Avi has a completed + a partial REAL lead, a "
                  "live chat, and a TEST lead; Bella has a completed REAL lead.\n")

            # ════════════════════════════════════════════════════════════════
            #  PART 1 — GET /api/leads (decrypted, filters, is_test excluded)
            # ════════════════════════════════════════════════════════════════

            # ── 1 — every M7 door is locked without a login (401) ────────────
            banner("1", "All M7 doors are LOCKED to strangers (401, no session)")
            explain("hit each M7 endpoint with NO login cookie",
                    "these screens expose decrypted PII + a tenant's whole funnel "
                    "— they must ALL sit behind the deny-by-default login wall.")
            async with AsyncClient(transport=transport, base_url="http://test") as anon:
                codes = {
                    "GET /leads": (await anon.get("/api/leads")).status_code,
                    "GET /dashboard": (await anon.get("/api/dashboard")).status_code,
                    "GET /conversations": (await anon.get("/api/conversations")).status_code,
                    "POST /conv/status": (await anon.post(
                        "/api/conversations/x/status", json={"status": "bot"})).status_code,
                    "POST /conv/reply": (await anon.post(
                        "/api/conversations/x/reply", json={"text": "hi"})).status_code,
                    "PUT /bot/publish": (await anon.put(
                        "/api/bot/publish", json={"is_published": True})).status_code,
                }
            all_401 = all(c == 401 for c in codes.values())
            result(all_401, f"every M7 door said 401 to a stranger: {codes}")

            # ── 2 — GET /api/leads returns DECRYPTED phone/name/answers ──────
            banner("2", "GET /api/leads shows the owner the REAL phone / name / answers")
            explain("read Avi's leads and find Dana's completed lead",
                    "the owner is the ONE party allowed to see plaintext — the API "
                    "must decrypt phone, contact_name and EVERY collected answer "
                    "(full detail, no hiding).")
            leads = (await http.get("/api/leads")).json()["leads"]
            dana = next((l for l in leads if l["id"] == a_done_lead), None)
            ok = (dana is not None
                  and dana["phone"] == A_PHONE_DIGITS
                  and dana["contact_name"] == A_NAME
                  and dana["lead_name"] == "quote"
                  and dana["status"] == "new"
                  and dana["answers"].get("full_name") == A_NAME
                  and dana["answers"].get("phone") == A_PHONE_DIGITS
                  and dana["answers"].get("insurance_type") == A_CHOICE)
            result(ok, "Dana's lead came back DECRYPTED: phone={}, name={}, every "
                   "answer present (insurance_type={})".format(
                       dana["phone"] if dana else "?",
                       dana["contact_name"] if dana else "?",
                       dana["answers"].get("insurance_type") if dana else "?"))

            # ── 3 — is_test excluded by DEFAULT, included on request ─────────
            banner("3", "Practice ('is_test') leads are hidden by default")
            explain("list leads with no flag, then with include_test=true",
                    "the try-me/sim drills must NOT pollute the owner's real list "
                    "— but the owner can still opt in to see them.")
            default_leads = (await http.get("/api/leads")).json()["leads"]
            with_test = (await http.get("/api/leads?include_test=true")).json()["leads"]
            any_test_in_default = any(l["is_test"] for l in default_leads)
            any_test_in_optin = any(l["is_test"] for l in with_test)
            ok = (not any_test_in_default
                  and any_test_in_optin
                  and len(with_test) > len(default_leads))
            result(ok, f"default list had {len(default_leads)} leads (0 test); "
                   f"include_test=true had {len(with_test)} (test leads now shown)")

            # ── 4 — status filter, incl. the synthetic 'open' ───────────────
            banner("4", "Status filter works (new / in_progress / abandoned / 'open')")
            explain("filter status=new, status=in_progress, status=open",
                    "'open' is a made-up bucket = new + in_progress (everything "
                    "still actionable). Each filter must return only matching rows.")
            new_only = (await http.get("/api/leads?status=new")).json()["leads"]
            inprog = (await http.get("/api/leads?status=in_progress")).json()["leads"]
            open_b = (await http.get("/api/leads?status=open")).json()["leads"]
            has_done_in_new = any(l["id"] == a_done_lead for l in new_only)
            has_open_in_inprog = any(l["id"] == a_open_lead for l in inprog)
            new_all_new = all(l["status"] == "new" for l in new_only)
            inprog_all = all(l["status"] == "in_progress" for l in inprog)
            open_all = all(l["status"] in ("new", "in_progress") for l in open_b)
            open_has_both = (any(l["id"] == a_done_lead for l in open_b)
                             and any(l["id"] == a_open_lead for l in open_b))
            ok = (has_done_in_new and new_all_new
                  and has_open_in_inprog and inprog_all
                  and open_all and open_has_both)
            result(ok, f"status=new→{len(new_only)} (all 'new', has Dana); "
                   f"status=in_progress→{len(inprog)} (all 'in_progress', has Yossi); "
                   f"status=open→{len(open_b)} (new+in_progress, has BOTH)")

            # ── 5 — flow filter ─────────────────────────────────────────────
            banner("5", "Flow filter narrows to one questionnaire (lead_name)")
            explain("filter flow=quote, then flow=nonexistent",
                    "an owner with several questionnaires must be able to see just "
                    "one flow's leads; an unknown flow returns nothing.")
            quote_only = (await http.get("/api/leads?flow=quote")).json()["leads"]
            none_flow = (await http.get("/api/leads?flow=__nope__")).json()["leads"]
            ok = (len(quote_only) >= 2
                  and all(l["lead_name"] == "quote" for l in quote_only)
                  and none_flow == [])
            result(ok, f"flow=quote→{len(quote_only)} (all 'quote'); "
                   f"flow=__nope__→{len(none_flow)} (empty)")

            # ── 6 — period filter (week vs all) ─────────────────────────────
            banner("6", "Period filter (week|month|all) bounds the time window")
            explain("compare period=all to a narrow window via back-dating one "
                    "lead, then period=week",
                    "the owner picks a time window; leads older than it must drop "
                    "out of the list.")
            # Back-date Yossi's partial lead ~40 days so 'week' and 'month' exclude it.
            async with tenant_connection(pool, BIZ_A) as conn:
                await conn.execute(
                    "UPDATE leads SET last_activity_at = now() - interval '40 days' "
                    "WHERE id = $1 AND business_id = $2", a_open_lead, BIZ_A)
            week_resp = await http.get("/api/leads?period=week")
            all_after = (await http.get("/api/leads?period=all")).json()["leads"]
            if week_resp.status_code != 200:
                # KNOWN BUG (see report): period=week|month 500s because
                # leads._period_clause binds a str to $N::interval and asyncpg
                # needs a timedelta.
                result(False, "GET /api/leads?period=week returned HTTP {} (expected "
                       "200). BUG: leads._period_clause passes a STRING '7 days' to "
                       "$N::interval — asyncpg needs a datetime.timedelta.".format(
                           week_resp.status_code))
            else:
                week = week_resp.json()["leads"]
                yossi_in_all = any(l["id"] == a_open_lead for l in all_after)
                yossi_in_week = any(l["id"] == a_open_lead for l in week)
                ok = (yossi_in_all and not yossi_in_week and len(week) < len(all_after))
                result(ok, f"period=all still shows the 40-day-old lead "
                       f"({len(all_after)} total); period=week dropped it "
                       f"({len(week)} recent) — window works")
            # restore Yossi's date so later checks are unaffected.
            async with tenant_connection(pool, BIZ_A) as conn:
                await conn.execute(
                    "UPDATE leads SET last_activity_at = now() "
                    "WHERE id = $1 AND business_id = $2", a_open_lead, BIZ_A)

            # ════════════════════════════════════════════════════════════════
            #  PART 2 — GET /api/dashboard (funnel counts)
            # ════════════════════════════════════════════════════════════════
            banner("7", "GET /api/dashboard funnel counts match the seeded data")
            explain("compare /api/dashboard numbers to the raw DB truth",
                    "the funnel (started / completed / abandoned / total) drives "
                    "the owner's whole sense of how the bot is doing — it must be "
                    "exactly right and exclude practice (is_test) data.")
            dash = (await http.get("/api/dashboard?period=all")).json()
            # Ground truth straight from the DB (real, non-test only).
            async with tenant_connection(pool, BIZ_A) as conn:
                ev = {r["event"]: r["n"] for r in await conn.fetch(
                    "SELECT event, count(*)::int n FROM flow_events "
                    "WHERE business_id=$1 AND is_test=false GROUP BY event", BIZ_A)}
                true_total = await conn.fetchval(
                    "SELECT count(*)::int FROM leads WHERE business_id=$1 "
                    "AND is_test=false", BIZ_A)
            ok = (dash["started"] == ev.get("started", 0)
                  and dash["completed"] == ev.get("completed", 0)
                  and dash["abandoned"] == ev.get("abandoned", 0)
                  and dash["total_leads"] == true_total)
            result(ok, "dashboard funnel matches DB: started={s}, completed={c}, "
                   "abandoned={a}, total={t}".format(
                       s=dash["started"], c=dash["completed"],
                       a=dash["abandoned"], t=dash["total_leads"]))

            # ── 8 — dashboard respects the period filter ────────────────────
            banner("8", "Dashboard respects the period filter too")
            explain("back-date Dana's whole funnel ~40 days, compare week vs all",
                    "the funnel must answer 'this week' differently from 'all "
                    "time' — older events drop out of the narrow window.")
            async with tenant_connection(pool, BIZ_A) as conn:
                await conn.execute(
                    "UPDATE flow_events SET created_at = now() - interval '40 days' "
                    "WHERE business_id=$1 AND lead_id=$2", BIZ_A, a_done_lead)
                await conn.execute(
                    "UPDATE leads SET started_at = now() - interval '40 days' "
                    "WHERE business_id=$1 AND id=$2", BIZ_A, a_done_lead)
            d_all = (await http.get("/api/dashboard?period=all")).json()
            d_week_resp = await http.get("/api/dashboard?period=week")
            if d_week_resp.status_code != 200:
                # SAME KNOWN BUG as check 6: funnel_stats also uses _period_clause.
                result(False, "GET /api/dashboard?period=week returned HTTP {} "
                       "(expected 200). SAME BUG: leads._period_clause binds a "
                       "string to $N::interval (asyncpg needs a timedelta).".format(
                           d_week_resp.status_code))
            else:
                d_week = d_week_resp.json()
                ok = (d_week["completed"] < d_all["completed"]
                      and d_week["total_leads"] < d_all["total_leads"]
                      and d_week["started"] < d_all["started"])
                result(ok, "week window is smaller than all-time: completed "
                       "{cw}<{ca}, total {tw}<{ta} (the old lead dropped out)".format(
                           cw=d_week["completed"], ca=d_all["completed"],
                           tw=d_week["total_leads"], ta=d_all["total_leads"]))

            # ════════════════════════════════════════════════════════════════
            #  PART 3 — GET /api/conversations + status + reply
            # ════════════════════════════════════════════════════════════════
            banner("9", "GET /api/conversations lists THIS tenant's live chats only")
            explain("list Avi's conversations and look for our live chat",
                    "the owner's live-chat board must show their own ongoing "
                    "conversations (status + preview + last activity).")
            convs = (await http.get("/api/conversations")).json()["conversations"]
            conv_ids = {c["conversation_id"] for c in convs}
            ok = (a_live_conv in conv_ids and len(convs) >= 1)
            result(ok, f"Avi sees {len(convs)} live conversation(s) incl. our live "
                   f"chat ({a_live_conv[:12]}...)")

            # ── 10 — POST status flips bot → human → closed ─────────────────
            banner("10", "POST /conversations/{id}/status flips bot↔human↔closed")
            explain("set the live chat to 'human', then 'closed'",
                    "the owner must be able to take over a chat (human) or end it "
                    "(closed); the change must stick.")
            r_h = (await http.post(f"/api/conversations/{a_live_conv}/status",
                                   json={"status": "human"})).json()
            after_h = await conversation_state.get_status(redis, BIZ_A, a_live_conv)
            r_c = (await http.post(f"/api/conversations/{a_live_conv}/status",
                                   json={"status": "closed"})).json()
            after_c = await conversation_state.get_status(redis, BIZ_A, a_live_conv)
            # bad status must be rejected (422).
            bad = (await http.post(f"/api/conversations/{a_live_conv}/status",
                                   json={"status": "banana"})).status_code
            ok = (r_h["status"] == "human" and after_h == "human"
                  and r_c["status"] == "closed" and after_c == "closed"
                  and bad == 422)
            result(ok, f"status went human→closed (Redis confirms: {after_c}); "
                   f"an invalid status was rejected ({bad}=422)")

            # ── 11 — POST reply appends an owner reply (preview + outbox) ────
            banner("11", "POST /conversations/{id}/reply queues an owner reply")
            explain("post a manual reply, then re-read the conversation",
                    "when a human takes over they type replies here; the reply "
                    "must be queued (for M6 to send) and become the chat preview.")
            reply_text = "תודה, נחזור אליך בהקדם"
            r_reply = (await http.post(f"/api/conversations/{a_live_conv}/reply",
                                       json={"text": reply_text})).json()
            # the preview should now reflect the reply; outbox should hold it.
            convs2 = (await http.get("/api/conversations")).json()["conversations"]
            live2 = next((c for c in convs2 if c["conversation_id"] == a_live_conv), None)
            outbox_len = await redis.llen(f"conv:{BIZ_A}:{a_live_conv}:outbox")
            # empty/oversized replies must be rejected (422).
            bad_empty = (await http.post(f"/api/conversations/{a_live_conv}/reply",
                                         json={"text": ""})).status_code
            ok = (r_reply["queued"] is True
                  and live2 is not None and reply_text in live2["preview"]
                  and outbox_len >= 1
                  and bad_empty == 422)
            result(ok, f"reply queued=true; preview now shows it; outbox has "
                   f"{outbox_len} msg(s); empty reply rejected ({bad_empty}=422)")

            # ════════════════════════════════════════════════════════════════
            #  PART 4 — PUT /api/bot/publish (reflected by GET /api/bot/settings)
            # ════════════════════════════════════════════════════════════════
            banner("12", "PUT /api/bot/publish toggles is_published (GET settings agrees)")
            explain("read settings, flip publish off then on, re-read settings",
                    "the go-live switch must persist and be visible to the builder "
                    "page (GET /api/bot/settings) — that's how the owner knows the "
                    "bot is live.")
            before = (await http.get("/api/bot/settings")).json()["is_published"]
            off = (await http.put("/api/bot/publish",
                                  json={"is_published": False})).json()
            settings_off = (await http.get("/api/bot/settings")).json()["is_published"]
            on = (await http.put("/api/bot/publish",
                                 json={"is_published": True})).json()
            settings_on = (await http.get("/api/bot/settings")).json()["is_published"]
            ok = (off["is_published"] is False and settings_off is False
                  and on["is_published"] is True and settings_on is True)
            result(ok, f"publish: was {before} → set False (settings={settings_off}) "
                   f"→ set True (settings={settings_on}); GET /settings tracks it")

            # ════════════════════════════════════════════════════════════════
            #  PART 5 — TENANT ISOLATION across every M7 read
            # ════════════════════════════════════════════════════════════════
            banner("13", "Isolation: Avi's /api/leads NEVER returns Bella's leads")
            explain("list Avi's leads, confirm NONE belong to Bella",
                    "the #1 SaaS rule. Bella's completed lead (Sara) exists; Avi's "
                    "leads endpoint must never include it. We also confirm Avi "
                    "can't see Sara's phone anywhere.")
            avi_leads = (await http.get("/api/leads?include_test=true")).json()["leads"]
            # Bella's lead ids (looked up directly, tenant-scoped).
            async with tenant_connection(pool, BIZ_B) as conn:
                bella_ids = {str(r["id"]) for r in await conn.fetch(
                    "SELECT id FROM leads WHERE business_id=$1", BIZ_B)}
            avi_ids = {l["id"] for l in avi_leads}
            no_overlap = avi_ids.isdisjoint(bella_ids)
            blob = json.dumps(avi_leads, ensure_ascii=False)
            no_sara = B_NAME not in blob and "0509999999" not in blob
            result(no_overlap and no_sara,
                   f"Avi's {len(avi_leads)} leads share NOTHING with Bella's "
                   f"{len(bella_ids)} leads; Sara's name/phone absent from Avi's data")

            # ── 14 — isolation on /api/dashboard ────────────────────────────
            banner("14", "Isolation: Avi's & Bella's dashboards are computed separately")
            explain("log Bella in, compare each owner's dashboard",
                    "each business's funnel must count ONLY its own events — "
                    "Bella's numbers must reflect Bella's data, not Avi's.")
            sid_b = await inject_session(redis, BELLA_USER, BIZ_B, "Bella Barber")
            sids.append(sid_b)
            async with AsyncClient(transport=transport, base_url="http://test") as bhttp:
                bhttp.cookies.set(SESSION_COOKIE_NAME, sid_b)
                bella_dash = (await bhttp.get("/api/dashboard?period=all")).json()
                bella_convs = (await bhttp.get("/api/conversations")).json()["conversations"]
            avi_dash = (await http.get("/api/dashboard?period=all")).json()

            # Ground truth for EACH tenant, computed independently from the DB.
            async def true_stats(bid: str) -> dict:
                async with tenant_connection(pool, bid) as conn:
                    ev = {r["event"]: r["n"] for r in await conn.fetch(
                        "SELECT event, count(*)::int n FROM flow_events "
                        "WHERE business_id=$1 AND is_test=false GROUP BY event", bid)}
                    tot = await conn.fetchval(
                        "SELECT count(*)::int FROM leads WHERE business_id=$1 "
                        "AND is_test=false", bid)
                return {"started": ev.get("started", 0),
                        "completed": ev.get("completed", 0),
                        "abandoned": ev.get("abandoned", 0), "total_leads": tot}

            b_truth = await true_stats(BIZ_B)
            a_truth = await true_stats(BIZ_A)
            # The real isolation guarantee: each owner's dashboard matches ONLY its
            # own tenant's DB truth (never the other tenant's). We do NOT require the
            # two dicts to differ — that's data-dependent, not a guarantee.
            bella_matches_own = (
                bella_dash["started"] == b_truth["started"]
                and bella_dash["completed"] == b_truth["completed"]
                and bella_dash["abandoned"] == b_truth["abandoned"]
                and bella_dash["total_leads"] == b_truth["total_leads"])
            avi_matches_own = (
                avi_dash["started"] == a_truth["started"]
                and avi_dash["completed"] == a_truth["completed"]
                and avi_dash["total_leads"] == a_truth["total_leads"])
            ok = (bella_matches_own and avi_matches_own and b_truth["completed"] >= 1)
            result(ok, "Bella's dashboard == Bella's own DB truth "
                   "(total={bt}, completed={bc}); Avi's == Avi's own (total={at}) "
                   "— each funnel reflects ONLY its tenant".format(
                       bt=bella_dash["total_leads"], bc=bella_dash["completed"],
                       at=avi_dash["total_leads"]))

            # ── 15 — isolation on /api/conversations ────────────────────────
            banner("15", "Isolation: Bella's conversation board excludes Avi's chats")
            explain("confirm Avi's live chat id is NOT in Bella's conversation list",
                    "the live-chat board is the most sensitive screen (it has "
                    "message previews); one tenant must never see another's chats.")
            bella_conv_ids = {c["conversation_id"] for c in bella_convs}
            ok = (a_live_conv not in bella_conv_ids
                  and a_done_conv not in bella_conv_ids)
            result(ok, f"Bella sees {len(bella_convs)} chat(s); none of Avi's "
                   f"conversation ids appear in her list (wall holds)")

    # ── cleanup: remove the test data we created ─────────────────────────────
    try:
        for bid, cid in made_conv_ids:
            await conversation_state.clear_state(redis, bid, cid)
            await redis.delete(f"conv:{bid}:{cid}:outbox")
        # Delete exactly the leads we created this run, matched by cache_chat_ref
        # (= conv:{business_id}:{conversation_id}). flow_events cascade. Tenant-scoped.
        for bid, cid in made_conv_ids:
            async with tenant_connection(pool, bid) as conn:
                await conn.execute(
                    "DELETE FROM leads WHERE business_id = $1 AND cache_chat_ref = $2",
                    bid, f"conv:{bid}:{cid}")
        # restore Bella's draft state + Avi's published state (we toggled Avi).
        from app.services import bot_settings as bs
        await bs.set_published(pool, BIZ_A, True)
        await bs.set_published(pool, BIZ_B, False)
        for sid in sids:
            await redis.delete(f"{_SESSION_KEY_PREFIX}{sid}")
    finally:
        await pool.close()
        await redis.aclose()

    # ── Scoreboard ───────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    if _passed == _total:
        print(f"  🎉 RESULT: {_passed}/{_total} checks held. The owner dashboard works: "
              "leads come back decrypted + filterable (test hidden), the funnel is "
              "correct, live chats list/flip/reply, publish toggles — and every "
              "screen is perfectly walled per tenant + locked to strangers. 🔒")
        print("=" * 74)
        return 0
    print(f"  🚨 RESULT: {_passed}/{_total} held — {_total - _passed} CHECK(S) FAILED. "
          "Do not ship until green.")
    print("=" * 74)
    return 1


# ── HOW TO RUN ───────────────────────────────────────────────────────────────
#   Easiest : double-click  tests/test_m7.bat   (it sets everything up).
#   By hand : from the project root, with the stack running (run.bat):
#     docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m7_full_test.py"
#
#   Needs the DB + Redis (the stack) + the seed (the 2 demo tenants). No GEMINI
#   key is needed — none of the M7 read paths call the AI.
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(__doc__)
    raise SystemExit(asyncio.run(run()))
