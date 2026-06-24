"""M13 strict — ISOLATION (zero-grant tables + RLS + negative control) + NO-PII.

Split out of the original test_m13.py (shared fixtures/helpers live in
_m13_helpers.py). Authoritative contract:
docs/decisions/0017-m13-backoffice-analytics-crm.md.

  ISOLATION the non-negotiable: app_role CANNOT directly SELECT business_crm /
            crm_notes / platform_snapshots (permission denied) — the SD functions
            are the ONLY path; tenant A's RLS still holds (A can't read B's
            usage_daily); ACTIVE negative control breaks the grant model on
            purpose then restores it.
  NO PII    no analytics / CRM response key carries end-customer lead/booking
            content (names, phones, messages, answers).
"""

from __future__ import annotations

import asyncpg
import pytest

from _m13_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    ADMIN_EMAIL,
    BIZ_A,
    BIZ_B,
    _login,
    _logout,
    _seed_booking,
    _seed_lead,
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
