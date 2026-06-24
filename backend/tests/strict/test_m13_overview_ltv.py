"""M13 strict — LTV estimate/summary + AI_CALL bump wiring + SNAPSHOT idempotency.

Split out of the original test_m13.py (shared fixtures/helpers live in
_m13_helpers.py). Authoritative contract:
docs/decisions/0017-m13-backoffice-analytics-crm.md.

  LTV       admin_business_extra.ltv_estimate + admin_ltv_summary return plan
            price x tenure-months (free/no-sub → 0), reconciled to DB truth.
  AI_CALL   the bump wiring increments usage_daily metric='ai_call' for the right
            business/day; it surfaces in by-plan + ai-ops + detail.
  SNAPSHOT  GET /api/admin/overview stamps today's platform_snapshots row and is
            idempotent (calling twice keeps ONE row); the body carries avg_ltv.
"""

from __future__ import annotations

import pytest

from _m13_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    ADMIN_EMAIL,
    BIZ_A,
    BIZ_B,
    PRICE_BASIC,
    PRICE_PRO,
    _bump,
    _login,
    _logout,
    _set_sub,
    admin_user,
    clean_m13,
    http,
    lifespan_app,
    pool,
    redis,
    su,
)
from app.db.session import tenant_connection
from app.services import usage as usage_service


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
