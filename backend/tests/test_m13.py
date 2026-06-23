"""M13 — back-office ANALYTICS + platform-level sales CRM, strict pytest (CI).

Authoritative contract: docs/decisions/0017-m13-backoffice-analytics-crm.md. The
narrated Hebrew story lives in m13_full_test.py; THIS is the strict gate CI runs.
It drives the REAL ASGI app over httpx ASGITransport so the deny-by-default /api
session gate, the router-level current_admin gate (ADMIN_EMAILS, checked LIVE),
the cross-tenant SECURITY DEFINER analytics/CRM functions, the per-tenant RLS,
and the ai_call usage bump are all exercised exactly like a live request.

What it proves (mapped to the QA goals in decision 0017 §10):

  GATE      no session → 401 on EVERY new M13 route (analytics/*, crm, crm notes,
            the PATCH stage, the POST note); authed NON-admin → 403 on every one;
            the admin → 200/201.
  ANALYTICS the aggregates reconcile with DB truth. We seed two businesses with
            subscriptions(plan), usage_daily rows (msg_in/msg_out/ai_call/lead/
            booking), leads (normal + a 'פנייה לנציג'/handed_off), and bookings,
            then assert admin_leads_by_type buckets (booking/lead/handoff),
            admin_messages_by_business totals, admin_by_plan grouping, the
            admin_ai_ops_series day sums, and admin_trends_series after a snapshot.
            Every assertion is a DELTA against a clean baseline.
  LTV       admin_business_extra.ltv_estimate + admin_ltv_summary return plan
            price x tenure-months (free/no-sub → 0), reconciled to DB truth.
  AI_CALL   exercising the bump wiring increments usage_daily metric='ai_call'
            for the right business/day; it surfaces in by-plan + ai-ops + detail.
  SNAPSHOT  GET /api/admin/overview stamps today's platform_snapshots row and is
            idempotent (calling twice keeps ONE row); the body carries avg_ltv.
  CRM       PATCH stage moves a business + writes an admin_audit row stamped with
            the REAL admin Google sub + email; bad stage → 422; unknown business
            → 404. POST note → 201 + GET notes returns it newest-first + the
            crm_list note_count increments; blank note → 422; unknown biz → 404.
  ISOLATION the non-negotiable: app_role CANNOT directly SELECT business_crm /
            crm_notes / platform_snapshots (permission denied) — the SD functions
            are the ONLY path; tenant A's RLS still holds (A can't read B's
            usage_daily); ACTIVE negative control breaks the grant model on
            purpose then restores it.
  NO PII    no analytics / CRM response key carries end-customer lead/booking
            content (names, phones, messages, answers).

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
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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


# ============================================================================
#  GATE — session + admin allow-list on EVERY new M13 route
# ============================================================================


@pytest.mark.asyncio
async def test_m13_routes_require_session(http):
    """No session → EVERY new M13 route is 401 (deny-by-default on /api)."""
    for route in M13_GET_ROUTES:
        assert (await http.get(route)).status_code == 401, route
    assert (
        await http.patch(f"/api/admin/businesses/{BIZ_A}/crm", json={"stage": "won"})
    ).status_code == 401
    assert (
        await http.post(
            f"/api/admin/businesses/{BIZ_A}/crm/notes", json={"note": "x"}
        )
    ).status_code == 401


@pytest.mark.asyncio
async def test_nonadmin_forbidden_on_every_m13_route(http, redis):
    """An authed NON-admin (Avi) → 403 on every new M13 route (reads + writes)."""
    sid = await _login(redis, http, AVI_USER, NONADMIN_EMAIL, BIZ_A)
    try:
        for route in M13_GET_ROUTES:
            assert (await http.get(route)).status_code == 403, route
        assert (
            await http.patch(
                f"/api/admin/businesses/{BIZ_A}/crm", json={"stage": "won"}
            )
        ).status_code == 403
        assert (
            await http.post(
                f"/api/admin/businesses/{BIZ_A}/crm/notes", json={"note": "x"}
            )
        ).status_code == 403
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_admin_allowed_on_every_m13_get_route(http, redis, admin_user):
    """The admin → 200 on every M13 read route (the gate lets the operator in)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        for route in M13_GET_ROUTES:
            assert (await http.get(route)).status_code == 200, route
    finally:
        await _logout(redis, http, sid)


# ============================================================================
#  ANALYTICS — the aggregates reconcile with DB truth (delta against baseline)
# ============================================================================


@pytest.mark.asyncio
async def test_leads_by_type_buckets_reconcile(http, redis, su, admin_user, clean_m13):
    """Seed 2 normal leads + 1 handoff + 1 booking for A; assert the donut buckets
    move by exactly those amounts vs a clean baseline (period='all')."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        base = (
            await http.get("/api/admin/analytics/leads-by-type?period=all&plan=all")
        ).json()

        await _seed_lead(su, BIZ_A, handoff=False)
        await _seed_lead(su, BIZ_A, handoff=False)
        await _seed_lead(su, BIZ_A, handoff=True)
        await _seed_booking(su, BIZ_A)

        after = (
            await http.get("/api/admin/analytics/leads-by-type?period=all&plan=all")
        ).json()
    finally:
        await _logout(redis, http, sid)

    assert after["lead"] == base["lead"] + 2, (base, after)
    assert after["handoff"] == base["handoff"] + 1, (base, after)
    assert after["booking"] == base["booking"] + 1, (base, after)


@pytest.mark.asyncio
async def test_leads_by_type_plan_filter(http, redis, su, admin_user, clean_m13):
    """The plan filter scopes the buckets: a lead on a 'pro' business shows for
    plan='pro' and plan='all', but NOT for plan='basic'."""
    await _set_sub(su, BIZ_A, "pro", "active")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        base_pro = (
            await http.get("/api/admin/analytics/leads-by-type?period=all&plan=pro")
        ).json()
        base_basic = (
            await http.get("/api/admin/analytics/leads-by-type?period=all&plan=basic")
        ).json()
        await _seed_lead(su, BIZ_A, handoff=False)
        after_pro = (
            await http.get("/api/admin/analytics/leads-by-type?period=all&plan=pro")
        ).json()
        after_basic = (
            await http.get("/api/admin/analytics/leads-by-type?period=all&plan=basic")
        ).json()
    finally:
        await _logout(redis, http, sid)

    assert after_pro["lead"] == base_pro["lead"] + 1
    # The 'pro' business's lead must NOT appear under the 'basic' filter.
    assert after_basic["lead"] == base_basic["lead"]


@pytest.mark.asyncio
async def test_messages_by_business_totals_reconcile(
    http, redis, su, pool, admin_user, clean_m13
):
    """Bump A's msg_in by 5 and msg_out by 3 today; the billing view's row for A
    grows by exactly those amounts (total = in + out)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        def _row(body, biz):
            return next(
                (r for r in body["businesses"] if r["business_id"] == biz), None
            )

        base = (await http.get("/api/admin/analytics/messages?period=all")).json()
        base_a = _row(base, BIZ_A) or {"msg_in": 0, "msg_out": 0, "total": 0}

        await _bump(pool, BIZ_A, usage_service.METRIC_MSG_IN, 5)
        await _bump(pool, BIZ_A, usage_service.METRIC_MSG_OUT, 3)

        after = (await http.get("/api/admin/analytics/messages?period=all")).json()
        after_a = _row(after, BIZ_A)
    finally:
        await _logout(redis, http, sid)

    assert after_a is not None
    assert after_a["msg_in"] == base_a["msg_in"] + 5
    assert after_a["msg_out"] == base_a["msg_out"] + 3
    assert after_a["total"] == base_a["total"] + 8
    assert after_a["total"] == after_a["msg_in"] + after_a["msg_out"]


@pytest.mark.asyncio
async def test_by_plan_groups_metric(http, redis, su, pool, admin_user, clean_m13):
    """A on 'pro', B on 'basic'; bump each business's lead metric, and assert
    admin_by_plan groups the values under the right plan codes."""
    await _set_sub(su, BIZ_A, "pro", "active")
    await _set_sub(su, BIZ_B, "basic", "active")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        def _val(body, plan):
            return next(
                (r["value"] for r in body["rows"] if r["plan_code"] == plan), 0
            )

        base = (
            await http.get("/api/admin/analytics/by-plan?metric=lead&period=all")
        ).json()
        base_pro = _val(base, "pro")
        base_basic = _val(base, "basic")

        await _bump(pool, BIZ_A, usage_service.METRIC_LEAD, 4)  # pro
        await _bump(pool, BIZ_B, usage_service.METRIC_LEAD, 7)  # basic

        after = (
            await http.get("/api/admin/analytics/by-plan?metric=lead&period=all")
        ).json()
    finally:
        await _logout(redis, http, sid)

    assert after["metric"] == "lead"
    assert _val(after, "pro") == base_pro + 4
    assert _val(after, "basic") == base_basic + 7


@pytest.mark.asyncio
async def test_ai_ops_series_day_sum_reconciles(
    http, redis, su, pool, admin_user, clean_m13
):
    """ai_call summed across all businesses for TODAY grows by exactly the bumps:
    A +2, B +3 → today's ai-ops point grows by 5."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        def _today(body):
            return next(
                (p["count"] for p in body["series"] if p["day"] == _today_iso()), 0
            )

        base = (await http.get("/api/admin/analytics/ai-ops")).json()
        base_today = _today(base)

        await _bump(pool, BIZ_A, usage_service.METRIC_AI_CALL, 2)
        await _bump(pool, BIZ_B, usage_service.METRIC_AI_CALL, 3)

        after = (await http.get("/api/admin/analytics/ai-ops")).json()
    finally:
        await _logout(redis, http, sid)

    assert _today(after) == base_today + 5


@pytest.mark.asyncio
async def test_ai_ops_bad_date_422(http, redis, admin_user):
    """A non-ISO from/to on ai-ops → 422 (the parse guard)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        assert (
            await http.get("/api/admin/analytics/ai-ops?from=nope")
        ).status_code == 422
        assert (
            await http.get("/api/admin/analytics/ai-ops?to=2026-13-99")
        ).status_code == 422
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_by_plan_junk_metric_422(http, redis, admin_user):
    """A metric outside the vocabulary → 422 at the edge (Literal), no DB call."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        assert (
            await http.get("/api/admin/analytics/by-plan?metric=bogus")
        ).status_code == 422
        # metric is required.
        assert (
            await http.get("/api/admin/analytics/by-plan")
        ).status_code == 422
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_trends_series_after_snapshot(http, redis, su, admin_user, clean_m13):
    """After GET /overview stamps today's snapshot, the trends series includes a
    row for today whose numbers match admin_overview's live totals."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        overview = (await http.get("/api/admin/overview")).json()
        trends = (await http.get("/api/admin/analytics/trends")).json()
    finally:
        await _logout(redis, http, sid)

    today_pt = next(
        (p for p in trends["series"] if p["day"] == _today_iso()), None
    )
    assert today_pt is not None, "overview should have stamped today's snapshot"
    # The snapshot's total_businesses + active_count must match the live overview.
    assert today_pt["total_businesses"] == overview["total_businesses"]
    assert today_pt["active_count"] == overview["active_count"]


# ============================================================================
#  LTV — admin_business_extra + admin_ltv_summary estimate (price x tenure)
# ============================================================================


@pytest.mark.asyncio
async def test_ltv_estimate_in_detail(http, redis, su, admin_user, clean_m13):
    """A on 'pro' started 3 months ago → ltv_estimate = 149 x 3 = 447; B free → 0."""
    await _set_sub(su, BIZ_A, "pro", "active", months_ago=3)
    # B left with NO subscription (free → 0).
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        a = (await http.get(f"/api/admin/businesses/{BIZ_A}")).json()
        b = (await http.get(f"/api/admin/businesses/{BIZ_B}")).json()
    finally:
        await _logout(redis, http, sid)

    # 3 whole months elapsed (started exactly 3 months ago) → 149 * 3.
    assert a["ltv_estimate"] == pytest.approx(PRICE_PRO * 3)
    assert a["plan_code"] == "pro"
    assert b["ltv_estimate"] == 0
    # The nested CRM block defaults to stage 'new' when no CRM row exists.
    assert a["crm"]["stage"] == "new"


@pytest.mark.asyncio
async def test_ltv_floor_is_one_month(http, redis, su, admin_user, clean_m13):
    """A brand-new paid sub (started now) is worth at least ONE month: basic → 49."""
    await _set_sub(su, BIZ_A, "basic", "active", months_ago=0)
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        a = (await http.get(f"/api/admin/businesses/{BIZ_A}")).json()
    finally:
        await _logout(redis, http, sid)
    assert a["ltv_estimate"] == pytest.approx(PRICE_BASIC)


@pytest.mark.asyncio
async def test_ltv_summary_reconciles_to_db(http, redis, su, pool, admin_user, clean_m13):
    """avg_ltv x total_businesses ≈ total_ltv, and total_ltv equals the SD summary
    read directly (the overview merges admin_ltv_summary)."""
    await _set_sub(su, BIZ_A, "pro", "active", months_ago=2)  # 149 * 2 = 298
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        overview = (await http.get("/api/admin/overview")).json()
    finally:
        await _logout(redis, http, sid)

    # Read the SD summary directly (EXECUTE is granted to app_role) and reconcile.
    async with pool.acquire() as conn:
        summ = await conn.fetchrow("SELECT * FROM admin_ltv_summary()")
    assert overview["total_ltv"] == pytest.approx(float(summ["total_ltv"]))
    assert overview["avg_ltv"] == pytest.approx(float(summ["avg_ltv"]))
    # A's 298 must be inside the total.
    assert overview["total_ltv"] >= PRICE_PRO * 2


# ============================================================================
#  AI_CALL BUMP — the wiring lands in usage_daily and surfaces in analytics
# ============================================================================


@pytest.mark.asyncio
async def test_ai_call_bump_increments_usage_daily(pool, su, clean_m13):
    """A bump_safe(ai_call) on A's tenant connection lands on today's row for A
    (the exact call the bot-builder + booking-welcome endpoints make)."""
    async with su.acquire() as conn:
        before = (
            await conn.fetchval(
                "SELECT count FROM usage_daily WHERE business_id=$1 "
                "AND day=current_date AND metric='ai_call'",
                BIZ_A,
            )
            or 0
        )
    async with tenant_connection(pool, BIZ_A) as conn:
        await usage_service.bump_safe(conn, BIZ_A, usage_service.METRIC_AI_CALL)
    async with su.acquire() as conn:
        after = await conn.fetchval(
            "SELECT count FROM usage_daily WHERE business_id=$1 "
            "AND day=current_date AND metric='ai_call'",
            BIZ_A,
        )
    assert after == before + 1


@pytest.mark.asyncio
async def test_ai_call_surfaces_in_detail_and_by_plan(
    http, redis, su, pool, admin_user, clean_m13
):
    """An ai_call bump on a 'pro' business shows up both in the business detail's
    ai_calls counter and in by-plan(metric=ai_call) under 'pro'."""
    await _set_sub(su, BIZ_A, "pro", "active")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        detail_before = (await http.get(f"/api/admin/businesses/{BIZ_A}")).json()
        base_calls = detail_before["ai_calls"] or 0

        await _bump(pool, BIZ_A, usage_service.METRIC_AI_CALL, 6)

        detail_after = (await http.get(f"/api/admin/businesses/{BIZ_A}")).json()
        by_plan = (
            await http.get("/api/admin/analytics/by-plan?metric=ai_call&period=all")
        ).json()
    finally:
        await _logout(redis, http, sid)

    assert detail_after["ai_calls"] == base_calls + 6
    pro_val = next(
        (r["value"] for r in by_plan["rows"] if r["plan_code"] == "pro"), 0
    )
    assert pro_val >= 6


# ============================================================================
#  SNAPSHOT — overview stamps today's row; idempotent (twice → one row)
# ============================================================================


@pytest.mark.asyncio
async def test_overview_stamps_snapshot_idempotently(http, redis, su, admin_user):
    """Two GET /overview calls keep EXACTLY one platform_snapshots row for today,
    and the body carries avg_ltv/total_ltv (additive M13 fields)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        b1 = (await http.get("/api/admin/overview")).json()
        b2 = (await http.get("/api/admin/overview")).json()
    finally:
        await _logout(redis, http, sid)

    assert "avg_ltv" in b1 and "total_ltv" in b1
    assert "avg_ltv" in b2
    async with su.acquire() as conn:
        rows = await conn.fetchval(
            "SELECT count(*) FROM platform_snapshots WHERE day = current_date"
        )
    assert rows == 1  # idempotent — two views, one row


# ============================================================================
#  CRM — stage move + audit; note round-trip; validation
# ============================================================================


@pytest.mark.asyncio
async def test_crm_stage_moves_and_audits(http, redis, su, admin_user, clean_m13):
    """PATCH stage to 'warming' moves the business in admin_crm_list AND writes an
    admin_audit row stamped with the REAL admin Google sub + email."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        r = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/crm",
            json={"stage": "warming", "next_followup": "2026-07-01T09:00:00+00:00"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["business_id"] == BIZ_A
        assert body["stage"] == "warming"
        assert body["next_followup_at"] is not None

        board = (await http.get("/api/admin/crm")).json()
        row = next(
            (c for c in board["businesses"] if c["business_id"] == BIZ_A), None
        )
        assert row is not None and row["stage"] == "warming"
    finally:
        await _logout(redis, http, sid)

    # The audit row is verifiable only via the SD-owner path → read as superuser.
    async with su.acquire() as conn:
        audit = await conn.fetchrow(
            "SELECT admin_user_id, admin_email, action, target_business_id, detail "
            "FROM admin_audit WHERE target_business_id = $1 AND action = 'crm_stage' "
            "ORDER BY created_at DESC LIMIT 1",
            BIZ_A,
        )
    assert audit is not None
    assert audit["admin_user_id"] == admin_user  # the REAL Google sub
    assert audit["admin_email"] == ADMIN_EMAIL
    assert audit["action"] == "crm_stage"
    assert str(audit["target_business_id"]) == BIZ_A
    detail = audit["detail"]
    detail = detail if isinstance(detail, dict) else json.loads(detail)
    assert detail == {"stage": "warming"}


@pytest.mark.asyncio
async def test_crm_bad_stage_422(http, redis, admin_user):
    """A stage outside the vocabulary → 422 (the Literal rejects before the SD call)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        r = await http.patch(
            f"/api/admin/businesses/{BIZ_A}/crm", json={"stage": "frozen"}
        )
        assert r.status_code == 422
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_crm_unknown_business_404(http, redis, admin_user, clean_m13):
    """An unknown (well-formed) business id → 404; a malformed uuid → 404 too."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        assert (
            await http.patch(
                f"/api/admin/businesses/{UNKNOWN_BIZ}/crm", json={"stage": "won"}
            )
        ).status_code == 404
        assert (
            await http.patch(
                "/api/admin/businesses/not-a-uuid/crm", json={"stage": "won"}
            )
        ).status_code == 404
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_crm_note_roundtrip_and_count(http, redis, su, admin_user, clean_m13):
    """POST a note → 201; GET notes returns it newest-first; the crm_list note_count
    increments; a second note comes back ahead of the first."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        # Baseline note_count from the board.
        board0 = (await http.get("/api/admin/crm")).json()
        base_count = next(
            (c["note_count"] for c in board0["businesses"] if c["business_id"] == BIZ_A),
            0,
        )

        r1 = await http.post(
            f"/api/admin/businesses/{BIZ_A}/crm/notes",
            json={"note": "called the owner; warm lead"},
        )
        assert r1.status_code == 201, r1.text
        note1 = r1.json()["note_id"]
        assert note1

        r2 = await http.post(
            f"/api/admin/businesses/{BIZ_A}/crm/notes",
            json={"note": "second touch; sent pricing"},
        )
        assert r2.status_code == 201
        note2 = r2.json()["note_id"]

        notes = (
            await http.get(f"/api/admin/businesses/{BIZ_A}/crm/notes")
        ).json()["notes"]
        ids = [n["id"] for n in notes]
        assert note1 in ids and note2 in ids
        # Newest first: note2 appears before note1.
        assert ids.index(note2) < ids.index(note1)
        assert notes[0]["note"] == "second touch; sent pricing"
        # The admin's display email is on the note (no end-customer PII).
        assert notes[0]["admin_email"] == ADMIN_EMAIL

        board1 = (await http.get("/api/admin/crm")).json()
        new_count = next(
            (c["note_count"] for c in board1["businesses"] if c["business_id"] == BIZ_A),
            0,
        )
        assert new_count == base_count + 2
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_crm_note_blank_422(http, redis, admin_user, clean_m13):
    """A whitespace-only note → 422 (the request model strips + min_length rejects)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        assert (
            await http.post(
                f"/api/admin/businesses/{BIZ_A}/crm/notes", json={"note": "   "}
            )
        ).status_code == 422
        # Empty body / missing note → 422 too.
        assert (
            await http.post(f"/api/admin/businesses/{BIZ_A}/crm/notes", json={})
        ).status_code == 422
    finally:
        await _logout(redis, http, sid)


@pytest.mark.asyncio
async def test_crm_note_unknown_business_404(http, redis, admin_user, clean_m13):
    """A note on an unknown business → 404 (the SD FK violation maps to not-found)."""
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        assert (
            await http.post(
                f"/api/admin/businesses/{UNKNOWN_BIZ}/crm/notes", json={"note": "x"}
            )
        ).status_code == 404
    finally:
        await _logout(redis, http, sid)


# ============================================================================
#  ISOLATION — the non-negotiable. app_role can't read the zero-grant M13
#  tables directly; the SD functions are the only path; per-tenant RLS holds;
#  an ACTIVE negative control proves the grant model is real.
# ============================================================================


@pytest.mark.asyncio
async def test_app_role_cannot_read_business_crm_directly(pool, su, admin_user):
    """app_role has NO grant on business_crm → a direct SELECT is denied, even
    though a row exists (we seed one via the SD function as superuser first)."""
    async with su.acquire() as conn:
        await conn.execute(
            "INSERT INTO business_crm (business_id, stage) VALUES ($1, 'warming') "
            "ON CONFLICT ON CONSTRAINT business_crm_pkey DO UPDATE SET stage='warming'",
            BIZ_A,
        )
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with tenant_connection(pool, BIZ_A) as conn:
                await conn.fetch("SELECT * FROM business_crm")
    finally:
        async with su.acquire() as conn:
            await conn.execute("DELETE FROM business_crm WHERE business_id = $1", BIZ_A)


@pytest.mark.asyncio
async def test_app_role_cannot_read_crm_notes_directly(pool):
    """app_role has NO grant on crm_notes → a direct SELECT is denied."""
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.fetch("SELECT * FROM crm_notes")


@pytest.mark.asyncio
async def test_app_role_cannot_read_platform_snapshots_directly(pool):
    """app_role has NO grant on platform_snapshots → a direct SELECT is denied."""
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.fetch("SELECT * FROM platform_snapshots")


@pytest.mark.asyncio
async def test_sd_functions_are_the_only_crm_path(pool):
    """The CRM/snapshot SD functions (EXECUTE granted to app_role) DO return data
    on a plain pooled connection — proving the sanctioned doorway works while the
    direct table reads above are denied."""
    async with pool.acquire() as conn:  # NO tenant context — SD bypasses RLS
        crm = await conn.fetch("SELECT * FROM admin_crm_list()")
        ltv = await conn.fetchrow("SELECT * FROM admin_ltv_summary()")
    assert len(crm) >= 2  # at least Avi + Bella
    assert ltv is not None


@pytest.mark.asyncio
async def test_tenant_a_cannot_read_b_usage_daily(pool):
    """usage_daily stays RLS-forced under M13: A bumps its own row, then A asking
    for B's usage rows gets ZERO (the tenant wall is not weakened by M13)."""
    async with tenant_connection(pool, BIZ_A) as conn:
        await usage_service.bump(conn, BIZ_A, usage_service.METRIC_LOGIN, 1)
    async with tenant_connection(pool, BIZ_A) as conn:
        rows = await conn.fetch(
            "SELECT * FROM usage_daily WHERE business_id = $1", BIZ_B
        )
    assert rows == []


@pytest.mark.asyncio
async def test_negative_control_grant_model_is_real(pool, su):
    """ACTIVE negative control: GRANT app_role a direct SELECT on crm_notes, prove
    the read now SUCCEEDS (so the test CAN catch a leak), then REVOKE it and prove
    the read is denied again. If the REVOKE did nothing the wall would be open.

    This proves the isolation tests above are not false-positives — the deny is a
    real, removable grant, and we restore it.
    """
    # 1) Break it on purpose: hand app_role a direct grant.
    async with su.acquire() as conn:
        await conn.execute("GRANT SELECT ON crm_notes TO app_role")
    try:
        # With the grant, the direct read SUCCEEDS (no exception).
        async with tenant_connection(pool, BIZ_A) as conn:
            leaked = await conn.fetch("SELECT * FROM crm_notes")
        assert isinstance(leaked, list)  # the door is open — the test can see a leak
    finally:
        # 2) Restore the wall.
        async with su.acquire() as conn:
            await conn.execute("REVOKE SELECT ON crm_notes FROM app_role")

    # 3) Assert restoration: the direct read is denied again.
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with tenant_connection(pool, BIZ_A) as conn:
            await conn.fetch("SELECT * FROM crm_notes")


# ============================================================================
#  NO PII — analytics + CRM responses carry only identity/aggregates/sales
#  context, never end-customer lead/booking content.
# ============================================================================


@pytest.mark.asyncio
async def test_analytics_responses_carry_no_customer_pii(
    http, redis, su, admin_user, clean_m13
):
    """Seed a handoff lead + a booking (so the buckets are non-zero), then assert
    NO analytics/CRM response key carries end-customer content (names, phones,
    answers, message text). The CRM note text IS present (owner sales data) but no
    end-customer PII keys leak anywhere."""
    await _seed_lead(su, BIZ_A, handoff=True)
    await _seed_booking(su, BIZ_A)

    forbidden = {
        "phone", "client_phone", "contact_name", "client_name", "lead_name",
        "message", "text", "answers", "client_email", "meet_link",
    }

    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    try:
        leads_by_type = (
            await http.get("/api/admin/analytics/leads-by-type?period=all")
        ).json()
        messages = (await http.get("/api/admin/analytics/messages?period=all")).json()
        ai_ops = (await http.get("/api/admin/analytics/ai-ops")).json()
        by_plan = (
            await http.get("/api/admin/analytics/by-plan?metric=lead")
        ).json()
        trends = (await http.get("/api/admin/analytics/trends")).json()
        crm = (await http.get("/api/admin/crm")).json()
        detail = (await http.get(f"/api/admin/businesses/{BIZ_A}")).json()
    finally:
        await _logout(redis, http, sid)

    # leads-by-type: only the three numeric buckets.
    assert set(leads_by_type.keys()) == {"booking", "lead", "handoff"}
    assert all(isinstance(v, int) for v in leads_by_type.values())

    # messages billing rows: identity + numeric counters only.
    allowed_msg = {"business_id", "name", "plan_code", "msg_in", "msg_out", "total"}
    for r in messages["businesses"]:
        assert set(r.keys()) <= allowed_msg
        assert not (set(r.keys()) & forbidden)

    # ai-ops + trends: pure day/number points.
    for p in ai_ops["series"]:
        assert set(p.keys()) == {"day", "count"}
    for p in trends["series"]:
        assert not (set(p.keys()) & forbidden)

    # by-plan: plan + value only.
    for r in by_plan["rows"]:
        assert set(r.keys()) == {"plan_code", "value"}

    # CRM board: identity + pipeline meta + note_count.
    allowed_crm = {
        "business_id", "name", "plan_code", "stage", "last_contacted_at",
        "next_followup_at", "note_count",
    }
    for c in crm["businesses"]:
        assert set(c.keys()) <= allowed_crm
        assert not (set(c.keys()) & forbidden)

    # detail M13 extras: aggregate money/AI + the CRM sub-block — no customer PII.
    assert not (set(detail.keys()) & forbidden)
    if detail.get("crm"):
        assert set(detail["crm"].keys()) <= {
            "stage", "last_contacted_at", "next_followup_at"
        }
