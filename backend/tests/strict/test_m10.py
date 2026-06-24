"""M10 — status-driven transcript TTL + encrypted outcome note, strict pytest (CI).

Per decision 0010. This suite proves the two M10 promises:

  A) TTL BY STATUS (Redis): the transcript must NOT vanish while a human is needed.
       bot     → sliding ~60-min TTL
       waiting → PERSIST (no expiry, TTL == -1)
       human   → PERSIST (no expiry, TTL == -1)
       closed  → 30-day TTL
     CRITICALLY: calling append_message on a 'waiting' conversation must NOT
     reintroduce a 60-min TTL — the chat must still PERSIST.

  B) OUTCOME NOTE: PATCH /api/leads/{id}/status with {status, note} stores the note
     ENCRYPTED (the raw DB column is NOT plaintext) and GET /api/leads returns it
     DECRYPTED for the owner — tenant-scoped (A can never set/read B's). LeadItem
     carries outcome_note.

It runs IN-PROCESS against the real ASGI app over httpx ASGITransport (so the
deny-by-default /api gate, the session dependency, and tenant_connection/RLS are
all real), and drives Redis via conversation_state directly where a test needs
exact control of the keys' TTLs. Every persisted row is is_test=true; the cleanup
fixture deletes the test leads + Redis conv keys it created. Nothing prints a
secret, a token, or PII.
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

from app.db.session import tenant_connection
from app.main import app
from app.services import conversation_state as cs
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (published)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (draft)
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

# How much slack we allow when asserting "TTL ~= N seconds" (a couple of round
# trips can shave a second off a freshly-set expiry).
_TTL_SLACK = 30


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
async def cleanup(pool, rds):
    """After each test: drop the conv keys we made + any is_test leads in A and B."""
    made: list[tuple[str, str]] = []
    yield made
    for bid, cid in made:
        await cs.clear_state(rds, bid, cid)
        await rds.delete(f"conv:{bid}:{cid}:log")
        await rds.delete(f"conv:{bid}:{cid}:outbox")
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute(
                "DELETE FROM leads WHERE business_id = $1 AND is_test = true", bid)


# --- helpers ----------------------------------------------------------------

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


def _new_conv() -> str:
    return f"sim:{secrets.token_hex(8)}"


async def _seed_test_lead(pool, business_id: str, *, status: str,
                          conversation_id: str | None) -> str:
    """Insert a minimal is_test lead with a given status (+ optional conv link)."""
    cache_chat_ref = (
        f"conv:{business_id}:{conversation_id}" if conversation_id else None
    )
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO leads
                (business_id, lead_name, status, is_test, cache_chat_ref,
                 started_at, last_activity_at)
            VALUES ($1, $2, $3, true, $4, now(), now())
            RETURNING id
            """,
            business_id, "test-flow", status, cache_chat_ref,
        )
    return str(row["id"])


# ============================================================================
#  A) TTL BY STATUS — the transcript must not vanish while a human is needed
# ============================================================================

@pytest.mark.asyncio
async def test_bot_status_slides_60min_ttl(rds, cleanup):
    """A 'bot' conversation: both the conv key AND its :log get a ~60-min TTL."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    key = cs._key(BIZ_A, conv)
    log_key = cs._log_key(BIZ_A, conv)

    await cs.append_message(rds, BIZ_A, conv, "customer", "שלום")
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_BOT)

    key_ttl = await rds.ttl(key)
    log_ttl = await rds.ttl(log_key)
    # ~3600s, allowing a little slack for the round trips since it was set.
    assert cs.CONVERSATION_TTL_SECONDS - _TTL_SLACK <= key_ttl <= cs.CONVERSATION_TTL_SECONDS
    assert cs.CONVERSATION_TTL_SECONDS - _TTL_SLACK <= log_ttl <= cs.CONVERSATION_TTL_SECONDS


@pytest.mark.asyncio
async def test_waiting_status_persists_no_expiry(rds, cleanup):
    """'waiting' → the conv key AND its :log have NO expiry (TTL == -1)."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    key = cs._key(BIZ_A, conv)
    log_key = cs._log_key(BIZ_A, conv)

    await cs.append_message(rds, BIZ_A, conv, "customer", "אני רוצה נציג")
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_WAITING)

    # TTL == -1 means the key exists with NO expiry (persists). -2 == missing.
    assert await rds.ttl(key) == -1
    assert await rds.ttl(log_key) == -1


@pytest.mark.asyncio
async def test_human_status_persists_no_expiry(rds, cleanup):
    """'human' → the conv key AND its :log persist (TTL == -1)."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    key = cs._key(BIZ_A, conv)
    log_key = cs._log_key(BIZ_A, conv)

    await cs.append_message(rds, BIZ_A, conv, "customer", "שלום")
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_HUMAN)

    assert await rds.ttl(key) == -1
    assert await rds.ttl(log_key) == -1


@pytest.mark.asyncio
async def test_closed_status_30day_ttl(rds, cleanup):
    """'closed' → the conv key AND its :log get a ~30-day TTL."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    key = cs._key(BIZ_A, conv)
    log_key = cs._log_key(BIZ_A, conv)

    await cs.append_message(rds, BIZ_A, conv, "customer", "תודה")
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_CLOSED)

    key_ttl = await rds.ttl(key)
    log_ttl = await rds.ttl(log_key)
    assert cs.CLOSED_TTL_SECONDS - _TTL_SLACK <= key_ttl <= cs.CLOSED_TTL_SECONDS
    assert cs.CLOSED_TTL_SECONDS - _TTL_SLACK <= log_ttl <= cs.CLOSED_TTL_SECONDS
    # And a closed TTL is clearly NOT the 60-min bot window.
    assert key_ttl > cs.CONVERSATION_TTL_SECONDS


@pytest.mark.asyncio
async def test_append_message_does_not_resurrect_ttl_while_waiting(rds, cleanup):
    """THE regression M10 guards against: a new message on a 'waiting' chat must
    NOT bring back a 60-min TTL — the chat must keep persisting (TTL == -1)."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    key = cs._key(BIZ_A, conv)
    log_key = cs._log_key(BIZ_A, conv)

    # The customer asked for a human; nobody has picked up yet → waiting/persist.
    await cs.append_message(rds, BIZ_A, conv, "customer", "אני רוצה נציג")
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_WAITING)
    assert await rds.ttl(key) == -1 and await rds.ttl(log_key) == -1

    # The customer sends ANOTHER message while still waiting. Pre-M10 this set a
    # flat 60-min expire and the transcript would later vanish. It must still
    # persist.
    await cs.append_message(rds, BIZ_A, conv, "customer", "מתי תענו לי?")

    assert await rds.ttl(key) == -1, "append_message resurrected a TTL on a waiting chat"
    assert await rds.ttl(log_key) == -1, "append_message resurrected a TTL on the :log"


@pytest.mark.asyncio
async def test_append_message_does_not_resurrect_ttl_while_human(rds, cleanup):
    """Same guard for 'human': an owner-side message must keep the chat persisting."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    key = cs._key(BIZ_A, conv)
    log_key = cs._log_key(BIZ_A, conv)

    await cs.append_message(rds, BIZ_A, conv, "customer", "שלום")
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_HUMAN)
    assert await rds.ttl(key) == -1

    # An owner reply (which also appends to the transcript) must not re-expire it.
    await cs.append_message(rds, BIZ_A, conv, "owner", "אני כאן, איך אפשר לעזור?")

    assert await rds.ttl(key) == -1
    assert await rds.ttl(log_key) == -1


@pytest.mark.asyncio
async def test_status_transition_waiting_then_closed_sets_30day(rds, cleanup):
    """Moving waiting → closed flips the persisted keys onto the 30-day window
    (so a finished-after-handoff chat is swept eventually, not kept forever)."""
    conv = _new_conv()
    cleanup.append((BIZ_A, conv))
    key = cs._key(BIZ_A, conv)
    log_key = cs._log_key(BIZ_A, conv)

    await cs.append_message(rds, BIZ_A, conv, "customer", "נציג")
    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_WAITING)
    assert await rds.ttl(key) == -1

    await cs.set_status(rds, BIZ_A, conv, cs.STATUS_CLOSED)
    assert cs.CLOSED_TTL_SECONDS - _TTL_SLACK <= await rds.ttl(key) <= cs.CLOSED_TTL_SECONDS
    assert cs.CLOSED_TTL_SECONDS - _TTL_SLACK <= await rds.ttl(log_key) <= cs.CLOSED_TTL_SECONDS


# ============================================================================
#  B) OUTCOME NOTE — encrypted at rest, decrypted for the owner, tenant-scoped
# ============================================================================

@pytest.mark.asyncio
async def test_outcome_note_stored_encrypted_and_returned_decrypted(http, rds, pool, cleanup):
    """PATCH {status:'deal', note} → DB column is ciphertext (NOT plaintext), and
    GET /api/leads returns the note decrypted for the owner."""
    await _login(rds, http, AVI_USER, BIZ_A)
    lead_id = await _seed_test_lead(pool, BIZ_A, status="new", conversation_id=None)
    note_plain = "הלקוח חתם על חוזה שנתי בסכום של 12000"

    r = await http.patch(
        f"/api/leads/{lead_id}/status", json={"status": "deal", "note": note_plain})
    assert r.status_code == 200 and r.json()["status"] == "deal"

    # The RAW DB column must NOT contain the plaintext (it is encrypted at rest).
    async with tenant_connection(pool, BIZ_A) as conn:
        raw = await conn.fetchval(
            "SELECT outcome_note FROM leads WHERE id = $1 AND business_id = $2",
            lead_id, BIZ_A)
    assert raw is not None
    assert note_plain not in raw, "outcome_note was stored in PLAINTEXT (must be encrypted)"

    # The owner reads it back decrypted via the API.
    rows = (await http.get("/api/leads?status=deal&include_test=true")).json()["leads"]
    match = [x for x in rows if x["id"] == lead_id]
    assert match, "the deal lead was not returned"
    assert match[0]["outcome_note"] == note_plain


@pytest.mark.asyncio
async def test_lead_item_includes_outcome_note_field(http, rds, pool, cleanup):
    """Every lead payload carries the outcome_note field (None when never set)."""
    await _login(rds, http, AVI_USER, BIZ_A)
    lead_id = await _seed_test_lead(pool, BIZ_A, status="new", conversation_id=None)

    rows = (await http.get("/api/leads?status=new&include_test=true")).json()["leads"]
    match = [x for x in rows if x["id"] == lead_id]
    assert match
    # Field is present in the response shape and is null until an outcome note is set.
    assert "outcome_note" in match[0]
    assert match[0]["outcome_note"] is None


@pytest.mark.asyncio
async def test_outcome_note_optional_status_without_note_leaves_it_null(http, rds, pool, cleanup):
    """The API accepts a status change WITHOUT a note (note is optional server-side);
    the outcome_note stays null."""
    await _login(rds, http, AVI_USER, BIZ_A)
    lead_id = await _seed_test_lead(pool, BIZ_A, status="new", conversation_id=None)

    r = await http.patch(f"/api/leads/{lead_id}/status", json={"status": "closed"})
    assert r.status_code == 200

    rows = (await http.get("/api/leads?status=closed&include_test=true")).json()["leads"]
    match = [x for x in rows if x["id"] == lead_id]
    assert match and match[0]["outcome_note"] is None


# ============================================================================
#  B') TENANT ISOLATION on the new column / paths
# ============================================================================

@pytest.mark.asyncio
async def test_isolation_cannot_set_other_tenants_outcome_note(http, rds, pool, cleanup):
    """A tries to PATCH B's lead with a note → 404 (RLS hid it); B's row untouched."""
    b_lead = await _seed_test_lead(pool, BIZ_B, status="new", conversation_id=None)
    await _login(rds, http, AVI_USER, BIZ_A)

    r = await http.patch(
        f"/api/leads/{b_lead}/status", json={"status": "deal", "note": "secret-A-note"})
    assert r.status_code == 404

    # B's lead is untouched: still 'new', no outcome_note written.
    async with tenant_connection(pool, BIZ_B) as conn:
        row = await conn.fetchrow(
            "SELECT status, outcome_note FROM leads WHERE id = $1 AND business_id = $2",
            b_lead, BIZ_B)
    assert row["status"] == "new"
    assert row["outcome_note"] is None


@pytest.mark.asyncio
async def test_isolation_cannot_read_other_tenants_outcome_note(http, rds, pool, cleanup):
    """B sets a note on its own lead; A must never see that lead or its note."""
    b_lead = await _seed_test_lead(pool, BIZ_B, status="new", conversation_id=None)
    b_note = "Bella private outcome note"
    await _login(rds, http, BELLA_USER, BIZ_B)
    r = await http.patch(
        f"/api/leads/{b_lead}/status", json={"status": "deal", "note": b_note})
    assert r.status_code == 200

    # Now Avi logs in and lists everything — must not see B's lead or its note.
    await _login(rds, http, AVI_USER, BIZ_A)
    a_rows = (await http.get("/api/leads?include_test=true")).json()["leads"]
    seen_ids = {x["id"] for x in a_rows}
    assert b_lead not in seen_ids
    assert all((x.get("outcome_note") or "") != b_note for x in a_rows)


# ============================================================================
#  The gate — the M10 doors are 401 without a session
# ============================================================================

@pytest.mark.asyncio
async def test_m10_routes_require_session(http):
    assert (await http.patch(
        "/api/leads/x/status", json={"status": "deal", "note": "n"})).status_code == 401
