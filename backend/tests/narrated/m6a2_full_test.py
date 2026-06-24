"""
============================================================================
  M6a.2 — THE OWNER'S MANUAL REPLY NOW REACHES WHATSAPP — EXPLAINED SIMPLY
============================================================================

WHAT IS THIS FILE, IN PLAIN WORDS?

  Before M6a.2 there was a hole. When the BOT answered a customer, the reply was
  sent to WhatsApp automatically. But when the OWNER took over a chat and typed a
  reply in the dashboard, that reply was only SAVED (queued in Redis). NOTHING
  actually sent it to the customer's WhatsApp. The customer never saw it.

  M6a.2 closes that hole. Now, when the owner sends a manual reply:
     1) it is STILL saved/queued exactly like before (so it's never lost), AND
     2) the backend immediately tries to SEND it to WhatsApp through the gateway.

  How does it know WHERE to send? Easy: the conversation's id IS the customer's
  WhatsApp address (their jid, e.g. '<number>@s.whatsapp.net'). So the backend
  just sends the reply straight "to" that id.

  THE PIECES we check here (each prints 🧪 what · 💡 why · ✅/❌ result):

   • The gateway's NEW front door — POST /send-bot (a private door only the
     backend may knock on, using the shared secret token):
        - a WRONG or MISSING token  → 401 (slammed shut, before any send)
        - a missing 'to' or 'text'  → 400 (nothing to send)
        - connected + valid + body  → 200 with a real message id (it sent!)

   • The backend's NEW helper — send_outbound(to, text):
        - when the gateway says "ok: true"   → returns True  ("delivered")
        - when ANYTHING goes wrong (gateway down, timeout, error, weird answer)
                                              → returns False, NEVER crashes
        - it NEVER writes the phone number or the message text into the logs.

   • The dashboard route — POST /api/conversations/{id}/reply:
        - STILL queues the reply in the outbox (the old promise is kept), AND
        - now also reports "delivered": true/false, AND
        - calls send_outbound with the conversation id as the address.

  THE ONE THING A SCRIPT CANNOT DO: type into WhatsApp on a real second phone.
  But because the gateway here is linked to Omer's real WhatsApp, the LIVE 200
  test below sends a tiny "please ignore" note to OMER'S OWN number (the safe
  self-chat) — so you can literally see a real message arrive. If WhatsApp is
  not linked, that one live check is skipped (everything else still runs).

  Run it with tests/test_m6a2.bat (double-click), or read HOW-TO at the bottom.
============================================================================

  (This file is a thin runner: helpers + stub client + narration live in
   _m6a2_story.py — same printed output, just organized.)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets

import httpx
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.services import conversation_state
from app.services import whatsapp as whatsapp_service

# Shared constants + helpers + stub client + narration live in _m6a2_story.py
# (a thin split: same printed output; this runner keeps the whole main() flow).
from _m6a2_story import (
    AVI_USER,
    BIZ_A,
    GATEWAY_BASE,
    GATEWAY_TOKEN,
    REPLY_TEXT,
    _StubClient,
    _check_loop_guard,
    _gateway_status,
    _login,
    _logout,
    banner,
    explain,
    result,
    skipped,
    tally,
)

async def main() -> int:  # noqa: C901 — a flat, readable list of checks on purpose
    print(__doc__)

    redis_url = os.environ["REDIS_URL"]
    rds = aioredis.from_url(redis_url, decode_responses=True)

    reachable, connected, own_phone = await _gateway_status()
    print(f"\n  (gateway: reachable={reachable}, whatsapp_connected={connected})")

    # We patch the dashboard's send_outbound symbol for the route checks so no
    # real WhatsApp message is sent there; restored at the end.
    import app.api.dashboard as dash
    real_send_outbound = dash.whatsapp_service.send_outbound

    # Save the REAL httpx.AsyncClient class up front. The send_outbound stub swaps
    # `whatsapp_service.httpx.AsyncClient` — which IS the httpx module's attribute
    # — so we must restore from this saved reference, never from `httpx.AsyncClient`
    # (that name already points at whatever we last set it to).
    real_async_client = httpx.AsyncClient

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:

            # ── TEST 1 ───────────────────────────────────────────────────────
            banner("1", "send_outbound: gateway says 'ok: true' → returns True (delivered)")
            explain(
                "call the backend helper send_outbound() but swap the real network "
                "client for a fake that answers 200 with {\"ok\": true}.",
                "this is the SUCCESS path: when the gateway confirms it sent the "
                "message, the owner's reply is 'delivered'. send_outbound must "
                "return True AND post to /send-bot with the token header + the jid "
                "and text in the body.")
            whatsapp_service.httpx.AsyncClient = _StubClient(200, {"ok": True})  # type: ignore[assignment]
            ok_true = await whatsapp_service.send_outbound("x@s.whatsapp.net", "hi")
            cap = _StubClient.captured
            ok1 = (
                ok_true is True
                and cap["url"].endswith("/send-bot")
                and cap["headers"].get("X-Gateway-Token") == GATEWAY_TOKEN
                and cap["json"] == {"to": "x@s.whatsapp.net", "text": "hi"}
            )
            result(
                ok1,
                f"returned {ok_true}; posted to …/send-bot with the X-Gateway-Token "
                f"header and a {{to,text}} body (token value not shown)")

            # ── TEST 2 ───────────────────────────────────────────────────────
            banner("2", "send_outbound: ANY failure → returns False, never crashes")
            explain(
                "feed send_outbound four bad answers in turn: {\"ok\": false}, a 503, "
                "a non-JSON body, and a dead gateway URL.",
                "the reply is ALWAYS already queued, so the send is 'best effort'. "
                "On any problem it must return False (so we can say 'queued but not "
                "delivered') and must NEVER raise and error the owner's request.")
            whatsapp_service.httpx.AsyncClient = _StubClient(200, {"ok": False})  # type: ignore[assignment]
            f_okfalse = await whatsapp_service.send_outbound("x@s.whatsapp.net", "hi")
            whatsapp_service.httpx.AsyncClient = _StubClient(503, {"ok": False})  # type: ignore[assignment]
            f_503 = await whatsapp_service.send_outbound("x@s.whatsapp.net", "hi")
            whatsapp_service.httpx.AsyncClient = _StubClient(200, ValueError("x"))  # type: ignore[assignment]
            f_badjson = await whatsapp_service.send_outbound("x@s.whatsapp.net", "hi")
            # Dead URL: restore the REAL client, point settings at a closed port.
            whatsapp_service.httpx.AsyncClient = real_async_client
            s = get_settings()
            saved_base = s.gateway_base_url
            s.gateway_base_url = "http://127.0.0.1:1"  # nothing listens here
            try:
                f_dead = await whatsapp_service.send_outbound("x@s.whatsapp.net", "hi")
            finally:
                s.gateway_base_url = saved_base
            ok2 = not any([f_okfalse, f_503, f_badjson, f_dead])
            result(
                ok2,
                f"ok:false→{f_okfalse}, 503→{f_503}, bad-json→{f_badjson}, "
                f"dead-url→{f_dead} (all False, no exception)")

            # ── TEST 3 ───────────────────────────────────────────────────────
            banner("3", "send_outbound NEVER logs the phone (jid) or the message text")
            explain(
                "make send_outbound fail while watching the log stream, using an "
                "obvious fake jid and an obvious fake message body.",
                "the golden rule: never log PII. Even when reporting a failure, the "
                "customer's number and the reply text must NOT appear in the logs.")
            secret_jid = "972599999999@s.whatsapp.net"
            secret_text = "super-secret-reply-body-xyz"
            captured_logs: list[str] = []

            class _Catch(logging.Handler):
                def emit(self, record):
                    captured_logs.append(record.getMessage())

            handler = _Catch()
            root = logging.getLogger()
            root.addHandler(handler)
            prev_level = root.level
            root.setLevel(logging.DEBUG)
            try:
                whatsapp_service.httpx.AsyncClient = _StubClient(503, {"ok": False})  # type: ignore[assignment]
                await whatsapp_service.send_outbound(secret_jid, secret_text)
            finally:
                root.removeHandler(handler)
                root.setLevel(prev_level)
            blob = " ".join(captured_logs)
            ok3 = (
                secret_jid not in blob
                and secret_text not in blob
                and GATEWAY_TOKEN not in blob
            )
            result(
                ok3,
                "the failure log contains neither the jid, the message text, nor "
                "the token (PII-safe logging holds)")

            # Restore the real network client for the rest of the run.
            whatsapp_service.httpx.AsyncClient = real_async_client

            # ── TEST 4 ───────────────────────────────────────────────────────
            banner("4", "Gateway /send-bot: a WRONG or MISSING token is slammed shut (401)")
            explain(
                "knock on the gateway's private door POST /send-bot with a wrong "
                "token, and then with no token at all.",
                "only the backend (holding the shared secret) may use this door. A "
                "bad/absent token must be a flat 401 BEFORE any send work happens.")
            if not reachable:
                skipped("gateway not reachable — run the stack (run.bat) first")
            else:
                async with httpx.AsyncClient(timeout=5.0) as c:
                    bad = await c.post(
                        f"{GATEWAY_BASE}/send-bot",
                        headers={"X-Gateway-Token": "totally-wrong"},
                        json={"to": "x@s.whatsapp.net", "text": "hi"})
                    missing = await c.post(
                        f"{GATEWAY_BASE}/send-bot",
                        json={"to": "x@s.whatsapp.net", "text": "hi"})
                ok4 = bad.status_code == 401 and missing.status_code == 401
                result(
                    ok4,
                    f"wrong token → {bad.status_code}, missing token → "
                    f"{missing.status_code} (both 401 — locked)")

            # ── TEST 5 ───────────────────────────────────────────────────────
            banner("5", "Gateway /send-bot: a missing/blank 'to' or 'text' → 400")
            explain(
                "with a VALID token, POST a body missing 'text', then a blank 'text', "
                "then a body missing 'to'.",
                "there is nothing to send without both fields. The gateway must "
                "answer 400 (bad request) rather than try to send empty messages.")
            if not reachable:
                skipped("gateway not reachable")
            else:
                hdr = {"X-Gateway-Token": GATEWAY_TOKEN}
                async with httpx.AsyncClient(timeout=5.0) as c:
                    no_text = await c.post(f"{GATEWAY_BASE}/send-bot", headers=hdr,
                                           json={"to": "x@s.whatsapp.net"})
                    blank = await c.post(f"{GATEWAY_BASE}/send-bot", headers=hdr,
                                         json={"to": "x@s.whatsapp.net", "text": "   "})
                    no_to = await c.post(f"{GATEWAY_BASE}/send-bot", headers=hdr,
                                         json={"text": "hi"})
                ok5 = (no_text.status_code == 400 and blank.status_code == 400
                       and no_to.status_code == 400)
                result(
                    ok5,
                    f"missing text → {no_text.status_code}, blank text → "
                    f"{blank.status_code}, missing to → {no_to.status_code} "
                    f"(all 400)")

            # ── TEST 6 (LIVE) ────────────────────────────────────────────────
            banner("6", "Gateway /send-bot LIVE: connected → 200 + real id (to OWNER's own #)")
            explain(
                "if WhatsApp is linked, send a tiny 'please ignore' note to the "
                "OWNER'S OWN number (the safe self-chat) with a valid token.",
                "this proves the whole send actually reaches WhatsApp: a 200 with a "
                "real message_id means Baileys accepted and sent it. We target the "
                "owner's own number so no stranger is ever messaged.")
            if not connected:
                skipped("WhatsApp not linked — scan the QR at :3000/qr to enable. "
                        "This is the one MANUAL step.")
            elif not own_phone:
                skipped("gateway connected but did not report its own number")
            else:
                async with httpx.AsyncClient(timeout=8.0) as c:
                    r6 = await c.post(
                        f"{GATEWAY_BASE}/send-bot",
                        headers={"X-Gateway-Token": GATEWAY_TOKEN},
                        json={"to": f"{own_phone}@s.whatsapp.net", "text": REPLY_TEXT})
                b6 = r6.json()
                ok6 = r6.status_code == 200 and b6.get("ok") is True and bool(
                    b6.get("message_id"))
                result(
                    ok6,
                    f"status={r6.status_code}, ok={b6.get('ok')}, got a real "
                    f"message_id={bool(b6.get('message_id'))} (a real WhatsApp "
                    f"message just landed in the owner's self-chat)")

            # ── TEST 7 ───────────────────────────────────────────────────────
            banner("7", "Reply route STILL queues the outbox AND now calls send_outbound")
            explain(
                "as a logged-in owner, POST /api/conversations/{id}/reply. We swap "
                "send_outbound for a fake that returns True (so no real send), then "
                "check: the outbox got the reply, the transcript got an 'owner' "
                "line, the response says delivered:true, and send_outbound was "
                "called with the conversation id as the address.",
                "M6a.2 must keep the OLD promise (the reply is queued and never "
                "lost) and ADD the new one (try to deliver it, report the result). "
                "And it must use the conversation id as the WhatsApp 'to'.")
            conv = f"m6a2:{secrets.token_hex(6)}"
            calls: list[tuple[str, str]] = []

            async def fake_send_true(to: str, text: str) -> bool:
                calls.append((to, text))
                return True

            dash.whatsapp_service.send_outbound = fake_send_true  # type: ignore[assignment]
            sid = await _login(rds, http, AVI_USER, BIZ_A)
            try:
                r7 = await http.post(
                    f"/api/conversations/{conv}/reply", json={"text": REPLY_TEXT})
                b7 = r7.json()
                outbox_key = f"conv:{BIZ_A}:{conv}:outbox"
                queued = await rds.lrange(outbox_key, 0, -1)
                in_outbox = any(
                    json.loads(item).get("body") == REPLY_TEXT for item in queued)
                msgs = await conversation_state.get_messages(rds, BIZ_A, conv)
                in_transcript = any(
                    m["role"] == "owner" and m["body"] == REPLY_TEXT for m in msgs)
                ok7 = (
                    r7.status_code == 200
                    and b7.get("queued") is True
                    and b7.get("delivered") is True
                    and b7.get("conversation_id") == conv
                    and calls == [(conv, REPLY_TEXT)]
                    and in_outbox and in_transcript
                )
                result(
                    ok7,
                    f"queued={b7.get('queued')}, delivered={b7.get('delivered')}, "
                    f"send_outbound called with the conv id={calls == [(conv, REPLY_TEXT)]}, "
                    f"reply in outbox={in_outbox}, in transcript={in_transcript}")
            finally:
                await rds.delete(f"conv:{BIZ_A}:{conv}", f"conv:{BIZ_A}:{conv}:outbox",
                                 f"conv:{BIZ_A}:{conv}:log")
                await rds.srem(f"convindex:{BIZ_A}", conv)
                await _logout(rds, http, sid)

            # ── TEST 8 ───────────────────────────────────────────────────────
            banner("8", "If delivery fails, the reply is STILL queued (queued=true, delivered=false)")
            explain(
                "POST a reply again, but this time the fake send_outbound returns "
                "False (pretend the gateway is down).",
                "the owner's request must NEVER fail just because WhatsApp is "
                "offline. The reply must still be queued (so it's not lost) and the "
                "response must honestly say delivered:false.")
            conv2 = f"m6a2:{secrets.token_hex(6)}"

            async def fake_send_false(to: str, text: str) -> bool:
                return False

            dash.whatsapp_service.send_outbound = fake_send_false  # type: ignore[assignment]
            sid2 = await _login(rds, http, AVI_USER, BIZ_A)
            try:
                r8 = await http.post(
                    f"/api/conversations/{conv2}/reply", json={"text": REPLY_TEXT})
                b8 = r8.json()
                outbox_key2 = f"conv:{BIZ_A}:{conv2}:outbox"
                queued2 = await rds.lrange(outbox_key2, 0, -1)
                in_outbox2 = any(
                    json.loads(item).get("body") == REPLY_TEXT for item in queued2)
                ok8 = (
                    r8.status_code == 200
                    and b8.get("queued") is True
                    and b8.get("delivered") is False
                    and in_outbox2
                )
                result(
                    ok8,
                    f"queued={b8.get('queued')}, delivered={b8.get('delivered')}, "
                    f"reply STILL in outbox={in_outbox2} (never lost)")
            finally:
                await rds.delete(f"conv:{BIZ_A}:{conv2}", f"conv:{BIZ_A}:{conv2}:outbox",
                                 f"conv:{BIZ_A}:{conv2}:log")
                await rds.srem(f"convindex:{BIZ_A}", conv2)
                await _logout(rds, http, sid2)

            # ── TEST 9 (auth gate) ───────────────────────────────────────────
            banner("9", "The reply route needs a login (no session → 401)")
            explain(
                "POST /api/conversations/{id}/reply with NO session cookie.",
                "the reply route lives behind the deny-by-default /api gate. No "
                "verified owner → no reply may be queued or sent. Must be 401.")
            r9 = await http.post(
                "/api/conversations/whatever/reply", json={"text": "hi"})
            ok9 = r9.status_code == 401
            result(ok9, f"no-session reply → {r9.status_code} (401 — locked)")

            # ── TEST 10 (loop-guard at code level) ───────────────────────────
            banner("10", "Loop-guard: the sent reply id is remembered so its echo won't re-trigger the bot")
            explain(
                "re-implement the gateway's loop-guard rules and confirm they hold: "
                "an id we (the gateway) just sent is SKIPPED if it echoes back.",
                "the owner's reply, once sent, echoes back as 'fromMe'. The /send-bot "
                "route calls rememberSentId(message_id) — the SAME guard the bot's "
                "auto-replies use — so handleInbound skips it at the top and the bot "
                "never answers its own outgoing reply. (The real phone echo is "
                "manual; this proves the logic.)")
            loop_ok, loop_detail = _check_loop_guard()
            result(loop_ok, loop_detail)

    # Restore the real send_outbound (defensive — process ends anyway).
    dash.whatsapp_service.send_outbound = real_send_outbound  # type: ignore[assignment]
    await rds.aclose()

    # ── Scoreboard ───────────────────────────────────────────────────────────
    _passed, _total = tally()
    print()
    print("=" * 74)
    if _passed == _total:
        print(f"  🎉 RESULT: {_passed}/{_total} checks held. The owner's manual "
              "reply now travels all the way to WhatsApp.  🤖➡️💬")
    else:
        print(f"  🚨 RESULT: {_passed}/{_total} held — {_total - _passed} FAILED. "
              "Do not ship until green.")
    print("=" * 74)
    print()
    print("  📱 MANUAL STEP FOR OMER (a script cannot do this part):")
    print("     1) Make sure WhatsApp is linked (scan the QR at :3000/qr).")
    print("     2) From a phone, message your linked WhatsApp so a chat appears in")
    print("        the dashboard; set it to 'human' and type a reply.")
    print("     3) That reply should ARRIVE on the customer's WhatsApp. (Test 6")
    print("        above already proved a live send to your OWN number works.)")
    print("=" * 74)
    return 0 if _passed == _total else 1


# ── HOW TO RUN ───────────────────────────────────────────────────────────────
#   Easiest : double-click  tests/test_m6a2.bat   (it sets everything up for you).
#   By hand : from the project root, with the stack running (run.bat):
#     docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m6a2_full_test.py"
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
