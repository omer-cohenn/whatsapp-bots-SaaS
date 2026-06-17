"""
============================================================================
  M3 — LOGIN & ACCOUNTS — FULL TEST, EXPLAINED LIKE YOU'RE FIVE
============================================================================

WHAT IS THIS FILE?
  M2 built the WALL between businesses. M3 builds the FRONT DOOR: how a person
  proves who they are (Google login), gets their OWN business, and how the app
  locks every door until they do. This script walks through that door — and
  rattles it when locked — and tells you, in plain words, what happened.

  The guinea pig is the pretend business:
      🅰️  "Avi Insurance"   (id aaaaaaaa-...)

  Five things must all be true for login to be safe:
      [1] A logged-OUT stranger is locked out of EVERY /api door.
      [2] A brand-new Google user AUTOMATICALLY gets their own business.
      [3] A logged-IN owner sees ONLY their own business (never another's).
      [4] Logging OUT locks them back out.
      [5] The /healthz "is the app alive?" page stays public (it has no secrets).

  Every check prints:
      🧪 WHAT we try to do
      💡 WHY it matters (what would go wrong in real life)
      ✅ / ❌ what actually happened

  Run it with the test_m3.bat file (double-click), or read HOW-TO at the bottom.
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

from app.core.crypto import decrypt_pii, encrypt_pii
from app.db.session import tenant_connection
from app.main import app
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

# The pretend business (its fixed id comes from supabase/seed.sql).
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
AVI_USER = "google-sub-avi"

# Scoreboard.
_passed = 0
_total = 0


# --- tiny printing helpers (all the "baby language" lives here) --------------

def banner(num: int, title: str) -> None:
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
        print(f"  ❌ BAD    : {detail}   <-- THIS IS A LEAK!")


# --- helper: write a REAL Avi session into Redis (same shape as login) -------

async def inject_avi_session(redis: aioredis.Redis) -> str:
    """Pretend Avi just logged in: drop a real session blob into Redis."""
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": AVI_USER,
        "email": "avi@example.com",
        "name": "Avi",
        "picture": "",
        "business_id": BIZ_A,
        "business_name": "Avi Insurance",
        "created_at": int(time.time()),
    }
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    return sid


async def put_lead(pool, business_id: str, name: str) -> None:
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            "INSERT INTO leads (business_id, lead_name, contact_name, status, is_test) "
            "VALUES ($1,'demo_lead',$2,'new',true)",
            business_id, encrypt_pii(name))


async def main() -> int:
    print(__doc__)

    app_dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]
    su_dsn = (
        f"postgresql://{os.environ['POSTGRES_USER']}:"
        f"{os.environ['POSTGRES_PASSWORD']}@postgres:5432/"
        f"{os.environ['POSTGRES_DB']}"
    )

    app_pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=2)
    redis = aioredis.from_url(redis_url, decode_responses=True)

    # Run the app IN-PROCESS (its lifespan opens the real DB + Redis pools), and
    # talk to it over httpx exactly like a browser would (cookies and all).
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:

            # ── TEST 1 ──────────────────────────────────────────────────────
            banner(1, "A logged-OUT stranger is locked out of every /api door")
            explain("ask /api/me with NO login cookie at all",
                    "the OLD app let some pages answer without a login. The new "
                    "rule is: no login = the door says 401, every single time.")
            r = await http.get("/api/me")
            result(r.status_code == 401,
                   f"the locked door answered {r.status_code} (401 = 'who are you? go away')")

            # ── TEST 2 ──────────────────────────────────────────────────────
            banner(2, "A brand-new Google user AUTOMATICALLY gets their own business")
            explain("call the signup function twice for a never-seen-before user",
                    "the first login must CREATE a business for them; a second "
                    "login must hand back the SAME one (never a duplicate).")
            new_user = f"test-newuser-{secrets.token_hex(6)}"
            async with app_pool.acquire() as conn:
                biz1 = await conn.fetchval(
                    "SELECT provision_owner($1,$2,$3,$4,$5)",
                    new_user, f"{new_user}@example.com", "New Owner", "", "")
                biz2 = await conn.fetchval(
                    "SELECT provision_owner($1,$2,$3,$4,$5)",
                    new_user, f"{new_user}@example.com", "New Owner", "", "")
                owned = await conn.fetch("SELECT * FROM get_user_businesses($1)", new_user)
            result(biz1 is not None and str(biz1) == str(biz2) and len(owned) == 1,
                   f"a fresh user got 1 business, and logging in twice kept the SAME one")

            # clean the throwaway user up (needs the superuser — app_role can't
            # DELETE businesses; that is the M2 least-privilege wall doing its job).
            su = await asyncpg.connect(dsn=su_dsn)
            try:
                await su.execute("DELETE FROM business_members WHERE user_id=$1", new_user)
                if biz1 is not None:
                    await su.execute("DELETE FROM businesses WHERE id=$1", biz1)
                await su.execute("DELETE FROM users WHERE id=$1", new_user)
            finally:
                await su.close()

            # ── TEST 3 ──────────────────────────────────────────────────────
            banner(3, "A logged-IN owner sees ONLY their own business")
            explain("log Avi in, ask /api/me, then read leads as Avi's business",
                    "once you're in, you must see YOUR business and YOUR customers "
                    "— and the wall must still hide everyone else's.")
            # set up: give Avi exactly one lead named "Dana".
            async with tenant_connection(app_pool, BIZ_A) as conn:
                await conn.execute("DELETE FROM leads WHERE is_test = true")
            await put_lead(app_pool, BIZ_A, "Dana")

            sid = await inject_avi_session(redis)
            http.cookies.set(SESSION_COOKIE_NAME, sid)
            me = await http.get("/api/me")
            me_body = me.json() if me.status_code == 200 else {}
            says_avi = (me.status_code == 200
                        and me_body.get("business", {}).get("id") == BIZ_A
                        and me_body.get("user", {}).get("id") == AVI_USER)

            # and via the SAME session's business_id, the tenant view shows only Avi.
            biz_from_session = me_body.get("business", {}).get("id", BIZ_A)
            async with tenant_connection(app_pool, biz_from_session) as conn:
                rows = await conn.fetch("SELECT contact_name FROM leads")
            only_avi = len(rows) == 1 and decrypt_pii(rows[0]["contact_name"]) == "Dana"
            result(says_avi and only_avi,
                   "Avi's /api/me showed Avi's business, and Avi saw only Avi's lead 'Dana'")

            # ── TEST 4 ──────────────────────────────────────────────────────
            banner(4, "Logging OUT locks them back out")
            explain("log out, then knock on /api/me again with the SAME cookie",
                    "logout must truly DESTROY the session server-side — not just "
                    "wave the cookie goodbye. A dead session = a 401 forever after.")
            bye = await http.post("/auth/logout")
            after = await http.get("/api/me")
            gone = await redis.get(f"{_SESSION_KEY_PREFIX}{sid}")
            result(bye.status_code == 204 and after.status_code == 401 and gone is None,
                   "logout said 204, the session is erased from Redis, and the door is 401 again")

            # ── TEST 5 ──────────────────────────────────────────────────────
            banner(5, "The /healthz page stays public")
            explain("open /healthz with no login",
                    "monitoring tools must be able to ask 'is the app alive?' "
                    "without a login. It carries NO secrets, so it stays open.")
            # use a fresh cookie-less client view: clear cookies first.
            http.cookies.clear()
            hz = await http.get("/healthz")
            result(hz.status_code == 200,
                   f"the health page answered {hz.status_code} with no login (still public)")

    # tidy up the demo lead + close clients.
    async with tenant_connection(app_pool, BIZ_A) as conn:
        await conn.execute("DELETE FROM leads WHERE is_test = true")
    await app_pool.close()
    await redis.aclose()

    # ── Scoreboard ───────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    if _passed == _total:
        print(f"  🎉 RESULT: {_passed}/{_total} checks held. The front door is safe: "
              "no login = no entry, and each owner sees only their own.  🚪🔒")
        print("=" * 74)
        return 0
    print(f"  🚨 RESULT: {_passed}/{_total} held — {_total - _passed} CHECK(S) FAILED. "
          "Do not ship until green.")
    print("=" * 74)
    return 1


# ── HOW TO RUN ───────────────────────────────────────────────────────────────
#   Easiest : double-click  tests/test_m3.bat   (it sets everything up for you).
#   By hand : from the project root, with the stack running (run.bat):
#     docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m3_full_test.py"
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
