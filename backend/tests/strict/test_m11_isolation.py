"""M11 strict — TENANT ISOLATION (incl. C4) + the admin-route session gate.

Split out of the original test_m11.py (shared fixtures/helpers live in
_m11_helpers.py). Per decision 0011.

  7. TENANT ISOLATION (incl. C4) — A cannot read/list/PATCH B's
     bookings/services/settings (foreign PATCH → 404); admin routes 401 without a
     session; public routes never expose another tenant.
"""

from __future__ import annotations

import pytest

from _m11_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    AVI_USER,
    BELLA_USER,
    BIZ_A,
    BIZ_B,
    _ALL_DAYS_9_17,
    _login,
    _make_service,
    _real_future_date,
    _set_settings,
    cleanup,
    http,
    lifespan_app,
    pool,
    rds,
)
from app.db.session import tenant_connection


# ============================================================================
#  GOAL 7 — TENANT ISOLATION (incl. C4) + admin gate
# ============================================================================

@pytest.mark.asyncio
async def test_admin_routes_require_session(http):
    """All admin booking routes are 401 without a session (deny-by-default)."""
    assert (await http.get("/api/booking/settings")).status_code == 401
    assert (await http.get("/api/services")).status_code == 401
    assert (await http.get("/api/bookings")).status_code == 401
    assert (await http.patch("/api/bookings/x", json={"status": "confirmed"})).status_code == 401
    assert (await http.get("/api/google/status")).status_code == 401


@pytest.mark.asyncio
async def test_isolation_a_cannot_list_b_bookings(http, rds, pool, cleanup):
    """A's GET /api/bookings never includes B's booking (C4 list isolation)."""
    slug_b = await _set_settings(pool, BIZ_B, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc_b = await _make_service(pool, BIZ_B, duration=60)
    date = _real_future_date()
    rb = await http.post(f"/api/book/{slug_b}", json={
        "service_id": svc_b, "date": date, "time": "09:00",
        "name": "bella-customer", "phone": "+972500000006"})
    b_booking = rb.json()["booking_id"]
    async with tenant_connection(pool, BIZ_B) as conn:
        await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", b_booking)
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_B)

    await _login(rds, http, AVI_USER, BIZ_A)
    rows = (await http.get("/api/bookings?include_test=true")).json()["bookings"]
    assert all(b["id"] != b_booking for b in rows), "A saw B's booking!"


@pytest.mark.asyncio
async def test_isolation_a_cannot_patch_b_booking(http, rds, pool, cleanup):
    """A PATCH on B's booking id → 404 (RLS hid it); B's row untouched (C4)."""
    slug_b = await _set_settings(pool, BIZ_B, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    svc_b = await _make_service(pool, BIZ_B, duration=60)
    date = _real_future_date()
    rb = await http.post(f"/api/book/{slug_b}", json={
        "service_id": svc_b, "date": date, "time": "09:00",
        "name": "bella-customer", "phone": "+972500000007"})
    b_booking = rb.json()["booking_id"]
    async with tenant_connection(pool, BIZ_B) as conn:
        await conn.execute("UPDATE bookings SET is_test=true WHERE id=$1", b_booking)
        await conn.execute("UPDATE leads SET is_test=true WHERE business_id=$1", BIZ_B)

    await _login(rds, http, AVI_USER, BIZ_A)
    r = await http.patch(f"/api/bookings/{b_booking}", json={"status": "cancelled"})
    assert r.status_code == 404, r.text

    async with tenant_connection(pool, BIZ_B) as conn:
        st = await conn.fetchval(
            "SELECT status FROM bookings WHERE id=$1 AND business_id=$2",
            b_booking, BIZ_B)
    assert st == "pending", "A's PATCH mutated B's booking!"


@pytest.mark.asyncio
async def test_isolation_a_cannot_patch_b_service(http, rds, pool, cleanup):
    """A PATCH/DELETE on B's service id → 404; the service is untouched (C4)."""
    svc_b = await _make_service(pool, BIZ_B, name="B-service", duration=45)
    await _login(rds, http, AVI_USER, BIZ_A)

    p = await http.patch(f"/api/services/{svc_b}", json={"name": "hacked"})
    assert p.status_code == 404
    d = await http.delete(f"/api/services/{svc_b}")
    assert d.status_code == 404

    async with tenant_connection(pool, BIZ_B) as conn:
        nm = await conn.fetchval(
            "SELECT name FROM services WHERE id=$1 AND business_id=$2", svc_b, BIZ_B)
    assert nm == "B-service", "A mutated/deleted B's service!"


@pytest.mark.asyncio
async def test_isolation_settings_scoped_per_tenant(http, rds, pool, cleanup):
    """Each tenant's GET /api/booking/settings returns its OWN slug, never the
    other's; A's slug != B's slug and neither leaks across."""
    slug_b = await _set_settings(pool, BIZ_B, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)

    await _login(rds, http, AVI_USER, BIZ_A)
    a_settings = (await http.get("/api/booking/settings")).json()
    assert a_settings["slug"] != slug_b, "A's settings exposed B's slug"

    await _login(rds, http, BELLA_USER, BIZ_B)
    b_settings = (await http.get("/api/booking/settings")).json()
    assert b_settings["slug"] == slug_b


@pytest.mark.asyncio
async def test_public_slug_only_exposes_its_own_services(http, pool, cleanup):
    """The public services for A's slug never include B's services (slug→tenant)."""
    slug_a = await _set_settings(pool, BIZ_A, working_hours={
        **_ALL_DAYS_9_17}, min_notice=0)
    await _make_service(pool, BIZ_A, name="A-only-service", duration=30)
    await _make_service(pool, BIZ_B, name="B-only-service", duration=30)

    rows = (await http.get(f"/api/book/{slug_a}/services")).json()["services"]
    names = {s["name"] for s in rows}
    assert "A-only-service" in names
    assert "B-only-service" not in names, "A's public page exposed B's service!"
