"""The multi-tenant isolation suite — the hard CI gate for M2.

Every test connects as a NON-service role. If any of these goes red, a tenant
can see another tenant's data (or the crown jewel), and the build must fail.
"""

from __future__ import annotations

import asyncio

import asyncpg
import pytest

from app.core.crypto import DecryptionError, decrypt_pii, encrypt_pii, phone_hash
from app.db.session import tenant_connection
from app.services import live_chat
from app.services.live_chat import CrossTenantCacheError
from tests.conftest import BIZ_A, BIZ_B


async def _seed_lead(pool, business_id, name):
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute("DELETE FROM leads WHERE is_test = true")
        await conn.execute(
            "INSERT INTO leads (business_id, contact_name, status, is_test) "
            "VALUES ($1,$2,'new',true)", business_id, encrypt_pii(name))


# --- DB / RLS ----------------------------------------------------------------

async def test_tenant_sees_only_its_own_rows(app_pool):
    await _seed_lead(app_pool, BIZ_A, "Dana")
    await _seed_lead(app_pool, BIZ_B, "Yossi")
    async with tenant_connection(app_pool, BIZ_A) as conn:
        rows = await conn.fetch("SELECT contact_name FROM leads")
    assert len(rows) == 1
    assert decrypt_pii(rows[0]["contact_name"]) == "Dana"


async def test_cannot_read_other_tenant_even_with_explicit_filter(app_pool):
    await _seed_lead(app_pool, BIZ_B, "Yossi")
    async with tenant_connection(app_pool, BIZ_A) as conn:
        rows = await conn.fetch("SELECT * FROM leads WHERE business_id = $1", BIZ_B)
    assert rows == []


async def test_with_check_blocks_cross_tenant_insert(app_pool):
    with pytest.raises(asyncpg.PostgresError):
        async with tenant_connection(app_pool, BIZ_A) as conn:
            await conn.execute(
                "INSERT INTO leads (business_id, status, is_test) "
                "VALUES ($1,'new',true)", BIZ_B)


async def test_no_session_var_returns_zero_rows(app_pool):
    # No tenant_connection → app.business_id unset → deny-by-default.
    async with app_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM leads")
    assert rows == []


async def test_app_role_denied_on_crown_jewel(app_pool):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with tenant_connection(app_pool, BIZ_A) as conn:
            await conn.fetch("SELECT auth_state FROM whatsapp_credentials")


# --- Encryption (fail-loud) --------------------------------------------------

async def test_decrypt_wrong_key_raises_not_returns_ciphertext():
    from cryptography.fernet import Fernet
    token = Fernet(Fernet.generate_key()).encrypt(b"secret").decode()
    with pytest.raises(DecryptionError):
        decrypt_pii(token)


# --- Pooling / concurrency (the top risk) ------------------------------------

async def test_no_business_id_bleed_across_pooled_connections(app_pool):
    """Interleave many A and B requests on a 2-connection pool; each must see
    ONLY its own tenant. A leak here = the SET-vs-SET-LOCAL pooling bug."""
    await _seed_lead(app_pool, BIZ_A, "Dana")
    await _seed_lead(app_pool, BIZ_B, "Yossi")

    async def who_do_i_see(business_id, expected_name):
        for _ in range(10):
            async with tenant_connection(app_pool, business_id) as conn:
                rows = await conn.fetch("SELECT contact_name FROM leads")
                assert len(rows) == 1
                assert decrypt_pii(rows[0]["contact_name"]) == expected_name
            await asyncio.sleep(0)  # yield → force interleaving on the shared pool

    await asyncio.gather(
        who_do_i_see(BIZ_A, "Dana"),
        who_do_i_see(BIZ_B, "Yossi"),
        who_do_i_see(BIZ_A, "Dana"),
        who_do_i_see(BIZ_B, "Yossi"),
    )


# --- Redis cache isolation (no RLS → app-layer guard) ------------------------

async def test_redis_rejects_cross_tenant_key(redis_client):
    ph = phone_hash("052-222-2222")
    await live_chat.set_status(redis_client, BIZ_B, ph, "human")
    # A claiming B's key is rejected by the guard...
    with pytest.raises(CrossTenantCacheError):
        live_chat._assert_owns(BIZ_A, f"chat:{BIZ_B}:{ph}")
    # ...and A's honest accessor never sees B's chat.
    a_view = await live_chat.get_chat(redis_client, BIZ_A, ph)
    assert a_view["status"] is None
