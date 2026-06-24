"""M4 bot builder strict — AI chat (mocked Gemini) + 503 + pure-function units.

Split out of the original test_bot_builder.py (shared fixtures/helpers live in
_bot_builder_helpers.py). The ONLY thing faked is the Gemini network call, via
the exact seam the backend exposes: bot_builder_ai.get_gemini_client.

  4) AI chat — mocked Gemini: reply + applied changes + persisted rows.
  5) Gemini unset → 503 (validate-at-use). NO mock patched here.
  6) Pure-function unit checks (no DB / no network) — extract + merge.
"""

from __future__ import annotations

import pytest

from _bot_builder_helpers import (  # noqa: F401  (fixtures imported register w/ pytest)
    AVI_USER,
    BELLA_USER,
    BIZ_A,
    BIZ_B,
    _INVALID_CHANGE_REPLY,
    _VALID_CHANGE_REPLY,
    _clear_build_chat,
    _fetch_build_chat,
    _inject_session,
    _patch_gemini,
    _session_payload,
    app_pool,
    client,
    redis_client,
)
from app.services import bot_builder_ai
from app.services.auth import _SESSION_KEY_PREFIX


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
