"""M3 — the auth gate + session, strict pytest (the CI version).

Runs IN-PROCESS against the real ASGI app (`app.main.app`) via httpx
ASGITransport, so the app's own lifespan opens the real Redis + Postgres
pools and every dependency (the deny-by-default `/api` gate, `load_session`,
`provision_owner`) is exercised for real — no mocks, no fakes.

These tests are the hard gate: if any goes red, either a logged-out stranger
can reach a protected route, or a session that should be dead is still alive,
or signup stopped being idempotent. The build must fail.

We connect to the SAME Redis the app uses (REDIS_URL), so a session we write
under `session:{sid}` is the exact session the app's `current_session`
dependency reads back. Nothing here prints a secret or PII.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from contextlib import asynccontextmanager

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.auth import (
    SESSION_COOKIE_NAME,
    _SESSION_KEY_PREFIX,
    _STATE_KEY_PREFIX,
)

# Avi's seeded business (supabase/seed.sql). Same fixed id the M2 wall uses.
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
AVI_USER = "google-sub-avi"


# --- shared lifespan-managed client ----------------------------------------

@asynccontextmanager
async def _lifespan_app():
    """Run the app's real lifespan (opens app.state.redis + pg_pool)."""
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def client():
    """An httpx client wired straight to the ASGI app, lifespan running."""
    async with _lifespan_app():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def redis_client():
    client = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    yield client
    await client.aclose()


def _avi_session_payload() -> dict:
    """A session blob shaped EXACTLY like services.auth.create_session writes."""
    return {
        "user_id": AVI_USER,
        "email": "avi@example.com",
        "name": "Avi",
        "picture": "",
        "business_id": BIZ_A,
        "business_name": "Avi Insurance",
        "created_at": int(time.time()),
    }


async def _inject_session(redis: aioredis.Redis, payload: dict) -> str:
    """Write a real session into Redis and return its opaque id (cookie value)."""
    sid = secrets.token_urlsafe(32)
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    return sid


# --- the gate: public vs protected -----------------------------------------

async def test_healthz_is_public(client):
    """/healthz must stay reachable with no cookie (it gates nothing)."""
    resp = await client.get("/healthz")
    assert resp.status_code == 200


async def test_api_me_no_cookie_is_401(client):
    """Deny-by-default: no session cookie → /api/me is 401."""
    resp = await client.get("/api/me")
    assert resp.status_code == 401


async def test_api_me_forged_cookie_is_401(client):
    """A random/forged opaque id matches no Redis session → 401."""
    forged = secrets.token_urlsafe(32)
    resp = await client.get("/api/me", cookies={SESSION_COOKIE_NAME: forged})
    assert resp.status_code == 401


# --- a valid session resolves to its OWN tenant ----------------------------

async def test_api_me_valid_session_returns_own_business(client, redis_client):
    """A real Avi session → 200 and /api/me reports Avi's business id only."""
    sid = await _inject_session(redis_client, _avi_session_payload())
    try:
        resp = await client.get("/api/me", cookies={SESSION_COOKIE_NAME: sid})
        assert resp.status_code == 200
        body = resp.json()
        # Frozen contract shape.
        assert set(body) == {"user", "business", "connection"}
        assert body["business"]["id"] == BIZ_A
        assert body["user"]["id"] == AVI_USER
        assert "status" in body["connection"]
    finally:
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid}")


# --- logout truly destroys the session -------------------------------------

async def test_logout_destroys_session(client, redis_client):
    """POST /auth/logout → 204, and the same cookie is 401 afterwards."""
    sid = await _inject_session(redis_client, _avi_session_payload())
    try:
        # Sanity: the session works before logout.
        ok = await client.get("/api/me", cookies={SESSION_COOKIE_NAME: sid})
        assert ok.status_code == 200

        bye = await client.post("/auth/logout", cookies={SESSION_COOKIE_NAME: sid})
        assert bye.status_code == 204

        # The server-side blob is gone → the cookie is now worthless.
        assert await redis_client.get(f"{_SESSION_KEY_PREFIX}{sid}") is None
        dead = await client.get("/api/me", cookies={SESSION_COOKIE_NAME: sid})
        assert dead.status_code == 401
    finally:
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid}")


# --- /auth/google starts a real OAuth round-trip ---------------------------

async def test_auth_google_redirects_and_stores_state(client, redis_client):
    """/auth/google → 302/307 to Google AND a single-use state lands in Redis."""
    before = set(await redis_client.keys(f"{_STATE_KEY_PREFIX}*"))
    resp = await client.get("/auth/google", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"].startswith("https://accounts.google.com/")

    after = set(await redis_client.keys(f"{_STATE_KEY_PREFIX}*"))
    new_states = after - before
    assert len(new_states) >= 1  # a fresh CSRF state was persisted
    # Clean up the state(s) we created so we don't leave litter.
    for key in new_states:
        await redis_client.delete(key)


# --- provision_owner is idempotent (the signup safety net) -----------------

async def test_provision_owner_is_idempotent():
    """Two calls for a brand-new user → SAME business + exactly ONE membership."""
    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=2)
    # A throwaway user id that cannot collide with the seeds.
    test_user = f"test-prov-{secrets.token_hex(8)}"
    try:
        async with pool.acquire() as conn:
            biz1 = await conn.fetchval(
                "SELECT provision_owner($1,$2,$3,$4,$5)",
                test_user, f"{test_user}@example.com", "Test User", "", "",
            )
            biz2 = await conn.fetchval(
                "SELECT provision_owner($1,$2,$3,$4,$5)",
                test_user, f"{test_user}@example.com", "Test User", "", "",
            )
            assert biz1 is not None
            assert str(biz1) == str(biz2)  # idempotent: same business back

            # get_user_businesses is SECURITY DEFINER + scoped to this user, so it
            # is the right lens to count memberships (a plain app_role SELECT on
            # business_members sees 0 rows here — no tenant context set — which is
            # the RLS deny-by-default working, not a missing membership).
            rows = await conn.fetch("SELECT * FROM get_user_businesses($1)", test_user)
            assert len(rows) == 1  # exactly one owner membership, no duplicate
            assert str(rows[0]["business_id"]) == str(biz1)
            assert rows[0]["role"] == "owner"
    finally:
        await pool.close()
        # Clean up the throwaway rows. app_role has NO delete grant on
        # businesses/business_members (RLS + least-privilege), so the cleanup
        # MUST run as the superuser — exactly the role that seeding/admin uses.
        # The superuser creds come from POSTGRES_* (present via the env_file).
        su_dsn = (
            f"postgresql://{os.environ['POSTGRES_USER']}:"
            f"{os.environ['POSTGRES_PASSWORD']}@postgres:5432/"
            f"{os.environ['POSTGRES_DB']}"
        )
        su = await asyncpg.connect(dsn=su_dsn)
        try:
            biz_ids = await su.fetch(
                "SELECT business_id FROM business_members WHERE user_id = $1", test_user
            )
            await su.execute("DELETE FROM business_members WHERE user_id = $1", test_user)
            for r in biz_ids:
                await su.execute("DELETE FROM businesses WHERE id = $1", r["business_id"])
            await su.execute("DELETE FROM users WHERE id = $1", test_user)
        finally:
            await su.close()
