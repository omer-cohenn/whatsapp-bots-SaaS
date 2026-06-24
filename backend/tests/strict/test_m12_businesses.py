"""M12 strict — LIST + DETAIL + SET SUBSCRIPTION (validation, audit, is_active).

Split out of the original test_m12.py (shared fixtures/helpers live in
_m12_helpers.py). Authoritative contract: docs/decisions/0016-m12-back-office.md.

  LIST     owner_email / created_at / last_login_at / plan (default 'free' +
           'active' when no subscription) / leads_count / msgs_30d; search
           filters; limit/offset bounds (422 out of range).
  DETAIL   the single-business profile + wa_status; unknown id → 404.
  SET SUB  changes plan+status; bad status → 422; unknown plan → 422; unknown
           business → 404; writes a REAL admin_audit row stamped with the real
           admin Google sub + email; suspending sets is_active=false, restoring it.
"""

from __future__ import annotations

import json

import pytest

from _m12_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    ADMIN_EMAIL,
    BIZ_A,
    BIZ_B,
    NONADMIN_EMAIL,
    _login,
    _logout,
    admin_user,
    clean_admin_state,
    http,
    lifespan_app,
    pool,
    redis,
    su,
)


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
