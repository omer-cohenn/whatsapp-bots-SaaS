"""Infra clients + reachability probes for Postgres and Redis.

Minimal for M0+M1: a lazily-created asyncpg pool and a redis.asyncio client,
held on app state for the process lifetime, plus `ping_*` helpers that the
/healthz endpoint uses to actually prove each dependency is reachable.

No secret is ever logged here; DSNs live only in the SecretStr settings.
"""

from __future__ import annotations

import asyncpg
import redis.asyncio as aioredis

from app.core.config import Settings


# --- Postgres -------------------------------------------------------------

async def create_pg_pool(settings: Settings) -> asyncpg.Pool:
    """Create a small asyncpg pool for the (non-service) app role.

    Kept tiny for the minimal build; the real pool sizing comes with the
    request-scoped tenant session work (roadmap 0.3).
    """

    return await asyncpg.create_pool(
        dsn=settings.database_url.get_secret_value(),
        min_size=1,
        max_size=5,
        command_timeout=5,
        timeout=5,  # connection acquisition timeout (seconds)
    )


async def ping_postgres(pool: asyncpg.Pool) -> None:
    """Raise if Postgres is not reachable. `SELECT 1` round-trip."""

    async with pool.acquire() as conn:
        await conn.execute("SELECT 1;")


# --- Redis ----------------------------------------------------------------

def create_redis(settings: Settings) -> aioredis.Redis:
    """Create an async Redis client (connection is established lazily)."""

    return aioredis.from_url(
        settings.redis_url.get_secret_value(),
        socket_connect_timeout=5,
        socket_timeout=5,
        decode_responses=True,
    )


async def ping_redis(client: aioredis.Redis) -> None:
    """Raise if Redis is not reachable. PING round-trip."""

    await client.ping()
