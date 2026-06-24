"""
============================================================================
  M5 — THE "TRY-ME" TEST CHAT — FULL TEST, EXPLAINED LIKE YOU'RE FIVE
============================================================================

WHAT IS THIS FILE?
  M2 built the WALL between businesses. M3 built the FRONT DOOR (login). M4
  let an owner DESIGN their bot. M5 lets the owner TRY their own bot, like a
  customer would — a little WhatsApp-style test chat — WITHOUT saving anything
  and WITHOUT touching any real customer's data.

  The brain that turns "one customer message + where we are in the chat" into
  "what the bot says next" is a PURE function called the bot ENGINE
  (app/services/bot_engine.py). "Pure" means: no database, no internet, no AI,
  no clock — same input always gives the same output. That makes it easy to
  test EVERY path with confidence.

  This script has two halves:

    PART A — the ENGINE alone (no Docker, no DB). We feed it a tiny made-up bot
             config and walk through every branch: the opening menu, picking a
             flow by NUMBER and by its LABEL, good/bad answers for phone, email,
             choice and text, finishing a lead, the human-handoff keyword, a
             handoff/booking flow chosen from the menu, typing "0" to go back to
             the menu mid-flow, and the little "type תפריט to go back" footer.

    PART B — the ENDPOINT POST /api/bot/tryme (this needs the running stack).
             A logged-out stranger is locked out (401); a logged-in owner runs
             THEIR OWN seeded bot; and a WHOLE simulated conversation writes
             NOTHING — no build-chat rows, no leads.

  Every check prints:
      🧪 WHAT we try to do
      💡 WHY it matters (what would go wrong in real life)
      ✅ / ❌ what actually happened

  Run it with tests/test_m5.bat (double-click), or read HOW-TO at the bottom.

  (This file is a thin runner: PART A + PART B and the narration helpers live in
   _m5_story.py — same printed output, just organized.)
============================================================================
"""

from __future__ import annotations

import asyncio

from _m5_story import part_a_engine_tests, part_b_endpoint_tests, tally


async def main() -> int:
    print(__doc__)

    print()
    print("=" * 74)
    print("  PART A — the PURE bot ENGINE (no DB, no internet, no AI)")
    print("=" * 74)
    part_a_engine_tests()

    print()
    print("=" * 74)
    print("  PART B — the /api/bot/tryme ENDPOINT (needs the running stack)")
    print("=" * 74)
    await part_b_endpoint_tests()

    # ── Scoreboard ───────────────────────────────────────────────────────────
    _passed, _total = tally()
    print()
    print("=" * 74)
    if _passed == _total:
        print(f"  🎉 RESULT: {_passed}/{_total} checks held. The try-me works: every "
              "engine path is correct, it runs each owner's OWN bot, and it "
              "writes NOTHING (no leads, no chat rows).  🤖🧪")
        print("=" * 74)
        return 0
    print(f"  🚨 RESULT: {_passed}/{_total} held — {_total - _passed} CHECK(S) FAILED. "
          "Do not ship until green.")
    print("=" * 74)
    return 1


# ── HOW TO RUN ───────────────────────────────────────────────────────────────
#   Easiest : double-click  tests/test_m5.bat   (it sets everything up for you).
#   By hand : from the project root, with the stack running (run.bat):
#     docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m5_full_test.py"
#
#   PART A needs NOTHING but Python (it's the pure engine). PART B needs the DB +
#   Redis (the stack) so it can prove the endpoint writes nothing. No GEMINI key
#   is needed — try-me never calls the AI.
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
