"""M4 — the AI bot builder, strict pytest (the CI version).

M2 built the WALL between businesses, M3 built the FRONT DOOR (login), and M4
adds the AI BOT BUILDER: the owner-facing screen + API where a business designs
its WhatsApp bot (the conversation flows + the bot's profile), optionally with an
AI assistant that proposes config changes.

These tests are the hard CI gate for M4. They run IN-PROCESS against the real
ASGI app (`app.main.app`) over httpx ASGITransport, so the app's own lifespan
opens the real Redis + Postgres pools and every dependency (the deny-by-default
`/api` gate, RLS via `tenant_connection`, the Pydantic validation gate) is
exercised for real. The ONLY thing faked is the Gemini network call, via the
exact seam the backend exposes: `bot_builder_ai.get_gemini_client`.

What must be true (or the build fails):
  * Unauthenticated request to ANY /api/bot/* route → 401 (deny-by-default).
  * GET/PUT /api/bot/settings are tenant-scoped — business A's saves are
    invisible to B, and a save is read back unchanged.
  * PUT validates untrusted input — out-of-bounds bodies are rejected with 422
    BEFORE any write (the validation IS the gate).
  * POST /api/bot/ai/chat with the MOCKED client returns a reply, applies +
    returns the proposed `changes`, and persists exactly two build-chat rows
    (user + assistant) for THIS tenant only.
  * POST /api/bot/ai/chat with the AI proposing an INVALID config still returns
    the reply but drops the change (changes is null) — the chat keeps flowing.
  * With GEMINI_API_KEY unset (no mock) → POST /api/bot/ai/chat is 503, and the
    app still boots.
  * GET /api/bot/ai/history returns this tenant's messages oldest→newest.

Nothing here prints a secret, a token, or PII.
"""

from __future__ import annotations

import os
import secrets
import time
from contextlib import asynccontextmanager

import asyncpg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import bot_builder_ai
from app.services.auth import _SESSION_KEY_PREFIX

# The two seeded tenants (fixed UUIDs from supabase/seed.sql), same ids the M2
# wall + M3 front-door tests use. Avi's bot is published; Bella's is a draft.
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber
AVI_USER = "google-sub-avi"
BELLA_USER = "google-sub-bella"


# --- the fake Gemini client (the mock seam the backend documented) -----------
#
# bot_builder_ai.generate_reply() calls get_gemini_client() fresh on every turn,
# then awaits  client.aio.models.generate_content(model=, contents=, config=)
# and reads `.text` off the result. So a minimal fake only has to mimic that
# exact async surface. We make the reply text configurable so one fake can drive
# both the "valid change" and "invalid change" paths.


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModels:
    def __init__(self, reply_text: str) -> None:
        self._reply_text = reply_text

    async def generate_content(self, **_kwargs):  # noqa: ANN003 - mirror SDK kwargs
        # Ignores model/contents/config (we don't hit the network); returns canned text.
        return _FakeResp(self._reply_text)


class _FakeAio:
    def __init__(self, reply_text: str) -> None:
        self.models = _FakeModels(reply_text)


class _FakeClient:
    """Mimics the slice of google-genai's async client that generate_reply uses."""

    def __init__(self, reply_text: str) -> None:
        self.aio = _FakeAio(reply_text)


def _patch_gemini(monkeypatch: pytest.MonkeyPatch, reply_text: str) -> None:
    """Swap the real client factory for one that returns our canned reply.

    This is the exact seam the backend exposes — no real key, no network.
    """
    monkeypatch.setattr(
        bot_builder_ai, "get_gemini_client", lambda: _FakeClient(reply_text)
    )


# A model reply that proposes a VALID config change: a fenced ```json block with
# a complete bot_profile + one lead flow. The merge must accept + return it.
_VALID_CHANGE_REPLY = (
    "מצוין! הוספתי מסלול לקבלת פרטים. ✨\n"
    "```json\n"
    "{\n"
    '  "bot_profile": {"name": "בוט הבדיקה", "system_prompt": "עזור ללקוחות בנימוס."},\n'
    '  "lead_steps": {\n'
    '    "signup": {"label": "הרשמה", "flow_type": "lead", "steps": [\n'
    '      {"key": "full_name", "question": "מה השם המלא?", "type": "text", "required": true}\n'
    "    ]}\n"
    "  }\n"
    "}\n"
    "```\n"
    "מה השלב הבא שתרצה להוסיף?"
)

# A model reply that proposes an INVALID change: a choice step with NO options
# (the contract requires 2..12). merge_changes must raise → the router drops the
# change but still returns the conversational reply.
_INVALID_CHANGE_REPLY = (
    "הנה מסלול עם בחירה:\n"
    "```json\n"
    "{\n"
    '  "bot_profile": {"name": "בוט", "system_prompt": "עזור."},\n'
    '  "lead_steps": {"pick": {"label": "בחירה", "flow_type": "lead", "steps": [\n'
    '    {"key": "color", "question": "איזה צבע?", "type": "choice", "required": true}\n'
    "  ]}}\n"
    "}\n"
    "```\n"
)


# --- shared lifespan-managed client + helpers (same pattern as test_auth_gate) -


@asynccontextmanager
async def _lifespan_app():
    """Run the app's real lifespan (opens app.state.redis + pg_pool)."""
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def client():
    """An httpx client wired straight to the ASGI app, lifespan running."""
    async with _lifespan_app():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest_asyncio.fixture
async def redis_client():
    c = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    yield c
    await c.aclose()


@pytest_asyncio.fixture
async def app_pool():
    """asyncpg pool as app_role (RLS applies) — for direct DB assertions/cleanup."""
    pool = await asyncpg.create_pool(
        dsn=os.environ["DATABASE_URL"], min_size=1, max_size=2
    )
    yield pool
    await pool.close()


def _session_payload(user_id: str, business_id: str, business_name: str) -> dict:
    """A session blob shaped EXACTLY like services.auth.create_session writes."""
    return {
        "user_id": user_id,
        "email": f"{user_id}@example.com",
        "name": user_id,
        "picture": "",
        "business_id": business_id,
        "business_name": business_name,
        "created_at": int(time.time()),
    }


async def _inject_session(redis: aioredis.Redis, payload: dict) -> str:
    """Write a real session into Redis and return its opaque id (cookie value)."""
    sid = secrets.token_urlsafe(32)
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", payload_json(payload), ex=3600)
    return sid


def payload_json(payload: dict) -> str:
    import json

    return json.dumps(payload)


async def _clear_build_chat(pool, business_id: str) -> None:
    """Remove this tenant's build-chat rows so message-count asserts are exact."""
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            "DELETE FROM bot_builder_messages WHERE business_id = $1", business_id
        )


def _minimal_valid_settings() -> dict:
    """The smallest BotSettings body PUT will accept (name + system_prompt)."""
    return {
        "lead_steps": {},
        "bot_profile": {"name": "בוט בדיקה", "system_prompt": "עזור ללקוחות בנימוס."},
        "handoff_keywords": ["נציג", "אדם"],
        "is_published": False,
    }


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


# ============================================================================
# 4) AI chat — mocked Gemini: reply + applied changes + persisted rows.
# ============================================================================


async def test_ai_chat_applies_valid_change_and_persists_two_rows(
    client, redis_client, app_pool, monkeypatch
):
    """POST /ai/chat (mocked) → reply + validated `changes`, and exactly 2 rows.

    The fake model returns a fenced ```json block with a complete profile + a
    lead flow. The endpoint must: return the reply, return the merged+validated
    BotSettings as `changes`, and persist one user + one assistant row for THIS
    tenant only.
    """
    from app.services.auth import SESSION_COOKIE_NAME

    _patch_gemini(monkeypatch, _VALID_CHANGE_REPLY)
    await _clear_build_chat(app_pool, BIZ_A)

    sid = await _inject_session(
        redis_client, _session_payload(AVI_USER, BIZ_A, "Avi Insurance")
    )
    try:
        resp = await client.post(
            "/api/bot/ai/chat",
            json={"message": "תוסיף מסלול הרשמה", "current_config": {}},
            cookies={SESSION_COOKIE_NAME: sid},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert isinstance(body["reply"], str) and body["reply"]
        # The proposed change was valid → returned as the full BotSettings shape.
        assert body["changes"] is not None
        assert "signup" in body["changes"]["lead_steps"]
        assert body["changes"]["bot_profile"]["name"] == "בוט הבדיקה"

        # Exactly the user turn + the assistant turn were persisted, in order.
        rows = await _fetch_build_chat(app_pool, BIZ_A)
        assert [r["role"] for r in rows] == ["user", "assistant"]
        assert rows[0]["content"] == "תוסיף מסלול הרשמה"
        assert rows[1]["content"] == _VALID_CHANGE_REPLY
    finally:
        await _clear_build_chat(app_pool, BIZ_A)
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid}")


async def test_ai_chat_drops_invalid_change_but_still_replies(
    client, redis_client, app_pool, monkeypatch
):
    """An AI-proposed INVALID config → reply kept, changes=null, chat persisted.

    The model proposes a choice step with no options (out of bounds). The merge
    raises, the router drops the change, but the conversational reply is still
    returned and the turn is still saved (the client keeps chatting).
    """
    from app.services.auth import SESSION_COOKIE_NAME

    _patch_gemini(monkeypatch, _INVALID_CHANGE_REPLY)
    await _clear_build_chat(app_pool, BIZ_A)

    sid = await _inject_session(
        redis_client, _session_payload(AVI_USER, BIZ_A, "Avi Insurance")
    )
    try:
        resp = await client.post(
            "/api/bot/ai/chat",
            json={"message": "תוסיף בחירה", "current_config": {}},
            cookies={SESSION_COOKIE_NAME: sid},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["reply"]  # the conversational reply is still returned
        assert body["changes"] is None  # the invalid change was dropped
        # The turn is still persisted (so history reflects the conversation).
        rows = await _fetch_build_chat(app_pool, BIZ_A)
        assert [r["role"] for r in rows] == ["user", "assistant"]
    finally:
        await _clear_build_chat(app_pool, BIZ_A)
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid}")


async def test_ai_chat_history_is_oldest_to_newest_and_tenant_scoped(
    client, redis_client, app_pool, monkeypatch
):
    """History returns THIS tenant's messages oldest→newest, never another's."""
    from app.services.auth import SESSION_COOKIE_NAME

    _patch_gemini(monkeypatch, _VALID_CHANGE_REPLY)
    await _clear_build_chat(app_pool, BIZ_A)
    await _clear_build_chat(app_pool, BIZ_B)

    sid_a = await _inject_session(
        redis_client, _session_payload(AVI_USER, BIZ_A, "Avi Insurance")
    )
    sid_b = await _inject_session(
        redis_client, _session_payload(BELLA_USER, BIZ_B, "Bella Barber")
    )
    try:
        # Avi has a conversation; Bella has a DIFFERENT one.
        await client.post(
            "/api/bot/ai/chat",
            json={"message": "הודעה ראשונה של אבי", "current_config": {}},
            cookies={SESSION_COOKIE_NAME: sid_a},
        )
        await client.post(
            "/api/bot/ai/chat",
            json={"message": "הודעה של בלה", "current_config": {}},
            cookies={SESSION_COOKIE_NAME: sid_b},
        )

        hist_a = (
            await client.get(
                "/api/bot/ai/history", cookies={SESSION_COOKIE_NAME: sid_a}
            )
        ).json()
        msgs = hist_a["messages"]
        # Oldest→newest: the first stored message is Avi's user turn.
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "הודעה ראשונה של אבי"
        assert msgs[-1]["role"] == "assistant"
        # Tenant isolation: Bella's message must NOT appear in Avi's history.
        assert all("בלה" not in m["content"] for m in msgs)
    finally:
        await _clear_build_chat(app_pool, BIZ_A)
        await _clear_build_chat(app_pool, BIZ_B)
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid_a}")
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid_b}")


async def test_ai_chat_does_not_persist_other_tenants_rows(
    client, redis_client, app_pool, monkeypatch
):
    """A chat as Avi writes rows ONLY under Avi's business_id (RLS write-side)."""
    from app.services.auth import SESSION_COOKIE_NAME

    _patch_gemini(monkeypatch, _VALID_CHANGE_REPLY)
    await _clear_build_chat(app_pool, BIZ_A)
    await _clear_build_chat(app_pool, BIZ_B)

    sid_a = await _inject_session(
        redis_client, _session_payload(AVI_USER, BIZ_A, "Avi Insurance")
    )
    try:
        await client.post(
            "/api/bot/ai/chat",
            json={"message": "שיחה של אבי בלבד", "current_config": {}},
            cookies={SESSION_COOKIE_NAME: sid_a},
        )
        # Avi's tenant sees 2 rows; Bella's tenant sees 0 (no cross-write).
        a_rows = await _fetch_build_chat(app_pool, BIZ_A)
        b_rows = await _fetch_build_chat(app_pool, BIZ_B)
        assert len(a_rows) == 2
        assert len(b_rows) == 0
    finally:
        await _clear_build_chat(app_pool, BIZ_A)
        await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid_a}")


# ============================================================================
# 5) Gemini unset → 503 (validate-at-use). NO mock patched here.
# ============================================================================


async def test_ai_chat_without_gemini_key_is_503(client, redis_client, monkeypatch):
    """With no GEMINI_API_KEY (and no mock): /ai/chat → 503, app still up.

    We force the key to be absent at the *settings* level and clear the cached
    settings so get_gemini_client() takes the not-configured branch. The route
    must map GeminiNotConfiguredError → 503 (never a 500), proving the stack
    boots and serves everything else without an AI key.
    """
    from app.core import config as config_module
    from app.services.auth import SESSION_COOKIE_NAME

    # Ensure no key is visible to the settings loader, then bust the lru_cache so
    # the next get_settings() re-reads the (key-less) environment.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config_module.get_settings.cache_clear()
    try:
        sid = await _inject_session(
            redis_client, _session_payload(AVI_USER, BIZ_A, "Avi Insurance")
        )
        try:
            resp = await client.post(
                "/api/bot/ai/chat",
                json={"message": "שלום", "current_config": {}},
                cookies={SESSION_COOKIE_NAME: sid},
            )
            assert resp.status_code == 503, resp.text
        finally:
            await redis_client.delete(f"{_SESSION_KEY_PREFIX}{sid}")
    finally:
        # Restore the cache to the real environment for any later test.
        config_module.get_settings.cache_clear()


# ============================================================================
# 6) Pure-function unit checks (no DB / no network) — extract + merge.
# ============================================================================


def test_extract_changes_pulls_json_fence():
    """extract_changes finds the ```json block and parses it to a dict."""
    out = bot_builder_ai.extract_changes(_VALID_CHANGE_REPLY)
    assert isinstance(out, dict)
    assert "lead_steps" in out and "signup" in out["lead_steps"]


def test_extract_changes_returns_none_on_no_block_or_bad_json():
    """No fence → None; malformed JSON in a fence → None (never raises)."""
    assert bot_builder_ai.extract_changes("just a plain reply, no JSON") is None
    bad = "```json\n{not valid json,,}\n```"
    assert bot_builder_ai.extract_changes(bad) is None


def test_merge_changes_strips_reserved_knowledge_key():
    """The reserved 'knowledge' key (RAG, Phase 3) is stripped, not written."""
    current: dict = {}
    changes = {
        "bot_profile": {
            "name": "בוט",
            "system_prompt": "עזור.",
            "knowledge": "SECRET RAG DOC",  # reserved → must be dropped
        }
    }
    _validated, merged = bot_builder_ai.merge_changes(current, changes)
    assert "knowledge" not in merged["bot_profile"]
    assert merged["bot_profile"]["name"] == "בוט"


def test_merge_changes_rejects_out_of_bounds():
    """A merged result that violates the bounds raises (caller must not persist)."""
    from pydantic import ValidationError

    current: dict = {}
    bad_changes = {
        "bot_profile": {"name": "בוט", "system_prompt": "עזור."},
        # choice step with no options → invalid.
        "lead_steps": {
            "pick": {
                "label": "x",
                "flow_type": "lead",
                "steps": [
                    {"key": "c", "question": "q", "type": "choice", "required": True}
                ],
            }
        },
    }
    with pytest.raises((ValidationError, ValueError)):
        bot_builder_ai.merge_changes(current, bad_changes)


async def test_generate_reply_without_key_raises_not_configured(monkeypatch):
    """generate_reply with no key (no mock) raises GeminiNotConfiguredError."""
    from app.core import config as config_module

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config_module.get_settings.cache_clear()
    try:
        with pytest.raises(bot_builder_ai.GeminiNotConfiguredError):
            await bot_builder_ai.generate_reply("hi", {})
    finally:
        config_module.get_settings.cache_clear()


# --- small DB helpers (app_role; RLS-scoped) ---------------------------------


async def _fetch_build_chat(pool, business_id: str):
    async with tenant_connection(pool, business_id) as conn:
        return await conn.fetch(
            "SELECT role, content FROM bot_builder_messages "
            "WHERE business_id = $1 ORDER BY created_at",
            business_id,
        )


async def _read_settings_db(pool, business_id: str):
    """Read a tenant's raw bot_settings row (for snapshot/restore)."""
    async with tenant_connection(pool, business_id) as conn:
        return await conn.fetchrow(
            "SELECT lead_steps, bot_profile, handoff_keywords, is_published "
            "FROM bot_settings WHERE business_id = $1",
            business_id,
        )


async def _restore_settings_db(pool, business_id: str, row) -> None:
    """Restore a tenant's bot_settings row from a snapshot (test cleanup)."""
    if row is None:
        return
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            """
            UPDATE bot_settings
               SET lead_steps = $2::jsonb,
                   bot_profile = $3::jsonb,
                   handoff_keywords = $4::jsonb,
                   is_published = $5,
                   updated_at = now()
             WHERE business_id = $1
            """,
            business_id,
            row["lead_steps"],
            row["bot_profile"],
            row["handoff_keywords"],
            row["is_published"],
        )
