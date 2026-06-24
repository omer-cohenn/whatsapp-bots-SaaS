"""M11.1 narrated — shared DB/session/seeding helpers for the story runner.

This module is NOT run directly. The thin runner m11_1_full_test.py imports
these helpers (session login, settings seeding, date math, the fake-Gemini seam,
service creation). Splitting them out keeps the runner under 500 lines WITHOUT
changing a single byte of printed output — all narration + the checks stay in
the runner. Nothing here prints a secret, a token, or a customer's details.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.db.session import tenant_connection
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"
JLM = ZoneInfo("Asia/Jerusalem")

_ALL_DAYS_9_17 = {str(k): [{"s": "09:00", "e": "17:00"}] for k in range(7)}


async def _login(rds, http, user_id: str, business_id: str) -> None:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": "x@example.com", "name": "x", "picture": "",
        "business_id": business_id, "business_name": "x", "created_at": int(time.time()),
    }
    await rds.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)


def _logout(http) -> None:
    http.cookies.clear()


async def _set_settings(pool, bid, *, working_hours, min_notice=0, buffer=0,
                        max_days=365) -> str:
    # The slug is server-owned and only set on the FIRST insert; on a conflict we
    # keep the existing slug (mirrors update_settings). We RETURN the row's live
    # slug so the caller always gets the one that actually resolves the page.
    slug = "demo-" + secrets.token_urlsafe(6)
    async with tenant_connection(pool, bid) as conn:
        live = await conn.fetchval(
            """INSERT INTO booking_settings
                 (business_id, working_hours, min_notice_minutes, buffer_minutes,
                  max_days_ahead, meet_enabled, slug)
               VALUES ($1,$2::jsonb,$3,$4,$5,false,$6)
               ON CONFLICT (business_id) DO UPDATE SET
                 working_hours=EXCLUDED.working_hours,
                 min_notice_minutes=EXCLUDED.min_notice_minutes,
                 buffer_minutes=EXCLUDED.buffer_minutes,
                 max_days_ahead=EXCLUDED.max_days_ahead
               RETURNING slug""",
            bid, json.dumps(working_hours), min_notice, buffer, max_days, slug)
    return live


def _real_future(weekday=2, days=9) -> str:
    """A local date at least `days` ahead, on a chosen weekday (Wed=2)."""
    d = (datetime.now(JLM) + timedelta(days=days)).date()
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d.isoformat()


def _wd(date_str) -> str:
    return str((datetime.fromisoformat(date_str).weekday() + 1) % 7)


def _superuser_dsn() -> str | None:
    """Build the DB SUPERUSER DSN from env (for the negative control ONLY)."""
    user = os.environ.get("POSTGRES_USER")
    pwd = os.environ.get("POSTGRES_PASSWORD")
    if not user or not pwd:
        return None
    base = os.environ["DATABASE_URL"]
    tail = base.split("@", 1)[1] if "@" in base else "postgres:5432/bizzup"
    return f"postgresql://{user}:{pwd}@{tail}"


# A pretend Gemini client (no key, no network) — the documented test seam.
class _FakeResp:
    def __init__(self, text): self.text = text


class _FakeModels:
    def __init__(self, text): self._text = text
    async def generate_content(self, **_): return _FakeResp(self._text)


class _FakeAio:
    def __init__(self, text): self.models = _FakeModels(text)


class _FakeClient:
    def __init__(self, text): self.aio = _FakeAio(text)


# --- small service-creation helpers -----------------------------------------

async def _make_service_http(http, rds, business_id, *, duration) -> str:
    user = AVI_USER if business_id == BIZ_A else BELLA_USER
    await _login(rds, http, user, business_id)
    r = await http.post("/api/services", json={"name": "svc", "duration_minutes": duration})
    return r.json()["id"]


async def _make_service_direct(pool, business_id, *, name, duration,
                               description=None, price=None) -> str:
    async with tenant_connection(pool, business_id) as conn:
        return str(await conn.fetchval(
            "INSERT INTO services (business_id,name,duration_minutes,active,"
            "description,price) VALUES ($1,$2,$3,true,$4,$5) RETURNING id",
            business_id, name, duration, description, price))
