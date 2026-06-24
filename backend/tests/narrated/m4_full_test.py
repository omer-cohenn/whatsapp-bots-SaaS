"""
============================================================================
  M4 — THE AI BOT BUILDER — FULL TEST, EXPLAINED LIKE YOU'RE FIVE
============================================================================

WHAT IS THIS FILE?
  M2 built the WALL between businesses. M3 built the FRONT DOOR (login). M4
  adds the BOT BUILDER: the screen + API where a business owner designs their
  WhatsApp bot — the question flows it asks customers, the bot's name and
  personality — and (optionally) an AI helper that suggests changes for them.

  This script proves the builder is safe and works, in plain words. Two pretend
  businesses are the guinea pigs (their bot configs come from supabase/seed.sql):
      🅰️  "Avi Insurance"   — a PUBLISHED bot (a 'quote' flow + a 'talk_to_human' flow)
      🅱️  "Bella Barber"    — a DRAFT bot     (an 'appointment' flow + 'talk_to_human')

  The AI helper talks to Google's Gemini. We do NOT call the real Gemini here
  (that needs an internet key and would cost money + be flaky). Instead we plug
  in a tiny PRETEND Gemini that returns a canned answer — using the exact "seam"
  the backend left open for tests. So every check below is fast and offline.

  Every check prints:
      🧪 WHAT we try to do
      💡 WHY it matters (what would go wrong in real life)
      ✅ / ❌ what actually happened

  Run it with the test_m4.bat file (double-click), or read HOW-TO at the bottom.
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

from app.core import config as config_module
from app.db.session import tenant_connection
from app.main import app
from app.services import bot_builder_ai
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

# The two pretend businesses (fixed ids from supabase/seed.sql).
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (published bot)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber (draft bot)
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

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
        print(f"  ❌ BAD    : {detail}   <-- THIS IS A PROBLEM!")


# --- the PRETEND Gemini (the exact mock seam the backend exposed) ------------
#
# bot_builder_ai.generate_reply() calls get_gemini_client() fresh each turn and
# then awaits  client.aio.models.generate_content(...)  and reads `.text`. So our
# fake only has to copy that little shape. We make the text configurable so the
# same fake can act "smart" (propose a valid change) or "silly" (propose junk).

class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModels:
    def __init__(self, text: str) -> None:
        self._text = text

    async def generate_content(self, **_kwargs):  # noqa: ANN003
        return _FakeResp(self._text)


class _FakeAio:
    def __init__(self, text: str) -> None:
        self.models = _FakeModels(text)


class _FakeClient:
    def __init__(self, text: str) -> None:
        self.aio = _FakeAio(text)


# A "smart" reply: a friendly sentence + a fenced ```json block that adds a
# complete bot profile and one lead flow. The backend should ACCEPT this.
_SMART_REPLY = (
    "מצוין! הוספתי מסלול הרשמה קצר. ✨\n"
    "```json\n"
    "{\n"
    '  "bot_profile": {"name": "בוט הבדיקה", "system_prompt": "עזור ללקוחות בנימוס."},\n'
    '  "lead_steps": {"signup": {"label": "הרשמה", "flow_type": "lead", "steps": ['
    '{"key": "full_name", "question": "מה השם המלא?", "type": "text", "required": true}]}}\n'
    "}\n"
    "```\n"
    "מה עוד תרצה להוסיף?"
)

# A "silly" reply: a choice question with NO options (against the rules). The
# backend should KEEP the chat reply but DROP the broken change.
_SILLY_REPLY = (
    "הנה מסלול עם בחירה:\n"
    "```json\n"
    '{"lead_steps": {"pick": {"label": "בחירה", "flow_type": "lead", '
    '"steps": [{"key": "c", "question": "איזה צבע?", "type": "choice", "required": true}]}}}\n'
    "```\n"
)


def use_fake_gemini(text: str) -> None:
    """Plug our pretend Gemini in (replaces the real client factory)."""
    bot_builder_ai.get_gemini_client = lambda: _FakeClient(text)  # type: ignore[assignment]


# --- helpers: a real session, and tidy build-chat rows -----------------------

async def inject_session(redis: aioredis.Redis, user_id: str, business_id: str,
                         business_name: str) -> str:
    """Pretend this owner just logged in: drop a real session blob into Redis."""
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id,
        "email": f"{user_id}@example.com",
        "name": user_id,
        "picture": "",
        "business_id": business_id,
        "business_name": business_name,
        "created_at": int(time.time()),
    }
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    return sid


async def clear_build_chat(pool, business_id: str) -> None:
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            "DELETE FROM bot_builder_messages WHERE business_id = $1", business_id
        )


async def count_build_chat(pool, business_id: str) -> int:
    async with tenant_connection(pool, business_id) as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM bot_builder_messages WHERE business_id = $1",
            business_id,
        )


async def main() -> int:
    print(__doc__)

    app_dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]

    app_pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=2)
    redis = aioredis.from_url(redis_url, decode_responses=True)

    # Start clean: no leftover build-chat rows for either business.
    await clear_build_chat(app_pool, BIZ_A)
    await clear_build_chat(app_pool, BIZ_B)

    # Run the app IN-PROCESS (its lifespan opens the real DB + Redis), and talk
    # to it over httpx exactly like a browser would (cookies and all).
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:

            # ── TEST 1 ──────────────────────────────────────────────────────
            banner(1, "A logged-OUT stranger is locked out of every bot door")
            explain("knock on all four /api/bot/* doors with NO login cookie",
                    "the bot builder edits a business's whole bot. If any door "
                    "answered without a login, anyone could read or rewrite it.")
            codes = {}
            codes["GET settings"] = (await http.get("/api/bot/settings")).status_code
            codes["PUT settings"] = (await http.put("/api/bot/settings", json={})).status_code
            codes["POST ai/chat"] = (await http.post("/api/bot/ai/chat", json={})).status_code
            codes["GET ai/history"] = (await http.get("/api/bot/ai/history")).status_code
            all_401 = all(c == 401 for c in codes.values())
            result(all_401, f"every bot door said 401 to a stranger: {codes}")

            # ── TEST 2 ──────────────────────────────────────────────────────
            banner(2, "Avi logs in and sees AVI's bot (not Bella's)")
            explain("log Avi in, ask GET /api/bot/settings",
                    "an owner must see their OWN bot config — the flows they "
                    "built — and never another business's.")
            sid_a = await inject_session(redis, AVI_USER, BIZ_A, "Avi Insurance")
            http.cookies.set(SESSION_COOKIE_NAME, sid_a)
            cfg = (await http.get("/api/bot/settings")).json()
            flows = set(cfg.get("lead_steps", {}))
            is_avis = (cfg.get("is_published") is True
                       and "quote" in flows and "appointment" not in flows)
            result(is_avis,
                   f"Avi sees his published bot with flows {sorted(flows)} "
                   "('quote' is Avi's; 'appointment' is Bella's and is hidden)")

            # ── TEST 3 ──────────────────────────────────────────────────────
            banner(3, "Avi cannot see BELLA's bot — even logged in")
            explain("as Bella this time, read settings; compare to Avi's",
                    "the core tenant rule: two owners, two configs, each sees "
                    "only their own. The flows must never overlap.")
            sid_b = await inject_session(redis, BELLA_USER, BIZ_B, "Bella Barber")
            http.cookies.set(SESSION_COOKIE_NAME, sid_b)
            cfg_b = (await http.get("/api/bot/settings")).json()
            flows_b = set(cfg_b.get("lead_steps", {}))
            isolated = "appointment" in flows_b and "quote" not in flows_b
            result(isolated,
                   f"Bella sees her own flows {sorted(flows_b)} and NOT Avi's 'quote'")

            # ── TEST 4 ──────────────────────────────────────────────────────
            banner(4, "Saving a bot, then loading it, gives back the SAME bot")
            explain("as Avi, PUT a new config, then GET it back",
                    "when an owner clicks 'save', the next time they open the "
                    "builder it must show exactly what they saved — no surprises.")
            http.cookies.set(SESSION_COOKIE_NAME, sid_a)
            # snapshot Avi's seeded config so we can put it back at the end.
            avi_before = (await http.get("/api/bot/settings")).json()
            new_cfg = {
                "lead_steps": {
                    "callback": {
                        "label": "שיחה חוזרת", "flow_type": "lead",
                        "steps": [
                            {"key": "full_name", "question": "מה השם המלא?",
                             "type": "text", "required": True},
                            {"key": "topic", "question": "במה לעזור?",
                             "type": "choice", "required": True,
                             "options": ["ביטוח רכב", "ביטוח דירה"]},
                        ],
                    },
                    "talk_to_human": {
                        "label": "דברו עם נציג", "flow_type": "human_handoff",
                        "steps": [],
                    },
                },
                "bot_profile": {"name": "בוט הבדיקה של אבי",
                                "system_prompt": "עזור ללקוחות בנימוס."},
                "handoff_keywords": ["נציג", "אדם"],
                "is_published": False,
            }
            put = await http.put("/api/bot/settings", json=new_cfg)
            back = (await http.get("/api/bot/settings")).json()
            saved_ok = (put.status_code == 200
                        and set(back.get("lead_steps", {})) == {"callback", "talk_to_human"}
                        and back["lead_steps"]["callback"]["steps"][1]["options"]
                        == ["ביטוח רכב", "ביטוח דירה"])
            result(saved_ok, "Avi's saved bot came back exactly as saved "
                   "(flows + the choice options round-tripped)")

            # ── TEST 5 ──────────────────────────────────────────────────────
            banner(5, "A broken bot config is REFUSED (the safety gate)")
            explain("as Avi, PUT a 'choice' question that has NO answer options",
                    "a choice with no options is a dead end for the customer. The "
                    "server must reject bad shapes with a 422, BEFORE saving them.")
            bad = {
                "bot_profile": {"name": "בוט", "system_prompt": "עזור."},
                "lead_steps": {"pick": {
                    "label": "בחירה", "flow_type": "lead",
                    "steps": [{"key": "c", "question": "איזה?", "type": "choice",
                               "required": True}],  # <-- no 'options'
                }},
            }
            bad_resp = await http.put("/api/bot/settings", json=bad)
            result(bad_resp.status_code == 422,
                   f"the server refused the broken bot with {bad_resp.status_code} "
                   "(422 = 'this config is invalid, not saved')")

            # ── TEST 6 ──────────────────────────────────────────────────────
            banner(6, "The AI helper replies AND applies a good suggestion")
            explain("turn on the PRETEND Gemini, send one chat message",
                    "the AI should answer in words AND, when it proposes a valid "
                    "config, hand it back ready to apply — and remember the chat.")
            use_fake_gemini(_SMART_REPLY)
            await clear_build_chat(app_pool, BIZ_A)
            chat = await http.post("/api/bot/ai/chat",
                                   json={"message": "תוסיף מסלול הרשמה",
                                         "current_config": {}})
            cbody = chat.json() if chat.status_code == 200 else {}
            got_change = (chat.status_code == 200
                          and bool(cbody.get("reply"))
                          and cbody.get("changes") is not None
                          and "signup" in cbody["changes"].get("lead_steps", {}))
            n_rows = await count_build_chat(app_pool, BIZ_A)
            result(got_change and n_rows == 2,
                   "the AI replied, returned a ready-to-apply 'signup' flow, "
                   f"and saved the 2-line chat ({n_rows} rows: your msg + its reply)")

            # ── TEST 7 ──────────────────────────────────────────────────────
            banner(7, "The AI's BAD idea is dropped, but the chat still flows")
            explain("make the pretend AI propose a 'choice' with no options",
                    "the AI is not trusted blindly. A broken suggestion must be "
                    "thrown away — yet the conversation should keep going.")
            use_fake_gemini(_SILLY_REPLY)
            await clear_build_chat(app_pool, BIZ_A)
            chat2 = await http.post("/api/bot/ai/chat",
                                    json={"message": "תוסיף בחירה",
                                          "current_config": {}})
            c2 = chat2.json() if chat2.status_code == 200 else {}
            dropped = (chat2.status_code == 200
                       and bool(c2.get("reply"))
                       and c2.get("changes") is None)
            result(dropped,
                   "the AI still answered, but the invalid change was dropped "
                   "(changes = none) — exactly the 'don't trust the AI blindly' rule")

            # ── TEST 8 ──────────────────────────────────────────────────────
            banner(8, "The build-chat history is private to each business")
            explain("give Avi and Bella DIFFERENT chats, then read Avi's history",
                    "the AI chat can contain business details. One owner must "
                    "never see another owner's conversation with the AI.")
            use_fake_gemini(_SMART_REPLY)
            await clear_build_chat(app_pool, BIZ_A)
            await clear_build_chat(app_pool, BIZ_B)
            http.cookies.set(SESSION_COOKIE_NAME, sid_a)
            await http.post("/api/bot/ai/chat",
                            json={"message": "הודעה של אבי", "current_config": {}})
            http.cookies.set(SESSION_COOKIE_NAME, sid_b)
            await http.post("/api/bot/ai/chat",
                            json={"message": "סוד של בלה", "current_config": {}})
            http.cookies.set(SESSION_COOKIE_NAME, sid_a)
            hist = (await http.get("/api/bot/ai/history")).json()
            msgs = hist.get("messages", [])
            order_ok = len(msgs) >= 2 and msgs[0]["role"] == "user" \
                and msgs[0]["content"] == "הודעה של אבי"
            no_leak = all("בלה" not in m["content"] for m in msgs)
            result(order_ok and no_leak,
                   "Avi's history reads oldest→newest and shows ONLY Avi's chat "
                   "(Bella's 'סוד של בלה' never appears)")

            # ── TEST 9 ──────────────────────────────────────────────────────
            banner(9, "With NO AI key set, the AI politely says 'unavailable'")
            explain("remove the Gemini key, send a chat message",
                    "the whole app must run even with no AI key (try-me/dev). The "
                    "AI door should answer 503 'not configured', never crash (500).")
            # Put the REAL factory back and make sure no key is visible.
            import importlib
            importlib.reload(bot_builder_ai)  # restores the real get_gemini_client
            os.environ.pop("GEMINI_API_KEY", None)
            config_module.get_settings.cache_clear()
            no_key = await http.post("/api/bot/ai/chat",
                                     json={"message": "שלום", "current_config": {}})
            config_module.get_settings.cache_clear()
            result(no_key.status_code == 503,
                   f"the AI door answered {no_key.status_code} with no key "
                   "(503 = 'AI helper not set up' — the rest of the app is fine)")

            # restore Avi's seeded config + tidy build-chat.
            use_fake_gemini(_SMART_REPLY)  # avoid touching the real net on cleanup
            http.cookies.set(SESSION_COOKIE_NAME, sid_a)
            try:
                await http.put("/api/bot/settings", json={
                    "lead_steps": avi_before.get("lead_steps", {}),
                    "bot_profile": avi_before.get("bot_profile")
                    or {"name": "עוזר הביטוח של אבי", "system_prompt": "עזור."},
                    "handoff_keywords": avi_before.get("handoff_keywords", []),
                    "is_published": avi_before.get("is_published", True),
                })
            except Exception:  # noqa: BLE001 - cleanup must never crash the report
                pass

    # tidy: remove the test build-chat rows + logout sessions.
    await clear_build_chat(app_pool, BIZ_A)
    await clear_build_chat(app_pool, BIZ_B)
    await redis.delete(f"{_SESSION_KEY_PREFIX}{sid_a}")
    await redis.delete(f"{_SESSION_KEY_PREFIX}{sid_b}")
    await app_pool.close()
    await redis.aclose()

    # ── Scoreboard ───────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    if _passed == _total:
        print(f"  🎉 RESULT: {_passed}/{_total} checks held. The bot builder is "
              "safe: each owner edits ONLY their own bot, bad configs are refused, "
              "and the AI helper is grounded + private.  🤖🔒")
        print("=" * 74)
        return 0
    print(f"  🚨 RESULT: {_passed}/{_total} held — {_total - _passed} CHECK(S) FAILED. "
          "Do not ship until green.")
    print("=" * 74)
    return 1


# ── HOW TO RUN ───────────────────────────────────────────────────────────────
#   Easiest : double-click  tests/test_m4.bat   (it sets everything up for you).
#   By hand : from the project root, with the stack running (run.bat):
#     docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m4_full_test.py"
#
#   The AI is tested with a PRETEND Gemini (no key, no internet) via the seam
#   bot_builder_ai.get_gemini_client. Test 9 deliberately runs with NO key to
#   prove the 503 path. You do NOT need a real GEMINI_API_KEY to run this file.
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
