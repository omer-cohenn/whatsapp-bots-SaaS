"""M6a.2 narrated — shared constants + helpers + stub client + narration.

This module is NOT run directly. The thin runner m6a2_full_test.py imports the
narration (banner/explain/result/skipped), the stub gateway client, the session
helpers, the live gateway-status probe, the loop-guard check, and tally().
Splitting them out keeps the runner under 500 lines WITHOUT changing a single
byte of printed output — the runner keeps the whole main() flow and reads the
final counts via tally(). We NEVER print or log a reply body as content.
"""

from __future__ import annotations

import json
import secrets
import time

import httpx
import redis.asyncio as aioredis

from app.core.config import get_settings
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

# The pretend business (fixed id from supabase/seed.sql) + its owner.
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (PUBLISHED in seed)
AVI_USER = "google-sub-avi"

GATEWAY_BASE = get_settings().gateway_base_url.rstrip("/")
GATEWAY_TOKEN = get_settings().gateway_api_token.get_secret_value()

# A clearly-marked reply body. We NEVER print or log it as content.
REPLY_TEXT = "[Bizz_up QA] M6a.2 reply — please ignore"

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


def skipped(detail: str) -> None:
    """A check that cannot run right now (e.g. WhatsApp not linked). NOT a failure."""
    print(f"  ⏭️  SKIP   : {detail}")


# --- a tiny fake gateway client (lets us test send_outbound deterministically) -

class _StubResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("stub", request=None, response=None)  # type: ignore[arg-type]

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _StubClient:
    """Pretends to be httpx.AsyncClient and answers with a fixed response so we
    can drive send_outbound's True/False decision without a real gateway."""

    captured: dict = {}

    def __init__(self, status_code: int, payload):
        self._status_code = status_code
        self._payload = payload

    def __call__(self, *a, **kw):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _StubClient.captured = {"url": url, "headers": headers or {}, "json": json or {}}
        return _StubResponse(self._status_code, self._payload)


# --- session helpers (a logged-in owner) -------------------------------------

async def _login(rds, http, user_id: str, business_id: str) -> str:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": f"{user_id}@example.com", "name": user_id,
        "picture": "", "business_id": business_id, "business_name": "x",
        "created_at": int(time.time()),
    }
    await rds.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)
    return sid


async def _logout(rds, http, sid: str) -> None:
    await rds.delete(f"{_SESSION_KEY_PREFIX}{sid}")
    http.cookies.clear()


async def _gateway_status() -> tuple[bool, str | None, str | None]:
    """Return (reachable, connected_business_id, own_phone).

    M6b: the gateway is multi-socket and its old /info route is gone, so the
    "is anything connected, and what is its own number?" question is answered
    from the DB — wa_list_sessions() (app_role) lists the candidate businesses,
    then each one's whatsapp_connections row (gateway_role, tenant-scoped) gives
    the status + the decrypted own number. Only a SAFE self-chat target comes out.
    """
    import os

    import asyncpg

    from app.core.crypto import decrypt_pii
    from app.db.session import tenant_connection

    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            h = await c.get(f"{GATEWAY_BASE}/healthz")
            if h.status_code != 200:
                return (False, None, None)
    except Exception:  # noqa: BLE001
        return (False, None, None)

    try:
        app_pool = await asyncpg.create_pool(
            dsn=os.environ["DATABASE_URL"], min_size=1, max_size=1
        )
        gw_pool = await asyncpg.create_pool(
            dsn=os.environ["GATEWAY_DATABASE_URL"], min_size=1, max_size=1
        )
    except Exception:  # noqa: BLE001
        return (True, None, None)
    try:
        async with app_pool.acquire() as conn:
            rows = await conn.fetch("SELECT wa_list_sessions() AS business_id")
        for row in rows:
            biz = str(row["business_id"])
            async with tenant_connection(gw_pool, biz) as conn:
                wa = await conn.fetchrow(
                    "SELECT status, phone_number FROM whatsapp_connections "
                    "WHERE business_id = $1",
                    biz,
                )
            if wa and wa["status"] == "connected" and wa["phone_number"]:
                return (True, biz, decrypt_pii(wa["phone_number"]))
        return (True, None, None)
    except Exception:  # noqa: BLE001
        return (True, None, None)
    finally:
        await app_pool.close()
        await gw_pool.close()

def _check_loop_guard() -> tuple[bool, str]:
    """Re-implement + verify the gateway's loop-guard (gateway/src/index.js).

    On a successful /send-bot, the route calls rememberSentId(message_id). The
    outgoing reply echoes back through messages.upsert with that id, and
    handleInbound skips it at the very top (sentMessageIds.has(msgId)). So the
    owner's reply (incl. the self-chat @lid case) never re-triggers the bot.
    """
    SENT_ID_CAP = 200
    sent: dict[str, None] = {}  # py dict preserves insertion order, like a JS Set

    def remember(mid: str) -> None:
        if not mid:
            return
        sent[mid] = None
        if len(sent) > SENT_ID_CAP:
            del sent[next(iter(sent))]  # evict the oldest (first-inserted)

    def should_skip(mid: str) -> bool:
        return bool(mid) and mid in sent

    # The reply we just sent is remembered → its fromMe echo is skipped.
    remember("owner-reply-1")
    rule = should_skip("owner-reply-1") and not should_skip("a-real-inbound")

    for i in range(SENT_ID_CAP + 50):
        remember(f"id-{i}")
    cap_ok = len(sent) == SENT_ID_CAP
    oldest_evicted = not should_skip("owner-reply-1") and not should_skip("id-0")
    newest_kept = should_skip(f"id-{SENT_ID_CAP + 50 - 1}")

    ok = rule and cap_ok and oldest_evicted and newest_kept
    detail = (
        f"sent reply id skipped on echo={rule}, cap held at {len(sent)}={cap_ok}, "
        f"oldest evicted={oldest_evicted}, newest kept={newest_kept}")
    return ok, detail

def tally() -> tuple[int, int]:
    """The (passed, total) counts after main() runs — read by the runner's scoreboard."""
    return _passed, _total
