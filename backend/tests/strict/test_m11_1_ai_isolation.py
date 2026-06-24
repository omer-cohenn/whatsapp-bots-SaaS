"""M11.1 strict — AI WELCOME (mocked Gemini) + TENANT ISOLATION on new fields.

Split out of the original test_m11_1.py (shared fixtures/helpers live in
_m11_1_helpers.py). Per decision 0012.

  G5 AI WELCOME — POST /api/booking/welcome/generate is gated (401 without a
     session); with Gemini mocked it returns the message; missing key → 503; the
     key never leaks into the response.
  G6 ISOLATION — A cannot read/patch B's services/settings; the public slug only
     ever exposes its own tenant's services + welcome_message.
"""

from __future__ import annotations

import pytest

from _m11_1_helpers import (  # noqa: F401  (fixtures imported by name register w/ pytest)
    AVI_USER,
    BELLA_USER,
    BIZ_A,
    BIZ_B,
    _ALL_DAYS_9_17,
    _login,
    _make_service_direct,
    _patch_welcome_gemini,
    _seed_settings,
    cleanup,
    http,
    lifespan_app,
    pool,
    rds,
)
from app.db.session import tenant_connection


# ============================================================================
#  GOAL 5 — AI WELCOME: gate (401), mocked success, no-key 503, no key leak
# ============================================================================

@pytest.mark.asyncio
async def test_welcome_generate_requires_session(http, cleanup):
    """POST /api/booking/welcome/generate without a session → 401 (gated)."""
    r = await http.post("/api/booking/welcome/generate", json={})
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_welcome_generate_returns_message_when_mocked(
    http, rds, pool, cleanup, monkeypatch
):
    """With Gemini mocked: returns the generated message (key never touched)."""
    await _login(rds, http, AVI_USER, BIZ_A)
    await http.post("/api/services", json={"name": "ייעוץ", "duration_minutes": 30})
    canned = "ברוכים הבאים! נשמח לעזור לכם. קבעו תור עכשיו."
    _patch_welcome_gemini(monkeypatch, canned)

    r = await http.post("/api/booking/welcome/generate", json={"tone": "חם"})
    assert r.status_code == 200, r.text
    assert r.json()["message"] == canned


@pytest.mark.asyncio
async def test_welcome_generate_no_key_is_503(http, rds, pool, cleanup, monkeypatch):
    """With NO Gemini key (real factory, key unset) → 503; the app stays up."""
    await _login(rds, http, AVI_USER, BIZ_A)
    # Force the not-configured branch: clear the cached settings + the env key.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from app.core import config as app_config
    app_config.get_settings.cache_clear()
    try:
        r = await http.post("/api/booking/welcome/generate", json={})
        assert r.status_code == 503, r.text
    finally:
        app_config.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_welcome_generate_never_leaks_key(http, rds, pool, cleanup, monkeypatch):
    """The generate response never contains the configured key, even on success."""
    await _login(rds, http, AVI_USER, BIZ_A)
    _patch_welcome_gemini(monkeypatch, "טקסט תקין")
    r = await http.post("/api/booking/welcome/generate", json={})
    assert r.status_code == 200
    from app.core.config import get_settings
    key = get_settings().gemini_api_key
    if key is not None:
        assert key.get_secret_value() not in r.text


# ============================================================================
#  GOAL 6 — TENANT ISOLATION on the new fields
# ============================================================================

@pytest.mark.asyncio
async def test_isolation_a_cannot_patch_b_service_fields(http, rds, pool, cleanup):
    """A PATCH on B's service (description/price) → 404; B's row untouched."""
    svc_b = await _make_service_direct(pool, BIZ_B, name="B-svc", duration=30,
                                       description="B-desc", price=99)
    await _login(rds, http, AVI_USER, BIZ_A)
    p = await http.patch(f"/api/services/{svc_b}", json={
        "description": "hacked", "price": 1})
    assert p.status_code == 404, p.text

    async with tenant_connection(pool, BIZ_B) as conn:
        row = await conn.fetchrow(
            "SELECT description, price FROM services WHERE id=$1 AND business_id=$2",
            svc_b, BIZ_B)
    assert row["description"] == "B-desc" and row["price"] == 99


@pytest.mark.asyncio
async def test_isolation_welcome_message_scoped(http, rds, pool, cleanup):
    """B's welcome_message never appears for A; each tenant sees only its own."""
    await _login(rds, http, BELLA_USER, BIZ_B)
    await http.put("/api/booking/settings", json={
        "working_hours": _ALL_DAYS_9_17, "min_notice_minutes": 0,
        "buffer_minutes": 0, "max_days_ahead": 30, "meet_enabled": False,
        "welcome_message": "ברוכים הבאים-B-SECRET"})

    await _login(rds, http, AVI_USER, BIZ_A)
    a = (await http.get("/api/booking/settings")).json()
    assert a.get("welcome_message") != "ברוכים הבאים-B-SECRET"


@pytest.mark.asyncio
async def test_public_slug_only_exposes_own_welcome_and_services(http, rds, pool, cleanup):
    """A's public page shows A's welcome + services, never B's."""
    slug_a = await _seed_settings(pool, BIZ_A, working_hours=_ALL_DAYS_9_17)
    await _make_service_direct(pool, BIZ_A, name="A-svc", duration=30)
    await _make_service_direct(pool, BIZ_B, name="B-svc", duration=30)
    # Give A a welcome; B a different one.
    async with tenant_connection(pool, BIZ_A) as conn:
        await conn.execute(
            "UPDATE booking_settings SET welcome_message=$1 WHERE business_id=$2",
            "A-welcome", BIZ_A)

    rows = (await http.get(f"/api/book/{slug_a}/services")).json()
    names = {s["name"] for s in rows["services"]}
    assert "A-svc" in names and "B-svc" not in names
    assert rows["welcome_message"] == "A-welcome"
