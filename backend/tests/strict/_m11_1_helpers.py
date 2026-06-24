"""Shared fixtures + helpers for the M11.1 strict suite (split across files).

This module is NOT a test file — it carries the common constants, fixtures and
helpers the two M11.1 test modules import:

  * test_m11_1_services.py      — SERVICES round-trip + SETTINGS welcome + AVAILABILITY
  * test_m11_1_ai_isolation.py  — AI WELCOME (mocked Gemini) + TENANT ISOLATION

It is imported as a top-level module (pytest puts tests/strict/ on sys.path).
Fixtures imported by name into a test module register with pytest as usual, so
the behavior is byte-for-byte identical to the original single-file test_m11_1.py.

Per decision 0012. It drives the welcome generator through its monkeypatched
Gemini seam (no key, no network) exactly like test_bot_builder.py. Every
persisted row is cleaned up after each test. Nothing prints a secret or PII.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import booking_welcome
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"

JLM = ZoneInfo("Asia/Jerusalem")

# Every weekday 09:00-17:00, so a real-clock future date always lands open.
_ALL_DAYS_9_17 = {str(k): [{"s": "09:00", "e": "17:00"}] for k in range(7)}


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
async def cleanup(pool, rds):
    """After each test: wipe the booking rows we touched, so the M2 wall stays
    pristine and tests never bleed into each other."""
    yield
    for bid in (BIZ_A, BIZ_B):
        async with tenant_connection(pool, bid) as conn:
            await conn.execute("DELETE FROM bookings WHERE business_id = $1", bid)
            await conn.execute(
                "DELETE FROM leads WHERE business_id = $1 "
                "AND (is_test = true OR lead_name = 'פגישה')", bid)
            await conn.execute("DELETE FROM services WHERE business_id = $1", bid)
            await conn.execute("DELETE FROM booking_settings WHERE business_id = $1", bid)
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


def _logout(http) -> None:
    http.cookies.clear()


async def _seed_settings(pool, business_id: str, *, working_hours: dict,
                         min_notice=120, buffer=0, max_days=365) -> str:
    """UPSERT booking_settings (fresh slug); return the slug."""
    slug = "t-" + secrets.token_urlsafe(8)
    async with tenant_connection(pool, business_id) as conn:
        # slug is server-owned (only set on first insert); RETURN the live slug so
        # the caller always uses the one that actually resolves the public page.
        live = await conn.fetchval(
            """
            INSERT INTO booking_settings
                (business_id, working_hours, min_notice_minutes, buffer_minutes,
                 max_days_ahead, meet_enabled, slug)
            VALUES ($1, $2::jsonb, $3, $4, $5, false, $6)
            ON CONFLICT (business_id) DO UPDATE SET
                working_hours = EXCLUDED.working_hours,
                min_notice_minutes = EXCLUDED.min_notice_minutes,
                buffer_minutes = EXCLUDED.buffer_minutes,
                max_days_ahead = EXCLUDED.max_days_ahead
            RETURNING slug
            """,
            business_id, json.dumps(working_hours), min_notice, buffer, max_days, slug,
        )
    return live


def _wd_key(date_str: str) -> str:
    return str((datetime.fromisoformat(date_str).weekday() + 1) % 7)


def _real_future_date(min_days_ahead: int = 7, weekday_local: int = 2) -> str:
    d = (datetime.now(JLM) + timedelta(days=min_days_ahead)).date()
    while d.weekday() != weekday_local:
        d += timedelta(days=1)
    return d.isoformat()


# --- the fake Gemini client (same seam as test_bot_builder) ------------------

class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModels:
    def __init__(self, reply_text: str) -> None:
        self._reply_text = reply_text

    async def generate_content(self, **_kwargs):  # noqa: ANN003
        return _FakeResp(self._reply_text)


class _FakeAio:
    def __init__(self, reply_text: str) -> None:
        self.models = _FakeModels(reply_text)


class _FakeClient:
    def __init__(self, reply_text: str) -> None:
        self.aio = _FakeAio(reply_text)


def _patch_welcome_gemini(monkeypatch, reply_text: str) -> None:
    monkeypatch.setattr(
        booking_welcome, "get_gemini_client", lambda: _FakeClient(reply_text)
    )


# --- service-creation helpers (HTTP for owner-path, direct for B-tenant) ------

async def _make_service_http(http, rds, pool, business_id, *, duration) -> str:
    """Create a service via the owner HTTP path (logs in as that tenant's owner)."""
    user = AVI_USER if business_id == BIZ_A else BELLA_USER
    await _login(rds, http, user, business_id)
    r = await http.post("/api/services", json={
        "name": "svc", "duration_minutes": duration})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _make_service_direct(pool, business_id, *, name, duration,
                               description=None, price=None) -> str:
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO services (business_id, name, duration_minutes, active,
                                  description, price)
            VALUES ($1, $2, $3, true, $4, $5) RETURNING id
            """,
            business_id, name, duration, description, price)
    return str(row["id"])
