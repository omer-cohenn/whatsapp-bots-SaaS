"""M4 bot builder strict — the gate + settings CRUD + PUT validation.

Split out of the original test_bot_builder.py (shared fixtures/helpers live in
_bot_builder_helpers.py). These run IN-PROCESS against the real ASGI app over
httpx ASGITransport so the deny-by-default /api gate, RLS via tenant_connection
and the Pydantic validation gate are all exercised for real.

  1) The gate — unauthenticated requests to every /api/bot/* route are 401.
  2) Settings CRUD — tenant-scoped read + round-trip save.
  3) PUT validation — untrusted input bounds are the gate (422).
"""

from __future__ import annotations

import secrets

import pytest

from _bot_builder_helpers import (  # noqa: F401  (fixtures imported register w/ pytest)
    AVI_USER,
    BELLA_USER,
    BIZ_A,
    BIZ_B,
    _inject_session,
    _minimal_valid_settings,
    _read_settings_db,
    _restore_settings_db,
    _session_payload,
    app_pool,
    client,
    redis_client,
)
from app.services.auth import _SESSION_KEY_PREFIX


# ============================================================================
# 1) The gate — unauthenticated requests to every /api/bot/* route are 401.
# ============================================================================


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/bot/settings"),
        ("PUT", "/api/bot/settings"),
        ("POST", "/api/bot/ai/chat"),
        ("GET", "/api/bot/ai/history"),
    ],
)
async def test_bot_routes_require_login(client, method, path):
    """Deny-by-default: NO session cookie → every bot route is 401 (no leak)."""
    resp = await client.request(method, path, json={})
    assert resp.status_code == 401, f"{method} {path} should be 401 without a session"


async def test_bot_routes_reject_forged_cookie(client):
    """A random/forged opaque id matches no Redis session → still 401."""
    from app.services.auth import SESSION_COOKIE_NAME

    forged = secrets.token_urlsafe(32)
    resp = await client.get(
        "/api/bot/settings", cookies={SESSION_COOKIE_NAME: forged}
    )
    assert resp.status_code == 401


# ============================================================================
# 2) Settings CRUD — tenant-scoped read + round-trip save.
# ============================================================================


async def test_get_settings_returns_own_seeded_config(client, redis_client):
    """Avi's GET returns AVI's seeded bot (published, object-keyed lead_steps)."""
    sid = await _inject_session(
        redis_client, _session_payload(AVI_USER, BIZ_A, "Avi Insurance")
    )
    from app.services.auth import SESSION_COOKIE_NAME

    try:
        resp = await client.get(
            "/api/bot/settings", cookies={SESSION_COOKIE_NAME: sid}
        )
        assert resp.status_code == 200
        body = resp.json()
        # The seeded shape (supabase/seed.sql): published, lead_steps is an
        # OBJECT keyed by flow name with quote + talk_to_human.
        assert body["is_published"] is True
        assert isinstance(body["lead_steps"], dict)
        assert set(body["lead_steps"]) == {"quote", "talk_to_human"}
        assert body["lead_steps"]["talk_to_human"]["flow_type"] == "human_handoff"
        assert body["bot_profile"]["name"]  # filled profile
    finally:
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid}")


async def test_put_then_get_round_trips_for_tenant(client, redis_client, app_pool):
    """A saved config (PUT) is read back unchanged (GET) — for the SAME tenant.

    We use Bella (the draft tenant) and restore her seeded config afterwards so
    later tests/seeds still see the expected fixture.
    """
    from app.services.auth import SESSION_COOKIE_NAME

    # Snapshot Bella's seeded config so we can restore it at the end.
    before = await _read_settings_db(app_pool, BIZ_B)

    sid = await _inject_session(
        redis_client, _session_payload(BELLA_USER, BIZ_B, "Bella Barber")
    )
    new_cfg = {
        "lead_steps": {
            "callback": {
                "label": "בקשת שיחה חוזרת",
                "flow_type": "lead",
                "steps": [
                    {
                        "key": "full_name",
                        "question": "מה השם המלא?",
                        "type": "text",
                        "required": True,
                    },
                    {
                        "key": "topic",
                        "question": "במה נוכל לעזור?",
                        "type": "choice",
                        "required": True,
                        "options": ["תספורת", "צבע", "אחר"],
                    },
                ],
            },
            "talk_to_human": {
                "label": "דברו עם נציג",
                "flow_type": "human_handoff",
                "steps": [],
            },
        },
        "bot_profile": {
            "name": "בוט בדיקה של בלה",
            "system_prompt": "עזור ללקוחות לקבוע תור בנימוס.",
            "language": "he",
        },
        "handoff_keywords": ["נציג", "אדם", "human"],
        "is_published": False,
    }
    try:
        put = await client.put(
            "/api/bot/settings", json=new_cfg, cookies={SESSION_COOKIE_NAME: sid}
        )
        assert put.status_code == 200, put.text

        got = await client.get(
            "/api/bot/settings", cookies={SESSION_COOKIE_NAME: sid}
        )
        assert got.status_code == 200
        body = got.json()
        assert set(body["lead_steps"]) == {"callback", "talk_to_human"}
        # choice step kept its options; non-choice steps carry none.
        topic = body["lead_steps"]["callback"]["steps"][1]
        assert topic["type"] == "choice"
        assert topic["options"] == ["תספורת", "צבע", "אחר"]
        assert body["bot_profile"]["name"] == "בוט בדיקה של בלה"
    finally:
        # Restore Bella's original seeded config (idempotent re-seed safety).
        await _restore_settings_db(app_pool, BIZ_B, before)
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid}")


async def test_settings_are_tenant_isolated_via_api(client, redis_client, app_pool):
    """Through the HTTP layer: Avi's GET never returns Bella's flow names.

    This is the end-to-end tenant check for settings: two real sessions, two
    business ids, each sees only its own row (RLS via current_business).
    """
    from app.services.auth import SESSION_COOKIE_NAME

    sid_a = await _inject_session(
        redis_client, _session_payload(AVI_USER, BIZ_A, "Avi Insurance")
    )
    sid_b = await _inject_session(
        redis_client, _session_payload(BELLA_USER, BIZ_B, "Bella Barber")
    )
    try:
        a = (await client.get("/api/bot/settings", cookies={SESSION_COOKIE_NAME: sid_a})).json()
        b = (await client.get("/api/bot/settings", cookies={SESSION_COOKIE_NAME: sid_b})).json()
        # Avi has 'quote'; Bella has 'appointment'. Neither should see the other's.
        assert "quote" in a["lead_steps"] and "appointment" not in a["lead_steps"]
        assert "appointment" in b["lead_steps"] and "quote" not in b["lead_steps"]
    finally:
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid_a}")
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid_b}")


# ============================================================================
# 3) PUT validation — untrusted input bounds are the gate (422).
# ============================================================================


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("missing profile name/prompt", lambda c: c.update({"bot_profile": {}})),
        (
            "choice step without options",
            lambda c: c.__setitem__(
                "lead_steps",
                {
                    "f": {
                        "label": "x",
                        "flow_type": "lead",
                        "steps": [
                            {
                                "key": "k",
                                "question": "q",
                                "type": "choice",
                                "required": True,
                            }
                        ],
                    }
                },
            ),
        ),
        (
            "lead flow with zero steps",
            lambda c: c.__setitem__(
                "lead_steps",
                {"f": {"label": "x", "flow_type": "lead", "steps": []}},
            ),
        ),
        (
            "human_handoff flow WITH steps",
            lambda c: c.__setitem__(
                "lead_steps",
                {
                    "h": {
                        "label": "x",
                        "flow_type": "human_handoff",
                        "steps": [
                            {
                                "key": "k",
                                "question": "q",
                                "type": "text",
                                "required": True,
                            }
                        ],
                    }
                },
            ),
        ),
        (
            "flow name not snake_case",
            lambda c: c.__setitem__(
                "lead_steps",
                {
                    "Bad Name": {
                        "label": "x",
                        "flow_type": "lead",
                        "steps": [
                            {
                                "key": "k",
                                "question": "q",
                                "type": "text",
                                "required": True,
                            }
                        ],
                    }
                },
            ),
        ),
        (
            "too many flows (>20)",
            lambda c: c.__setitem__(
                "lead_steps",
                {
                    f"f{i}": {
                        "label": "x",
                        "flow_type": "lead",
                        "steps": [
                            {
                                "key": "k",
                                "question": "q",
                                "type": "text",
                                "required": True,
                            }
                        ],
                    }
                    for i in range(21)
                },
            ),
        ),
    ],
)
async def test_put_rejects_out_of_bounds_body(client, redis_client, label, mutate):
    """Every malformed config is rejected with 422 before any write."""
    from app.services.auth import SESSION_COOKIE_NAME

    sid = await _inject_session(
        redis_client, _session_payload(AVI_USER, BIZ_A, "Avi Insurance")
    )
    try:
        body = _minimal_valid_settings()
        mutate(body)
        resp = await client.put(
            "/api/bot/settings", json=body, cookies={SESSION_COOKIE_NAME: sid}
        )
        assert resp.status_code == 422, f"{label!r} should be 422, got {resp.status_code}"
    finally:
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid}")


async def test_put_oversized_message_is_not_settings(client, redis_client):
    """An over-long AI chat message (>4000 chars) is rejected with 422."""
    from app.services.auth import SESSION_COOKIE_NAME

    sid = await _inject_session(
        redis_client, _session_payload(AVI_USER, BIZ_A, "Avi Insurance")
    )
    try:
        resp = await client.post(
            "/api/bot/ai/chat",
            json={"message": "x" * 4001, "current_config": {}},
            cookies={SESSION_COOKIE_NAME: sid},
        )
        assert resp.status_code == 422
    finally:
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid}")
