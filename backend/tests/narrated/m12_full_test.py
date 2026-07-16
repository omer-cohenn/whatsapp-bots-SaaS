"""
============================================================================
  M12 — THE BACK-OFFICE (Omer's control room) — FULL TEST, EXPLAINED SIMPLY
============================================================================

WHAT IS THIS FILE?
  Bizz_up is a mall. Every BUSINESS is a shop with a key only to itself (that is
  the tenant wall, M2/M7). Omer owns the MALL, so he gets a CONTROL ROOM: one
  window onto EVERY shop at once — who opened and when, last login, which plan,
  how busy (messages / leads). And from that room he can ACT: change a shop's
  plan, or LOCK (suspend) a shop. The control-room key belongs to Omer ALONE.

  This is the ONE place we cross the tenant wall on purpose. So it has its own
  separate locked door (an admin allow-list of emails), and crossing happens only
  through a few narrow "SECURITY DEFINER" database functions — nobody else can
  read those control-room tables directly.

  This script PRETENDS to be the browser. It logs in three ways and checks the
  control room does the right thing every time:

      🔑 nobody logged in   → the door is shut (401)
      🙍 a normal shop owner → "you're not the mall owner" (403)
      👑 Omer (the admin)    → welcome in (200)

  Every check prints:
      🧪 WHAT we try to do
      💡 WHY it matters (what would go wrong in real life)
      ✅ / ❌ what actually happened

  The most important checks: a LOCKED shop's bot really goes SILENT on WhatsApp
  (not just a label), and a normal shop owner can NEVER peek at the control-room
  tables or another shop's numbers. We also break a lock on purpose and watch the
  test catch it, then restore it.

  Run it with tests/test_m12.bat (double-click), or read HOW-TO at the bottom.
============================================================================
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.services import whatsapp as whatsapp_service

# The 13 test phases + constants + narration + helpers live in _m12_story.py
# (a thin split: same printed output; this runner just does set-up + scoreboard).
from _m12_story import (
    ACC_A, ADMIN_EMAIL, BIZ_A, BIZ_B, OWN_PHONE, _superuser_dsn, run_phases, tally,
)

async def main() -> int:  # noqa: C901 — a flat, readable list of checks on purpose
    print(__doc__)

    app_dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]
    gw_token = get_settings().gateway_api_token.get_secret_value()

    pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=4)
    redis = aioredis.from_url(redis_url, decode_responses=True)
    su = await asyncpg.create_pool(dsn=_superuser_dsn(), min_size=1, max_size=2)

    # Resolve the REAL admin user id for the audit FK (users.email is unique).
    async with su.acquire() as conn:
        admin_user = await conn.fetchval(
            "SELECT id FROM users WHERE email = $1", ADMIN_EMAIL)
        if admin_user is None:
            admin_user = "google-sub-m12-admin"
            await conn.execute(
                "INSERT INTO users (id, email, name) VALUES ($1,$2,'M12 Admin')",
                admin_user, ADMIN_EMAIL)
    admin_user = str(admin_user)

    # Clean baseline for the control-room tables of our two test shops, and map
    # Avi's gateway account so a webhook bot turn can run.
    async with su.acquire() as conn:
        await conn.execute(
            "DELETE FROM subscriptions WHERE business_id = ANY($1::uuid[])",
            [BIZ_A, BIZ_B])
        await conn.execute(
            "DELETE FROM admin_audit WHERE target_business_id = ANY($1::uuid[])",
            [BIZ_A, BIZ_B])
        await conn.execute(
            "UPDATE businesses SET is_active = true WHERE id = ANY($1::uuid[])",
            [BIZ_A, BIZ_B])
    await whatsapp_service.upsert_connection(
        pool, BIZ_A, gateway_account_id=ACC_A, phone=OWN_PHONE, status="connected")
    print("\n  (set-up done: clean plans/audit for Avi+Bella, Avi↔ACC_A mapped, "
          "admin user resolved)")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            auth = {"X-Gateway-Token": gw_token}
            await run_phases(http, auth, redis, su, pool, admin_user)

    # ── clean up everything we created for the control-room tables ────────────
    async with su.acquire() as conn:
        await conn.execute(
            "DELETE FROM subscriptions WHERE business_id = ANY($1::uuid[])",
            [BIZ_A, BIZ_B])
        await conn.execute(
            "DELETE FROM admin_audit WHERE target_business_id = ANY($1::uuid[])",
            [BIZ_A, BIZ_B])
        await conn.execute(
            "UPDATE businesses SET is_active=true WHERE id = ANY($1::uuid[])",
            [BIZ_A, BIZ_B])
    await pool.close()
    await su.close()
    await redis.aclose()

    # ── Scoreboard ────────────────────────────────────────────────────────────
    _passed, _total = tally()
    print()
    print("=" * 74)
    if _passed == _total:
        print(f"  🎉 RESULT: M12 {_passed}/{_total} checks held. The mall control "
              "room is locked, honest, and the suspend switch truly mutes the bot. 👑")
    else:
        print(f"  🚨 RESULT: M12 {_passed}/{_total} held — {_total - _passed} "
              "FAILED. Do not ship until green.")
    print("=" * 74)
    return 0 if _passed == _total else 1


# ── HOW TO RUN ───────────────────────────────────────────────────────────────
#   Easiest : double-click  tests/test_m12.bat   (it sets everything up for you).
#   By hand : from the project root, with the stack running (run.bat):
#     docker compose --env-file infra/.env -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m12_full_test.py"
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
