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


# --- M4: bot_settings + bot_builder_messages isolation (same RLS contract) ----
# These run as the NON-service app_role (RLS applies), so they prove the M4
# tables are walled exactly like leads. The seed gives each tenant its own
# bot_settings row (Avi: 'quote'/'talk_to_human'; Bella: 'appointment'/...).


async def test_bot_settings_tenant_sees_only_its_own_row(app_pool):
    """Avi sees exactly ONE bot_settings row, and it is Avi's (flow 'quote')."""
    async with tenant_connection(app_pool, BIZ_A) as conn:
        rows = await conn.fetch("SELECT lead_steps FROM bot_settings")
    assert len(rows) == 1
    # lead_steps is a jsonb OBJECT keyed by flow name (contract §2).
    flows = rows[0]["lead_steps"]
    flows = flows if isinstance(flows, dict) else __import__("json").loads(flows)
    assert "quote" in flows  # Avi's seeded flow, never Bella's 'appointment'
    assert "appointment" not in flows


async def test_bot_settings_cannot_read_other_tenant_even_with_filter(app_pool):
    """Avi explicitly asking for Bella's bot_settings row gets ZERO rows."""
    async with tenant_connection(app_pool, BIZ_A) as conn:
        rows = await conn.fetch(
            "SELECT * FROM bot_settings WHERE business_id = $1", BIZ_B
        )
    assert rows == []


async def test_bot_settings_with_check_blocks_cross_tenant_insert(app_pool):
    """Avi cannot UPDATE Bella's bot_settings (RLS hides her row → 0 updated).

    bot_settings has UNIQUE(business_id), so a cross-tenant INSERT would also be
    blocked by WITH CHECK; the cleanest non-destructive probe is to confirm Avi's
    UPDATE of Bella's row affects nothing (her row is invisible to Avi).
    """
    async with tenant_connection(app_pool, BIZ_A) as conn:
        status = await conn.execute(
            "UPDATE bot_settings SET is_published = true WHERE business_id = $1",
            BIZ_B,
        )
    # asyncpg returns e.g. "UPDATE 0" — Avi changed none of Bella's rows.
    assert status.endswith(" 0")


async def test_bot_settings_no_session_var_returns_zero_rows(app_pool):
    """No tenant context set → bot_settings reads nothing (deny-by-default)."""
    async with app_pool.acquire() as conn:  # no tenant_connection → app.business_id unset
        rows = await conn.fetch("SELECT * FROM bot_settings")
    assert rows == []


async def test_bot_builder_messages_are_tenant_isolated(app_pool):
    """A build-chat row written under B is invisible to A (and vice-versa).

    We write one message as Bella, then prove Avi can neither see it by listing
    nor by explicitly filtering on Bella's id. Cleaned up at the end as Bella.
    """
    marker = "isolation-probe-do-not-keep"
    # Write a build-chat row under Bella's tenant (author = Bella's seeded user).
    async with tenant_connection(app_pool, BIZ_B) as conn:
        await conn.execute(
            "INSERT INTO bot_builder_messages (business_id, author_user_id, role, content) "
            "VALUES ($1, $2, 'user', $3)",
            BIZ_B, "google-sub-bella", marker,
        )
    try:
        # Avi lists his own build-chat: Bella's probe must NOT appear.
        async with tenant_connection(app_pool, BIZ_A) as conn:
            a_rows = await conn.fetch(
                "SELECT content FROM bot_builder_messages"
            )
            a_filtered = await conn.fetch(
                "SELECT content FROM bot_builder_messages WHERE business_id = $1",
                BIZ_B,
            )
        assert all(r["content"] != marker for r in a_rows)
        assert a_filtered == []  # explicit cross-tenant filter still yields nothing

        # Bella DOES see her own probe (the wall blocks others, not yourself).
        async with tenant_connection(app_pool, BIZ_B) as conn:
            b_rows = await conn.fetch(
                "SELECT content FROM bot_builder_messages WHERE content = $1", marker
            )
        assert len(b_rows) == 1
    finally:
        # Clean the probe up under Bella's own tenant (app_role has DELETE grant).
        async with tenant_connection(app_pool, BIZ_B) as conn:
            await conn.execute(
                "DELETE FROM bot_builder_messages WHERE content = $1", marker
            )


async def test_bot_builder_messages_with_check_blocks_cross_tenant_insert(app_pool):
    """Avi cannot plant a build-chat row labelled as Bella's (WITH CHECK rejects)."""
    with pytest.raises(asyncpg.PostgresError):
        async with tenant_connection(app_pool, BIZ_A) as conn:
            await conn.execute(
                "INSERT INTO bot_builder_messages (business_id, role, content) "
                "VALUES ($1, 'user', 'poison')",
                BIZ_B,
            )


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
