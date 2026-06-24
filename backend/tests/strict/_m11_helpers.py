"""Shared fixtures + helpers for the M11 strict pytest suite (split across files).

This module is NOT a test file — it carries the common constants, fixtures and
helpers the M11 test modules import:

  * test_m11_slots.py      — SLOT ALGORITHM + RULES (compute_slots, direct)
  * test_m11_booking.py    — PUBLIC BOOKING + GUARDS + CANCEL/RESCHEDULE
  * test_m11_isolation.py  — TENANT ISOLATION (incl. C4)
  * test_m11_google.py     — GOOGLE (MOCK): hook params, Meet, graceful failure

It is imported as a top-level module (pytest puts tests/strict/ on sys.path).
Fixtures imported by name into a test module register with pytest as usual, so
the behavior is byte-for-byte identical to the original single-file test_m11.py.

Per decision 0011. Every persisted row is is_test=true; the cleanup fixture
deletes the test bookings/leads/services/settings/credentials and Redis keys it
created. Nothing prints a secret, a token, or PII.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import asyncpg
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import booking as booking_service
from app.services import google_calendar
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

JLM = ZoneInfo("Asia/Jerusalem")

# A FIXED "now" far in the future on a quiet weekday so notice/max-days math is
# deterministic and the test never collides with a real-clock boundary. We pick a
# Wednesday (2099-06-10) at 06:00 UTC (= 09:00 local in summer DST).
FIXED_NOW = datetime(2099, 6, 10, 6, 0, tzinfo=timezone.utc)


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
async def google_hook(pool):
    """Register the real Google-calendar sync hook against the TEST pool.

    The hook is normally wired in the app lifespan (main.py). The Google-direct
    tests don't spin up the lifespan, so they register it here against their own
    pool; the calendar client itself is still the injected fake. Unregistered on
    teardown so it can't leak into another test."""
    google_calendar.register(pool)
    yield
    booking_service.register_google_hook(None)


@pytest_asyncio.fixture
async def cleanup(pool, rds):
    """After each test: delete every is_test booking + lead and any settings /
    services / google_credentials we touched, plus rate-limit Redis keys.

    We always reset the Google hook + calendar factory + any in-DB google creds so
    one test's mock can never leak into the next.
    """
    yield
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute(
                "DELETE FROM bookings WHERE business_id = $1 AND is_test = true", bid)
            # Booking-created leads use lead_name='פגישה'. The PUBLIC HTTP path
            # always creates them is_test=false (the route has no test flag), so we
            # must clean BOTH is_test leads AND those booking leads to leave a
            # pristine slate for the M2 wall (which expects no stray rows).
            await conn.execute(
                "DELETE FROM leads WHERE business_id = $1 "
                "AND (is_test = true OR lead_name = 'פגישה')", bid)
            await conn.execute("DELETE FROM services WHERE business_id = $1", bid)
            await conn.execute("DELETE FROM booking_settings WHERE business_id = $1", bid)
            await conn.execute("DELETE FROM google_credentials WHERE business_id = $1", bid)
    # Reset the Google seam so the real client + no hook side effects remain.
    google_calendar.set_calendar_client_factory(None)
    # Clear rate-limit buckets created by public POSTs.
    keys = await rds.keys("ratelimit:book:*")
    if keys:
        await rds.delete(*keys)


# --- helpers ----------------------------------------------------------------

async def _login(rds, http, user_id: str, business_id: str) -> None:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": f"{user_id}@example.com", "name": user_id,
        "picture": "", "business_id": business_id, "business_name": "x",
        "created_at": int(time.time()),
    }
    await rds.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)


async def _set_settings(pool, business_id: str, *, working_hours: dict,
                        min_notice=120, buffer=0, max_days=365, meet=False) -> str:
    """UPSERT booking_settings for a tenant with a fresh slug; return the slug."""
    slug = "t-" + secrets.token_urlsafe(8)
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            """
            INSERT INTO booking_settings
                (business_id, working_hours, min_notice_minutes, buffer_minutes,
                 max_days_ahead, meet_enabled, slug)
            VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7)
            ON CONFLICT (business_id) DO UPDATE SET
                working_hours = EXCLUDED.working_hours,
                min_notice_minutes = EXCLUDED.min_notice_minutes,
                buffer_minutes = EXCLUDED.buffer_minutes,
                max_days_ahead = EXCLUDED.max_days_ahead,
                meet_enabled = EXCLUDED.meet_enabled
            """,
            business_id, json.dumps(working_hours), min_notice, buffer, max_days,
            meet, slug,
        )
    return slug


async def _make_service(pool, business_id: str, *, name="ייעוץ",
                        duration=30, active=True) -> str:
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO services (business_id, name, duration_minutes, active)
            VALUES ($1, $2, $3, $4) RETURNING id
            """,
            business_id, name, duration, active,
        )
    return str(row["id"])


def _future_date(days_from_now: int, weekday_local: int | None = None) -> str:
    """A local YYYY-MM-DD `days_from_now` after FIXED_NOW (optionally a weekday).

    weekday_local uses Python Mon=0..Sun=6 if given (we step forward to it).
    Used ONLY by pure compute_slots(now=FIXED_NOW) tests, where the date math is
    anchored to the SAME injected FIXED_NOW so it's fully deterministic.
    """
    d = (FIXED_NOW.astimezone(JLM) + timedelta(days=days_from_now)).date()
    if weekday_local is not None:
        while d.weekday() != weekday_local:
            d += timedelta(days=1)
    return d.isoformat()


def _real_future_date(min_days_ahead: int = 7, weekday_local: int = 2) -> str:
    """A local YYYY-MM-DD at least `min_days_ahead` after the REAL clock, on a given
    weekday (Python Mon=0..Sun=6; default Wed=2).

    The HTTP / create_public_booking paths call compute_slots WITHOUT an injected
    `now`, so they use the real server clock. These tests must pick a date relative
    to REAL now (with generous max_days_ahead) so the slot survives notice/max-days.
    """
    d = (datetime.now(JLM) + timedelta(days=min_days_ahead)).date()
    while d.weekday() != weekday_local:
        d += timedelta(days=1)
    return d.isoformat()


def _wd_key(date_str: str) -> str:
    """Our working_hours weekday key (Sun=0..Sat=6) for a YYYY-MM-DD date."""
    return str((datetime.fromisoformat(date_str).weekday() + 1) % 7)


# Every weekday 09:00–17:00 — used by the HTTP / create-path tests so a real-clock
# future date always lands on an OPEN day regardless of which weekday it is.
_ALL_DAYS_9_17 = {str(k): [{"s": "09:00", "e": "17:00"}] for k in range(7)}
