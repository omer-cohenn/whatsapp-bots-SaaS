"""Shared fixtures + helpers for the M13 strict pytest suite (split across files).

This module is NOT a test file — it carries the common constants, fixtures and
out-of-band seeding helpers that the four M13 test modules import:

  * test_m13_analytics.py     — GATE + ANALYTICS aggregates reconcile with DB
  * test_m13_overview_ltv.py  — LTV estimate/summary + AI_CALL bump + SNAPSHOT
  * test_m13_crm.py           — CRM stage move + audit + note round-trip
  * test_m13_isolation.py     — zero-grant table isolation + RLS + NO-PII

It is imported as a top-level module (pytest puts tests/strict/ on sys.path).
Fixtures imported by name into a test module register with pytest as usual, so
the behavior is byte-for-byte identical to the original single-file test_m13.py.

Authoritative contract: docs/decisions/0017-m13-backoffice-analytics-crm.md.

Privileged set-up + verification of the zero-grant tables (subscriptions,
business_crm, crm_notes, platform_snapshots, admin_audit) uses a SUPERUSER DSN
built from POSTGRES_* (present in the backend container) — the app itself only
ever reaches them through the SD functions. Everything we create is cleaned up.
Nothing prints/asserts a secret or end-customer PII.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import date

import asyncpg
import pytest_asyncio

from app.db.session import tenant_connection
from app.main import app
from app.services import usage as usage_service
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (PUBLISHED in seed)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (DRAFT in seed)
UNKNOWN_BIZ = "cccccccc-cccc-cccc-cccc-cccccccccccc"  # matches no business

# The admin identity. ADMIN_EMAILS in infra/.env.local includes oyc3333@gmail.com.
# CRM writers stamp admin_audit.admin_user_id + crm_notes.admin_user_id, which
# REFERENCE users(id). users.email is UNIQUE, so the admin_user fixture resolves
# the REAL users(id) for this email (creating one only if absent) so the FKs are
# honored honestly — and yields it as the admin session user_id.
ADMIN_EMAIL = "oyc3333@gmail.com"
ADMIN_USER_ID_FALLBACK = "google-sub-m13-admin"

# A non-admin owner (Avi) — email NOT on ADMIN_EMAILS.
AVI_USER = "google-sub-avi"
NONADMIN_EMAIL = "avi@example.com"

# Plan catalog prices (migration 0015): free=0, basic=49, pro=149.
PRICE_BASIC = 49.0
PRICE_PRO = 149.0

# Every NEW M13 GET route, so a NEW route can't silently skip the gate. The PATCH
# stage + POST note are checked separately (they have bodies).
M13_GET_ROUTES = [
    "/api/admin/analytics/leads-by-type",
    "/api/admin/analytics/messages",
    "/api/admin/analytics/ai-ops",
    "/api/admin/analytics/by-plan?metric=ai_call",
    "/api/admin/analytics/trends",
    "/api/admin/crm",
    f"/api/admin/businesses/{BIZ_A}/crm/notes",
]


# --- fixtures ---------------------------------------------------------------


def _superuser_dsn() -> str:
    """Build the SUPERUSER DSN from POSTGRES_* (present in the backend container).

    The app role canNOT read the operator-only tables (subscriptions, business_crm,
    crm_notes, platform_snapshots, admin_audit — zero direct grant). The test needs
    to seed + verify + clean those tables, so it uses the superuser connection ONLY
    for that out-of-band bookkeeping — never to stand in for the app's own RLS path.
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
    """A superuser pool for privileged set-up/verify/cleanup of the zero-grant tables."""
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
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=lifespan_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def redis(lifespan_app):
    return lifespan_app.state.redis


@pytest_asyncio.fixture
async def admin_user(su):
    """Resolve the REAL users(id) for ADMIN_EMAIL, yielding it as the admin sub.

    The admin's session user_id is stamped into admin_audit.admin_user_id +
    crm_notes.admin_user_id, both REFERENCING users(id). We look up the existing row
    by email (the real operator's login) and reuse its id; only if none exists do we
    create a synthetic one. We never delete the user (other state may reference it).
    """
    async with su.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT id FROM users WHERE email = $1", ADMIN_EMAIL
        )
        if existing is None:
            await conn.execute(
                "INSERT INTO users (id, email, name) VALUES ($1, $2, 'M13 Admin')",
                ADMIN_USER_ID_FALLBACK,
                ADMIN_EMAIL,
            )
            existing = ADMIN_USER_ID_FALLBACK
    yield str(existing)


@pytest_asyncio.fixture
async def clean_m13(su):
    """Reset all M13 + seed state our tests touch (zero-grant + tenant tables).

    Runs BEFORE (clean slate) and AFTER (tidy up) each test that uses it, so every
    analytics assertion measures a known delta. We delete the CRM/notes/snapshot/
    audit/subscription rows AND the synthetic leads/bookings/flow_events/usage rows
    we mark with our test sentinels, then restore is_active=true on both businesses.
    """
    await _wipe(su)
    yield
    await _wipe(su)


async def _wipe(su) -> None:
    async with su.acquire() as conn:
        ids = [BIZ_A, BIZ_B]
        await conn.execute(
            "DELETE FROM crm_notes WHERE business_id = ANY($1::uuid[])", ids
        )
        await conn.execute(
            "DELETE FROM business_crm WHERE business_id = ANY($1::uuid[])", ids
        )
        await conn.execute(
            "DELETE FROM admin_audit WHERE target_business_id = ANY($1::uuid[])", ids
        )
        await conn.execute(
            "DELETE FROM subscriptions WHERE business_id = ANY($1::uuid[])", ids
        )
        # Synthetic analytics rows: identify them by our test sentinels so we never
        # touch real seed leads. flow_events first (FK to leads), then leads/bookings.
        await conn.execute(
            "DELETE FROM flow_events WHERE business_id = ANY($1::uuid[]) "
            "AND flow_key = 'm13-test'",
            ids,
        )
        await conn.execute(
            "DELETE FROM bookings WHERE business_id = ANY($1::uuid[]) "
            "AND cancel_token LIKE 'm13-%'",
            ids,
        )
        await conn.execute(
            "DELETE FROM leads WHERE business_id = ANY($1::uuid[]) "
            "AND lead_name IN ('m13-lead', 'פנייה לנציג')",
            ids,
        )
        # Reset the usage counters our tests bump (keep other days untouched: only
        # today's synthetic metrics matter, but a full reset for our two test
        # businesses keeps the deltas deterministic across re-runs).
        await conn.execute(
            "DELETE FROM usage_daily WHERE business_id = ANY($1::uuid[]) "
            "AND day = current_date "
            "AND metric IN ('msg_in', 'msg_out', 'ai_call', 'lead', 'booking')",
            ids,
        )
        await conn.execute(
            "UPDATE businesses SET is_active = true WHERE id = ANY($1::uuid[])", ids
        )


# --- session helpers --------------------------------------------------------


async def _login(redis, http, user_id: str, email: str, business_id: str) -> str:
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


def _today_iso() -> str:
    return date.today().isoformat()


# --- privileged seeding (out-of-band, superuser) ----------------------------


async def _set_sub(su, business_id: str, plan: str, status_value: str,
                   months_ago: int = 0) -> None:
    """Seed a subscription out-of-band, optionally backdating started_at by N months
    (so the LTV tenure-multiplier is exercised, not just the floor-of-1)."""
    is_active = status_value == "active"
    async with su.acquire() as conn:
        await conn.execute(
            "INSERT INTO subscriptions (business_id, plan_code, status, started_at) "
            "VALUES ($1, $2, $3, now() - ($4 || ' months')::interval) "
            "ON CONFLICT ON CONSTRAINT subscriptions_pkey DO UPDATE "
            "SET plan_code = EXCLUDED.plan_code, status = EXCLUDED.status, "
            "started_at = EXCLUDED.started_at",
            business_id, plan, status_value, str(months_ago),
        )
        await conn.execute(
            "UPDATE businesses SET is_active = $2 WHERE id = $1",
            business_id, is_active,
        )


async def _seed_lead(su, business_id: str, *, handoff: bool) -> str:
    """Insert ONE non-test lead today; if handoff, also write a handed_off event +
    name it 'פנייה לנציג' (mirrors bot_runtime). Returns the lead id."""
    async with su.acquire() as conn:
        lead_id = await conn.fetchval(
            "INSERT INTO leads (business_id, lead_name, status, is_test, started_at) "
            "VALUES ($1, $2, 'new', false, now()) RETURNING id",
            business_id,
            "פנייה לנציג" if handoff else "m13-lead",
        )
        if handoff:
            await conn.execute(
                "INSERT INTO flow_events (business_id, lead_id, flow_key, event, "
                "is_test, created_at) VALUES ($1, $2, 'm13-test', 'handed_off', "
                "false, now())",
                business_id, lead_id,
            )
    return str(lead_id)


async def _seed_booking(su, business_id: str) -> None:
    """Insert ONE non-test booking today, tagged with an 'm13-' cancel_token."""
    async with su.acquire() as conn:
        await conn.execute(
            "INSERT INTO bookings (business_id, scheduled_at, duration_minutes, "
            "status, cancel_token, is_test, created_at) "
            "VALUES ($1, now() + interval '1 day', 30, 'pending', $2, false, now())",
            business_id, f"m13-{secrets.token_hex(6)}",
        )


async def _bump(pool, business_id: str, metric: str, n: int) -> None:
    """Bump a usage_daily counter on the business's OWN tenant connection (RLS ok)."""
    async with tenant_connection(pool, business_id) as conn:
        await usage_service.bump(conn, business_id, metric, n)
