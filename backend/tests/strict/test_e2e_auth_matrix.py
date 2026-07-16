"""E2E — the full AUTH MATRIX, strict pytest (the CI pre-production gate).

One suite that walks the app's four auth groups end-to-end against the REAL
ASGI app (`app.main.app`) over httpx ASGITransport, with the real lifespan open
(so Redis + Postgres pools + every dependency run for real — no mocks). It proves
the front door is shaped exactly as the route inventory documents it:

  1. SESSION-GATED /api/*  — representative routes (/api/me, /api/dashboard,
     /api/leads) → 401 with NO cookie, 200 with an INJECTED valid session.
  2. ADMIN /api/admin/*    — /api/admin/overview → 401 (no session),
     403 (a NON-admin session), 200 (an admin session; email in ADMIN_EMAILS).
  3. TOKEN /webhook + /internal/wa/*  — POST /webhook/whatsapp and
     GET /internal/wa/sessions → 401 with no/wrong X-Gateway-Token, success
     (200) with the RIGHT token (read from settings like the other suites).
  4. PUBLIC booking by slug — the REAL customer flow against a seeded business:
     GET services → GET availability/slots → POST a booking → cancel with the
     returned cancel_token; a WRONG cancel_token is rejected (404).

This is a regression net for the security-hardening pass: if any group's gate
drifts (a protected route goes public, admin gate weakens, the token stops
gating, or the public cancel stops checking the token), a test here goes red.

Reuses the seeded pretend tenants (Avi/Bella). The user's REAL business is never
touched. Every booking/lead row we create is is_test and cleaned up. The admin
identity is resolved from the REAL users(id) for ADMIN_EMAIL (created if absent)
so no FK is faked. Nothing prints/asserts a secret, a token, or PII text.
"""

from __future__ import annotations

import json
import os
import secrets
import time

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.db.session import tenant_connection
from app.main import app
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

# Reuse the proven M11 booking set-up helpers (plain functions, not fixtures — so
# importing them registers NO fixtures and can't collide with ours below).
from _m11_helpers import (
    _ALL_DAYS_9_17,
    _make_service,
    _real_future_date,
    _set_settings,
)

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (PUBLISHED in seed)
AVI_USER = "google-sub-avi"

# The admin identity. ADMIN_EMAILS in infra/.env includes oyc3333@gmail.com. We
# resolve the REAL users(id) for it so an admin session is honest (see admin_user).
ADMIN_EMAIL = "oyc3333@gmail.com"
ADMIN_USER_ID_FALLBACK = "google-sub-e2e-admin"
NONADMIN_EMAIL = "avi@example.com"

GATEWAY_TOKEN = get_settings().gateway_api_token.get_secret_value()
GOOD_HDR = {"X-Gateway-Token": GATEWAY_TOKEN}
BAD_HDR = {"X-Gateway-Token": "totally-wrong"}

# Representative session-gated GET routes (a stranger must be bounced from all).
SESSION_GET_ROUTES = ["/api/me", "/api/dashboard", "/api/leads"]

# An unmapped gateway account: the webhook accepts the token then answers 200
# {"status": "no business"} — proving the TOKEN gate opened without needing to
# set up (or mutate) any real business↔account mapping.
UNMAPPED_ACCOUNT = "e2e-acct-nobody"


# --- fixtures ---------------------------------------------------------------


def _superuser_dsn() -> str:
    """SUPERUSER DSN from POSTGRES_* — used ONLY to resolve/insert the admin user
    row (users has no app_role INSERT here). Never stands in for the app's RLS."""
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
async def admin_user():
    """Resolve the REAL users(id) for ADMIN_EMAIL, yielding it as the admin sub.

    users.email is UNIQUE; we reuse the real operator's row id if it exists, else
    create a synthetic one (never deleted — other state may reference it). This
    keeps the admin session honest so the gate is exercised for real.
    """
    su = await asyncpg.connect(dsn=_superuser_dsn())
    try:
        existing = await su.fetchval("SELECT id FROM users WHERE email = $1", ADMIN_EMAIL)
        if existing is None:
            await su.execute(
                "INSERT INTO users (id, email, name) VALUES ($1, $2, 'E2E Admin')",
                ADMIN_USER_ID_FALLBACK,
                ADMIN_EMAIL,
            )
            existing = ADMIN_USER_ID_FALLBACK
    finally:
        await su.close()
    yield str(existing)


@pytest_asyncio.fixture
async def cleanup_booking(pool, redis):
    """Remove any booking/lead rows + rate-limit keys the public flow created."""
    yield
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute(
            "DELETE FROM bookings WHERE business_id = $1 AND is_test = true", BIZ_A
        )
        # The public HTTP path creates its lead is_test=false (no test flag on the
        # route); booking leads use lead_name='פגישה'. Clean BOTH so the M2 wall
        # sees a pristine slate afterwards.
        await conn.execute(
            "DELETE FROM leads WHERE business_id = $1 "
            "AND (is_test = true OR lead_name = 'פגישה')",
            BIZ_A,
        )
        await conn.execute("DELETE FROM services WHERE business_id = $1", BIZ_A)
        await conn.execute("DELETE FROM booking_settings WHERE business_id = $1", BIZ_A)
    keys = await redis.keys("ratelimit:book:*")
    if keys:
        await redis.delete(*keys)


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


def _webhook_body(account_id: str, text: str) -> dict:
    return {
        "gateway_account_id": account_id,
        "from": "+972500000001",
        "push_name": "Owner",
        "message_id": f"e2e-{secrets.token_hex(6)}",
        "timestamp": 1_700_000_000,
        "type": "text",
        "text": text,
        "raw": {"note": "synthetic e2e test"},
        "self_test": True,
        "conversation_id": f"self:{secrets.token_hex(6)}",
    }


# ============================================================================
#  GROUP 1 — SESSION-GATED /api/*  (deny-by-default; a real session opens it)
# ============================================================================


@pytest.mark.asyncio
async def test_session_routes_401_without_cookie(http):
    """No session cookie → every representative /api/* route is 401."""
    for route in SESSION_GET_ROUTES:
        resp = await http.get(route)
        assert resp.status_code == 401, f"{route} should be 401 with no cookie"


@pytest.mark.asyncio
async def test_session_routes_401_with_forged_cookie(http):
    """A random opaque id matches no Redis session → still 401 (not a 500/200)."""
    forged = secrets.token_urlsafe(32)
    http.cookies.set(SESSION_COOKIE_NAME, forged)
    for route in SESSION_GET_ROUTES:
        resp = await http.get(route)
        assert resp.status_code == 401, f"{route} should reject a forged cookie"
    http.cookies.clear()


@pytest.mark.asyncio
async def test_session_routes_200_with_valid_session(http, redis):
    """A real injected Avi session → every representative /api/* route is 200."""
    sid = await _login(redis, http, AVI_USER, NONADMIN_EMAIL, BIZ_A)
    try:
        for route in SESSION_GET_ROUTES:
            resp = await http.get(route)
            assert resp.status_code == 200, f"{route} should be 200 for a valid session"
        # /api/me resolves to the session's OWN tenant (no cross-tenant bleed).
        me = (await http.get("/api/me")).json()
        assert me["business"]["id"] == BIZ_A
        assert me["is_admin"] is False
    finally:
        await _logout(redis, http, sid)


# ============================================================================
#  GROUP 2 — ADMIN /api/admin/*  (401 no session → 403 non-admin → 200 admin)
# ============================================================================


@pytest.mark.asyncio
async def test_admin_overview_401_without_session(http):
    """No session → /api/admin/overview is 401 (before any admin check runs)."""
    assert (await http.get("/api/admin/overview")).status_code == 401


@pytest.mark.asyncio
async def test_admin_overview_403_for_nonadmin(http, redis):
    """An authed NON-admin (Avi, not on ADMIN_EMAILS) → 403 (forbidden, not 401)."""
    sid = await _login(redis, http, AVI_USER, NONADMIN_EMAIL, BIZ_A)
    try:
        assert (await http.get("/api/admin/overview")).status_code == 403
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_admin_overview_200_for_admin(http, redis, admin_user):
    """An admin session (email in ADMIN_EMAILS) → 200 on the back-office overview."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        resp = await http.get("/api/admin/overview")
        assert resp.status_code == 200, resp.text
        assert "total_businesses" in resp.json()
    finally:
        await _logout(redis, http, sid)


# ============================================================================
#  GROUP 3 — TOKEN routes  (X-Gateway-Token gates the webhook + internal API)
# ============================================================================


@pytest.mark.asyncio
async def test_webhook_401_without_or_wrong_token(http):
    """POST /webhook/whatsapp → 401 with a missing OR a wrong token."""
    body = _webhook_body(UNMAPPED_ACCOUNT, "היי")
    missing = await http.post("/webhook/whatsapp", json=body)
    wrong = await http.post("/webhook/whatsapp", json=body, headers=BAD_HDR)
    assert missing.status_code == 401
    assert wrong.status_code == 401


@pytest.mark.asyncio
async def test_webhook_200_with_right_token(http):
    """The RIGHT token opens the webhook: an unmapped account → 200 'no business'
    (the token gate passed; no crash, no business work leaks)."""
    resp = await http.post(
        "/webhook/whatsapp", json=_webhook_body(UNMAPPED_ACCOUNT, "היי"), headers=GOOD_HDR
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "no business"


@pytest.mark.asyncio
async def test_internal_sessions_401_without_or_wrong_token(http):
    """GET /internal/wa/sessions → 401 with a missing OR a wrong token."""
    assert (await http.get("/internal/wa/sessions")).status_code == 401
    assert (await http.get("/internal/wa/sessions", headers=BAD_HDR)).status_code == 401


@pytest.mark.asyncio
async def test_internal_sessions_200_with_right_token(http):
    """The RIGHT token → 200 and the frozen {"sessions": [...]} shape only."""
    resp = await http.get("/internal/wa/sessions", headers=GOOD_HDR)
    assert resp.status_code == 200, resp.text
    assert set(resp.json().keys()) == {"sessions"}


# ============================================================================
#  GROUP 4 — PUBLIC booking by slug  (the full customer flow, token on cancel)
# ============================================================================


@pytest.mark.asyncio
async def test_public_booking_full_flow_and_cancel_token(http, pool, cleanup_booking):
    """End-to-end public booking: read services → read slots → create → cancel with
    the returned cancel_token; a WRONG cancel_token is rejected (404).

    Driven against Avi (a seeded, provisioned business) after giving it an open
    all-week grid + one service. If the seed ever ships without a resolvable
    business the flow would 404 at services — but Avi is provisioned in seed.sql,
    so this is the real path, not a skip.
    """
    date = _real_future_date()
    await _set_settings(pool, BIZ_A, working_hours={**_ALL_DAYS_9_17}, min_notice=0)
    # _set_settings' UPSERT only sets the slug on INSERT; if Avi already had a
    # booking_settings row the stored slug is unchanged. Read the ACTUAL stored
    # slug (the one resolve_slug will match) rather than the generated candidate.
    async with tenant_connection(pool, BIZ_A) as conn:
        slug = await conn.fetchval(
            "SELECT slug FROM booking_settings WHERE business_id = $1", BIZ_A
        )
    assert slug, "Avi must have a resolvable booking slug"
    svc = await _make_service(pool, BIZ_A, duration=60)

    # (a) PUBLIC READ — services page resolves the tenant from the slug (200).
    services = await http.get(f"/api/book/{slug}/services")
    assert services.status_code == 200, services.text
    assert any(s["id"] == svc for s in services.json()["services"])

    # (b) PUBLIC READ — availability + concrete slots for the chosen day.
    avail = await http.get(
        f"/api/book/{slug}/availability",
        params={"service_id": svc, "from": date, "to": date},
    )
    assert avail.status_code == 200, avail.text
    slots = await http.get(
        f"/api/book/{slug}/slots", params={"service_id": svc, "date": date}
    )
    assert slots.status_code == 200, slots.text
    assert "09:00" in slots.json()["slots"]

    # (c) PUBLIC CREATE — a real booking; capture the unguessable cancel_token.
    created = await http.post(
        f"/api/book/{slug}",
        json={
            "service_id": svc,
            "date": date,
            "time": "09:00",
            "name": "בודק אוטומטי",
            "phone": "+972500000009",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    cancel_token = body["cancel_token"]
    booking_id = body["booking_id"]
    assert cancel_token and booking_id

    # Mark the rows is_test so the cleanup fixture reaps them.
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", booking_id)
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_A)

    # (d) NEGATIVE — a WRONG cancel_token is not this page's → 404 (no row touched).
    wrong = await http.post(
        f"/api/book/{slug}/cancel/not-the-real-token-{secrets.token_urlsafe(6)}"
    )
    assert wrong.status_code == 404

    # (e) POSITIVE — the RIGHT cancel_token cancels the booking (200).
    ok = await http.post(f"/api/book/{slug}/cancel/{cancel_token}")
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_public_booking_unknown_slug_404(http):
    """An unprovisioned slug never resolves a tenant → 404 (no cross-tenant leak)."""
    bogus = "e2e-no-such-page-" + secrets.token_urlsafe(6)
    assert (await http.get(f"/api/book/{bogus}/services")).status_code == 404
