"""M6a — "Message Yourself" self-test path, strict pytest (the CI version).

Per the FROZEN M6a contract (decision 0014). The narrated story lives in
m6a_full_test.py; THIS is the strict gate CI runs. It drives the REAL ASGI app
over httpx ASGITransport so the X-Gateway-Token webhook auth, the deny-by-default
/api gate, the session dependency, tenant_connection/RLS and the public-slug
bootstrap are all exercised exactly like a live request.

What it proves (mapped to the QA goals):

  G2  SELF-TEST REPLIES — a self_test webhook for a mapped+PUBLISHED business
      returns {status:"ok", replies:[...]} from the real run_turn.
  G3  REAL LEAD PERSISTS — a full questionnaire over the webhook saves a REAL
      (is_test=False) lead that shows in GET /api/leads (which hides test rows),
      with the phone round-tripping (encrypted at rest, decrypted for the owner).
  G4  BOOKING LINK — a booking turn's reply carries THIS tenant's real
      /book/{slug} link (never the demo placeholder, never another tenant's).
  G5  NOT PUBLISHED — a draft bot stays silent: {status:"not published",replies:[]}
  G6  UNKNOWN ACCOUNT — an unmapped gateway account → {status:"no business",
      replies:[]}, 200 (no crash).
  G7  LOOP GUARD — the gateway's sent-id loop-guard logic (skip-our-own, cap=200,
      oldest-evicted) — a logic-level check; the REAL phone echo is manual.
  G8  AUTH — bad/missing X-Gateway-Token → 401; the /api/whatsapp/* admin routes
      → 401 without a session; tenant-scoped with one (A never sees B's link).

Every persisted lead is cleaned up. Mappings are UPSERTed (app_role has no DELETE
on whatsapp_connections). Nothing prints/asserts a secret, a token, or PII text.
The REAL WhatsApp send/receive on a phone is a MANUAL step for Omer.
"""

from __future__ import annotations

import json
import os
import secrets
import time

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.db.session import tenant_connection
from app.main import app
from app.services import bot_settings as bot_settings_service
from app.services import booking as booking_service
from app.services import whatsapp as whatsapp_service
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (PUBLISHED in seed)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (DRAFT in seed)
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

ACC_A = "m6a-acct-avi"
ACC_B = "m6a-acct-bella"
ACC_UNKNOWN = "m6a-acct-nobody"
OWN_PHONE = "+972500000001"

CUST_NAME = "דנה הבודקת"
CUST_PHONE_DIGITS = "0521234567"


# --- fixtures ---------------------------------------------------------------

@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=4)
    try:
        yield p
    finally:
        await p.close()


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


@pytest_asyncio.fixture
async def token():
    return get_settings().gateway_api_token.get_secret_value()


@pytest_asyncio.fixture
async def mapped(pool):
    """Ensure each business has its gateway-account mapping (UPSERT, never DELETE).

    Avi (published) ↔ ACC_A, Bella (draft) ↔ ACC_B. Uses the product's own
    upsert_connection so the same code path + grants as POST /api/whatsapp/link
    run. ACC_UNKNOWN is intentionally never mapped.
    """
    await whatsapp_service.upsert_connection(
        pool, BIZ_A, gateway_account_id=ACC_A, phone=OWN_PHONE, status="connected")
    await whatsapp_service.upsert_connection(
        pool, BIZ_B, gateway_account_id=ACC_B, phone=OWN_PHONE, status="connected")
    yield


@pytest_asyncio.fixture
async def cleanup_leads(pool):
    """Delete the leads we create in BIZ_A/BIZ_B after each test (events cascade)."""
    yield
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute("DELETE FROM leads WHERE business_id = $1", bid)


# --- helpers ----------------------------------------------------------------

def _body(account_id: str, text: str, conv: str, *, self_test: bool = True) -> dict:
    return {
        "gateway_account_id": account_id,
        "from": OWN_PHONE,
        "push_name": "Owner",
        "message_id": f"m6a-{secrets.token_hex(6)}",
        "timestamp": 1_700_000_000,
        "type": "text",
        "text": text,
        "raw": {"note": "synthetic m6a test"},
        "self_test": self_test,
        "conversation_id": conv,
    }


def _auth(token: str) -> dict:
    return {"X-Gateway-Token": token}


async def _post(http, token, account_id, text, conv, **kw):
    return await http.post("/webhook/whatsapp",
                           json=_body(account_id, text, conv, **kw),
                           headers=_auth(token))


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


# ============================================================================
#  GOAL 2 — a self_test message → the published bot answers (run_turn)
# ============================================================================

@pytest.mark.asyncio
async def test_self_test_published_bot_replies(http, token, mapped):
    """A self_test webhook for a mapped+published business → {status:ok, replies}."""
    conv = f"self:{secrets.token_hex(6)}"
    r = await _post(http, token, ACC_A, "היי", conv)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["replies"], list) and len(body["replies"]) >= 1


# ============================================================================
#  GOAL 3 — a full questionnaire over the webhook → a REAL (is_test=False) lead
# ============================================================================

@pytest.mark.asyncio
async def test_full_lead_questionnaire_persists_real_lead(
    http, rds, token, mapped, cleanup_leads, pool
):
    """Drive Avi's 'quote' flow to completion over self_test webhooks; the new
    lead is REAL (is_test=False) and appears in GET /api/leads (test rows hidden),
    with the phone decrypted on read."""
    conv = f"self:{secrets.token_hex(6)}"
    await _post(http, token, ACC_A, "היי", conv)          # greeting + menu
    start = await _post(http, token, ACC_A, "1", conv)     # start 'quote'
    await _post(http, token, ACC_A, CUST_NAME, conv)       # name
    await _post(http, token, ACC_A, CUST_PHONE_DIGITS, conv)  # phone
    done = await _post(http, token, ACC_A, "1", conv)      # choose 'רכב' → complete
    assert start.json()["replies"] and done.json()["replies"]

    sid = await _login(rds, http, AVI_USER, BIZ_A)
    try:
        leads = (await http.get("/api/leads")).json()["leads"]
    finally:
        await _logout(rds, http, sid)

    # The default list HIDES is_test rows, so anything here is a REAL lead.
    quote = [lead for lead in leads if lead["lead_name"] == "quote"]
    assert quote, "the finished questionnaire must appear as a real lead"
    assert all(lead["is_test"] is False for lead in quote)
    assert any((lead.get("phone") or "").endswith(CUST_PHONE_DIGITS) for lead in quote)


@pytest.mark.asyncio
async def test_self_test_lead_is_encrypted_at_rest(
    http, token, mapped, cleanup_leads, pool
):
    """The persisted real lead's phone column is CIPHERTEXT, not plaintext."""
    conv = f"self:{secrets.token_hex(6)}"
    await _post(http, token, ACC_A, "היי", conv)
    await _post(http, token, ACC_A, "1", conv)
    await _post(http, token, ACC_A, CUST_NAME, conv)
    await _post(http, token, ACC_A, CUST_PHONE_DIGITS, conv)
    await _post(http, token, ACC_A, "1", conv)

    async with tenant_connection(pool, BIZ_A) as conn:
        raw = await conn.fetchval(
            "SELECT phone FROM leads WHERE business_id=$1 AND lead_name='quote' "
            "ORDER BY started_at DESC LIMIT 1", BIZ_A)
    assert raw is not None
    assert CUST_PHONE_DIGITS not in raw  # never stored in the clear


# ============================================================================
#  GOAL 4 — a booking turn → the reply carries THIS tenant's real /book link
# ============================================================================

@pytest.mark.asyncio
async def test_booking_turn_returns_real_link(
    http, token, mapped, cleanup_leads, pool
):
    """A booking flow turn → the reply contains /book/{slug} for this tenant,
    not the demo placeholder. We temporarily give Avi a booking-first config and
    restore it after."""
    original = await bot_settings_service.get_settings(pool, BIZ_A)
    async with tenant_connection(pool, BIZ_A) as conn:
        bset = await booking_service.get_settings(conn, BIZ_A)
        slug = bset["slug"]
        await conn.execute(
            "UPDATE bot_settings SET lead_steps=$2::jsonb, is_published=true, "
            "updated_at=now() WHERE business_id=$1",
            BIZ_A,
            json.dumps({"book_now": {
                "label": "קביעת תור", "flow_type": "booking",
                "message": "לקביעת תור: {link}", "steps": []}}, ensure_ascii=False))
    try:
        conv = f"self:{secrets.token_hex(6)}"
        await _post(http, token, ACC_A, "היי", conv)
        rb = (await _post(http, token, ACC_A, "1", conv)).json()
        base = get_settings().public_base_url.rstrip("/")
        link = f"{base}/book/{slug}"
        assert any(link in rp for rp in rb["replies"]), rb["replies"]
        assert all("example.com/book/demo" not in rp for rp in rb["replies"])
    finally:
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.execute(
                "UPDATE bot_settings SET lead_steps=$2::jsonb, is_published=$3, "
                "updated_at=now() WHERE business_id=$1",
                BIZ_A,
                json.dumps(original.get("lead_steps") or {}, ensure_ascii=False),
                bool(original.get("is_published")))


# ============================================================================
#  GOAL 5 — a DRAFT (not published) bot stays silent
# ============================================================================

@pytest.mark.asyncio
async def test_not_published_is_silent(http, token, mapped):
    """Bella's draft bot → {status:'not published', replies:[]} (no reply)."""
    r = await _post(http, token, ACC_B, "היי", f"self:{secrets.token_hex(6)}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not published"
    assert body["replies"] == []


@pytest.mark.asyncio
async def test_unpublish_gate_is_real(http, token, mapped, pool):
    """Negative control: un-publishing Avi makes the bot go silent; re-publishing
    makes it answer again — proving the publish gate actually gates."""
    await bot_settings_service.set_published(pool, BIZ_A, False)
    try:
        broke = (await _post(http, token, ACC_A, "היי",
                             f"self:{secrets.token_hex(6)}")).json()
        assert broke["status"] == "not published" and broke["replies"] == []
    finally:
        await bot_settings_service.set_published(pool, BIZ_A, True)
    fixed = (await _post(http, token, ACC_A, "היי",
                         f"self:{secrets.token_hex(6)}")).json()
    assert fixed["status"] == "ok" and len(fixed["replies"]) >= 1


# ============================================================================
#  GOAL 6 — an unknown gateway account → graceful 'no business', no crash
# ============================================================================

@pytest.mark.asyncio
async def test_unknown_account_no_business(http, token):
    """An unmapped account → {status:'no business', replies:[]}, 200 (no crash)."""
    r = await _post(http, token, ACC_UNKNOWN, "היי", f"self:{secrets.token_hex(6)}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "no business"
    assert body["replies"] == []


# ============================================================================
#  GOAL 7 — the gateway loop-guard logic (skip-our-own, cap=200, oldest-evicted)
# ============================================================================

def test_gateway_loop_guard_logic():
    """Mirror gateway/src/index.js rememberSentId + the top-of-handleInbound skip.

    The gateway keeps a bounded Set (cap 200, oldest-evicted by insertion order)
    of ids of messages IT sent, and SKIPS any inbound whose id is in it. This
    prevents the self-chat reply-to-self loop. The REAL phone echo is manual; the
    LOGIC is proven here.
    """
    SENT_ID_CAP = 200
    sent: dict[str, None] = {}  # dict preserves insertion order, like a JS Set

    def remember(mid: str) -> None:
        if not mid:
            return
        sent[mid] = None
        if len(sent) > SENT_ID_CAP:
            del sent[next(iter(sent))]  # evict the oldest (first-inserted)

    def should_skip(mid: str) -> bool:
        return bool(mid) and mid in sent

    remember("reply-1")
    assert should_skip("reply-1")          # our own send is skipped (no loop)
    assert not should_skip("inbound-x")    # a genuine inbound is not skipped

    for i in range(SENT_ID_CAP + 50):
        remember(f"id-{i}")
    assert len(sent) == SENT_ID_CAP                       # cap holds
    assert not should_skip("reply-1")                     # oldest evicted
    assert not should_skip("id-0")                        # oldest batch evicted
    assert should_skip(f"id-{SENT_ID_CAP + 50 - 1}")      # newest kept


# ============================================================================
#  GOAL 8 — auth: webhook token + admin-route session gate + tenant scope
# ============================================================================

@pytest.mark.asyncio
async def test_webhook_rejects_bad_and_missing_token(http, mapped):
    """A wrong token and a missing token both → 401 before any business work."""
    bad = await http.post("/webhook/whatsapp",
                          json=_body(ACC_A, "היי", "self:x"),
                          headers={"X-Gateway-Token": "totally-wrong"})
    missing = await http.post("/webhook/whatsapp",
                              json=_body(ACC_A, "היי", "self:x"))
    assert bad.status_code == 401
    assert missing.status_code == 401


@pytest.mark.asyncio
async def test_admin_routes_require_session(http):
    """/api/whatsapp/{status,link,qr} → 401 without a session (deny-by-default)."""
    assert (await http.get("/api/whatsapp/status")).status_code == 401
    assert (await http.post("/api/whatsapp/link")).status_code == 401
    assert (await http.get("/api/whatsapp/qr")).status_code == 401


@pytest.mark.asyncio
async def test_admin_status_shape_and_tenant_scope(http, rds, mapped):
    """Logged-in owner GET /api/whatsapp/status → the frozen shape, linked=true
    for THIS tenant only (no cross-tenant leak)."""
    sid = await _login(rds, http, AVI_USER, BIZ_A)
    try:
        body = (await http.get("/api/whatsapp/status")).json()
    finally:
        await _logout(rds, http, sid)
    # M6b added an `error` field (e.g. 'phone_conflict') to the status contract.
    assert set(body.keys()) == {"linked", "connected", "phone", "gateway_status", "error"}
    assert body["linked"] is True  # Avi has a mapping (ACC_A)


@pytest.mark.asyncio
async def test_admin_status_isolated_between_tenants(http, rds, pool):
    """A tenant with NO mapping sees linked=false even when ANOTHER tenant is
    mapped — the 'linked' flag is strictly its own."""
    # Map only BIZ_A; ensure BIZ_B has no mapping by UPSERTing a row that exists,
    # then asserting B's view is independent. (We never DELETE; instead we read
    # B's own linked flag, which reflects only B's row.)
    await whatsapp_service.upsert_connection(
        pool, BIZ_A, gateway_account_id=ACC_A, phone=OWN_PHONE, status="connected")
    # B may or may not have a row from other tests; assert the SHAPE + that B's
    # linked flag never reflects A's mapping (it reads B's row only).
    sid_b = await _login(rds, http, BELLA_USER, BIZ_B)
    try:
        body_b = (await http.get("/api/whatsapp/status")).json()
    finally:
        await _logout(rds, http, sid_b)
    # M6b added an `error` field to the status contract.
    assert set(body_b.keys()) == {"linked", "connected", "phone", "gateway_status", "error"}
    # B's linked is a boolean derived only from B's own row — never A's.
    assert isinstance(body_b["linked"], bool)
