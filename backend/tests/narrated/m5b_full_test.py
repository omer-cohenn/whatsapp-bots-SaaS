"""
============================================================================
  M5 (part B) — THE BOT'S LEAD MEMORY — FULL TEST, EXPLAINED LIKE YOU'RE FIVE
============================================================================

WHAT IS THIS FILE?
  The earlier M5 test (m5_full_test.py) proved the "try-me" sandbox that
  saves NOTHING. THIS file proves the OTHER side of M5: the real RUNTIME that
  REMEMBERS. When a customer talks to the bot for real, the bot must:

    1. open a LEAD note the moment a questionnaire starts,
    2. fill that note in as the customer answers each question,
    3. mark the note "done" (status 'new') when the questionnaire finishes,
    4. write down the customer's phone/name/answers in a LOCKED way
       (encrypted) — so a stolen database is useless to a thief,
    5. STEP ASIDE and go silent the moment a human takes over, and
    6. give up on notes that went quiet for an hour ("abandoned").

  And — the rule that can never break — business A must NEVER see or touch
  business B's lead notes. Each business has its own locked drawer.

  We drive real conversations two ways:
    * over the real endpoint  POST /api/bot/sim  (login-gated, is_test=true)
    * by calling  bot_runtime.run_turn(...)  directly (for the handoff-silence
      and the abandoned-sweep checks, which need exact control of Redis state).

  Then we re-prove nothing regressed: M2 wall, M3 login, M4 builder, and the
  M5 try-me suite all stay green (the .bat runner does that part).

  Every check prints:  🧪 WHAT we try · 💡 WHY it matters · ✅/❌ the result.

  Run it with tests/test_m5b.bat (double-click), or read HOW-TO at the bottom.
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

from app.core import crypto
from app.db.session import tenant_connection
from app.main import app
from app.services import bot_runtime, conversation_state
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

# The two pretend businesses (fixed ids from supabase/seed.sql).
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (published bot)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (draft bot)
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

# Avi's seeded 'quote' lead flow has 3 steps: full_name(text) → phone(phone)
# → insurance_type(choice of 4). The plaintext we will type as a customer:
CUST_NAME = "דנה הבודקת"
CUST_PHONE = "052-1234567"
CUST_PHONE_DIGITS = "0521234567"   # the engine normalizes phones to digits-only
CUST_CHOICE_TEXT = "רכב"           # option #1 in Avi's insurance_type step

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


# --- small DB helpers (each opens its OWN tenant-scoped connection) ----------

async def fetch_lead(pool, business_id: str, lead_id: str) -> dict | None:
    """Read ONE lead row (raw, as stored on disk) for this tenant."""
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            "SELECT * FROM leads WHERE id = $1 AND business_id = $2",
            lead_id, business_id,
        )
    return dict(row) if row else None


async def fetch_events(pool, business_id: str, lead_id: str) -> list[str]:
    """The ordered list of funnel event names for a lead (oldest→newest)."""
    async with tenant_connection(pool, business_id) as conn:
        rows = await conn.fetch(
            """
            SELECT event FROM flow_events
            WHERE business_id = $1 AND lead_id = $2
            ORDER BY created_at, id
            """,
            business_id, lead_id,
        )
    return [r["event"] for r in rows]


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


# ============================================================================
#  THE TESTS
# ============================================================================

async def run() -> int:
    app_dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]
    pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=3)
    redis = aioredis.from_url(redis_url, decode_responses=True)

    # ids/sessions we create so we can clean them up at the end.
    made_conv_ids: list[tuple[str, str]] = []   # (business_id, conversation_id)
    sids: list[str] = []

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:

            # ── 1 — door is locked without a login ───────────────────────────
            banner("1", "POST /api/bot/sim is locked to strangers (401)")
            explain("POST /api/bot/sim with NO login cookie",
                    "the sim runs a business's own bot and WRITES lead rows — it "
                    "must sit behind the same login wall as everything else, or a "
                    "stranger could forge leads / probe another tenant.")
            code = (await http.post("/api/bot/sim", json={"message": "1"})).status_code
            result(code == 401, f"the sim door said {code} to a stranger (401 = locked)")

            # Log Avi in for the rest of the endpoint checks.
            sid_a = await inject_session(redis, AVI_USER, BIZ_A, "Avi Insurance")
            sids.append(sid_a)
            http.cookies.set(SESSION_COOKIE_NAME, sid_a)

            # ── 2 — starting a flow CREATES an in_progress test lead + 'started' ─
            banner("2", "Starting a flow opens a lead (is_test, in_progress) + 'started'")
            explain("send '1' (pick Avi's 'quote' flow) on a fresh sim conversation",
                    "the instant a customer begins a questionnaire the bot must "
                    "open a lead note so nothing is lost — flagged is_test so this "
                    "drill never pollutes the real funnel, and a 'started' funnel "
                    "event so the owner can later see how many people began.")
            r = (await http.post("/api/bot/sim", json={"message": "1"})).json()
            conv_id = r["conversation_id"]
            made_conv_ids.append((BIZ_A, conv_id))
            lead_id = r["lead_id"]
            lead = await fetch_lead(pool, BIZ_A, lead_id) if lead_id else None
            events = await fetch_events(pool, BIZ_A, lead_id) if lead_id else []
            ok = (lead_id is not None
                  and lead is not None
                  and lead["status"] == "in_progress"
                  and lead["is_test"] is True
                  and lead["lead_name"] == "quote"
                  and lead["submitted_at"] is None
                  and events == ["started"])
            result(ok, f"a lead row appeared (status=in_progress, is_test=true, "
                   f"flow='quote', not yet submitted) with events {events}")

            # ── 3 — answering a step UPDATES the lead + emits 'step' ─────────
            banner("3", "Answering a question grows the same lead + a 'step' event")
            explain("answer the name question, then the phone question (2 turns)",
                    "as the customer answers, the SAME lead note must fill in and "
                    "advance — each answered step adding a 'step' funnel event — "
                    "never spawning a new note per message.")
            r2 = (await http.post("/api/bot/sim",
                                  json={"message": CUST_NAME, "conversation_id": conv_id})).json()
            r3 = (await http.post("/api/bot/sim",
                                  json={"message": CUST_PHONE, "conversation_id": conv_id})).json()
            lead_after = await fetch_lead(pool, BIZ_A, lead_id)
            events_after = await fetch_events(pool, BIZ_A, lead_id)
            # same lead the whole time; still in progress; two 'step' events added.
            ok = (r2["lead_id"] == lead_id and r3["lead_id"] == lead_id
                  and lead_after["status"] == "in_progress"
                  and lead_after["last_step_index"] is not None
                  and events_after == ["started", "step", "step"])
            result(ok, f"the same lead grew (still in_progress, last_step_index="
                   f"{lead_after['last_step_index']}) and events are {events_after}")

            # ── 4 — the stored PII is ENCRYPTED at rest (not plaintext) ──────
            banner("4", "The phone / name / answers are stored LOCKED (encrypted)")
            explain("read the RAW DB columns and compare to what the customer typed",
                    "if a thief steals the database, the lead's phone, name and "
                    "answers must be scrambled ciphertext — NEVER the plaintext. "
                    "And our own key must turn it back into the real values.")
            raw_phone = lead_after["phone"]
            raw_name = lead_after["contact_name"]
            raw_answers = lead_after["answers"]          # jsonb → str or dict
            answers_obj = raw_answers if isinstance(raw_answers, dict) else json.loads(raw_answers)
            # (a) the raw columns must NOT contain the plaintext anywhere.
            blob_text = json.dumps(answers_obj, ensure_ascii=False)
            no_plaintext = (
                raw_phone is not None and CUST_PHONE_DIGITS not in raw_phone
                and CUST_PHONE not in raw_phone
                and raw_name is not None and CUST_NAME not in raw_name
                and CUST_NAME not in blob_text and CUST_PHONE_DIGITS not in blob_text
            )
            # (b) the answers blob uses the encrypted {"_": ciphertext} shape.
            shaped = set(answers_obj.keys()) == {"_"}
            # (c) and with OUR key it all decrypts back to the real values.
            dec_phone = crypto.decrypt_pii(raw_phone)
            dec_name = crypto.decrypt_pii(raw_name)
            dec_answers = crypto.decrypt_answers(answers_obj)
            round_trips = (dec_phone == CUST_PHONE_DIGITS
                           and dec_name == CUST_NAME
                           and dec_answers.get("phone") == CUST_PHONE_DIGITS
                           and dec_answers.get("full_name") == CUST_NAME)
            result(no_plaintext and shaped and round_trips,
                   "phone/name/answers on disk are ciphertext (no plaintext "
                   "leaked), shaped {\"_\": ...}, and decrypt back to the real "
                   "values with our key")

            # ── 5 — finishing sets status 'new' + submitted_at + 'completed' ─
            banner("5", "Finishing the questionnaire marks the lead 'new' + 'completed'")
            explain("answer the last (choice) question to complete the flow",
                    "when the last answer arrives the note must flip to 'new' "
                    "(ready for the owner to read), stamp the submission time, and "
                    "log a 'completed' funnel event — the moment a lead is 'real'.")
            r4 = (await http.post("/api/bot/sim",
                                  json={"message": "1", "conversation_id": conv_id})).json()
            done_lead = await fetch_lead(pool, BIZ_A, lead_id)
            done_events = await fetch_events(pool, BIZ_A, lead_id)
            dec_done = crypto.decrypt_answers(
                done_lead["answers"] if isinstance(done_lead["answers"], dict)
                else json.loads(done_lead["answers"])
            )
            ok = (r4["event"] == "lead_completed"
                  and done_lead["status"] == "new"
                  and done_lead["submitted_at"] is not None
                  and done_events == ["started", "step", "step", "completed"]
                  and dec_done.get("insurance_type") == CUST_CHOICE_TEXT)
            result(ok, f"the lead finished: status='new', submitted_at set, events "
                   f"{done_events}, and the final answer ({CUST_CHOICE_TEXT}) was "
                   "captured")

            # ── 6 — human handoff → chat_status 'waiting' + bot goes SILENT ──
            # M8 contract: a handoff flips the chat to 'waiting' (the customer
            # asked for a person, nobody has picked up YET), not straight to
            # 'human'. The bot is silent in BOTH 'waiting' and 'human'.
            banner("6", "A human handoff flips the chat to 'waiting' and the bot goes silent")
            explain("trigger handoff (run_turn), then send ANOTHER message",
                    "the customer asked for a person → status becomes 'waiting' in "
                    "Redis and the bot must NOT talk over them — every later turn "
                    "returns no replies at all (silent).")
            ho_conv = f"sim:{secrets.token_hex(8)}"
            made_conv_ids.append((BIZ_A, ho_conv))
            # 'נציג' is one of Avi's handoff keywords → keyword handoff.
            ho = await bot_runtime.run_turn(pool, redis, BIZ_A, ho_conv,
                                            "אני רוצה לדבר עם נציג", is_test=True)
            status_after = await conversation_state.get_status(redis, BIZ_A, ho_conv)
            # the NEXT turn must be silent (bot paused).
            nxt = await bot_runtime.run_turn(pool, redis, BIZ_A, ho_conv,
                                             "שלום? יש מישהו?", is_test=True)
            ok = (ho["event"] == "handed_off"
                  and status_after == conversation_state.STATUS_WAITING
                  and nxt["silent"] is True
                  and nxt["replies"] == []
                  and nxt["event"] is None)
            result(ok, "handoff set chat_status='waiting' in Redis; the next turn "
                   "was SILENT (no replies, silent=true)")

            # ── 7 — abandoned sweep flips a stale in_progress lead ──────────
            banner("7", "An idle in_progress lead gets swept to 'abandoned' + event")
            explain("open a lead, back-date its last_activity_at >60 min, run the "
                    "sweep function directly",
                    "a customer who starts then vanishes leaves a stuck note. The "
                    "background sweep must, after the idle window, mark it "
                    "'abandoned' and log an 'abandoned' event so the owner can "
                    "follow up and the funnel reflects reality.")
            ab_conv = f"sim:{secrets.token_hex(8)}"
            made_conv_ids.append((BIZ_A, ab_conv))
            ab = await bot_runtime.run_turn(pool, redis, BIZ_A, ab_conv, "1", is_test=True)
            ab_lead_id = ab["lead_id"]
            # back-date this lead's clock to 2 hours ago (tenant-scoped UPDATE).
            async with tenant_connection(pool, BIZ_A) as conn:
                await conn.execute(
                    "UPDATE leads SET last_activity_at = now() - interval '120 minutes' "
                    "WHERE id = $1 AND business_id = $2",
                    ab_lead_id, BIZ_A,
                )
            from app.services import abandoned_sweep
            n = await abandoned_sweep.run_sweep_once(pool)
            swept_lead = await fetch_lead(pool, BIZ_A, ab_lead_id)
            swept_events = await fetch_events(pool, BIZ_A, ab_lead_id)
            ok = (n >= 1
                  and swept_lead["status"] == "abandoned"
                  and "abandoned" in swept_events
                  and swept_lead["is_test"] is True)
            result(ok, f"the idle lead was swept to 'abandoned' (sweep touched "
                   f"{n} lead(s)); its events now include 'abandoned': {swept_events}")

            # ── 8 — tenant isolation: B cannot see A's lead ─────────────────
            banner("8", "Business B cannot read business A's lead (the wall holds)")
            explain("ask for A's lead id, but on a connection scoped to B",
                    "the #1 SaaS rule: one business must NEVER reach another's "
                    "data. Even with A's exact lead id, B's RLS-scoped query must "
                    "return nothing.")
            async with tenant_connection(pool, BIZ_B) as conn:
                seen_by_b = await conn.fetchrow(
                    "SELECT id FROM leads WHERE id = $1", lead_id
                )
                # B also cannot read it even if it tries to name A's business_id.
                seen_by_b2 = await conn.fetchrow(
                    "SELECT id FROM leads WHERE id = $1 AND business_id = $2",
                    lead_id, BIZ_A,
                )
            result(seen_by_b is None and seen_by_b2 is None,
                   "B's RLS-scoped query for A's lead returned NOTHING (no leak)")

            # ── 9 — tenant isolation: B cannot WRITE/steal A's lead ─────────
            banner("9", "Business B cannot overwrite business A's lead")
            explain("try to UPDATE A's lead from a B-scoped connection",
                    "isolation must block writes too — B must not be able to "
                    "tamper with, claim, or delete A's lead.")
            async with tenant_connection(pool, BIZ_B) as conn:
                res = await conn.execute(
                    "UPDATE leads SET status = 'new' WHERE id = $1", lead_id
                )
            # asyncpg returns e.g. 'UPDATE 0' — 0 rows touched means RLS blocked it.
            still_a = await fetch_lead(pool, BIZ_A, lead_id)
            ok = (res.strip().endswith(" 0") and still_a["status"] == "new")
            result(ok, f"B's UPDATE on A's lead touched 0 rows ({res.strip()!r}); "
                   "A's lead is untouched")

            # ── 10 — /api/bot/sim is scoped to the CALLER only ──────────────
            banner("10", "Avi's /api/bot/sim writes a lead under AVI only (not B)")
            explain("count B's leads, run a sim turn as Avi, count B's leads again",
                    "the sim takes the tenant from the LOGIN session, never the "
                    "body — so Avi using it can only ever create AVI leads; B's "
                    "lead count must not move.")
            async def count_leads(bid: str) -> int:
                async with tenant_connection(pool, bid) as conn:
                    return await conn.fetchval(
                        "SELECT count(*) FROM leads WHERE business_id = $1", bid
                    )
            b_before = await count_leads(BIZ_B)
            sim_conv = f"sim:{secrets.token_hex(8)}"
            made_conv_ids.append((BIZ_A, sim_conv))
            r = (await http.post("/api/bot/sim",
                                 json={"message": "1", "conversation_id": sim_conv})).json()
            new_lead = await fetch_lead(pool, BIZ_A, r["lead_id"])
            b_after = await count_leads(BIZ_B)
            ok = (new_lead is not None
                  and str(new_lead["business_id"]) == BIZ_A
                  and b_after == b_before)
            result(ok, f"Avi's sim created a lead under BIZ_A; B's lead count "
                   f"stayed {b_before}→{b_after} (no cross-tenant write)")

    # ── cleanup: remove the test leads/events/state we made ─────────────────
    try:
        for bid, cid in made_conv_ids:
            await conversation_state.clear_state(redis, bid, cid)
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.execute(
                "DELETE FROM leads WHERE business_id = $1 AND is_test = true", BIZ_A
            )
        for sid in sids:
            await redis.delete(f"{_SESSION_KEY_PREFIX}{sid}")
    finally:
        await pool.close()
        await redis.aclose()

    # ── Scoreboard ──────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    if _passed == _total:
        print(f"  🎉 RESULT: {_passed}/{_total} checks held. The lead MEMORY works: "
              "leads are opened, grown, completed, encrypted at rest, swept when "
              "abandoned, silent on handoff — and perfectly walled per tenant. 🔒")
        print("=" * 74)
        return 0
    print(f"  🚨 RESULT: {_passed}/{_total} held — {_total - _passed} CHECK(S) FAILED. "
          "Do not ship until green.")
    print("=" * 74)
    return 1


# ── HOW TO RUN ───────────────────────────────────────────────────────────────
#   Easiest : double-click  tests/test_m5b.bat   (it sets everything up).
#   By hand : from the project root, with the stack running (run.bat):
#     docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m5b_full_test.py"
#
#   Needs the DB + Redis (the stack). No GEMINI key is needed — the runtime path
#   never calls the AI (the engine is pure).
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(__doc__)
    raise SystemExit(asyncio.run(run()))
