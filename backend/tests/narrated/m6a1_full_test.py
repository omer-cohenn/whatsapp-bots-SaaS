"""
============================================================================
  M6a.1 — EXTERNAL "TEST NUMBERS" ALLOW-LIST — FULL TEST, EXPLAINED SIMPLY
============================================================================

WHAT IS THIS FILE?
  M6a (the milestone before this) let a business OWNER rehearse their LIVE bot
  by messaging their OWN WhatsApp number ("Message Yourself"). M6a.1 widens that
  rehearsal to a few TRUSTED OUTSIDE phones: the owner may register up to 5
  phone numbers (each with an optional name). When ANY of those numbers messages
  the owner's WhatsApp, the gateway runs it through the REAL bot pipeline and
  replies — exactly like the self-chat, but for those external test numbers.

  The golden rule: everyone NOT on the list is IGNORED (silent). And just like
  the self-chat, the bot answers only when the owner's bot is PUBLISHED. Real
  data (is_test=False), so a finished questionnaire becomes a real lead.

  This script PRETENDS to be the gateway. It POSTs the exact webhook the real
  gateway would send for an OUTSIDE phone (self_test = false, with the secret
  X-Gateway-Token header), and checks the backend does the right thing:

      • a number ON the list, bot published   → the bot answers; a real lead saves
      • a number NOT on the list              → silent (status "not allowed")
      • a number ON the list, bot a DRAFT     → silent (status "not published")
      • the phone-normalize rule              → '0547…' stored == '+97254 7…' inbound

  It also tests the owner's admin API (GET/PUT /api/whatsapp/test-numbers):
  the ≤5 cap, the round-trip of labels, that the raw DB columns are CIPHERTEXT
  (never the plaintext phone/label), the 401-without-a-session gate, and tenant
  isolation (one business cannot see another's list).

  Every check prints:  🧪 WHAT we try · 💡 WHY it matters · ✅/❌ the result.

  THE ONE THING A SCRIPT CANNOT DO: actually send a real WhatsApp message from a
  second phone. That last mile is a MANUAL step for Omer — see the note at the
  end. Everything UP TO the phone is proven here, automatically.

  Run it with tests/test_m6a1.bat (double-click), or read HOW-TO at the bottom.
============================================================================
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.db.session import tenant_connection
from app.main import app
from app.services import whatsapp as whatsapp_service
from app.services import whatsapp_test_numbers as test_numbers_service

# The 11 test phases + constants + narration + helpers live in _m6a1_story.py
# (a thin split: same printed output; this runner does set-up + cleanup + tally).
from _m6a1_story import (
    ACC_A, ACC_B, BIZ_A, BIZ_B, DAD_LOCAL, MOM_INTL, OWN_PHONE, run_phases, tally,
)


async def main() -> int:
    print(__doc__)

    app_dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]
    token = get_settings().gateway_api_token.get_secret_value()

    pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=4)
    rds = aioredis.from_url(redis_url, decode_responses=True)

    # --- SET-UP ------------------------------------------------------------- --
    # Map each business to its own gateway account (UPSERT — never DELETE; the
    # webhook resolves account -> business via resolve_wa_account).
    await whatsapp_service.upsert_connection(
        pool, BIZ_A, gateway_account_id=ACC_A, phone=OWN_PHONE, status="connected")
    await whatsapp_service.upsert_connection(
        pool, BIZ_B, gateway_account_id=ACC_B, phone=OWN_PHONE, status="connected")

    # Clean any leftover test leads for both tenants (RLS-scoped).
    for biz in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, biz) as conn:
            await conn.execute("DELETE FROM leads WHERE business_id = $1", biz)

    # Avi's allow-list = exactly 2 numbers: DAD (stored Israeli-local) + MOM.
    await test_numbers_service.set_test_numbers(pool, BIZ_A, [
        {"phone": DAD_LOCAL, "label": "Dad"},
        {"phone": MOM_INTL, "label": "Mom"},
    ])
    # Bella's allow-list = DAD too (so we can prove the publish gate independently).
    await test_numbers_service.set_test_numbers(pool, BIZ_B, [
        {"phone": DAD_LOCAL, "label": "Dad"},
    ])
    print("\n  (set-up done: Avi↔ACC_A [published, allow=Dad+Mom], "
          "Bella↔ACC_B [draft, allow=Dad])")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            auth = {"X-Gateway-Token": token}
            await run_phases(auth, http, rds, pool)

    # ── clean up the leads we made (we leave the connection mappings; app_role
    #    cannot DELETE them, and a re-run simply UPSERTs them again) ────────────
    for biz in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, biz) as conn:
            await conn.execute("DELETE FROM leads WHERE business_id = $1", biz)
    await pool.close()
    await rds.aclose()

    # ── Scoreboard ───────────────────────────────────────────────────────────
    _passed, _total = tally()
    print()
    print("=" * 74)
    if _passed == _total:
        print(f"  🎉 RESULT: {_passed}/{_total} checks held. The external "
              "'test numbers' allow-list path works end-to-end.  🤖💬")
    else:
        print(f"  🚨 RESULT: {_passed}/{_total} held — {_total - _passed} FAILED. "
              "Do not ship until green.")
    print("=" * 74)
    print()
    print("  📱 MANUAL STEP FOR OMER (a script cannot do this part):")
    print("     1) Make sure WhatsApp is linked (scan the QR at :3000/qr).")
    print("     2) In the dashboard, add a SECOND phone you own to 'מספרים לבדיקה'.")
    print("     3) From THAT phone, message your linked WhatsApp number — the bot")
    print("        should reply there. A phone NOT on the list gets no reply.")
    print("     This proves the REAL send/receive on real phones. Everything")
    print("     BEFORE the phone (the whole backend pipeline) is proven above.")
    print("=" * 74)
    return 0 if _passed == _total else 1


# ── HOW TO RUN ───────────────────────────────────────────────────────────────
#   Easiest : double-click  tests/test_m6a1.bat   (it sets everything up for you).
#   By hand : from the project root, with the stack running (run.bat):
#     docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m6a1_full_test.py"
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
