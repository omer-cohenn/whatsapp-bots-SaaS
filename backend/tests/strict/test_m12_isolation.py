"""M12 strict — ISOLATION (zero-grant tables + RLS + negative control) + NO-PII.

Split out of the original test_m12.py (shared fixtures/helpers live in
_m12_helpers.py). Authoritative contract: docs/decisions/0016-m12-back-office.md.

  ISOLATION the non-negotiable: app_role CANNOT directly SELECT subscriptions or
           admin_audit (permission denied) — the SD functions are the ONLY path;
           tenant A's RLS still holds (A can't read B's usage_daily); and an
           ACTIVE negative control flips is_active and watches the bot fall silent
           then restores it.
  NO PII   no admin response body / response key carries lead or booking content.
"""

from __future__ import annotations

import secrets

import asyncpg
import pytest

from _m12_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    ACC_A,
    ADMIN_EMAIL,
    BIZ_A,
    BIZ_B,
    _login,
    _logout,
    _set_sub_via_su,
    _webhook_body,
    admin_user,
    clean_admin_state,
    http,
    lifespan_app,
    mapped,
    pool,
    redis,
    su,
)
from app.core.config import get_settings
from app.db.session import tenant_connection
from app.services import usage as usage_service


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

    # M13 added three ADDITIVE detail keys (aggregate money + AI usage + the
    # sales-pipeline block) — all operator analytics, never end-customer content.
    allowed_detail_keys = allowed_row_keys | {
        "business_type", "wa_status", "ltv_estimate", "ai_calls", "crm",
    }
    assert set(detail.keys()) <= allowed_detail_keys, set(detail.keys())
    # The nested M13 `crm` block is sales-pipeline meta only — no customer PII.
    if detail.get("crm"):
        assert set(detail["crm"].keys()) <= {
            "stage", "last_contacted_at", "next_followup_at",
        }, set(detail["crm"].keys())

    # The usage series is pure numbers: a day + a metric→int map, nothing else.
    assert set(usage.keys()) == {"business_id", "metrics_present", "series"}
    forbidden = {"phone", "contact_name", "lead_name", "message", "note", "text",
                 "email_body", "answers"}
    for point in usage["series"]:
        assert set(point.keys()) == {"day", "metrics"}
        assert not (set(point["metrics"].keys()) & forbidden)
