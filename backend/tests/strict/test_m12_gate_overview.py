"""M12 strict — GATE (session + admin allow-list) + OVERVIEW KPI reconciliation.

Split out of the original test_m12.py (shared fixtures/helpers live in
_m12_helpers.py). Authoritative contract: docs/decisions/0016-m12-back-office.md.

  GATE     no session → 401 on /api/me and EVERY /api/admin/* route; authed
           NON-admin → 403 on every /api/admin/* route; admin → 200. /api/me
           reports is_admin true for the admin, false for the non-admin.
  OVERVIEW the KPI aggregates reconcile with DB truth (seed a couple of
           subscriptions + usage rows and assert the counts move correctly).
"""

from __future__ import annotations

import pytest

from _m12_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    ADMIN_EMAIL,
    ADMIN_GET_ROUTES,
    AVI_USER,
    BIZ_A,
    BIZ_B,
    NONADMIN_EMAIL,
    _login,
    _logout,
    _set_sub_via_su,
    admin_user,
    clean_admin_state,
    http,
    lifespan_app,
    pool,
    redis,
    su,
)
from app.db.session import tenant_connection
from app.services import usage as usage_service


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
