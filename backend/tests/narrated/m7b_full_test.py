"""
============================================================================
  M7 POLISH — "WORK THE LEAD TO A SALE" — FULL TEST, EXPLAINED LIKE YOU'RE FIVE
============================================================================

WHAT IS THIS FILE?
  M7 gave the owner the WINDOWS (the leads list + the dashboard). This polish
  adds the two BUTTONS the owner pushes to actually run a lead to a sale:

    * PATCH /api/leads/{id}/status → the owner stamps a lead:
        "deal"   = "I won this one!"   (Hebrew: בוצעה עסקה)
        "closed" = "this lead is done" (Hebrew: ליד סגור)
      ...and GET /api/leads must show the new stamp.

    * GET /api/dashboard now reports "orders" = how many leads are stamped
      "deal". Push the deal button → the orders number goes up by one.

  THE RULES THAT CAN NEVER BREAK:
    - a stranger (no login) cannot push the button         → 401
    - a nonsense status is refused                          → 422
    - a lead that doesn't exist is refused                  → 404
    - business A can NEVER stamp business B's lead          → 404 / no change
    - "orders" obeys the same filters as the rest (is_test hidden by default,
      and the week/month window).

  HOW WE TEST IT FOR REAL:
    We SEED a real lead by driving a whole conversation through the real bot
    door (POST /api/bot/sim), then we push the buttons and re-read the windows.

  Every check prints:  🧪 WHAT we try · 💡 WHY it matters · ✅/❌ the result.

  Run it with tests/test_m7b.bat (double-click), or read HOW-TO at the bottom.
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
from app.services import conversation_state
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

A_NAME = "דנה כהן"
A_PHONE = "052-1234567"
B_NAME = "שרה בלה-לקוחה"
B_PHONE = "050-9999999"

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


async def inject_session(redis, user_id, business_id, name) -> str:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": f"{user_id}@example.com", "name": user_id,
        "picture": "", "business_id": business_id, "business_name": name,
        "created_at": int(time.time()),
    }
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    return sid


async def sim(http, conv, msg):
    return (await http.post(
        "/api/bot/sim", json={"message": msg, "conversation_id": conv})).json()


async def seed_quote(http, conv, name, phone):
    """Drive Avi's full 3-step quote flow to completion. Returns lead_id."""
    s = await sim(http, conv, "1")
    await sim(http, conv, name)
    await sim(http, conv, phone)
    done = await sim(http, conv, "1")
    return done.get("lead_id") or s.get("lead_id")


async def status_of(http, lead_id):
    leads = (await http.get("/api/leads?include_test=true")).json()["leads"]
    return next((l["status"] for l in leads if l["id"] == lead_id), None)


async def run() -> int:
    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=3)
    redis = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    made: list[tuple[str, str]] = []
    sids: list[str] = []

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            print("\n  ⏳ Seeding a real (test) lead via the bot door (/api/bot/sim) ...")
            sid_a = await inject_session(redis, AVI_USER, BIZ_A, "Avi Insurance")
            sids.append(sid_a)
            http.cookies.set(SESSION_COOKIE_NAME, sid_a)
            a_conv = f"sim:{secrets.token_hex(8)}"
            made.append((BIZ_A, a_conv))
            a_lead = await seed_quote(http, a_conv, A_NAME, A_PHONE)
            print(f"  ✅ Seeded one completed lead (status 'new').\n")

            # ── 1 — the button is LOCKED to strangers (401) ─────────────────
            banner("1", "PATCH /api/leads/{id}/status is LOCKED to strangers (401)")
            explain("push the status button with NO login cookie",
                    "stamping a lead changes a tenant's data — it must sit behind "
                    "the deny-by-default login wall like every other /api door.")
            async with AsyncClient(transport=transport, base_url="http://test") as anon:
                code = (await anon.patch(
                    f"/api/leads/{a_lead}/status", json={"status": "deal"})).status_code
            result(code == 401, f"a stranger got {code} (expected 401)")

            # ── 2 — stamp 'deal', GET /api/leads reflects it ────────────────
            banner("2", "Owner stamps a lead 'deal' (בוצעה עסקה); the list shows it")
            explain("PATCH the lead to 'deal', then re-read /api/leads",
                    "this is the owner saying 'I won this customer'. The change "
                    "must persist and be visible in the leads list.")
            before = await status_of(http, a_lead)
            r = await http.patch(f"/api/leads/{a_lead}/status", json={"status": "deal"})
            body = r.json()
            after = await status_of(http, a_lead)
            ok = (r.status_code == 200 and body == {"lead_id": a_lead, "status": "deal"}
                  and before == "new" and after == "deal")
            result(ok, f"status went '{before}' → '{after}'; response echoed "
                   f"{{lead_id, status='deal'}}")

            # ── 3 — stamp 'closed', GET /api/leads reflects it ──────────────
            banner("3", "Owner stamps a lead 'closed' (ליד סגור); the list shows it")
            explain("PATCH the same lead to 'closed', then re-read /api/leads",
                    "the owner can also retire a lead. The new stamp must stick.")
            r = await http.patch(f"/api/leads/{a_lead}/status", json={"status": "closed"})
            after = await status_of(http, a_lead)
            ok = (r.status_code == 200 and r.json()["status"] == "closed"
                  and after == "closed")
            result(ok, f"status is now '{after}' (response said 'closed')")

            # ── 4 — invalid status is refused (422), lead unchanged ─────────
            banner("4", "A nonsense status is refused (422) and changes nothing")
            explain("PATCH status='banana' and status with an extra field",
                    "the API must only accept the five known statuses; junk input "
                    "must be rejected and must NOT corrupt the lead.")
            bad = (await http.patch(
                f"/api/leads/{a_lead}/status", json={"status": "banana"})).status_code
            extra = (await http.patch(
                f"/api/leads/{a_lead}/status",
                json={"status": "deal", "x": 1})).status_code
            still = await status_of(http, a_lead)
            ok = (bad == 422 and extra == 422 and still == "closed")
            result(ok, f"status='banana'→{bad}, extra-field→{extra} (both 422); "
                   f"lead untouched (still '{still}')")

            # ── 5 — unknown lead id is 404 ──────────────────────────────────
            banner("5", "An unknown lead id is 404")
            explain("PATCH a made-up uuid that belongs to no one",
                    "the owner can only stamp a lead that actually exists for them; "
                    "a missing lead is a clean 404, not a silent success.")
            ghost = "00000000-0000-0000-0000-000000000000"
            code = (await http.patch(
                f"/api/leads/{ghost}/status", json={"status": "deal"})).status_code
            result(code == 404, f"PATCH on a ghost lead returned {code} (expected 404)")

            # ── 6 — TENANT ISOLATION: A cannot stamp B's lead ───────────────
            banner("6", "Isolation: Avi CANNOT stamp Bella's lead (404 / no change)")
            explain("Bella creates a lead; Avi tries to mark it 'deal'",
                    "the #1 SaaS rule. One business must NEVER be able to change "
                    "another's data — the attempt must 404 and leave B's lead alone.")
            sid_b = await inject_session(redis, BELLA_USER, BIZ_B, "Bella Barber")
            sids.append(sid_b)
            async with AsyncClient(transport=transport, base_url="http://test") as bhttp:
                bhttp.cookies.set(SESSION_COOKIE_NAME, sid_b)
                b_conv = f"sim:{secrets.token_hex(8)}"
                made.append((BIZ_B, b_conv))
                await sim(bhttp, b_conv, "1")
                await sim(bhttp, b_conv, B_NAME)
                await sim(bhttp, b_conv, B_PHONE)
                b_done = await sim(bhttp, b_conv, "1")
                b_lead = b_done.get("lead_id")
                b_before = await status_of(bhttp, b_lead)
                # Avi (main client) attacks Bella's lead id.
                attack = (await http.patch(
                    f"/api/leads/{b_lead}/status", json={"status": "deal"})).status_code
                b_after = await status_of(bhttp, b_lead)
            async with tenant_connection(pool, BIZ_B) as conn:
                raw = await conn.fetchval(
                    "SELECT status FROM leads WHERE id=$1 AND business_id=$2",
                    b_lead, BIZ_B)
            ok = (attack == 404 and b_before == b_after and raw != "deal")
            result(ok, f"Avi's cross-tenant PATCH got {attack} (404); Bella's lead "
                   f"unchanged ('{b_before}' → '{b_after}', DB says '{raw}')")

            # ── 7 — dashboard 'orders' increments when a lead becomes 'deal' ─
            banner("7", "GET /api/dashboard 'orders' = count of 'deal' leads")
            explain("read orders, mark a fresh lead 'deal', read orders again",
                    "the 'orders' (הזמנות) tile on the dashboard counts won deals. "
                    "Pushing the deal button must bump it by exactly one.")
            conv2 = f"sim:{secrets.token_hex(8)}"
            made.append((BIZ_A, conv2))
            lead2 = await seed_quote(http, conv2, A_NAME, A_PHONE)
            before = (await http.get(
                "/api/dashboard?period=all&include_test=true")).json()
            orders_before = before.get("orders")
            await http.patch(f"/api/leads/{lead2}/status", json={"status": "deal"})
            after = (await http.get(
                "/api/dashboard?period=all&include_test=true")).json()
            async with tenant_connection(pool, BIZ_A) as conn:
                raw_deals = await conn.fetchval(
                    "SELECT count(*)::int FROM leads WHERE business_id=$1 "
                    "AND status='deal'", BIZ_A)
            ok = ("orders" in before and after["orders"] == orders_before + 1
                  and after["orders"] == raw_deals)
            result(ok, f"orders {orders_before} → {after['orders']} (+1); matches DB "
                   f"truth ({raw_deals} 'deal' leads)")

            # ── 8 — 'orders' respects is_test (hidden by default) ───────────
            banner("8", "'orders' hides practice (is_test) deals by default")
            explain("compare orders default vs include_test=true",
                    "our seeded deals are TEST leads — they must not pollute the "
                    "real orders count, but the owner can opt in to see them.")
            default = (await http.get("/api/dashboard?period=all")).json()
            with_test = (await http.get(
                "/api/dashboard?period=all&include_test=true")).json()
            ok = with_test["orders"] >= default["orders"] + 1
            result(ok, f"orders default={default['orders']} (test deals hidden) < "
                   f"include_test={with_test['orders']}")

            # ── 9 — 'orders' respects the period window ─────────────────────
            banner("9", "'orders' respects the week/month time window")
            explain("back-date a deal ~40 days, compare period=all vs period=week",
                    "the dashboard's time filter must apply to orders too — an old "
                    "deal counts in 'all time' but drops out of 'this week'.")
            async with tenant_connection(pool, BIZ_A) as conn:
                await conn.execute(
                    "UPDATE leads SET started_at = now() - interval '40 days' "
                    "WHERE id=$1 AND business_id=$2", lead2, BIZ_A)
            all_q = (await http.get(
                "/api/dashboard?period=all&include_test=true")).json()
            week_resp = await http.get(
                "/api/dashboard?period=week&include_test=true")
            if week_resp.status_code != 200:
                result(False, f"period=week returned {week_resp.status_code} "
                       "(expected 200)")
            else:
                week = week_resp.json()
                ok = (all_q["orders"] >= 1
                      and week["orders"] == all_q["orders"] - 1)
                result(ok, f"orders all={all_q['orders']}, week={week['orders']} "
                       "(the 40-day-old deal dropped out of the week window)")

    # ── cleanup ──────────────────────────────────────────────────────────────
    try:
        for bid, cid in made:
            await conversation_state.clear_state(redis, bid, cid)
            await redis.delete(f"conv:{bid}:{cid}:outbox")
        for bid in (BIZ_A, BIZ_B):
            async with tenant_connection(pool, bid) as conn:
                await conn.execute(
                    "DELETE FROM leads WHERE business_id=$1 AND is_test=true", bid)
        for sid in sids:
            await redis.delete(f"{_SESSION_KEY_PREFIX}{sid}")
    finally:
        await pool.close()
        await redis.aclose()

    print()
    print("=" * 74)
    if _passed == _total:
        print(f"  🎉 RESULT: {_passed}/{_total} checks held. The owner can work a lead "
              "to a sale: stamp it 'deal'/'closed' (reflected in the list), junk is "
              "refused (422/404), no tenant can touch another's lead, and the "
              "dashboard 'orders' counts won deals correctly (test hidden, window "
              "respected). 🔒")
        print("=" * 74)
        return 0
    print(f"  🚨 RESULT: {_passed}/{_total} held — {_total - _passed} CHECK(S) FAILED. "
          "Do not ship until green.")
    print("=" * 74)
    return 1


# ── HOW TO RUN ───────────────────────────────────────────────────────────────
#   Easiest : double-click  tests/test_m7b.bat
#   By hand : from the project root, with the stack running (run.bat):
#     docker compose --env-file infra/.env -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m7b_full_test.py"
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(__doc__)
    raise SystemExit(asyncio.run(run()))
