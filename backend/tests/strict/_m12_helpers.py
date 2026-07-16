"""Shared fixtures + helpers for the M12 strict pytest suite (split across files).

This module is NOT a test file — it carries the common constants, fixtures and
out-of-band seeding helpers the M12 test modules import:

  * test_m12_gate_overview.py  — GATE (session + admin allow-list) + OVERVIEW
  * test_m12_businesses.py      — LIST + DETAIL + SET SUBSCRIPTION (audit, validation)
  * test_m12_suspend_usage.py   — SUSPEND ENFORCEMENT (webhook goes silent) + USAGE
  * test_m12_isolation.py       — zero-grant table isolation + RLS + neg control + NO-PII

It is imported as a top-level module (pytest puts tests/strict/ on sys.path).
Fixtures imported by name into a test module register with pytest as usual, so
the behavior is byte-for-byte identical to the original single-file test_m12.py.

Authoritative contract: docs/decisions/0016-m12-back-office.md.

Privileged set-up + verification of the zero-grant tables (subscriptions,
admin_audit) is done over a SUPERUSER DSN built from POSTGRES_* (present in the
backend container) — the app itself only ever reaches them through the SD
functions. Everything we create is cleaned up. Nothing prints/asserts a secret.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import date

import asyncpg
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import whatsapp as whatsapp_service
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (PUBLISHED in seed)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (DRAFT in seed)

# The admin identity. ADMIN_EMAILS in infra/.env includes oyc3333@gmail.com.
# admin_set_subscription stamps the audit row with the session user_id (a Google
# sub that MUST exist in users(id) for the FK) + email. The `admin_user` fixture
# resolves the REAL users(id) for this email (creating one if absent) so the audit
# FK is satisfied honestly — and yields it as the admin session user_id.
ADMIN_EMAIL = "oyc3333@gmail.com"
# Fallback synthetic id used ONLY if no user with ADMIN_EMAIL exists yet.
ADMIN_USER_ID_FALLBACK = "google-sub-m12-admin"

# A non-admin owner (Avi) — email NOT on ADMIN_EMAILS.
AVI_USER = "google-sub-avi"
NONADMIN_EMAIL = "avi@example.com"

# Gateway account mappings for the suspend-enforcement webhook drive.
ACC_A = "m12-acct-avi"
OWN_PHONE = "+972500000001"

# The full set of /api/admin/* routes, used by the gate tests so a NEW route
# can't silently skip the gate.
ADMIN_GET_ROUTES = [
    "/api/admin/overview",
    "/api/admin/businesses",
    f"/api/admin/businesses/{BIZ_A}",
    f"/api/admin/businesses/{BIZ_A}/usage",
    "/api/admin/plans",
]


# --- fixtures ---------------------------------------------------------------


def _superuser_dsn() -> str:
    """Build the SUPERUSER DSN from POSTGRES_* (present in the backend container).

    The app role can NOT read subscriptions/admin_audit (zero direct grant). The
    test needs to seed + verify + clean those tables, so it uses the superuser
    connection ONLY for that out-of-band bookkeeping — never to stand in for the
    app's own RLS-scoped path.
    """
    user = os.environ["POSTGRES_USER"]
    pw = os.environ["POSTGRES_PASSWORD"]
    db = os.environ["POSTGRES_DB"]
    return f"postgresql://{user}:{pw}@postgres:5432/{db}"


@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=4)
    try:
        yield p
    finally:
        await p.close()


@pytest_asyncio.fixture
async def su():
    """A superuser pool for privileged set-up/verify/cleanup of zero-grant tables."""
    p = await asyncpg.create_pool(dsn=_superuser_dsn(), min_size=1, max_size=2)
    try:
        yield p
    finally:
        await p.close()


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
async def redis(lifespan_app):
    # Reuse the app's own redis client (created in the lifespan).
    return lifespan_app.state.redis


@pytest_asyncio.fixture
async def admin_user(su):
    """Resolve the REAL users(id) for ADMIN_EMAIL, yielding it as the admin sub.

    The admin's session user_id is stamped into admin_audit.admin_user_id, which
    REFERENCES users(id). users.email is UNIQUE, so we look up the existing row by
    email (the real operator's login) and reuse its id; only if none exists do we
    create a synthetic one. Yields the id so tests mint a session that the audit FK
    can honor. We never delete the user (other state may reference it).
    """
    async with su.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM users WHERE email = $1", ADMIN_EMAIL
        )
        if existing is None:
            await conn.execute(
                "INSERT INTO users (id, email, name) VALUES ($1, $2, 'M12 Admin')",
                ADMIN_USER_ID_FALLBACK,
                ADMIN_EMAIL,
            )
            existing = ADMIN_USER_ID_FALLBACK
    yield str(existing)


@pytest_asyncio.fixture
async def clean_admin_state(su):
    """Reset subscriptions + admin_audit for our test businesses after each test.

    These tables have NO app_role grant; we clean them as the superuser. This
    keeps OVERVIEW counts deterministic across tests and removes audit rows we
    wrote. We also restore is_active=true on both businesses.
    """
    yield
    async with su.acquire() as conn:
        await conn.execute(
            "DELETE FROM subscriptions WHERE business_id = ANY($1::uuid[])",
            [BIZ_A, BIZ_B],
        )
        await conn.execute(
            "DELETE FROM admin_audit WHERE target_business_id = ANY($1::uuid[])",
            [BIZ_A, BIZ_B],
        )
        await conn.execute(
            "UPDATE businesses SET is_active = true WHERE id = ANY($1::uuid[])",
            [BIZ_A, BIZ_B],
        )


@pytest_asyncio.fixture
async def mapped(pool):
    """Map Avi (published) ↔ ACC_A for the suspend-enforcement webhook drive."""
    await whatsapp_service.upsert_connection(
        pool, BIZ_A, gateway_account_id=ACC_A, phone=OWN_PHONE, status="connected"
    )
    yield


# --- helpers ----------------------------------------------------------------


async def _login(redis, http, user_id: str, email: str, business_id: str) -> str:
    """Mint an opaque Redis session + set the cookie, like a logged-in owner."""
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id,
        "email": email,
        "name": user_id,
        "picture": "",
        "business_id": business_id,
        "business_name": "x",
        "created_at": int(time.time()),
    }
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)
    return sid


async def _logout(redis, http, sid: str) -> None:
    await redis.delete(f"{_SESSION_KEY_PREFIX}{sid}")
    http.cookies.clear()


def _webhook_body(account_id: str, text: str, conv: str) -> dict:
    return {
        "gateway_account_id": account_id,
        "from": OWN_PHONE,
        "push_name": "Owner",
        "message_id": f"m12-{secrets.token_hex(6)}",
        "timestamp": 1_700_000_000,
        "type": "text",
        "text": text,
        "raw": {"note": "synthetic m12 test"},
        "self_test": True,
        "conversation_id": conv,
    }


async def _set_sub_via_su(su, business_id: str, plan: str, status_value: str) -> None:
    """Seed a subscription + sync is_active out-of-band (superuser), for OVERVIEW
    fixtures that should NOT depend on the API write path under test."""
    is_active = status_value == "active"
    async with su.acquire() as conn:
        await conn.execute(
            "INSERT INTO subscriptions (business_id, plan_code, status) "
            "VALUES ($1, $2, $3) "
            "ON CONFLICT ON CONSTRAINT subscriptions_pkey DO UPDATE "
            "SET plan_code = EXCLUDED.plan_code, status = EXCLUDED.status",
            business_id,
            plan,
            status_value,
        )
        await conn.execute(
            "UPDATE businesses SET is_active = $2 WHERE id = $1",
            business_id,
            is_active,
        )


def _today_iso() -> str:
    return date.today().isoformat()
