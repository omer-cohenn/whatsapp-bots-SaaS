"""Tenant-scoped DB sessions — the backend half of the RLS contract.

The wall only works if two things hold on EVERY tenant query:
  1. We connect as a NON-service role (app_role / gateway_role) so RLS applies.
     (The old system used a service key that bypassed RLS — the core bug.)
  2. We set the per-request business id as a TRANSACTION-LOCAL value, in the
     SAME transaction as the query, and never leak it to the next request on a
     pooled connection.

`tenant_connection()` enforces (2): it opens a transaction, sets
`app.business_id` with `set_config(..., is_local => true)` (the parameterized,
transaction-scoped form of `SET LOCAL`), and the value vanishes when the
transaction ends — so a recycled pooled connection starts clean. RLS reads the
value back via `current_business_id()` (migration 0002).

⚠️ Pooler note (deferred to the AWS phase): with an external pooler (PgBouncer)
this is only safe in *transaction* mode. We use asyncpg's own pool here, where a
connection is held for the whole transaction, so the guarantee holds locally.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg


@asynccontextmanager
async def tenant_connection(
    pool: asyncpg.Pool, business_id: str
) -> AsyncIterator[asyncpg.Connection]:
    """Yield a connection bound to `business_id` for the life of one transaction.

    Usage:
        async with tenant_connection(pool, business_id) as conn:
            rows = await conn.fetch("SELECT * FROM leads")   # RLS-scoped to the tenant

    The caller MUST pass an already-verified business id (verified against
    `business_members` for the authenticated user) — never a raw client value.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # set_config(key, value, is_local=true) == SET LOCAL but parameterized,
            # so the uuid is bound safely (no string interpolation into SQL).
            await conn.execute(
                "SELECT set_config('app.business_id', $1, true)", str(business_id)
            )
            yield conn
        # On exit the transaction ends and the LOCAL setting is discarded; the
        # connection returns to the pool with no tenant context attached.
