"""Shared fixtures + helpers for the M4 bot-builder strict suite (split files).

This module is NOT a test file — it carries the fake Gemini client (the mock
seam the backend documents), the lifespan-managed httpx client + Redis/PG
fixtures, the session-injection helpers, the canned model-reply constants, and
the small RLS-scoped DB helpers shared by the two bot-builder test modules:

  * test_bot_builder_settings.py — gate + settings CRUD + PUT validation
  * test_bot_builder_ai.py        — AI chat (mocked Gemini) + 503 + pure units

It is imported as a top-level module (pytest puts tests/strict/ on sys.path).
Fixtures imported by name into a test module register with pytest as usual, so
the behavior is byte-for-byte identical to the original single-file
test_bot_builder.py. Nothing here prints a secret, a token, or PII.

The ONLY thing faked is the Gemini network call, via the exact seam the backend
exposes: bot_builder_ai.get_gemini_client.
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
