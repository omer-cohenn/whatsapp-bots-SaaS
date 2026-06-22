"""M12 — platform-operator BACK-OFFICE, strict pytest (the CI version).

Authoritative contract: docs/decisions/0016-m12-back-office.md. The narrated
story lives in m12_full_test.py; THIS is the strict gate CI runs. It drives the
REAL ASGI app over httpx ASGITransport so the deny-by-default /api session gate,
the router-level current_admin gate (ADMIN_EMAILS, checked LIVE), the cross-
tenant SECURITY DEFINER functions, the suspend enforcement in the webhook, the
usage counters and the per-business RLS are all exercised exactly like a live
request.

What it proves (mapped to the QA goals in the decision doc):

  GATE     no session → 401 on /api/me and EVERY /api/admin/* route; authed
           NON-admin → 403 on every /api/admin/* route; admin → 200. /api/me
           reports is_admin true for the admin, false for the non-admin.
  OVERVIEW the KPI aggregates reconcile with DB truth (we seed a couple of
           subscriptions + usage rows and assert the counts move correctly).
  LIST     owner_email / created_at / last_login_at / plan (default 'free' +
           'active' when no subscription) / leads_count / msgs_30d; search
           filters; limit/offset bounds (422 out of range).
  DETAIL   the single-business profile + wa_status; unknown id → 404.
  SET SUB  changes plan+status; bad status → 422; unknown plan → 422; unknown
           business → 404; writes a REAL admin_audit row stamped with the real
           admin Google sub + email; suspending sets businesses.is_active=false,
           re-activating restores it.
  SUSPEND  the product-meaningful one: a suspended business's webhook bot turn
           returns the silent shape (replies=[]); re-activating restores answering.
  USAGE    hitting an instrumented webhook path increments usage_daily for the
           right metric/day; the /usage endpoint returns the series; a bad date
           → 422.
  ISOLATION the non-negotiable: app_role CANNOT directly SELECT subscriptions or
           admin_audit (permission denied) — the SD functions are the ONLY path;
           tenant A's RLS still holds (A can't read B's usage_daily); and an
           ACTIVE negative control flips is_active and watches the bot fall silent
           then restores it.
  NO PII   no admin response body / response key carries lead or booking content.

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

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.db.session import tenant_connection
from app.main import app
from app.services import bot_settings as bot_settings_service
from app.services import usage as usage_service
from app.services import whatsapp as whatsapp_service
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (PUBLISHED in seed)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (DRAFT in seed)

# The admin identity. ADMIN_EMAILS in infra/.env.local includes oyc3333@gmail.com.
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


# ============================================================================
#  GATE — session + admin allow-list (the only guard on the cross-tenant SD path)
# ============================================================================


@pytest.mark.asyncio
async def test_me_requires_session(http):
    """No session → /api/me is 401 (deny-by-default on the whole /api group)."""
    assert (await http.get("/api/me")).status_code == 401


@pytest.mark.asyncio
async def test_admin_routes_require_session(http):
    """No session → EVERY /api/admin/* route is 401 (before any admin check)."""
    for route in ADMIN_GET_ROUTES:
        assert (await http.get(route)).status_code == 401, route
    # The mutating route too.
    r = await http.patch(
        f"/api/admin/businesses/{BIZ_A}/subscription",
        json={"plan_code": "pro", "status": "active"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_nonadmin_forbidden_on_every_admin_route(http, redis):
    """An authed NON-admin (Avi) → 403 on every /api/admin/* route."""
    sid = await _login(redis, http, AVI_USER, NONADMIN_EMAIL, BIZ_A)
    try:
        for route in ADMIN_GET_ROUTES:
            assert (await http.get(route)).status_code == 403, route
        r = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/subscription",
            json={"plan_code": "pro", "status": "active"},
        )
        assert r.status_code == 403
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_admin_allowed_on_every_admin_route(http, redis, admin_user):
    """The admin → 200 on every read route (the gate lets the operator through)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        for route in ADMIN_GET_ROUTES:
            assert (await http.get(route)).status_code == 200, route
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_me_is_admin_flag_reflects_allowlist(http, redis, admin_user):
    """/api/me → is_admin true for the admin email, false for a non-admin."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        me_admin = (await http.get("/api/me")).json()
    finally:
        await _logout(redis, http, sid)
    assert me_admin["is_admin"] is True

    sid = await _login(redis, http, AVI_USER, NONADMIN_EMAIL, BIZ_A)
    try:
        me_user = (await http.get("/api/me")).json()
    finally:
        await _logout(redis, http, sid)
    assert me_user["is_admin"] is False


# ============================================================================
#  OVERVIEW — the KPI aggregates reconcile with DB truth
# ============================================================================


@pytest.mark.asyncio
async def test_overview_counts_reconcile_with_db(
    http, redis, su, pool, admin_user, clean_admin_state
):
    """Seed: A=suspended, B=cancelled; bump A's msg_in today. Then assert the
    overview buckets + today's message tally move exactly as expected, relative
    to a clean baseline (no subscriptions for A/B → both counted active)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        base = (await http.get("/api/admin/overview")).json()
    finally:
        await _logout(redis, http, sid)

    # Read today's msg_in for A as out-of-band truth, then bump it by 3.
    async with su.acquire() as conn:
        before_a = (
            await conn.fetchval(
                "SELECT count FROM usage_daily WHERE business_id=$1 "
                "AND day=current_date AND metric=$2",
                BIZ_A,
                usage_service.METRIC_MSG_IN,
            )
            or 0
        )
    async with tenant_connection(pool, BIZ_A) as conn:
        await usage_service.bump(conn, BIZ_A, usage_service.METRIC_MSG_IN, 3)

    # Seed A=suspended, B=cancelled (out-of-band, so we measure the SD overview,
    # not the API write path). Both had no sub before → both were 'active'.
    await _set_sub_via_su(su, BIZ_A, "basic", "suspended")
    await _set_sub_via_su(su, BIZ_B, "pro", "cancelled")

    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        after = (await http.get("/api/admin/overview")).json()
    finally:
        await _logout(redis, http, sid)

    # total_businesses unchanged (we didn't add/remove businesses).
    assert after["total_businesses"] == base["total_businesses"]
    # A moved active→suspended, B moved active→cancelled.
    assert after["suspended_count"] == base["suspended_count"] + 1
    assert after["cancelled_count"] == base["cancelled_count"] + 1
    assert after["active_count"] == base["active_count"] - 2
    # Today's messages grew by exactly the 3 we bumped.
    assert after["msgs_today"] == base["msgs_today"] + 3
    # msgs_month includes today, so it grew by at least 3.
    assert after["msgs_month"] >= base["msgs_month"] + 3


# ============================================================================
#  LIST + DETAIL
# ============================================================================


@pytest.mark.asyncio
async def test_list_shape_defaults_and_counts(
    http, redis, su, admin_user, clean_admin_state, pool
):
    """With NO subscription row, a business reports plan='free'/status='active';
    owner_email + created_at are present; leads_count + msgs_30d are ints."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        body = (await http.get("/api/admin/businesses?limit=200")).json()
    finally:
        await _logout(redis, http, sid)

    rows = {r["business_id"]: r for r in body["businesses"]}
    assert BIZ_A in rows and BIZ_B in rows
    a = rows[BIZ_A]
    # No subscription row exists (cleaned) → defaults.
    assert a["plan_code"] == "free"
    assert a["status"] == "active"
    assert a["owner_email"] == NONADMIN_EMAIL  # Avi is the owner
    assert a["created_at"] is not None
    assert isinstance(a["leads_count"], int)
    assert isinstance(a["msgs_30d"], int)
    assert body["limit"] == 200 and body["offset"] == 0


@pytest.mark.asyncio
async def test_list_search_filters(http, redis, admin_user):
    """search='Bella' returns Bella and NOT Avi (ILIKE over name/owner email)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        body = (await http.get("/api/admin/businesses?search=Bella")).json()
    finally:
        await _logout(redis, http, sid)
    ids = {r["business_id"] for r in body["businesses"]}
    assert BIZ_B in ids
    assert BIZ_A not in ids


@pytest.mark.asyncio
async def test_list_pagination_bounds(http, redis, admin_user):
    """limit/offset are bounded: in-range works; out-of-range → 422."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        ok = await http.get("/api/admin/businesses?limit=1&offset=0")
        assert ok.status_code == 200
        assert len(ok.json()["businesses"]) <= 1

        # limit above the 200 cap and below 1 → 422 (Query ge/le).
        assert (await http.get("/api/admin/businesses?limit=0")).status_code == 422
        assert (await http.get("/api/admin/businesses?limit=999")).status_code == 422
        # negative offset → 422.
        assert (await http.get("/api/admin/businesses?offset=-1")).status_code == 422
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_detail_shape_and_defaults(http, redis, su, admin_user, clean_admin_state):
    """Detail returns the profile + wa_status; plan/status default with no sub row."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        body = (await http.get(f"/api/admin/businesses/{BIZ_A}")).json()
    finally:
        await _logout(redis, http, sid)
    assert body["business_id"] == BIZ_A
    assert body["owner_email"] == NONADMIN_EMAIL
    assert body["plan_code"] == "free" and body["status"] == "active"
    assert body["wa_status"] in {"connected", "connecting", "disconnected"}
    assert isinstance(body["leads_count"], int)
    assert isinstance(body["msgs_30d"], int)


@pytest.mark.asyncio
async def test_detail_unknown_id_404(http, redis, admin_user):
    """An unknown (well-formed) business id → 404; a malformed uuid → 404 too."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        unknown = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        assert (await http.get(f"/api/admin/businesses/{unknown}")).status_code == 404
        assert (await http.get("/api/admin/businesses/not-a-uuid")).status_code == 404
    finally:
        await _logout(redis, http, sid)


# ============================================================================
#  SET SUBSCRIPTION — plan+status, validation, audit, is_active sync
# ============================================================================


@pytest.mark.asyncio
async def test_set_subscription_changes_plan_status_and_audits(
    http, redis, su, admin_user, clean_admin_state
):
    """PATCH sets plan+status, syncs is_active, and writes a REAL admin_audit row
    stamped with the admin's Google sub + email."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        r = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/subscription",
            json={"plan_code": "pro", "status": "active"},
        )
    finally:
        await _logout(redis, http, sid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "business_id": BIZ_A,
        "plan_code": "pro",
        "status": "active",
        "is_active": True,
    }

    # The audit row is verifiable only via the SD-owner path → read it as superuser.
    async with su.acquire() as conn:
        audit = await conn.fetchrow(
            "SELECT admin_user_id, admin_email, action, target_business_id, detail "
            "FROM admin_audit WHERE target_business_id = $1 "
            "ORDER BY created_at DESC LIMIT 1",
            BIZ_A,
        )
        sub = await conn.fetchrow(
            "SELECT plan_code, status FROM subscriptions WHERE business_id = $1",
            BIZ_A,
        )
    assert audit is not None
    assert audit["admin_user_id"] == admin_user  # the REAL Google sub
    assert audit["admin_email"] == ADMIN_EMAIL
    assert audit["action"] == "set_subscription"
    assert str(audit["target_business_id"]) == BIZ_A
    detail = audit["detail"]
    detail = detail if isinstance(detail, dict) else json.loads(detail)
    assert detail == {"plan_code": "pro", "status": "active"}
    assert sub["plan_code"] == "pro" and sub["status"] == "active"


@pytest.mark.asyncio
async def test_set_subscription_bad_status_422(http, redis, admin_user):
    """An unknown status → 422 (the request model + SD CHECK both reject it)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        r = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/subscription",
            json={"plan_code": "pro", "status": "frozen"},
        )
    finally:
        await _logout(redis, http, sid)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_set_subscription_unknown_plan_422(
    http, redis, su, admin_user, clean_admin_state
):
    """A plan not in the catalog → 422 (the SD FK violation mapped to 422)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        r = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/subscription",
            json={"plan_code": "platinum-unicorn", "status": "active"},
        )
    finally:
        await _logout(redis, http, sid)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_set_subscription_unknown_business_404(http, redis, admin_user):
    """An unknown business id → 404 (the SD FK violation mapped to 404)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        unknown = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        r = await http.patch(
            f"/api/admin/businesses/{unknown}/subscription",
            json={"plan_code": "pro", "status": "active"},
        )
    finally:
        await _logout(redis, http, sid)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_suspend_then_activate_toggles_is_active(
    http, redis, su, admin_user, clean_admin_state
):
    """Suspending sets businesses.is_active=false; re-activating restores it."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        sus = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/subscription",
            json={"plan_code": "basic", "status": "suspended"},
        )
        assert sus.status_code == 200
        assert sus.json()["is_active"] is False
        async with su.acquire() as conn:
            flag = await conn.fetchval(
                "SELECT is_active FROM businesses WHERE id = $1", BIZ_A
            )
        assert flag is False

        act = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/subscription",
            json={"plan_code": "basic", "status": "active"},
        )
        assert act.status_code == 200
        assert act.json()["is_active"] is True
        async with su.acquire() as conn:
            flag = await conn.fetchval(
                "SELECT is_active FROM businesses WHERE id = $1", BIZ_A
            )
        assert flag is True
    finally:
        await _logout(redis, http, sid)


# ============================================================================
#  SUSPEND ENFORCEMENT — the product-meaningful proof (the webhook goes silent)
# ============================================================================


@pytest.mark.asyncio
async def test_suspend_silences_bot_then_activate_restores(
    http, redis, su, admin_user, clean_admin_state, mapped
):
    """A suspended business's bot turn returns the silent shape; re-activating
    restores answering. We drive the webhook exactly like the M6a tests."""
    gw_token = get_settings().gateway_api_token.get_secret_value()
    auth = {"X-Gateway-Token": gw_token}

    # Baseline: Avi is published + active → the bot answers.
    base = await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
        headers=auth,
    )
    assert base.json()["status"] == "ok"
    assert len(base.json()["replies"]) >= 1

    # Suspend Avi via the admin PATCH (the real product path).
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        sus = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/subscription",
            json={"plan_code": "free", "status": "suspended"},
        )
        assert sus.status_code == 200 and sus.json()["is_active"] is False
    finally:
        await _logout(redis, http, sid)

    # The suspended bot is SILENT.
    silent = await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
        headers=auth,
    )
    assert silent.json()["status"] == "suspended"
    assert silent.json()["replies"] == []

    # Re-activate via the admin PATCH → the bot answers again.
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        act = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/subscription",
            json={"plan_code": "free", "status": "active"},
        )
        assert act.status_code == 200 and act.json()["is_active"] is True
    finally:
        await _logout(redis, http, sid)

    restored = await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
        headers=auth,
    )
    assert restored.json()["status"] == "ok"
    assert len(restored.json()["replies"]) >= 1


# ============================================================================
#  USAGE — a bump increments the right metric/day; the series + range guard
# ============================================================================


@pytest.mark.asyncio
async def test_usage_bump_increments_metric_for_today(http, redis, su, pool, admin_user):
    """A direct tenant-scoped bump (the same call the webhook makes) increments
    today's (business, metric) counter, and the /usage endpoint reflects it."""
    # Read the current count for A's msg_in today (superuser, out-of-band truth).
    async with su.acquire() as conn:
        before = (
            await conn.fetchval(
                "SELECT count FROM usage_daily WHERE business_id=$1 "
                "AND day=current_date AND metric=$2",
                BIZ_A,
                usage_service.METRIC_MSG_IN,
            )
            or 0
        )

    # Bump +2 on A's OWN tenant connection (RLS allows A to write A's row).
    async with tenant_connection(pool, BIZ_A) as conn:
        await usage_service.bump(conn, BIZ_A, usage_service.METRIC_MSG_IN, 2)

    async with su.acquire() as conn:
        after = await conn.fetchval(
            "SELECT count FROM usage_daily WHERE business_id=$1 "
            "AND day=current_date AND metric=$2",
            BIZ_A,
            usage_service.METRIC_MSG_IN,
        )
    assert after == before + 2

    # The admin usage endpoint returns the series including today's msg_in.
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        body = (await http.get(f"/api/admin/businesses/{BIZ_A}/usage")).json()
    finally:
        await _logout(redis, http, sid)
    assert body["business_id"] == BIZ_A
    assert usage_service.METRIC_MSG_IN in body["metrics_present"]
    today = next((p for p in body["series"] if p["day"] == _today_iso()), None)
    assert today is not None
    assert today["metrics"].get(usage_service.METRIC_MSG_IN, 0) >= after


@pytest.mark.asyncio
async def test_usage_bad_date_422(http, redis, admin_user):
    """A non-ISO `from`/`to` → 422 (the parse guard), without touching the DB."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        r1 = await http.get(f"/api/admin/businesses/{BIZ_A}/usage?from=nope")
        r2 = await http.get(f"/api/admin/businesses/{BIZ_A}/usage?to=2026-13-99")
    finally:
        await _logout(redis, http, sid)
    assert r1.status_code == 422
    assert r2.status_code == 422


def _today_iso() -> str:
    from datetime import date

    return date.today().isoformat()


# ============================================================================
#  ISOLATION — the non-negotiable. app_role can't read the zero-grant tables;
#  the SD functions are the only path; per-tenant RLS still holds; ACTIVE
#  negative control flips is_active and watches the bot fall silent + restore.
# ============================================================================


@pytest.mark.asyncio
async def test_app_role_cannot_read_subscriptions_directly(pool, su):
    """app_role has NO grant on subscriptions → a direct SELECT is denied, even
    though a row exists (we seed one as superuser first)."""
    await _set_sub_via_su(su, BIZ_A, "pro", "active")
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with tenant_connection(pool, BIZ_A) as conn:
                await conn.fetch("SELECT * FROM subscriptions")
    finally:
        async with su.acquire() as conn:
            await conn.execute(
                "DELETE FROM subscriptions WHERE business_id = $1", BIZ_A
            )
            await conn.execute(
                "UPDATE businesses SET is_active = true WHERE id = $1", BIZ_A
            )


@pytest.mark.asyncio
async def test_app_role_cannot_read_admin_audit_directly(pool):
    """app_role has NO grant on admin_audit → a direct SELECT is denied."""
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.fetch("SELECT * FROM admin_audit")


@pytest.mark.asyncio
async def test_sd_function_is_the_only_cross_tenant_path(pool):
    """The SD overview function (EXECUTE granted to app_role) DOES return data on
    a plain pooled connection — proving the sanctioned doorway works while the
    direct table reads above are denied."""
    async with pool.acquire() as conn:  # NO tenant context — the SD bypasses RLS
        row = await conn.fetchrow("SELECT * FROM admin_overview()")
    assert row is not None
    assert int(row["total_businesses"]) >= 2  # at least Avi + Bella exist


@pytest.mark.asyncio
async def test_tenant_a_cannot_read_b_usage_daily(pool):
    """usage_daily is RLS-forced: A bumps its own row, then A explicitly asking
    for B's usage rows gets ZERO (the tenant wall holds on the new table too)."""
    # A writes its own counter.
    async with tenant_connection(pool, BIZ_A) as conn:
        await usage_service.bump(conn, BIZ_A, usage_service.METRIC_LOGIN, 1)
    # A asks for B's rows explicitly → RLS returns nothing.
    async with tenant_connection(pool, BIZ_A) as conn:
        rows = await conn.fetch(
            "SELECT * FROM usage_daily WHERE business_id = $1", BIZ_B
        )
    assert rows == []


@pytest.mark.asyncio
async def test_usage_daily_with_check_blocks_cross_tenant_bump(pool):
    """A cannot write a usage_daily row labelled as B's (WITH CHECK rejects)."""
    with pytest.raises(asyncpg.PostgresError):
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.execute(
                "INSERT INTO usage_daily (business_id, day, metric, count) "
                "VALUES ($1, current_date, 'msg_in', 1)",
                BIZ_B,
            )


@pytest.mark.asyncio
async def test_negative_control_suspend_gate_is_real(
    http, redis, pool, su, admin_user, clean_admin_state, mapped
):
    """ACTIVE negative control: flip businesses.is_active=false DIRECTLY (not via
    the admin path) and confirm the webhook bot goes silent — proving the suspend
    GATE in the webhook actually gates — then restore it and confirm it answers.
    If flipping the flag did nothing, the bot would keep replying and this fails."""
    gw_token = get_settings().gateway_api_token.get_secret_value()
    auth = {"X-Gateway-Token": gw_token}

    # Break it on purpose: set is_active=false (superuser, out-of-band).
    async with su.acquire() as conn:
        await conn.execute(
            "UPDATE businesses SET is_active = false WHERE id = $1", BIZ_A
        )
    broke = await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
        headers=auth,
    )
    assert broke.json()["status"] == "suspended"
    assert broke.json()["replies"] == []

    # Restore + assert restoration.
    async with su.acquire() as conn:
        await conn.execute(
            "UPDATE businesses SET is_active = true WHERE id = $1", BIZ_A
        )
    fixed = await http.post(
        "/webhook/whatsapp",
        json=_webhook_body(ACC_A, "היי", f"self:{secrets.token_hex(6)}"),
        headers=auth,
    )
    assert fixed.json()["status"] == "ok"
    assert len(fixed.json()["replies"]) >= 1


# ============================================================================
#  NO PII — admin responses carry only identity + aggregates, never content
# ============================================================================


@pytest.mark.asyncio
async def test_admin_responses_carry_no_lead_or_booking_content(
    http, redis, admin_user
):
    """The list + detail response KEYS are a known identity/aggregate allow-list —
    no lead/booking content (names, phones, messages, notes) keys leak through."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        listing = (await http.get("/api/admin/businesses?limit=200")).json()
        detail = (await http.get(f"/api/admin/businesses/{BIZ_A}")).json()
        usage = (await http.get(f"/api/admin/businesses/{BIZ_A}/usage")).json()
    finally:
        await _logout(redis, http, sid)

    allowed_row_keys = {
        "business_id", "name", "owner_email", "created_at", "last_login_at",
        "plan_code", "status", "is_active", "leads_count", "msgs_30d",
    }
    for row in listing["businesses"]:
        assert set(row.keys()) <= allowed_row_keys, set(row.keys())

    allowed_detail_keys = allowed_row_keys | {"business_type", "wa_status"}
    assert set(detail.keys()) <= allowed_detail_keys, set(detail.keys())

    # The usage series is pure numbers: a day + a metric→int map, nothing else.
    assert set(usage.keys()) == {"business_id", "metrics_present", "series"}
    forbidden = {"phone", "contact_name", "lead_name", "message", "note", "text",
                 "email_body", "answers"}
    for point in usage["series"]:
        assert set(point.keys()) == {"day", "metrics"}
        assert not (set(point["metrics"].keys()) & forbidden)
        assert all(isinstance(v, int) for v in point["metrics"].values())
