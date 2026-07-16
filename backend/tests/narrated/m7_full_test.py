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

  (This file is a thin runner: the test phases + narration + helpers live in
   _m7_story.py — same printed output, just organized.)
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import conversation_state

# The test phases + constants + narration + helpers live in _m7_story.py
# (a thin split: same printed output; this runner does set-up + cleanup + tally).
from _m7_story import BIZ_A, BIZ_B, run_phases, tally

from app.services.auth import _SESSION_KEY_PREFIX


async def run() -> int:
    app_dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]
    pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=3)
    redis = aioredis.from_url(redis_url, decode_responses=True)

    made_conv_ids: list[tuple[str, str]] = []
    sids: list[str] = []

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            await run_phases(http, pool, redis, made_conv_ids, sids)

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
    _passed, _total = tally()
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
#     docker compose --env-file infra/.env -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m7_full_test.py"
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
