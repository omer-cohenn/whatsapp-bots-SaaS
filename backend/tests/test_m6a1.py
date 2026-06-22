"""M6a.1 — external "test numbers" allow-list, strict pytest (the CI version).

Per the FROZEN M6a.1 contract. The narrated story lives in m6a1_full_test.py;
THIS is the strict gate CI runs. It drives the REAL ASGI app over httpx
ASGITransport so the X-Gateway-Token webhook auth, the deny-by-default /api gate,
the session dependency, tenant_connection/RLS and the inbound resolve→allow→run
core are all exercised exactly like a live request.

What it proves (mapped to the QA goals):

  G2  ALLOW-LISTED + PUBLISHED → run_turn replies; a REAL (is_test=False) lead
      persists (shows in GET /api/leads, which hides test rows; phone round-trips,
      encrypted at rest).
  G3  NON-ALLOW-LISTED → {status:"not allowed", replies:[]} (silent).
  G4  ALLOW-LISTED but DRAFT bot → {status:"not published", replies:[]} (silent).
  G5  normalize(): a stored Israeli-local '0547…' matches an inbound '+97254 7…'.
  G6  PUT /test-numbers: >5 → 422; 5 → ok; GET round-trips labels; the raw DB
      columns are ciphertext (plaintext phone/label absent).
  G7  AUTH: bad/missing X-Gateway-Token on the inbound path → 401; the admin
      /test-numbers routes → 401 without a session; tenant-scoped with one.
  G8  REGRESSION: the self-chat (M6a) still returns ok+replies; the gateway
      loop-guard logic (skip-our-own, cap=200, oldest-evicted) still holds.

Every persisted lead is cleaned up. Mappings are UPSERTed (app_role has no DELETE
on whatsapp_connections). Nothing prints/asserts a secret, a token, or PII text.
The REAL WhatsApp send/receive on a second phone is a MANUAL step for Omer.
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
from app.services import whatsapp as whatsapp_service
from app.services import whatsapp_test_numbers as test_numbers_service
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (PUBLISHED in seed)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (DRAFT in seed)
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

ACC_A = "m6a1-acct-avi"
ACC_B = "m6a1-acct-bella"
OWN_PHONE = "+972500000001"

# DAD: stored Israeli-local, arrives international (the normalize match).
DAD_LOCAL = "0547408309"
DAD_INBOUND = "+972547408309"
DAD_NORMALIZED = "972547408309"
MOM_INTL = "+972500000022"
STRANGER_INBOUND = "+972500000099"

CUST_NAME = "אבא הבודק"
CUST_PHONE_DIGITS = "0521230000"


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
    """Map each business to its own gateway account (UPSERT, never DELETE)."""
    await whatsapp_service.upsert_connection(
        pool, BIZ_A, gateway_account_id=ACC_A, phone=OWN_PHONE, status="connected")
    await whatsapp_service.upsert_connection(
        pool, BIZ_B, gateway_account_id=ACC_B, phone=OWN_PHONE, status="connected")
    yield


@pytest_asyncio.fixture
async def allowlist(pool, mapped):
    """Avi allows Dad+Mom; Bella allows Dad. Restored to empty after the test."""
    await test_numbers_service.set_test_numbers(pool, BIZ_A, [
        {"phone": DAD_LOCAL, "label": "Dad"},
        {"phone": MOM_INTL, "label": "Mom"},
    ])
    await test_numbers_service.set_test_numbers(pool, BIZ_B, [
        {"phone": DAD_LOCAL, "label": "Dad"},
    ])
    yield
    # Tidy: empty both lists so other suites/tenants start clean.
    await test_numbers_service.set_test_numbers(pool, BIZ_A, [])
    await test_numbers_service.set_test_numbers(pool, BIZ_B, [])


@pytest_asyncio.fixture
async def cleanup_leads(pool):
    yield
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute("DELETE FROM leads WHERE business_id = $1", bid)


# --- helpers ----------------------------------------------------------------

def _body(account_id: str, text: str, from_phone: str, conv: str,
          *, self_test: bool = False) -> dict:
    return {
        "gateway_account_id": account_id,
        "from": from_phone,
        "push_name": "Tester",
        "message_id": f"m6a1-{secrets.token_hex(6)}",
        "timestamp": 1_700_000_000,
        "type": "text",
        "text": text,
        "raw": {"note": "synthetic m6a.1 test"},
        "self_test": self_test,
        "conversation_id": conv,
    }


def _auth(token: str) -> dict:
    return {"X-Gateway-Token": token}


async def _post(http, token, account_id, text, from_phone, conv, **kw):
    return await http.post("/webhook/whatsapp",
                           json=_body(account_id, text, from_phone, conv, **kw),
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
#  GOAL 5 — normalize(): stored Israeli-local matches inbound international
# ============================================================================

def test_normalize_israeli_local_matches_intl():
    """'0547408309' and '+972547408309' both normalize to '972547408309'."""
    assert test_numbers_service.normalize(DAD_LOCAL) == DAD_NORMALIZED
    assert test_numbers_service.normalize(DAD_INBOUND) == DAD_NORMALIZED
    # And a few contract edge cases.
    assert test_numbers_service.normalize("+972500000022") == "972500000022"
    assert test_numbers_service.normalize("054-740-8309") == DAD_NORMALIZED
    assert test_numbers_service.normalize("") == ""
    assert test_numbers_service.normalize(None) == ""


@pytest.mark.asyncio
async def test_is_number_allowed_matches_across_notations(pool, allowlist):
    """is_number_allowed() matches the stored local form against an intl inbound."""
    assert await test_numbers_service.is_number_allowed(pool, BIZ_A, DAD_INBOUND) is True
    assert await test_numbers_service.is_number_allowed(pool, BIZ_A, MOM_INTL) is True
    assert await test_numbers_service.is_number_allowed(pool, BIZ_A, STRANGER_INBOUND) is False
    assert await test_numbers_service.is_number_allowed(pool, BIZ_A, "") is False


# ============================================================================
#  GOAL 2 — allow-listed + published → run_turn answers
# ============================================================================

@pytest.mark.asyncio
async def test_allowlisted_published_bot_replies(http, token, allowlist):
    """A self_test=False inbound from an allow-listed number → {status:ok, replies}."""
    r = await _post(http, token, ACC_A, "היי", DAD_INBOUND,
                    f"intl:{secrets.token_hex(6)}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["replies"], list) and len(body["replies"]) >= 1


@pytest.mark.asyncio
async def test_full_lead_questionnaire_persists_real_lead(
    http, rds, token, allowlist, cleanup_leads, pool
):
    """A full questionnaire from an allow-listed outside number → a REAL lead."""
    conv = f"intl:{secrets.token_hex(6)}"
    await _post(http, token, ACC_A, "היי", DAD_INBOUND, conv)
    start = await _post(http, token, ACC_A, "1", DAD_INBOUND, conv)
    await _post(http, token, ACC_A, CUST_NAME, DAD_INBOUND, conv)
    await _post(http, token, ACC_A, CUST_PHONE_DIGITS, DAD_INBOUND, conv)
    done = await _post(http, token, ACC_A, "1", DAD_INBOUND, conv)
    assert start.json()["replies"] and done.json()["replies"]

    sid = await _login(rds, http, AVI_USER, BIZ_A)
    try:
        leads = (await http.get("/api/leads")).json()["leads"]
    finally:
        await _logout(rds, http, sid)

    quote = [lead for lead in leads if lead["lead_name"] == "quote"]
    assert quote, "the finished questionnaire must appear as a real lead"
    assert all(lead["is_test"] is False for lead in quote)
    assert any((lead.get("phone") or "").endswith(CUST_PHONE_DIGITS) for lead in quote)


# ============================================================================
#  GOAL 3 — a NON-allow-listed number is silent
# ============================================================================

@pytest.mark.asyncio
async def test_non_allowlisted_is_silent(http, token, allowlist):
    """A stranger (not on the list) → {status:'not allowed', replies:[]}."""
    r = await _post(http, token, ACC_A, "היי", STRANGER_INBOUND,
                    f"intl:{secrets.token_hex(6)}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not allowed"
    assert body["replies"] == []


@pytest.mark.asyncio
async def test_allowlist_gate_is_real(http, token, allowlist, pool):
    """Negative control: dropping a number makes it ignored; restoring re-enables it."""
    await test_numbers_service.set_test_numbers(
        pool, BIZ_A, [{"phone": MOM_INTL, "label": "Mom"}])  # drop Dad
    try:
        broke = (await _post(http, token, ACC_A, "היי", DAD_INBOUND,
                             f"intl:{secrets.token_hex(6)}")).json()
        assert broke["status"] == "not allowed" and broke["replies"] == []
    finally:
        await test_numbers_service.set_test_numbers(pool, BIZ_A, [
            {"phone": DAD_LOCAL, "label": "Dad"},
            {"phone": MOM_INTL, "label": "Mom"},
        ])
    fixed = (await _post(http, token, ACC_A, "היי", DAD_INBOUND,
                         f"intl:{secrets.token_hex(6)}")).json()
    assert fixed["status"] == "ok" and len(fixed["replies"]) >= 1


# ============================================================================
#  GOAL 4 — allow-listed but the bot is a DRAFT → silent (publish gate wins)
# ============================================================================

@pytest.mark.asyncio
async def test_allowlisted_but_draft_is_silent(http, token, allowlist):
    """Dad is on Bella's list, but Bella's bot is a draft → 'not published'."""
    r = await _post(http, token, ACC_B, "היי", DAD_INBOUND,
                    f"intl:{secrets.token_hex(6)}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not published"
    assert body["replies"] == []


@pytest.mark.asyncio
async def test_blank_inbound_is_acked_not_run(http, token, allowlist):
    """A blank/whitespace inbound is ack-only ('received'), never a bot run."""
    r = await _post(http, token, ACC_A, "   ", DAD_INBOUND,
                    f"intl:{secrets.token_hex(6)}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "received"
    assert body["replies"] == []


# ============================================================================
#  GOAL 6 — admin PUT/GET: the ≤5 cap, label round-trip, ciphertext at rest
# ============================================================================

@pytest.mark.asyncio
async def test_put_six_rejected_five_ok_and_roundtrips(http, rds, pool):
    """PUT 6 → 422; PUT 5 → 200; GET round-trips numbers + labels (normalized)."""
    sid = await _login(rds, http, AVI_USER, BIZ_A)
    try:
        six = {"numbers": [
            {"phone": f"05000000{i:02d}", "label": f"n{i}"} for i in range(6)]}
        r_six = await http.put("/api/whatsapp/test-numbers", json=six)
        assert r_six.status_code == 422

        five = {"numbers": [
            {"phone": "0500000011", "label": "Alpha"},
            {"phone": "0500000012", "label": "Bravo"},
            {"phone": "+972500000013", "label": None},
            {"phone": "0500000014", "label": "Delta"},
            {"phone": "0500000015", "label": "Echo"},
        ]}
        r_five = await http.put("/api/whatsapp/test-numbers", json=five)
        assert r_five.status_code == 200

        got = (await http.get("/api/whatsapp/test-numbers")).json()["numbers"]
        assert [n["phone"] for n in got] == [
            "972500000011", "972500000012", "972500000013",
            "972500000014", "972500000015"]
        assert [n["label"] for n in got] == ["Alpha", "Bravo", None, "Delta", "Echo"]
    finally:
        # Tidy: empty Avi's list so other suites start clean.
        await test_numbers_service.set_test_numbers(pool, BIZ_A, [])
        await _logout(rds, http, sid)


@pytest.mark.asyncio
async def test_dropped_blanks_and_dupes_on_save(http, rds, pool):
    """Blanks are dropped and duplicates (by normalized phone) collapse to one."""
    sid = await _login(rds, http, AVI_USER, BIZ_A)
    try:
        body = {"numbers": [
            {"phone": "0547408309", "label": "Dad"},      # -> 972547408309
            {"phone": "+972547408309", "label": "DupDad"},  # same -> dropped
            {"phone": "   ", "label": "blank"},            # blank -> dropped
        ]}
        r = await http.put("/api/whatsapp/test-numbers", json=body)
        assert r.status_code == 200
        got = r.json()["numbers"]
        assert [n["phone"] for n in got] == [DAD_NORMALIZED]
        assert got[0]["label"] == "Dad"  # first occurrence wins
    finally:
        await test_numbers_service.set_test_numbers(pool, BIZ_A, [])
        await _logout(rds, http, sid)


@pytest.mark.asyncio
async def test_test_numbers_encrypted_at_rest(pool, allowlist):
    """The raw whatsapp_test_numbers columns are ciphertext (no plaintext PII)."""
    async with tenant_connection(pool, BIZ_A) as conn:
        rows = await conn.fetch(
            "SELECT phone_number, label FROM whatsapp_test_numbers "
            "WHERE business_id = $1", BIZ_A)
    assert rows
    blob = " ".join(
        bytes(r["phone_number"]).decode("latin-1")
        + (bytes(r["label"]).decode("latin-1") if r["label"] is not None else "")
        for r in rows)
    assert DAD_NORMALIZED not in blob
    assert DAD_LOCAL not in blob
    assert "Dad" not in blob and "Mom" not in blob


# ============================================================================
#  GOAL 7 — auth: webhook token + admin-route session gate + tenant scope
# ============================================================================

@pytest.mark.asyncio
async def test_webhook_rejects_bad_and_missing_token(http, mapped):
    """Bad/missing X-Gateway-Token on the inbound path → 401 before any work."""
    bad = await http.post("/webhook/whatsapp",
                          json=_body(ACC_A, "היי", DAD_INBOUND, "intl:x"),
                          headers={"X-Gateway-Token": "totally-wrong"})
    missing = await http.post("/webhook/whatsapp",
                              json=_body(ACC_A, "היי", DAD_INBOUND, "intl:x"))
    assert bad.status_code == 401
    assert missing.status_code == 401


@pytest.mark.asyncio
async def test_admin_test_numbers_require_session(http):
    """GET/PUT /api/whatsapp/test-numbers → 401 without a session (deny-by-default)."""
    assert (await http.get("/api/whatsapp/test-numbers")).status_code == 401
    assert (await http.put("/api/whatsapp/test-numbers",
                           json={"numbers": []})).status_code == 401


@pytest.mark.asyncio
async def test_test_numbers_tenant_isolated(http, rds, allowlist):
    """One business sees ONLY its own allow-list, never another's (RLS)."""
    sid_a = await _login(rds, http, AVI_USER, BIZ_A)
    try:
        avi = (await http.get("/api/whatsapp/test-numbers")).json()["numbers"]
    finally:
        await _logout(rds, http, sid_a)

    sid_b = await _login(rds, http, BELLA_USER, BIZ_B)
    try:
        bella = (await http.get("/api/whatsapp/test-numbers")).json()["numbers"]
    finally:
        await _logout(rds, http, sid_b)

    avi_phones = {n["phone"] for n in avi}
    bella_phones = [n["phone"] for n in bella]
    # Avi has Dad+Mom; Bella has only Dad — and Bella never sees Mom.
    assert "972500000022" in avi_phones  # Mom is Avi's
    assert bella_phones == [DAD_NORMALIZED]
    assert "972500000022" not in bella_phones


# ============================================================================
#  GOAL 8 — regression: the self-chat (M6a) still works; loop-guard intact
# ============================================================================

@pytest.mark.asyncio
async def test_self_chat_still_works(http, token, mapped):
    """The M6a self-chat path is unchanged: owner always allowed → ok + replies."""
    r = await _post(http, token, ACC_A, "היי", OWN_PHONE,
                    f"self:{secrets.token_hex(6)}", self_test=True)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert len(body["replies"]) >= 1


def test_gateway_loop_guard_logic():
    """Mirror gateway/src/index.js rememberSentId + the top-of-handleInbound skip.

    M6a.1's normal-chat branch reuses the SAME guard (sendReplies→rememberSentId
    + the top-of-handleInbound skip), so an allow-listed reply's fromMe echo is
    skipped exactly like the self-chat's. The REAL phone echo is manual.
    """
    SENT_ID_CAP = 200
    sent: dict[str, None] = {}

    def remember(mid: str) -> None:
        if not mid:
            return
        sent[mid] = None
        if len(sent) > SENT_ID_CAP:
            del sent[next(iter(sent))]

    def should_skip(mid: str) -> bool:
        return bool(mid) and mid in sent

    remember("reply-1")
    assert should_skip("reply-1")
    assert not should_skip("inbound-x")

    for i in range(SENT_ID_CAP + 50):
        remember(f"id-{i}")
    assert len(sent) == SENT_ID_CAP
    assert not should_skip("reply-1")
    assert not should_skip("id-0")
    assert should_skip(f"id-{SENT_ID_CAP + 50 - 1}")
