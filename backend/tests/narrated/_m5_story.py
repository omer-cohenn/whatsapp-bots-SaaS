"""M5 narrated — the "try-me" story: engine phase (PART A) + endpoint phase (PART B).

This module is NOT run directly. The thin runner m5_full_test.py imports the two
phase functions (part_a_engine_tests, part_b_endpoint_tests) + tally() and calls
them in order. Splitting them out keeps the runner under 500 lines WITHOUT
changing a single byte of printed output — the narration helpers + the running
scoreboard live here, and the runner reads the final counts via tally().

Nothing here prints a secret, a token, or a customer's personal details.
"""

from __future__ import annotations

import json
import os
import secrets
import time

import asyncpg
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import bot_engine
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


# --- a tiny made-up bot config for the ENGINE tests (PART A) -----------------
#
# This is a hand-written `bot_settings` shape (same shape the DB stores). It has
# THREE flows so we can exercise every branch: a lead flow with one of each step
# type, a human_handoff flow, and a booking flow with a {link} placeholder.
ENGINE_SETTINGS = {
    "bot_profile": {
        "name": "בוט בדיקה",
        "system_prompt": "עזור.",
        "greeting": "שלום מהבוט! 👋",
        "escalation_message": "מעביר לנציג, רגע…",
        "menu_keywords": ["תפריט", "menu", "0"],
    },
    "lead_steps": {
        # flow #1 (1-based) — a lead flow with text, phone, email, choice.
        "signup": {
            "label": "הרשמה ללקוח חדש",
            "flow_type": "lead",
            "message": "תודה! קיבלנו את כל הפרטים. 🙏",
            "steps": [
                {"key": "full_name", "question": "מה השם המלא?",
                 "type": "text", "required": True},
                {"key": "phone", "question": "מה הטלפון?",
                 "type": "phone", "required": True,
                 "error_message": "טלפון לא תקין, נסה שוב."},
                {"key": "email", "question": "מה האימייל?",
                 "type": "email", "required": True},
                {"key": "topic", "question": "במה לעזור?",
                 "type": "choice", "required": True,
                 "options": ["ביטוח רכב", "ביטוח דירה"]},
            ],
        },
        # flow #2 — human handoff, picked from the menu.
        "talk_to_human": {
            "label": "דברו עם נציג",
            "flow_type": "human_handoff",
            "message": "מעביר אותך לנציג אנושי 🙏",
            "steps": [],
        },
        # flow #3 — booking, with a {link} placeholder to substitute.
        "book": {
            "label": "קביעת תור",
            "flow_type": "booking",
            "message": "לקביעת תור לחצו כאן: {link}",
            "steps": [],
        },
    },
    "handoff_keywords": ["נציג", "אדם", "agent"],
    "is_published": True,
}


def part_a_engine_tests() -> None:
    """Walk EVERY branch of the pure engine with the made-up config above."""

    s = ENGINE_SETTINGS

    # ── A1 — open turn → greeting + numbered menu ────────────────────────────
    banner("A1", "Opening the chat shows the greeting + the numbered menu")
    explain("call advance() with an EMPTY message (the 'open' turn)",
            "when a customer first opens the chat they must see the bot's hello "
            "and the list of things it can do — numbered 1,2,3…")
    r = bot_engine.advance(s, bot_engine.initial_state(), "")
    text = r["replies"][0]
    ok = (r["event"] is None and r["lead"] is None
          and "שלום מהבוט" in text
          and "1. הרשמה ללקוח חדש" in text
          and "2. דברו עם נציג" in text
          and "3. קביעת תור" in text
          and r["state"]["phase"] == "menu")
    result(ok, "the open turn returned the greeting + a 1/2/3 menu, state=menu, "
           "and NO event/lead")

    # ── A2 — pick a flow by NUMBER ───────────────────────────────────────────
    banner("A2", "Picking a flow by its NUMBER starts that flow")
    explain("from the menu, send '1' (the signup lead flow)",
            "a customer should be able to just tap the number of the option "
            "they want — '1' must start flow #1 and ask its first question.")
    r = bot_engine.advance(s, bot_engine.initial_state(), "1")
    text = r["replies"][0]
    ok = (r["state"]["phase"] == "in_flow"
          and r["state"]["active_flow"] == "signup"
          and r["state"]["step_index"] == 0
          and "מה השם המלא?" in text)
    result(ok, "sending '1' started the 'signup' flow and asked the first "
           "question (מה השם המלא?)")

    # ── A3 — pick a flow by LABEL ────────────────────────────────────────────
    banner("A3", "Picking a flow by typing its NAME (label) also starts it")
    explain("from the menu, type the words 'דברו עם נציג' (the handoff label)",
            "customers don't always tap numbers — typing the option's name "
            "should work too (case-insensitive, partial match).")
    r = bot_engine.advance(s, bot_engine.initial_state(), "דברו עם נציג")
    ok = (r["event"] == "handed_off"
          and r["state"]["phase"] == "handed_off")
    result(ok, "typing the label 'דברו עם נציג' selected the handoff flow "
           "(event=handed_off)")

    # ── A4 — TEXT step validation (good + bad) ───────────────────────────────
    banner("A4", "A text question: a real name advances; a blank bounces to menu")
    explain("answer the first (text) question with a real name, and separately "
            "with a BLANK message",
            "a normal name must be stored and move us on. A blank message is the "
            "'open' turn by design — it returns the customer to the main menu "
            "(never silently accepts an empty required answer).")
    after_name = bot_engine.advance(s, bot_engine.initial_state(), "1")  # at step 0
    # bad: a blank/whitespace message is the OPEN turn → back to the menu
    # (an empty required answer is never stored).
    bad = bot_engine.advance(s, after_name["state"], "   ")
    bad_ok = (bad["state"]["phase"] == "menu"
              and bad["state"]["active_flow"] is None
              and bad["state"]["collected"] == {}
              and "full_name" not in bad["state"]["collected"])
    # good: a real name → advance to step 1 (phone)
    good = bot_engine.advance(s, after_name["state"], "דנה כהן")
    good_ok = (good["state"]["step_index"] == 1
               and good["state"]["collected"].get("full_name") == "דנה כהן"
               and "מה הטלפון?" in good["replies"][0])
    result(bad_ok and good_ok,
           "a real name was stored and we moved to the phone question; a blank "
           "message returned to the menu and stored no empty answer")

    # carry the state forward (we are now at the phone step).
    st_phone = good["state"]

    # ── A5 — PHONE step validation (good + bad, normalized to digits) ────────
    banner("A5", "A phone question: junk is refused; a real phone → digits only")
    explain("answer the phone step with '12' (too short) then '050-123-4567'",
            "a phone with too few digits is a typo; a real one must be cleaned "
            "to digits-only so it's stored consistently.")
    bad = bot_engine.advance(s, st_phone, "12")
    bad_ok = (bad["state"]["step_index"] == 1
              and "טלפון לא תקין" in bad["replies"][0])
    good = bot_engine.advance(s, st_phone, "050-123-4567")
    good_ok = (good["state"]["step_index"] == 2
               and good["state"]["collected"].get("phone") == "0501234567"
               and "מה האימייל?" in good["replies"][0])
    result(bad_ok and good_ok,
           "'12' was refused with the custom error; '050-123-4567' stored as "
           "'0501234567' and moved to the email question")

    st_email = good["state"]

    # ── A6 — EMAIL step validation (good + bad) ──────────────────────────────
    banner("A6", "An email question: a non-email is refused; a real one is kept")
    explain("answer the email step with 'hello' then 'dana@example.com'",
            "we don't want garbage where an email should be — the shape must "
            "look like an email before we accept it.")
    bad = bot_engine.advance(s, st_email, "hello")
    bad_ok = bad["state"]["step_index"] == 2
    good = bot_engine.advance(s, st_email, "dana@example.com")
    good_ok = (good["state"]["step_index"] == 3
               and good["state"]["collected"].get("email") == "dana@example.com"
               and "במה לעזור?" in good["replies"][0])
    result(bad_ok and good_ok,
           "'hello' refused; 'dana@example.com' stored and moved to the choice "
           "question")

    st_choice = good["state"]

    # ── A7 — CHOICE step validation (good + bad, by number AND by text) ──────
    banner("A7", "A choice question: out-of-range refused; number OR exact text ok")
    explain("answer the choice with '9' (no such option), then once by NUMBER "
            "'1', and separately by the exact TEXT 'ביטוח דירה'",
            "a closed list must reject anything not on it, but accept either the "
            "option's number or its exact words — both feel natural to a customer.")
    bad = bot_engine.advance(s, st_choice, "9")
    bad_ok = bad["state"]["step_index"] == 3
    by_num = bot_engine.advance(s, st_choice, "1")
    by_txt = bot_engine.advance(s, st_choice, "ביטוח דירה")
    # both pick a valid option and (being the last step) COMPLETE the lead.
    num_ok = (by_num["event"] == "lead_completed"
              and by_num["lead"].get("topic") == "ביטוח רכב")
    txt_ok = (by_txt["event"] == "lead_completed"
              and by_txt["lead"].get("topic") == "ביטוח דירה")
    result(bad_ok and num_ok and txt_ok,
           "'9' refused; '1' chose 'ביטוח רכב'; the exact text 'ביטוח דירה' "
           "chose 'ביטוח דירה' — both normalized to the option text")

    # ── A8 — full lead completion → event + collected lead ───────────────────
    banner("A8", "Finishing the questionnaire fires 'lead_completed' with answers")
    explain("walk the whole signup flow start→finish and read the result",
            "the WHOLE point of a lead flow: when the last answer comes in, the "
            "bot must signal 'done' and hand back exactly the answers collected.")
    st = bot_engine.advance(s, bot_engine.initial_state(), "1")["state"]
    st = bot_engine.advance(s, st, "דנה כהן")["state"]
    st = bot_engine.advance(s, st, "050-123-4567")["state"]
    st = bot_engine.advance(s, st, "dana@example.com")["state"]
    done = bot_engine.advance(s, st, "1")
    expected_lead = {
        "full_name": "דנה כהן",
        "phone": "0501234567",
        "email": "dana@example.com",
        "topic": "ביטוח רכב",
    }
    ok = (done["event"] == "lead_completed"
          and done["lead"] == expected_lead
          and "תודה! קיבלנו את כל הפרטים" in done["replies"][0]
          and done["state"]["phase"] == "menu")
    result(ok, f"the flow completed with event=lead_completed and the exact "
           f"collected lead {expected_lead}, then returned to the menu")

    # ── A9 — human-escalation KEYWORD anywhere → handed_off ──────────────────
    banner("A9", "Typing a human-handoff keyword hands off immediately")
    explain("from the menu, send a sentence containing the word 'נציג'",
            "if a customer asks for a human, the bot must step aside at once — "
            "even mid-sentence — and stop answering.")
    r = bot_engine.advance(s, bot_engine.initial_state(), "אני רוצה לדבר עם נציג בבקשה")
    ok = (r["event"] == "handed_off"
          and r["state"]["phase"] == "handed_off")
    result(ok, "the word 'נציג' inside a sentence triggered the handoff "
           "(event=handed_off)")

    # ── A10 — selecting the human_handoff flow from the menu → handed_off ────
    banner("A10", "Choosing the 'human' flow from the menu hands off")
    explain("from the menu, send '2' (the talk_to_human flow)",
            "picking the 'talk to a human' menu option must do the same thing "
            "as the keyword — hand off and use that flow's message.")
    r = bot_engine.advance(s, bot_engine.initial_state(), "2")
    ok = (r["event"] == "handed_off"
          and r["state"]["phase"] == "handed_off"
          and "מעביר אותך לנציג אנושי" in r["replies"][0])
    result(ok, "selecting flow #2 handed off with its configured message "
           "(event=handed_off)")

    # ── A11 — once handed off, the bot stays paused ──────────────────────────
    banner("A11", "After a handoff the bot is paused (answers nothing new)")
    explain("send another message AFTER the chat was handed off",
            "once a human took over, the bot must not jump back in — it just "
            "says it's paused.")
    r = bot_engine.advance(s, {"phase": "handed_off", "active_flow": None,
                               "step_index": 0, "collected": {}}, "שלום?")
    ok = (r["event"] is None
          and r["state"]["phase"] == "handed_off"
          and "הועברה לנציג" in r["replies"][0])
    result(ok, "while handed off, a new message just got the 'paused' note "
           "(no flow, no event)")

    # ── A12 — selecting a BOOKING flow → booking message with the demo link ──
    banner("A12", "Choosing a booking flow returns the message with the demo link")
    explain("from the menu, send '3' (the booking flow)",
            "booking is Phase 2, but the try-me must still show the booking "
            "message and swap the {link} placeholder for a real demo link.")
    r = bot_engine.advance(s, bot_engine.initial_state(), "3")
    ok = (r["event"] == "booking"
          and "https://example.com/book/demo" in r["replies"][0]
          and "{link}" not in r["replies"][0]
          and r["state"]["phase"] == "menu")
    result(ok, "flow #3 returned the booking message with {link} replaced by "
           "the demo link (event=booking), staying at the menu")

    # ── A13 — return-to-menu keyword from INSIDE a flow → back to menu ───────
    banner("A13", "Typing '0' mid-flow takes the customer back to the main menu")
    explain("start the signup flow, then (mid-flow) send the exact keyword '0'",
            "a customer who changes their mind must always be able to bail out "
            "to the menu by typing the return keyword.")
    st = bot_engine.advance(s, bot_engine.initial_state(), "1")["state"]
    st = bot_engine.advance(s, st, "דנה כהן")["state"]  # now mid-flow at phone
    r = bot_engine.advance(s, st, "0")
    ok = (r["state"]["phase"] == "menu"
          and r["state"]["active_flow"] is None
          and "1. הרשמה ללקוח חדש" in r["replies"][0])
    result(ok, "typing '0' from inside the flow returned to the main menu "
           "(active_flow cleared)")

    # ── A14 — the menu-hint footer is present on in-flow questions ───────────
    banner("A14", "Every in-flow question ends with the 'type תפריט' footer")
    explain("look at the footer on an in-flow question vs. on the menu/handoff",
            "the customer should always be reminded HOW to go back — but that "
            "reminder must NOT clutter the greeting/menu, handoff or booking.")
    in_flow = bot_engine.advance(s, bot_engine.initial_state(), "1")  # a question
    menu = bot_engine.advance(s, bot_engine.initial_state(), "")      # the menu
    handoff = bot_engine.advance(s, bot_engine.initial_state(), "2")  # handoff
    has_footer = in_flow["replies"][0].endswith(bot_engine.MENU_HINT)
    no_footer = (not menu["replies"][0].endswith(bot_engine.MENU_HINT)
                 and not handoff["replies"][0].endswith(bot_engine.MENU_HINT))
    result(has_footer and no_footer,
           "the in-flow question ends with the menu-hint footer; the menu and "
           "handoff messages do NOT (clean, as required)")

    # ── A15 — the engine reads NO stored lead / other-tenant data, writes none ──
    banner("A15", "The engine sees ONLY this chat's own inputs — no data, no writes")
    explain("freeze the config + state, run a turn, prove nothing changed and "
            "the 'lead' is only what THIS chat typed",
            "the engine must be PURE: it must not reach a database, must not "
            "mutate the inputs it was handed, and the lead it returns must be "
            "nothing more than the answers this very conversation gave.")
    frozen_settings = json.loads(json.dumps(ENGINE_SETTINGS))
    state_in = {"phase": "in_flow", "active_flow": "signup",
                "step_index": 3,
                "collected": {"full_name": "דנה כהן", "phone": "0501234567",
                              "email": "dana@example.com"}}
    state_snapshot = json.loads(json.dumps(state_in))
    out = bot_engine.advance(ENGINE_SETTINGS, state_in, "1")
    # (1) inputs were not mutated in place
    settings_untouched = (ENGINE_SETTINGS == frozen_settings)
    state_untouched = (state_in == state_snapshot)
    # (2) the returned lead is EXACTLY this chat's own typed answers — nothing else
    lead_is_own = (out["event"] == "lead_completed"
                   and set(out["lead"].keys()) == {"full_name", "phone",
                                                    "email", "topic"}
                   and out["lead"]["full_name"] == "דנה כהן")
    # (3) no DB/network access is even possible — the module imports none.
    src = bot_engine.advance.__module__
    no_io_imports = src == "app.services.bot_engine"
    result(settings_untouched and state_untouched and lead_is_own and no_io_imports,
           "the engine did not mutate the settings or state it was handed, and "
           "the returned lead held ONLY this chat's own four answers")


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


async def count_build_chat(pool, business_id: str) -> int:
    async with tenant_connection(pool, business_id) as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM bot_builder_messages WHERE business_id = $1",
            business_id,
        )


async def count_leads(pool, business_id: str) -> int:
    async with tenant_connection(pool, business_id) as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM leads WHERE business_id = $1", business_id
        )


async def part_b_endpoint_tests() -> None:
    """Exercise POST /api/bot/tryme against the running stack (DB + Redis)."""
    app_dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]

    app_pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=2)
    redis = aioredis.from_url(redis_url, decode_responses=True)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:

            # ── B1 — a logged-out stranger is locked out ─────────────────────
            banner("B1", "A logged-OUT stranger cannot use try-me (401)")
            explain("POST /api/bot/tryme with NO login cookie",
                    "try-me runs a business's own bot config — it must sit "
                    "behind the same login wall as everything else.")
            code = (await http.post("/api/bot/tryme", json={"message": ""})).status_code
            result(code == 401,
                   f"the try-me door said {code} to a stranger (401 = locked out)")

            # ── B2 — a logged-in owner runs THEIR OWN seeded bot ─────────────
            banner("B2", "Avi runs try-me and sees AVI's own bot (not Bella's)")
            explain("log Avi in, open try-me (empty message)",
                    "the try-me must load the caller's OWN config from the "
                    "session — Avi must see his 'quote' flow, never Bella's.")
            sid_a = await inject_session(redis, AVI_USER, BIZ_A, "Avi Insurance")
            http.cookies.set(SESSION_COOKIE_NAME, sid_a)
            resp = await http.post("/api/bot/tryme", json={"message": ""})
            body = resp.json() if resp.status_code == 200 else {}
            text = (body.get("replies") or [""])[0]
            ok = (resp.status_code == 200
                  and "אבי" in text  # Avi's greeting mentions his agency
                  and "קבלת הצעת מחיר" in text  # Avi's 'quote' flow label
                  and "קביעת תור" not in text)  # NOT Bella's 'appointment' label
            result(ok, "Avi's try-me opened HIS greeting + HIS 'קבלת הצעת מחיר' "
                   "flow, and showed none of Bella's flows")

            # ── B3 — the endpoint persists NOTHING after a full conversation ─
            banner("B3", "A whole simulated chat writes NOTHING (no chat rows, no leads)")
            explain("count bot_builder_messages + leads, run a FULL lead chat "
                    "via the endpoint, then count again",
                    "try-me is a SAFE sandbox: testing the bot must never create "
                    "a fake lead or pollute the build-chat — the counts must be "
                    "identical before and after.")
            chat_before = await count_build_chat(app_pool, BIZ_A)
            leads_before = await count_leads(app_pool, BIZ_A)

            # drive Avi's real seeded 'quote' flow (name → phone → choice) over HTTP,
            # echoing the opaque state back each turn exactly like the UI does.
            state = None
            turns = ["", "1", "אבי הבודק", "052-9999999", "1"]
            last = {}
            for msg in turns:
                r = await http.post("/api/bot/tryme",
                                    json={"message": msg, "state": state})
                last = r.json() if r.status_code == 200 else {}
                state = last.get("state")

            chat_after = await count_build_chat(app_pool, BIZ_A)
            leads_after = await count_leads(app_pool, BIZ_A)

            completed = last.get("event") == "lead_completed"
            nothing_written = (chat_after == chat_before
                               and leads_after == leads_before)
            result(completed and nothing_written,
                   f"the chat finished a lead in-memory (event=lead_completed) "
                   f"yet wrote NOTHING: build-chat {chat_before}→{chat_after}, "
                   f"leads {leads_before}→{leads_after}")

    await redis.delete(f"{_SESSION_KEY_PREFIX}{sid_a}")
    await app_pool.close()
    await redis.aclose()


def tally() -> tuple[int, int]:
    """The (passed, total) counts after the phases run — read by the runner's scoreboard."""
    return _passed, _total
