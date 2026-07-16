"""M6a.2 — wire the owner's manual reply to WhatsApp, strict pytest (CI version).

Per the FROZEN M6a.2 contract. The narrated story lives in m6a2_full_test.py;
THIS is the strict gate CI runs. It exercises the three seams the milestone adds:

  * the backend `send_outbound(business_id, to, text) -> bool` helper (the httpx
    call to the gateway's internal /send-bot; M6b names the sending business so
    the multi-socket gateway picks the right session), proving True only on a
    2xx + {"ok":true} and a GRACEFUL False on any failure (bad URL / non-2xx /
    bad shape / timeout);
  * the gateway POST /send-bot route over the REAL live gateway on the Docker
    network — auth (401), validation (400), and (when connected) a real 200 with
    a message_id sent to the OWNER'S OWN number (the safe self-chat target);
  * the dashboard POST /api/conversations/{id}/reply route, proving it STILL
    queues the reply in the Redis outbox (append_reply unchanged), now returns
    `delivered: bool`, and calls send_outbound(business_id, conversation_id, text).

Nothing prints/asserts a secret, a token, or PII text. The send_outbound True/
False unit checks are deterministic (a stub transport / a bad URL). The live
gateway 200 send is SKIPPED automatically when WhatsApp isn't linked.
"""

from __future__ import annotations

import json
import os
import secrets
import time

import asyncpg
import httpx
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.services import conversation_state
from app.services import whatsapp as whatsapp_service
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (PUBLISHED in seed)
AVI_USER = "google-sub-avi"

GATEWAY_BASE = get_settings().gateway_base_url.rstrip("/")
GATEWAY_TOKEN = get_settings().gateway_api_token.get_secret_value()

# A reply body we never print/log. Marked so a stray real send is obviously a test.
REPLY_TEXT = "[Bizz_up QA] M6a.2 reply — please ignore"


# --- fixtures ---------------------------------------------------------------

@pytest_asyncio.fixture
async def rds():
    r = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    try:
        yield r
    finally:
        await r.aclose()


@pytest_asyncio.fixture
async def lifespan_app():
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def http(lifespan_app):
    transport = ASGITransport(app=lifespan_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


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


async def _gateway_up() -> bool:
    """True if the live gateway answers /healthz (used to skip live send checks)."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{GATEWAY_BASE}/healthz")
            return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


async def _find_connected_business() -> tuple[str, str] | None:
    """(business_id, own_phone) of a CONNECTED WhatsApp session, or None.

    M6b: the gateway is multi-socket and its old /info route is gone, so we
    resolve a connected session from the DB instead — wa_list_sessions() on the
    app_role pool gives the candidate businesses, then each one's own
    whatsapp_connections row (gateway_role, tenant-scoped) tells us the status
    and the (decrypted) own number. Used only to pick a SAFE self-chat target.
    """
    from app.core.crypto import decrypt_pii
    from app.db.session import tenant_connection

    try:
        app_pool = await asyncpg.create_pool(
            dsn=os.environ["DATABASE_URL"], min_size=1, max_size=1
        )
        gw_pool = await asyncpg.create_pool(
            dsn=os.environ["GATEWAY_DATABASE_URL"], min_size=1, max_size=1
        )
    except Exception:  # noqa: BLE001
        return None
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
                return biz, decrypt_pii(wa["phone_number"])
        return None
    except Exception:  # noqa: BLE001
        return None
    finally:
        await app_pool.close()
        await gw_pool.close()


# ============================================================================
#  GOAL 4 — backend send_outbound: True only on 2xx+ok, graceful False otherwise
# ============================================================================

class _StubResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "stub error", request=None, response=None  # type: ignore[arg-type]
            )

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _StubClient:
    """A drop-in for httpx.AsyncClient that returns a fixed response and records
    that NO PII (the jid `to` / the body `text`) is ever passed to a logger.
    """

    captured: dict = {}

    def __init__(self, status_code: int, payload):
        self._status_code = status_code
        self._payload = payload

    def __call__(self, *a, **kw):  # the `httpx.AsyncClient(timeout=...)` call
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _StubClient.captured = {"url": url, "headers": headers or {}, "json": json or {}}
        return _StubResponse(self._status_code, self._payload)


@pytest.mark.asyncio
async def test_send_outbound_true_on_2xx_ok(monkeypatch):
    """A 2xx response whose JSON is {"ok": true} → send_outbound returns True."""
    monkeypatch.setattr(
        whatsapp_service.httpx, "AsyncClient", _StubClient(200, {"ok": True})
    )
    assert await whatsapp_service.send_outbound(BIZ_A, "x@s.whatsapp.net", "hi") is True
    # It posts to /send-bot, carries the token header, and names the sending
    # business (M6b multi-socket) + the jid + text in the body.
    cap = _StubClient.captured
    assert cap["url"].endswith("/send-bot")
    assert cap["headers"].get("X-Gateway-Token") == GATEWAY_TOKEN
    assert cap["json"] == {"business_id": BIZ_A, "to": "x@s.whatsapp.net", "text": "hi"}


@pytest.mark.asyncio
async def test_send_outbound_false_on_ok_false(monkeypatch):
    """A 2xx whose JSON says {"ok": false} → not delivered → False."""
    monkeypatch.setattr(
        whatsapp_service.httpx, "AsyncClient", _StubClient(200, {"ok": False})
    )
    assert await whatsapp_service.send_outbound(BIZ_A, "x@s.whatsapp.net", "hi") is False


@pytest.mark.asyncio
async def test_send_outbound_false_on_non_2xx(monkeypatch):
    """A 503 (gateway not connected) → False (best-effort, never raises)."""
    monkeypatch.setattr(
        whatsapp_service.httpx, "AsyncClient",
        _StubClient(503, {"ok": False, "error": "not connected"}),
    )
    assert await whatsapp_service.send_outbound(BIZ_A, "x@s.whatsapp.net", "hi") is False


@pytest.mark.asyncio
async def test_send_outbound_false_on_bad_json(monkeypatch):
    """A 2xx with a non-JSON / bad body → False (defensive shape check)."""
    monkeypatch.setattr(
        whatsapp_service.httpx, "AsyncClient",
        _StubClient(200, ValueError("not json")),
    )
    assert await whatsapp_service.send_outbound(BIZ_A, "x@s.whatsapp.net", "hi") is False


@pytest.mark.asyncio
async def test_send_outbound_false_on_unreachable_gateway(monkeypatch):
    """Pointed at a dead URL (connection refused) → graceful False, no raise."""
    s = get_settings()
    # Point the (cached) settings at a port nothing listens on.
    monkeypatch.setattr(s, "gateway_base_url", "http://127.0.0.1:1", raising=False)
    assert await whatsapp_service.send_outbound(BIZ_A, "x@s.whatsapp.net", "hi") is False


@pytest.mark.asyncio
async def test_send_outbound_never_logs_pii(monkeypatch, caplog):
    """On a failure the warning carries NO jid / NO body text / NO token."""
    import logging

    secret_jid = "972599999999@s.whatsapp.net"
    secret_text = "super-secret-reply-body-xyz"
    monkeypatch.setattr(
        whatsapp_service.httpx, "AsyncClient",
        _StubClient(503, {"ok": False}),
    )
    with caplog.at_level(logging.WARNING):
        await whatsapp_service.send_outbound(BIZ_A, secret_jid, secret_text)
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert secret_jid not in blob
    assert secret_text not in blob
    assert GATEWAY_TOKEN not in blob


# ============================================================================
#  GOAL 2/3 — the LIVE gateway POST /send-bot: auth (401), validation (400),
#             and a real 200 when WhatsApp is connected (sent to OWNER's own num)
# ============================================================================

@pytest.mark.asyncio
async def test_gateway_send_bot_bad_and_missing_token():
    """Bad/missing X-Gateway-Token → 401 BEFORE any send (live gateway)."""
    if not await _gateway_up():
        pytest.skip("gateway not reachable")
    async with httpx.AsyncClient(timeout=5.0) as c:
        bad = await c.post(
            f"{GATEWAY_BASE}/send-bot",
            headers={"X-Gateway-Token": "totally-wrong"},
            json={"business_id": BIZ_A, "to": "x@s.whatsapp.net", "text": "hi"},
        )
        missing = await c.post(
            f"{GATEWAY_BASE}/send-bot",
            json={"business_id": BIZ_A, "to": "x@s.whatsapp.net", "text": "hi"},
        )
    assert bad.status_code == 401
    assert missing.status_code == 401


@pytest.mark.asyncio
async def test_gateway_send_bot_missing_fields():
    """Valid token but missing/blank business_id, to or text → 400 (live gateway).

    M6b: /send-bot must name the sending business (multi-socket), so a missing
    business_id is a 400 just like a missing to/text.
    """
    if not await _gateway_up():
        pytest.skip("gateway not reachable")
    hdr = {"X-Gateway-Token": GATEWAY_TOKEN}
    async with httpx.AsyncClient(timeout=5.0) as c:
        no_text = await c.post(f"{GATEWAY_BASE}/send-bot", headers=hdr,
                               json={"business_id": BIZ_A, "to": "x@s.whatsapp.net"})
        blank_text = await c.post(f"{GATEWAY_BASE}/send-bot", headers=hdr,
                                  json={"business_id": BIZ_A,
                                        "to": "x@s.whatsapp.net", "text": "   "})
        no_to = await c.post(f"{GATEWAY_BASE}/send-bot", headers=hdr,
                             json={"business_id": BIZ_A, "text": "hi"})
        no_biz = await c.post(f"{GATEWAY_BASE}/send-bot", headers=hdr,
                              json={"to": "x@s.whatsapp.net", "text": "hi"})
    assert no_text.status_code == 400
    assert blank_text.status_code == 400
    assert no_to.status_code == 400
    assert no_biz.status_code == 400


@pytest.mark.asyncio
async def test_gateway_send_bot_live_200_to_owner_self():
    """Connected + valid token + own-number target → 200 {ok:true, message_id}.

    SAFE target: the owner's OWN number (the self-chat). The message lands in
    the owner's "Message Yourself" chat, never a stranger.
    """
    if not await _gateway_up():
        pytest.skip("gateway not reachable")
    found = await _find_connected_business()
    if not found:
        pytest.skip("no business has a connected WhatsApp — live send is manual")
    biz, own = found
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.post(
            f"{GATEWAY_BASE}/send-bot",
            headers={"X-Gateway-Token": GATEWAY_TOKEN},
            json={"business_id": biz,
                  "to": f"{own}@s.whatsapp.net", "text": REPLY_TEXT},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("message_id")  # a real id back from Baileys


# ============================================================================
#  GOAL 5 — /api/conversations/{id}/reply: queues outbox + returns delivered +
#           calls send_outbound(business_id, conversation_id, text)
# ============================================================================

@pytest.mark.asyncio
async def test_reply_queues_outbox_and_returns_delivered(http, rds, monkeypatch):
    """POST reply still queues the outbox; returns delivered; calls send_outbound.

    We stub send_outbound so the route's delivery result is controllable and no
    real WhatsApp message is sent. We assert it was called with the session's
    business_id, the conversation id as `to`, and the reply text, and that the
    outbox got the reply.
    """
    conv = f"m6a2:{secrets.token_hex(6)}"
    calls: list[tuple[str, str, str]] = []

    async def fake_send(business_id: str, to: str, text: str) -> bool:
        calls.append((business_id, to, text))
        return True

    # Patch the symbol the dashboard router actually calls.
    import app.api.dashboard as dash
    monkeypatch.setattr(dash.whatsapp_service, "send_outbound", fake_send)

    sid = await _login(rds, http, AVI_USER, BIZ_A)
    try:
        r = await http.post(
            f"/api/conversations/{conv}/reply", json={"text": REPLY_TEXT}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["conversation_id"] == conv
        assert body["queued"] is True
        assert body["delivered"] is True  # our stub returned True

        # send_outbound called exactly once with the tenant + conv id + text.
        assert calls == [(BIZ_A, conv, REPLY_TEXT)]

        # The reply is STILL queued in the Redis outbox (append_reply unchanged).
        outbox_key = f"conv:{BIZ_A}:{conv}:outbox"
        queued = await rds.lrange(outbox_key, 0, -1)
        assert any(json.loads(item).get("body") == REPLY_TEXT for item in queued)

        # And it's mirrored into the transcript as an 'owner' line.
        msgs = await conversation_state.get_messages(rds, BIZ_A, conv)
        assert any(m["role"] == "owner" and m["body"] == REPLY_TEXT for m in msgs)
    finally:
        await rds.delete(f"conv:{BIZ_A}:{conv}", f"conv:{BIZ_A}:{conv}:outbox",
                         f"conv:{BIZ_A}:{conv}:log")
        await rds.srem(f"convindex:{BIZ_A}", conv)
        await _logout(rds, http, sid)


@pytest.mark.asyncio
async def test_reply_delivered_false_when_send_fails(http, rds, monkeypatch):
    """When send_outbound returns False, the reply is STILL queued (queued=True),
    only delivered=False — the owner's request never errors."""
    conv = f"m6a2:{secrets.token_hex(6)}"

    async def fake_send(business_id: str, to: str, text: str) -> bool:
        return False

    import app.api.dashboard as dash
    monkeypatch.setattr(dash.whatsapp_service, "send_outbound", fake_send)

    sid = await _login(rds, http, AVI_USER, BIZ_A)
    try:
        r = await http.post(
            f"/api/conversations/{conv}/reply", json={"text": REPLY_TEXT}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["queued"] is True
        assert body["delivered"] is False

        outbox_key = f"conv:{BIZ_A}:{conv}:outbox"
        queued = await rds.lrange(outbox_key, 0, -1)
        assert any(json.loads(item).get("body") == REPLY_TEXT for item in queued)
    finally:
        await rds.delete(f"conv:{BIZ_A}:{conv}", f"conv:{BIZ_A}:{conv}:outbox",
                         f"conv:{BIZ_A}:{conv}:log")
        await rds.srem(f"convindex:{BIZ_A}", conv)
        await _logout(rds, http, sid)


@pytest.mark.asyncio
async def test_reply_requires_session(http):
    """No session → the /api gate denies the reply route (401)."""
    r = await http.post("/api/conversations/whatever/reply", json={"text": "hi"})
    assert r.status_code == 401


# ============================================================================
#  Contract surface — the response model carries `delivered` (backward-compat)
# ============================================================================

def test_reply_response_model_has_delivered_field():
    """ConversationReplyResponse defaults delivered=False (older clients unaffected)."""
    from app.models.dashboard import ConversationReplyResponse

    fields = set(ConversationReplyResponse.model_fields)
    assert {"conversation_id", "queued", "delivered"} <= fields
    # Backward-compatible default.
    m = ConversationReplyResponse(conversation_id="x", queued=True)
    assert m.delivered is False
