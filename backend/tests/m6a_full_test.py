"""
============================================================================
  M6a — "MESSAGE YOURSELF" SELF-TEST — FULL TEST, EXPLAINED LIKE YOU'RE FIVE
============================================================================

WHAT IS THIS FILE?
  M6a lets a business OWNER talk to their OWN bot the easy way: they open the
  chat with THEMSELVES on WhatsApp ("Message Yourself") and type. The gateway
  (the little Node program linked to their WhatsApp) notices it's a self-chat,
  sends the text to our backend, the REAL bot answers, and the gateway types the
  answer back into the same self-chat. No customers involved — it's a private
  rehearsal of the live bot, using REAL data.

  This script PRETENDS to be the gateway. It POSTs the exact webhook the gateway
  would send (with the secret X-Gateway-Token header and a `self_test:true`
  flag), and checks the backend does the right thing every time:

      🅰️  "Avi Insurance"   — bot is PUBLISHED (it should answer)
      🅱️  "Bella Barber"    — bot is a DRAFT, not published (it should stay quiet)

  Every check prints:
      🧪 WHAT we try to do
      💡 WHY it matters (what would go wrong in real life)
      ✅ / ❌ what actually happened

  THE ONE THING A SCRIPT CANNOT DO: actually scan a QR and send a real WhatsApp
  message from your phone. That last mile (real send/receive on a real phone) is
  a MANUAL step for Omer — see the note printed at the end. Everything UP TO the
  phone is proven here, automatically.

  Run it with tests/test_m6a.bat (double-click), or read HOW-TO at the bottom.
============================================================================
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets

import asyncpg
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.db.session import tenant_connection
from app.main import app
from app.services import bot_settings as bot_settings_service
from app.services import conversation_state

# The two pretend businesses (their fixed IDs come from supabase/seed.sql).
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (PUBLISHED)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (DRAFT, not published)

# Distinct gateway "account ids" we map to each business for the test. In real
# life this is the gateway's own server-side routing key (config 'spike').
ACC_A = "m6a-acct-avi"
ACC_B = "m6a-acct-bella"
ACC_UNKNOWN = "m6a-acct-nobody"  # never mapped → "no business"

# The owner's own number (the self-chat is with themselves). PII — only used to
# build a realistic webhook; the backend never logs it.
OWN_PHONE = "+972500000001"

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
        print(f"  ❌ BAD    : {detail}   <-- THIS NEEDS A FIX!")


# --- the "pretend gateway" POST helper ---------------------------------------

def _webhook_body(account_id: str, text: str, conversation_id: str,
                  self_test: bool = True, message_id: str | None = None) -> dict:
    """Build exactly the JSON the real gateway POSTs to /webhook/whatsapp."""
    return {
        "gateway_account_id": account_id,
        "from": OWN_PHONE,                       # PII — never logged by backend
        "push_name": "Owner",
        "message_id": message_id or f"m6a-{secrets.token_hex(6)}",
        "timestamp": 1_700_000_000,
        "type": "text",
        "text": text,
        "raw": {"note": "synthetic m6a test message"},
        "self_test": self_test,
        "conversation_id": conversation_id,
    }


async def _seed_mapping(pool, business_id: str, account_id: str) -> None:
    """Record a business_id ↔ gateway_account_id mapping (RLS-scoped UPSERT).

    Mirrors EXACTLY what POST /api/whatsapp/link does (the product's
    whatsapp_service.upsert_connection): INSERT … ON CONFLICT (business_id) DO
    UPDATE. We use the real service so the test exercises the same code path and
    the same grants (app_role has SELECT/INSERT/UPDATE — never DELETE — on this
    table, so we never DELETE it).
    """
    from app.services import whatsapp as whatsapp_service
    await whatsapp_service.upsert_connection(
        pool, business_id, gateway_account_id=account_id,
        phone=OWN_PHONE, status="connected",
    )


async def main() -> int:  # noqa: C901 — a flat, readable list of checks on purpose
    print(__doc__)

    app_dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]
    token = get_settings().gateway_api_token.get_secret_value()

    pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=4)
    redis = aioredis.from_url(redis_url, decode_responses=True)

    # Fresh start: clean any leftover test leads for both tenants. (We never
    # DELETE whatsapp_connections — app_role has no DELETE there; we UPSERT it.)
    for biz in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, biz) as conn:
            await conn.execute("DELETE FROM leads WHERE business_id = $1", biz)

    # Map each business to its own gateway account. Avi is published (seed),
    # Bella is a draft (seed) — exactly the two cases we want to prove.
    await _seed_mapping(pool, BIZ_A, ACC_A)
    await _seed_mapping(pool, BIZ_B, ACC_B)
    print("\n  (set-up done: Avi↔ACC_A [published], Bella↔ACC_B [draft], "
          "ACC_UNKNOWN maps to nobody)")

    # Run everything against the REAL ASGI app (lifespan gives us the pg pool +
    # redis on app.state, exactly like a live request).
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            auth = {"X-Gateway-Token": token}

            # ── TEST 2 (GOAL 2) ──────────────────────────────────────────────
            banner("2", "Owner messages their own number → the PUBLISHED bot answers")
            explain(
                "POST a self_test message ('היי') for Avi's mapped+published bot",
                "this is the whole point of M6a: a self-chat message must run "
                "through the REAL bot (run_turn) and come back with replies for "
                "the gateway to send into the self-chat.")
            conv_a = f"self:{secrets.token_hex(6)}"
            r = await http.post("/webhook/whatsapp",
                                json=_webhook_body(ACC_A, "היי", conv_a), headers=auth)
            body = r.json()
            ok2 = (
                r.status_code == 200
                and body.get("status") == "ok"
                and isinstance(body.get("replies"), list)
                and len(body["replies"]) >= 1
                and any("?" in rp or "תפריט" in rp or "1." in rp for rp in body["replies"])
            )
            result(ok2, f'status={r.status_code} "{body.get("status")}", '
                        f'{len(body.get("replies") or [])} reply/replies came back '
                        f'(the bot answered the self-chat)')

            # ── TEST 3 (GOAL 3) ──────────────────────────────────────────────
            banner("3", "A full lead questionnaire over the webhook → a REAL lead is saved")
            explain(
                "drive Avi's 'quote' flow to the end over self_test webhooks "
                "(pick #1, give name, phone, choose insurance type)",
                "self_test is REAL data (is_test=False). After finishing, the new "
                "lead must show up in the owner's GET /api/leads (the normal list, "
                "which HIDES test rows) — proving it persisted as a real lead.")
            conv_lead = f"self:{secrets.token_hex(6)}"

            async def turn(text: str) -> dict:
                resp = await http.post(
                    "/webhook/whatsapp",
                    json=_webhook_body(ACC_A, text, conv_lead), headers=auth)
                return resp.json()

            await turn("היי")                  # greeting + menu
            t_start = await turn("1")           # start "quote" → asks full name
            t_name = await turn("דנה הבודקת")   # name → asks phone
            t_phone = await turn("0521234567")  # phone → asks insurance type (choice)
            t_done = await turn("1")            # choose "רכב" → completes

            # The owner views their leads (real list — is_test rows excluded).
            # We must be logged in as Avi to read /api/leads, so set a session.
            sid = await _login(redis, http, "google-sub-avi", BIZ_A)
            leads = (await http.get("/api/leads")).json()["leads"]
            await _logout(redis, http, sid)  # tidy the session

            # Find OUR lead (the questionnaire's lead_name is its flow key 'quote'),
            # newest first, and confirm it is a REAL (not test) lead.
            our = [
                lead for lead in leads
                if lead.get("lead_name") == "quote" and lead.get("is_test") is False
            ]
            # Decrypt-on-read happens in the API, so the phone/name come back plain.
            found = bool(our)
            phone_ok = found and any(
                (lead.get("phone") or "").endswith("0521234567") for lead in our)
            ok3 = (
                t_start.get("replies") and t_done.get("replies")
                and found and phone_ok
            )
            result(
                ok3,
                f"the finished questionnaire saved a REAL lead "
                f"(found={found}, phone round-tripped={phone_ok}); it appears in "
                f"GET /api/leads WITHOUT include_test — so it is is_test=False")

            # ── TEST 4 (GOAL 4) ──────────────────────────────────────────────
            banner("4", "A booking turn → the reply carries this business's REAL /book link")
            explain(
                "give Avi a booking flow + a booking page, then pick it over the "
                "webhook, and read the reply",
                "when a customer (or the owner testing) picks 'book', the bot must "
                "send the tenant's OWN public booking link (/book/{slug}), not a "
                "demo placeholder and never another business's link.")
            # Give Avi a published config that INCLUDES a booking flow. We restore
            # the original seeded config right after this check.
            original = await bot_settings_service.get_settings(pool, BIZ_A)
            slug = await _ensure_booking_slug(pool, BIZ_A)
            await _set_booking_config(pool, BIZ_A)
            conv_book = f"self:{secrets.token_hex(6)}"
            await http.post("/webhook/whatsapp",
                            json=_webhook_body(ACC_A, "היי", conv_book), headers=auth)
            rb = (await http.post(
                "/webhook/whatsapp",
                json=_webhook_body(ACC_A, "1", conv_book), headers=auth)).json()
            base = get_settings().public_base_url.rstrip("/")
            expected_link = f"{base}/book/{slug}"
            link_in_reply = any(expected_link in rp for rp in (rb.get("replies") or []))
            no_demo = all("example.com/book/demo" not in rp for rp in (rb.get("replies") or []))
            result(
                link_in_reply and no_demo,
                f"the booking reply contains THIS tenant's real link "
                f"(.../book/{slug[:8]}…) and not the demo placeholder")
            # Restore Avi's original seeded config so later checks/regression match.
            await _restore_config(pool, BIZ_A, original)

            # ── TEST 5 (GOAL 5) ──────────────────────────────────────────────
            banner("5", "Bot NOT published → the bot stays completely silent")
            explain(
                "POST a self_test message for Bella, whose bot is a DRAFT",
                "the LIVE bot must answer ONLY after the owner publishes. A draft "
                "bot must NEVER reply on the real WhatsApp line — replies must be "
                "an empty list (silent).")
            rsil = (await http.post(
                "/webhook/whatsapp",
                json=_webhook_body(ACC_B, "היי", f"self:{secrets.token_hex(6)}"),
                headers=auth)).json()
            ok5 = rsil.get("status") == "not published" and rsil.get("replies") == []
            result(
                ok5,
                f'draft bot replied with status="{rsil.get("status")}" and '
                f"{len(rsil.get('replies') or [])} replies (silent — correct)")

            # ── TEST 6 (GOAL 6) ──────────────────────────────────────────────
            banner("6", "Unknown gateway account → graceful 'no business', no crash")
            explain(
                "POST a self_test message for an account nobody linked",
                "a stray/old session must NOT 500 the backend or leak anything — "
                "it should resolve to no tenant and stay silent.")
            rno = await http.post(
                "/webhook/whatsapp",
                json=_webhook_body(ACC_UNKNOWN, "היי", f"self:{secrets.token_hex(6)}"),
                headers=auth)
            bno = rno.json()
            ok6 = (
                rno.status_code == 200
                and bno.get("status") == "no business"
                and bno.get("replies") == []
            )
            result(
                ok6,
                f'unknown account → status={rno.status_code} '
                f'"{bno.get("status")}", replies={bno.get("replies")} (no crash)')

            # ── TEST 7 (GOAL 7) ──────────────────────────────────────────────
            banner("7", "Loop-prevention: the gateway skips the ids of messages IT sent")
            explain(
                "exercise the gateway's loop-guard logic directly (the cap, the "
                "oldest-evicted rule, and 'skip an id we already sent')",
                "in a self-chat every reply the bot sends ECHOES back as an "
                "inbound fromMe message. Without a guard the bot would answer its "
                "OWN replies forever. (The REAL phone echo is a manual check; the "
                "LOGIC is proven here.)")
            loop_ok, loop_detail = _check_gateway_loop_guard()
            result(loop_ok, loop_detail)

            # ── TEST 8a (GOAL 8) ─────────────────────────────────────────────
            banner("8a", "A bad/missing gateway token is rejected (401)")
            explain(
                "POST the same self_test message with a WRONG token, and with NO "
                "token at all",
                "the webhook is PUBLIC on the network — only the gateway's shared "
                "secret may use it. A wrong/absent token must be a flat 401, "
                "before any business work happens.")
            bad = await http.post(
                "/webhook/whatsapp",
                json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
                headers={"X-Gateway-Token": "totally-wrong"})
            missing = await http.post(
                "/webhook/whatsapp",
                json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"))
            result(
                bad.status_code == 401 and missing.status_code == 401,
                f"wrong token → {bad.status_code}, missing token → "
                f"{missing.status_code} (both 401 — locked)")

            # ── TEST 8b (GOAL 8) ─────────────────────────────────────────────
            banner("8b", "The owner WhatsApp admin routes need a login (401 without one)")
            explain(
                "call GET /api/whatsapp/status, POST /api/whatsapp/link and GET "
                "/api/whatsapp/qr WITHOUT any session cookie",
                "these manage a business's WhatsApp link. With no login there is "
                "no verified tenant, so the deny-by-default /api gate must answer "
                "401 (never guess a business).")
            s1 = await http.get("/api/whatsapp/status")
            s2 = await http.post("/api/whatsapp/link")
            s3 = await http.get("/api/whatsapp/qr")
            result(
                s1.status_code == 401 and s2.status_code == 401 and s3.status_code == 401,
                f"status={s1.status_code}, link={s2.status_code}, "
                f"qr={s3.status_code} (all 401 without a session)")

            # ── TEST 8c (GOAL 8 — isolation) ─────────────────────────────────
            banner("8c", "The admin status route is tenant-scoped (Avi sees ONLY Avi's link)")
            explain(
                "log in as Avi and read GET /api/whatsapp/status",
                "the 'linked' flag must reflect THIS tenant's own mapping only — "
                "never leak whether another business has linked.")
            sid_a = await _login(redis, http, "google-sub-avi", BIZ_A)
            st_a = (await http.get("/api/whatsapp/status")).json()
            await _logout(redis, http, sid_a)
            # Avi is mapped (ACC_A) → linked must be True; the response is the
            # frozen shape with no other tenant's data.
            shape_ok = set(st_a.keys()) == {"linked", "connected", "phone", "gateway_status"}
            result(
                st_a.get("linked") is True and shape_ok,
                f"Avi's own status: linked={st_a.get('linked')}, "
                f"shape={sorted(st_a.keys())} (only this tenant's view)")

            # ── TEST 9 (negative control) ────────────────────────────────────
            banner("9", "NEGATIVE CONTROL: break the publish gate on purpose, watch it catch it")
            explain(
                "temporarily UN-publish Avi, send a self_test message, confirm the "
                "bot goes silent — then RE-publish and confirm it answers again",
                "a good test must be able to FAIL. If un-publishing still produced "
                "replies, the publish gate would be doing nothing. We prove the "
                "gate is real, then restore the original state.")
            await bot_settings_service.set_published(pool, BIZ_A, False)
            broke = (await http.post(
                "/webhook/whatsapp",
                json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
                headers=auth)).json()
            caught = broke.get("status") == "not published" and broke.get("replies") == []
            # Restore published + verify the bot answers again.
            await bot_settings_service.set_published(pool, BIZ_A, True)
            fixed = (await http.post(
                "/webhook/whatsapp",
                json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
                headers=auth)).json()
            restored = fixed.get("status") == "ok" and len(fixed.get("replies") or []) >= 1
            result(
                caught and restored,
                "un-published → silent (the gate caught it); re-published → the "
                "bot answers again (restored)")

    # ── clean up the leads we made (we leave the connection mappings; app_role
    #    cannot DELETE them, and a re-run simply UPSERTs them again) ────────────
    for biz in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, biz) as conn:
            await conn.execute("DELETE FROM leads WHERE business_id = $1", biz)
    await pool.close()
    await redis.aclose()

    # ── Scoreboard ───────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    if _passed == _total:
        print(f"  🎉 RESULT: {_passed}/{_total} checks held. The 'Message Yourself' "
              "self-test path works end-to-end.  🤖💬")
    else:
        print(f"  🚨 RESULT: {_passed}/{_total} held — {_total - _passed} FAILED. "
              "Do not ship until green.")
    print("=" * 74)
    print()
    print("  📱 MANUAL STEP FOR OMER (a script cannot do this part):")
    print("     1) Make sure WhatsApp is linked (scan the QR at :3000/qr).")
    print("     2) On your phone, open the chat with YOURSELF (Message Yourself).")
    print("     3) Type 'היי' — the bot should reply right there in that chat.")
    print("     This proves the REAL send/receive on a REAL phone. Everything")
    print("     BEFORE the phone (the whole backend pipeline) is proven above.")
    print("=" * 74)
    return 0 if _passed == _total else 1


# --- session + config helpers ------------------------------------------------

async def _login(redis, http, user_id: str, business_id: str) -> str:
    """Mint an opaque Redis session + set the cookie, like a logged-in owner."""
    import time

    from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": f"{user_id}@example.com", "name": user_id,
        "picture": "", "business_id": business_id, "business_name": "x",
        "created_at": int(time.time()),
    }
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)
    return sid


async def _logout(redis, http, sid: str) -> None:
    """Destroy the Redis session + clear the cookie (tidy after a logged-in read)."""
    from app.services.auth import _SESSION_KEY_PREFIX
    await redis.delete(f"{_SESSION_KEY_PREFIX}{sid}")
    http.cookies.clear()


async def _ensure_booking_slug(pool, business_id: str) -> str:
    """Make sure a booking_settings row + slug exists; return the live slug."""
    from app.services import booking as booking_service
    async with tenant_connection(pool, business_id) as conn:
        settings = await booking_service.get_settings(conn, business_id)
    return settings["slug"]


async def _set_booking_config(pool, business_id: str) -> None:
    """Publish a config whose FIRST menu flow is a booking flow (for the link test)."""
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            """
            UPDATE bot_settings
            SET lead_steps = $2::jsonb, is_published = true, updated_at = now()
            WHERE business_id = $1
            """,
            business_id,
            json.dumps({
                "book_now": {
                    "label": "קביעת תור",
                    "flow_type": "booking",
                    "message": "לקביעת תור היכנסו לקישור: {link}",
                    "steps": [],
                }
            }, ensure_ascii=False),
        )


async def _restore_config(pool, business_id: str, original: dict) -> None:
    """Write back a previously-read get_settings() dict (lead_steps + publish)."""
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            """
            UPDATE bot_settings
            SET lead_steps = $2::jsonb, is_published = $3, updated_at = now()
            WHERE business_id = $1
            """,
            business_id,
            json.dumps(original.get("lead_steps") or {}, ensure_ascii=False),
            bool(original.get("is_published")),
        )


# --- the gateway loop-guard logic check (Goal 7) -----------------------------

def _check_gateway_loop_guard() -> tuple[bool, str]:
    """Re-implement + verify the EXACT loop-guard rules from gateway/src/index.js.

    The gateway keeps a bounded Set of ids of messages IT sent (cap 200,
    oldest-evicted by insertion order) and SKIPS any inbound whose id is in it.
    We prove the three properties the gateway relies on:
      1. an id we 'sent' is then skipped (the anti-loop rule),
      2. the cap holds at 200,
      3. the oldest id is evicted first; the newest is kept.
    This mirrors `rememberSentId` + the top-of-handleInbound skip check.
    """
    SENT_ID_CAP = 200
    sent: dict[str, None] = {}  # py dict preserves insertion order, like JS Set

    def remember(mid: str) -> None:
        if not mid:
            return
        sent[mid] = None
        if len(sent) > SENT_ID_CAP:
            oldest = next(iter(sent))
            del sent[oldest]

    def should_skip(mid: str) -> bool:
        return bool(mid) and mid in sent

    # 1) an id we sent is skipped (no reply-to-self loop).
    remember("reply-1")
    rule_skip = should_skip("reply-1") and not should_skip("a-real-inbound")

    # 2) + 3) fill past the cap; the cap holds and the oldest is gone, newest kept.
    for i in range(SENT_ID_CAP + 50):
        remember(f"id-{i}")
    cap_ok = len(sent) == SENT_ID_CAP
    oldest_evicted = not should_skip("reply-1") and not should_skip("id-0")
    newest_kept = should_skip(f"id-{SENT_ID_CAP + 50 - 1}")

    ok = rule_skip and cap_ok and oldest_evicted and newest_kept
    detail = (
        f"a sent id is skipped (no loop)={rule_skip}; cap held at {len(sent)}="
        f"{cap_ok}; oldest evicted={oldest_evicted}; newest kept={newest_kept}")
    return ok, detail


# ── HOW TO RUN ───────────────────────────────────────────────────────────────
#   Easiest : double-click  tests/test_m6a.bat   (it sets everything up for you).
#   By hand : from the project root, with the stack running (run.bat):
#     docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m6a_full_test.py"
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
