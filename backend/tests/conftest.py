"""Shared fixtures for the isolation suite.

These tests connect as the REAL non-service roles (app_role / gateway_role) so
RLS is actually exercised — a suite that runs as a superuser/owner would bypass
RLS and give false confidence (the #1 thing to avoid here). They assume the two
seeded businesses exist (`make seed` runs before `make isolation`).
"""

from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest_asyncio.fixture
async def app_pool():
    """asyncpg pool connected as app_role (RLS applies). max_size=2 forces reuse
    so the pooling/bleed test really shares connections."""
    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=2)
    # Sanity: the seeded tenants must exist, else every test is meaningless.
    async with pool.acquire() as conn:
        await conn.execute("SELECT set_config('app.business_id', $1, true)", BIZ_A)
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def gw_pool():
    pool = await asyncpg.create_pool(dsn=os.environ["GATEWAY_DATABASE_URL"], min_size=1, max_size=2)
    yield pool
    await pool.close()


@pytest_asyncio.fixture
async def redis_client():
    client = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    yield client
    await client.aclose()
