"""M6b — the multi-tenant WhatsApp WALL, strict pytest (CI version).

M6b makes WhatsApp multi-tenant: one Baileys socket per business, each session's
auth_state envelope-encrypted in `whatsapp_credentials` (the 🔒🔒 CROWN JEWEL),
and a token-gated INTERNAL API (`/internal/wa/*`) the gateway uses to discover
sessions, load/save creds, and report status. This suite proves the WALL holds
around all of it, with the REAL DB / Redis / running app:

  a. CROWN JEWEL ISOLATION  — gateway_role + tenant_connection: business B can
     neither read, update, nor forge business A's whatsapp_credentials row.
  b. app_role LOCKOUT       — app_role has ZERO grant on whatsapp_credentials:
     any touch raises insufficient_privilege, even with a tenant context set.
  c. wa_list_sessions()     — callable on app_role, returns ONLY business uuids
     (the businesses that have a whatsapp_connections row), nothing else.
  d. INTERNAL API AUTH      — /internal/wa/* without (or with a wrong)
     X-Gateway-Token is a flat 401; the right token is a 200.
  e. ROUND-TRIP + AT-REST   — PUT creds stores CIPHERTEXT (the plaintext is NOT
     in the raw bytes), GET returns the exact original, and B never gets A's.
  f. PER-BUSINESS QR        — a QR reported for A lands in Redis wa:qr:{A} only;
     B's (and the real business's) QR slot is never given A's code.

Tenants: the two SEEDED pretend businesses (Avi/Bella). The user's REAL business
(7fca1b13-…) is never written to. Every row/key the suite creates is cleaned up,
and pre-existing rows are snapshotted + restored. No secret/PII is ever printed:
payloads are random markers, never real credentials.
"""

from __future__ import annotations

import base64
import secrets
import uuid

import asyncpg
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.db.session import tenant_connection
from app.main import app
from tests.conftest import BIZ_A, BIZ_B

# The user's REAL business — this suite must NEVER write to it.
REAL_BIZ = "7fca1b13-902a-4ce2-a4a4-28ecd48f96eb"

GATEWAY_TOKEN = get_settings().gateway_api_token.get_secret_value()
GOOD_HDR = {"X-Gateway-Token": GATEWAY_TOKEN}
BAD_HDR = {"X-Gateway-Token": "totally-wrong"}


# --- fixtures (app_pool / gw_pool / redis_client come from tests/conftest.py) --

@pytest_asyncio.fixture
async def lifespan_app():
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def http(lifespan_app):
    transport = ASGITransport(app=lifespan_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# --- tiny helpers -------------------------------------------------------------

async def _delete_creds(gw_pool: asyncpg.Pool, business_id: str) -> None:
    """Remove a TEST creds row under its own tenant context (RLS-scoped)."""
    async with tenant_connection(gw_pool, business_id) as conn:
        await conn.execute(
            "DELETE FROM whatsapp_credentials WHERE business_id = $1", business_id
        )


async def _fetch_creds_raw(gw_pool: asyncpg.Pool, business_id: str):
    """The RAW stored row (ciphertext bytes) under its own tenant context."""
    async with tenant_connection(gw_pool, business_id) as conn:
        return await conn.fetchrow(
            "SELECT auth_state, key_version FROM whatsapp_credentials "
            "WHERE business_id = $1",
            business_id,
        )


# ============================================================================
#  (a) CROWN JEWEL ISOLATION — gateway_role, tenant-scoped by RLS
# ============================================================================

async def test_crown_jewel_b_cannot_read_update_or_forge_a(gw_pool):
    """Insert a creds row for A (as A); prove B sees/changes/forges NOTHING.

    All four probes run as gateway_role — the ONLY role with a grant — so what
    blocks them is purely the RLS policy (business_id = current_business_id()).
    """
    marker = f"m6b-wall-{secrets.token_hex(8)}".encode()
    # A stores its (fake) session under its own tenant context.
    async with tenant_connection(gw_pool, BIZ_A) as conn:
        await conn.execute(
            "INSERT INTO whatsapp_credentials (business_id, auth_state, key_version) "
            "VALUES ($1, $2, 1) "
            "ON CONFLICT (business_id) DO UPDATE SET auth_state = EXCLUDED.auth_state",
            BIZ_A, marker,
        )
    try:
        # B, explicitly asking for A's row → ZERO rows (RLS hides it).
        async with tenant_connection(gw_pool, BIZ_B) as conn:
            rows = await conn.fetch(
                "SELECT * FROM whatsapp_credentials WHERE business_id = $1", BIZ_A
            )
        assert rows == []

        # B listing everything → never sees A's ciphertext either.
        async with tenant_connection(gw_pool, BIZ_B) as conn:
            all_rows = await conn.fetch("SELECT auth_state FROM whatsapp_credentials")
        assert all(bytes(r["auth_state"]) != marker for r in all_rows)

        # B UPDATE-ing A's row → affects 0 rows (the row is invisible to B).
        async with tenant_connection(gw_pool, BIZ_B) as conn:
            status = await conn.execute(
                "UPDATE whatsapp_credentials SET key_version = 99 "
                "WHERE business_id = $1",
                BIZ_A,
            )
        assert status.endswith(" 0")

        # B INSERT-ing a row labelled as A's → WITH CHECK rejects it outright.
        with pytest.raises(asyncpg.PostgresError):
            async with tenant_connection(gw_pool, BIZ_B) as conn:
                await conn.execute(
                    "INSERT INTO whatsapp_credentials (business_id, auth_state, key_version) "
                    "VALUES ($1, $2, 1)",
                    BIZ_A, b"poison",
                )

        # A's row is intact after all of B's attempts.
        row = await _fetch_creds_raw(gw_pool, BIZ_A)
        assert row is not None
        assert bytes(row["auth_state"]) == marker
        assert row["key_version"] == 1
    finally:
        await _delete_creds(gw_pool, BIZ_A)


async def test_crown_jewel_no_tenant_context_sees_nothing(gw_pool):
    """gateway_role with NO app.business_id set → deny-by-default, zero rows."""
    async with gw_pool.acquire() as conn:  # no tenant_connection on purpose
        rows = await conn.fetch("SELECT business_id FROM whatsapp_credentials")
    assert rows == []


# ============================================================================
#  (b) app_role LOCKOUT — zero grant on the crown jewel
# ============================================================================

async def test_app_role_any_select_raises_insufficient_privilege(app_pool):
    """Even with a valid tenant context, app_role may not SELECT the table."""
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with tenant_connection(app_pool, BIZ_A) as conn:
            await conn.fetch("SELECT * FROM whatsapp_credentials")


async def test_app_role_locked_out_without_context_and_for_writes(app_pool):
    """No context → still insufficient_privilege; INSERT into OWN tenant too."""
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with app_pool.acquire() as conn:
            await conn.fetch("SELECT business_id FROM whatsapp_credentials")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with tenant_connection(app_pool, BIZ_A) as conn:
            await conn.execute(
                "INSERT INTO whatsapp_credentials (business_id, auth_state, key_version) "
                "VALUES ($1, $2, 1)",
                BIZ_A, b"nope",
            )


# ============================================================================
#  (c) wa_list_sessions() — app_role-callable, uuids ONLY
# ============================================================================

async def test_wa_list_sessions_returns_only_business_uuids(app_pool, gw_pool):
    """app_role can EXECUTE it with NO tenant context; the rows are bare uuids.

    We guarantee at least one known member (a connections row for A, restored
    afterwards) and prove an unknown business is absent. The SETOF uuid return
    shape is itself the leak-proofing: no phone, status, or auth_state can ride
    along a bare uuid column.
    """
    # Snapshot A's connections row (it may pre-exist), then make sure one exists.
    async with tenant_connection(gw_pool, BIZ_A) as conn:
        snap = await conn.fetchrow(
            "SELECT gateway_account_id, phone_number, status, last_connected_at "
            "FROM whatsapp_connections WHERE business_id = $1",
            BIZ_A,
        )
        await conn.execute(
            # $1 is a uuid, $2 the text account id (same value, distinct types).
            "INSERT INTO whatsapp_connections (business_id, gateway_account_id, status) "
            "VALUES ($1, $2, 'qr_pending') ON CONFLICT (business_id) DO NOTHING",
            BIZ_A, BIZ_A,
        )
    try:
        async with app_pool.acquire() as conn:  # NO tenant context — none needed
            rows = await conn.fetch("SELECT wa_list_sessions() AS business_id")
        ids = [r["business_id"] for r in rows]

        assert ids, "at least one session (we just ensured A's row) must be listed"
        assert all(isinstance(i, uuid.UUID) for i in ids)  # uuids, nothing else
        assert all(len(r) == 1 for r in rows)  # a single bare column
        assert uuid.UUID(BIZ_A) in ids
        assert uuid.UUID(str(uuid.uuid4())) not in ids  # a random stranger is absent
    finally:
        # Restore A exactly as it was (delete the row only if WE created it).
        async with tenant_connection(gw_pool, BIZ_A) as conn:
            if snap is None:
                await conn.execute(
                    "DELETE FROM whatsapp_connections WHERE business_id = $1", BIZ_A
                )
            else:
                await conn.execute(
                    "UPDATE whatsapp_connections SET gateway_account_id = $2, "
                    "phone_number = $3, status = $4, last_connected_at = $5 "
                    "WHERE business_id = $1",
                    BIZ_A, snap["gateway_account_id"], snap["phone_number"],
                    snap["status"], snap["last_connected_at"],
                )


# ============================================================================
#  (d) INTERNAL API AUTH — X-Gateway-Token gates every route
# ============================================================================

async def test_internal_wa_routes_reject_missing_or_wrong_token(http):
    """Every /internal/wa route → 401 with a missing OR a wrong token."""
    probes = [
        ("GET", "/internal/wa/sessions", None),
        ("GET", f"/internal/wa/creds/{BIZ_A}", None),
        ("PUT", f"/internal/wa/creds/{BIZ_A}",
         {"auth_state": base64.b64encode(b"x").decode()}),
        ("POST", f"/internal/wa/status/{BIZ_A}", {"status": "qr_pending"}),
    ]
    for method, path, body in probes:
        missing = await http.request(method, path, json=body)
        wrong = await http.request(method, path, json=body, headers=BAD_HDR)
        assert missing.status_code == 401, f"{method} {path} (no token)"
        assert wrong.status_code == 401, f"{method} {path} (wrong token)"


async def test_internal_wa_routes_accept_the_right_token(http):
    """With the REAL token the read routes answer 200 (and leak only safe shapes)."""
    sessions = await http.get("/internal/wa/sessions", headers=GOOD_HDR)
    assert sessions.status_code == 200, sessions.text
    body = sessions.json()
    assert set(body.keys()) == {"sessions"}
    for biz in body["sessions"]:
        uuid.UUID(biz)  # every entry parses as a uuid — nothing else rides along

    creds = await http.get(f"/internal/wa/creds/{BIZ_A}", headers=GOOD_HDR)
    assert creds.status_code == 200, creds.text
    assert set(creds.json().keys()) == {"auth_state", "key_version"}


async def test_internal_wa_rejects_malformed_business_id(http):
    """A non-uuid business_id never reaches the DB — 422 (with a valid token)."""
    r = await http.get("/internal/wa/creds/not-a-uuid", headers=GOOD_HDR)
    assert r.status_code == 422


# ============================================================================
#  (e) CREDS ROUND-TRIP + ENCRYPTION AT REST
# ============================================================================

async def test_creds_roundtrip_is_encrypted_at_rest_and_tenant_scoped(http, gw_pool):
    """PUT → stored bytes are CIPHERTEXT; GET returns the exact original; and
    B's GET never yields A's payload."""
    plaintext = f"m6b-crown-probe-{secrets.token_hex(16)}".encode()
    b64 = base64.b64encode(plaintext).decode()

    put = await http.put(
        f"/internal/wa/creds/{BIZ_A}", headers=GOOD_HDR, json={"auth_state": b64}
    )
    assert put.status_code == 200, put.text
    assert put.json() == {"ok": True}
    try:
        # AT REST: the raw stored bytes must NOT contain the plaintext (nor its
        # base64 wire form) — only the envelope ciphertext.
        row = await _fetch_creds_raw(gw_pool, BIZ_A)
        assert row is not None
        raw = bytes(row["auth_state"])
        assert plaintext not in raw
        assert b64.encode() not in raw
        assert row["key_version"] == 1  # stamped with the current KEK version

        # ROUND-TRIP: GET decrypts back to the EXACT original base64.
        got = await http.get(f"/internal/wa/creds/{BIZ_A}", headers=GOOD_HDR)
        assert got.status_code == 200, got.text
        assert got.json()["auth_state"] == b64
        assert got.json()["key_version"] == 1

        # TENANT WALL over HTTP: B's creds are NOT A's payload (B has none here).
        got_b = await http.get(f"/internal/wa/creds/{BIZ_B}", headers=GOOD_HDR)
        assert got_b.status_code == 200, got_b.text
        assert got_b.json()["auth_state"] != b64
    finally:
        await _delete_creds(gw_pool, BIZ_A)


async def test_creds_put_rejects_bad_base64(http, gw_pool):
    """Garbage (non-base64) auth_state → 422, and the stored row is untouched."""
    before = await _fetch_creds_raw(gw_pool, BIZ_B)
    r = await http.put(
        f"/internal/wa/creds/{BIZ_B}", headers=GOOD_HDR,
        json={"auth_state": "!!!not-base64!!!"},
    )
    assert r.status_code == 422
    after = await _fetch_creds_raw(gw_pool, BIZ_B)
    # Nothing was written: the row is exactly as it was (usually absent).
    if before is None:
        assert after is None
    else:
        assert after is not None
        assert bytes(after["auth_state"]) == bytes(before["auth_state"])


# ============================================================================
#  (f) PER-BUSINESS QR ISOLATION — wa:qr:{A} never bleeds into B (or the real biz)
# ============================================================================

async def test_qr_reported_for_a_never_lands_in_b_or_real_business(
    http, gw_pool, redis_client
):
    """POST status for A with a unique fake QR → only wa:qr:{A} carries it."""
    fake_qr = f"data:image/png;base64,M6BWALL{secrets.token_hex(12)}"

    # Snapshot A's connections row — the status POST upserts it (and would null
    # the phone), so we must put back exactly what was there.
    async with tenant_connection(gw_pool, BIZ_A) as conn:
        snap = await conn.fetchrow(
            "SELECT gateway_account_id, phone_number, status, last_connected_at "
            "FROM whatsapp_connections WHERE business_id = $1",
            BIZ_A,
        )
    try:
        r = await http.post(
            f"/internal/wa/status/{BIZ_A}", headers=GOOD_HDR,
            json={"status": "qr_pending", "qr_data_url": fake_qr},
        )
        assert r.status_code == 200, r.text
        # M6b's one-number guard added a `conflict` flag to the status response;
        # a qr_pending report is never a conflict, so ok=True and conflict is False.
        assert r.json()["ok"] is True
        assert r.json().get("conflict") in (False, None)

        # A's QR slot carries the code we just reported…
        assert await redis_client.get(f"wa:qr:{BIZ_A}") == fake_qr
        # …and NOBODY else's slot ever received A's code.
        assert await redis_client.get(f"wa:qr:{BIZ_B}") != fake_qr
        assert await redis_client.get(f"wa:qr:{REAL_BIZ}") != fake_qr

        # The status write landed on A's row only (tenant-scoped upsert).
        async with tenant_connection(gw_pool, BIZ_A) as conn:
            wa = await conn.fetchrow(
                "SELECT status FROM whatsapp_connections WHERE business_id = $1",
                BIZ_A,
            )
        assert wa is not None and wa["status"] == "qr_pending"
    finally:
        # Drop the fake QR and restore A's connections row exactly as snapped.
        await redis_client.delete(f"wa:qr:{BIZ_A}")
        async with tenant_connection(gw_pool, BIZ_A) as conn:
            if snap is None:
                await conn.execute(
                    "DELETE FROM whatsapp_connections WHERE business_id = $1", BIZ_A
                )
            else:
                await conn.execute(
                    "UPDATE whatsapp_connections SET gateway_account_id = $2, "
                    "phone_number = $3, status = $4, last_connected_at = $5 "
                    "WHERE business_id = $1",
                    BIZ_A, snap["gateway_account_id"], snap["phone_number"],
                    snap["status"], snap["last_connected_at"],
                )


async def test_qr_connected_report_clears_the_qr(http, gw_pool, redis_client):
    """Once a business reports 'connected' its stale QR is wiped from Redis.

    Run on B (a pretend business), with B's connections row snapshotted and
    restored so the live gateway's view of B is unchanged afterwards.
    """
    fake_qr = f"data:image/png;base64,M6BWALL{secrets.token_hex(12)}"
    async with tenant_connection(gw_pool, BIZ_B) as conn:
        snap = await conn.fetchrow(
            "SELECT gateway_account_id, phone_number, status, last_connected_at "
            "FROM whatsapp_connections WHERE business_id = $1",
            BIZ_B,
        )
    try:
        r1 = await http.post(
            f"/internal/wa/status/{BIZ_B}", headers=GOOD_HDR,
            json={"status": "qr_pending", "qr_data_url": fake_qr},
        )
        assert r1.status_code == 200
        assert await redis_client.get(f"wa:qr:{BIZ_B}") == fake_qr

        r2 = await http.post(
            f"/internal/wa/status/{BIZ_B}", headers=GOOD_HDR,
            json={"status": "connected"},
        )
        assert r2.status_code == 200
        assert await redis_client.get(f"wa:qr:{BIZ_B}") is None  # wiped
    finally:
        await redis_client.delete(f"wa:qr:{BIZ_B}")
        async with tenant_connection(gw_pool, BIZ_B) as conn:
            if snap is None:
                await conn.execute(
                    "DELETE FROM whatsapp_connections WHERE business_id = $1", BIZ_B
                )
            else:
                await conn.execute(
                    "UPDATE whatsapp_connections SET gateway_account_id = $2, "
                    "phone_number = $3, status = $4, last_connected_at = $5 "
                    "WHERE business_id = $1",
                    BIZ_B, snap["gateway_account_id"], snap["phone_number"],
                    snap["status"], snap["last_connected_at"],
                )
