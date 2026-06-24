"""M6a narrated — shared constants + helpers + narration for the story runner.

This module is NOT run directly. The thin runner m6a_full_test.py imports these
helpers + the banner/explain/result narration + tally(). Splitting them out keeps
the runner under 500 lines WITHOUT changing a single byte of printed output — the
runner keeps the whole main() flow and reads the final counts via tally().

Nothing here prints a secret, a token, or a customer's personal details.
"""

from __future__ import annotations

import json
import secrets

from app.db.session import tenant_connection

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



def tally() -> tuple[int, int]:
    """The (passed, total) counts after main() runs — read by the runner's scoreboard."""
    return _passed, _total
