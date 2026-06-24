"""M11 narrated — shared constants + helpers + the fake calendar + narration.

This module is NOT run directly. The thin runner m11_full_test.py imports the
check() narration, the session/settings/service helpers, the date helpers, the
fake Google calendar, and tally(). Splitting them out keeps the runner under 500
lines WITHOUT changing a single byte of printed output — the runner keeps the
whole main() flow and reads the final counts via tally().

Nothing here prints a secret, a token, or a customer's personal details.
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

_passed = 0
_failed = 0


def check(name: str, why: str, ok: bool) -> None:
    global _passed, _failed
    print(f"\n🧪 {name}")
    print(f"   💡 {why}")
    if ok:
        _passed += 1
        print("   ✅ PASS")
    else:
        _failed += 1
        print("   ❌ FAIL")


async def _login(rds, http, user_id: str, business_id: str) -> None:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": "x@example.com", "name": "x", "picture": "",
        "business_id": business_id, "business_name": "x", "created_at": int(time.time()),
    }
    await rds.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)


async def _set_settings(pool, bid, *, working_hours, min_notice=0, buffer=0,
                        max_days=365, meet=False) -> str:
    slug = "demo-" + secrets.token_urlsafe(6)
    async with tenant_connection(pool, bid) as conn:
        await conn.execute(
            """INSERT INTO booking_settings
                 (business_id, working_hours, min_notice_minutes, buffer_minutes,
                  max_days_ahead, meet_enabled, slug)
               VALUES ($1,$2::jsonb,$3,$4,$5,$6,$7)
               ON CONFLICT (business_id) DO UPDATE SET
                 working_hours=EXCLUDED.working_hours,
                 min_notice_minutes=EXCLUDED.min_notice_minutes,
                 buffer_minutes=EXCLUDED.buffer_minutes,
                 max_days_ahead=EXCLUDED.max_days_ahead,
                 meet_enabled=EXCLUDED.meet_enabled""",
            bid, json.dumps(working_hours), min_notice, buffer, max_days, meet, slug)
    return slug


async def _make_service(pool, bid, *, name="ייעוץ", duration=30) -> str:
    async with tenant_connection(pool, bid) as conn:
        return str(await conn.fetchval(
            "INSERT INTO services (business_id,name,duration_minutes,active) "
            "VALUES ($1,$2,$3,true) RETURNING id", bid, name, duration))


def _real_future(weekday=2, days=9) -> str:
    """A local date at least `days` ahead, on a chosen weekday (Wed=2)."""
    d = (datetime.now(JLM) + timedelta(days=days)).date()
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d.isoformat()


def _wd(date_str) -> str:
    return str((datetime.fromisoformat(date_str).weekday() + 1) % 7)


def _superuser_dsn() -> str | None:
    """Build the DB SUPERUSER DSN from env (for the negative control ONLY).

    The app itself connects as the least-privileged app_role, which CANNOT toggle
    RLS — that's the wall. The negative control needs a privileged connection to
    deliberately break + restore the wall. We derive it from POSTGRES_USER /
    POSTGRES_PASSWORD (the compose superuser), reusing DATABASE_URL's host/db.
    Returns None if not available (then the control degrades to an assertion that
    the app role can't bypass)."""
    user = os.environ.get("POSTGRES_USER")
    pwd = os.environ.get("POSTGRES_PASSWORD")
    if not user or not pwd:
        return None
    base = os.environ["DATABASE_URL"]
    # host:port/db is everything after the '@' in the app DSN.
    tail = base.split("@", 1)[1] if "@" in base else "postgres:5432/bizzup"
    return f"postgresql://{user}:{pwd}@{tail}"


class _FakeCalendar:
    """A pretend Google Calendar that records the calls (no real network)."""
    last: "_FakeCalendar | None" = None

    def __init__(self, refresh_token):
        self.refresh_token = refresh_token
        self.created = []
        _FakeCalendar.last = self

    def create_event(self, body, *, with_meet):
        self.created.append((body, with_meet))
        ev = {"id": "evt-" + secrets.token_hex(3)}
        if with_meet:
            ev["hangoutLink"] = "https://meet.google.com/demo-link"
        return ev

    def patch_event(self, event_id, body):
        return {"id": event_id}

    def delete_event(self, event_id):
        pass


def tally() -> tuple[int, int]:
    """The (passed, failed) counts after main() runs — read by the runner's scoreboard."""
    return _passed, _failed
