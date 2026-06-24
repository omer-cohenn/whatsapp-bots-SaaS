"""M12 strict — SUSPEND ENFORCEMENT (the bot goes silent) + USAGE counters.

Split out of the original test_m12.py (shared fixtures/helpers live in
_m12_helpers.py). Authoritative contract: docs/decisions/0016-m12-back-office.md.

  SUSPEND  the product-meaningful one: a suspended business's webhook bot turn
           returns the silent shape (replies=[]); re-activating restores answering.
  USAGE    hitting an instrumented webhook path increments usage_daily for the
           right metric/day; the /usage endpoint returns the series; a bad date
           → 422.
"""

from __future__ import annotations

import secrets

import pytest

from _m12_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    ACC_A,
    ADMIN_EMAIL,
    BIZ_A,
    _login,
    _logout,
    _today_iso,
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
