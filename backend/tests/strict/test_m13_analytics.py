"""M13 strict — GATE (session + admin allow-list) + ANALYTICS aggregates.

Split out of the original test_m13.py (shared fixtures/helpers live in
_m13_helpers.py). Authoritative contract:
docs/decisions/0017-m13-backoffice-analytics-crm.md.

  GATE      no session → 401 on EVERY new M13 route; authed NON-admin → 403 on
            every one; the admin → 200.
  ANALYTICS the aggregates reconcile with DB truth — every assertion is a DELTA
            against a clean baseline (leads-by-type buckets, plan filter,
            messages totals, by-plan grouping, ai-ops day sums, trends series).
"""

from __future__ import annotations

import pytest

from _m13_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    ADMIN_EMAIL,
    AVI_USER,
    BIZ_A,
    BIZ_B,
    M13_GET_ROUTES,
    NONADMIN_EMAIL,
    _bump,
    _login,
    _logout,
    _seed_booking,
    _seed_lead,
    _set_sub,
    _today_iso,
    admin_user,
    clean_m13,
    http,
    lifespan_app,
    pool,
    redis,
    su,
)
from app.services import usage as usage_service


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
