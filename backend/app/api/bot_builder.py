"""Protected /api/bot/* router — the AI bot builder (M4).

This router is mounted under the gated `/api` group (see app/main.py), so every
route here inherits the deny-by-default session gate. Endpoints:

  GET  /api/bot/settings    → the current bot config (BotSettings-shaped).
  PUT  /api/bot/settings    → validate (untrusted input) + UPSERT the config.
  POST /api/bot/ai/chat     → one AI builder turn; persists user + assistant
                              messages; returns {reply, changes?}. 503 if Gemini
                              is not configured.
  GET  /api/bot/ai/history  → recent build-chat messages (oldest→newest).

Tenant safety: the business id ALWAYS comes from `current_business` (the server
session), never from any body, and every DB access goes through
`tenant_connection(...)` so RLS scopes it. We never log message text or secrets.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError

from app.core.deps import current_business, current_user
from app.core.logging import get_logger
from app.db.session import tenant_connection
from app.models.bot_builder import (
    BotAiChatRequest,
    BotAiChatResponse,
    BotAiHistoryResponse,
    BotAiMessage,
    BotSettings,
    BotTryMeRequest,
    BotTryMeResponse,
)
from app.services import bot_builder_ai, bot_engine, bot_settings as bot_settings_service

router = APIRouter(prefix="/bot", tags=["bot-builder"])
log = get_logger("app.api.bot_builder")

# How many recent build-chat messages GET /api/bot/ai/history returns.
_HISTORY_LIMIT = 50


@router.get("/settings")
async def get_bot_settings(
    request: Request,
    business_id: str = Depends(current_business),
) -> dict[str, Any]:
    """Return this tenant's current bot config (permissive read; empties if new)."""
    return await bot_settings_service.get_settings(request.app.state.pg_pool, business_id)


@router.put("/settings", response_model=BotSettings)
async def put_bot_settings(
    settings: BotSettings,
    request: Request,
    business_id: str = Depends(current_business),
) -> BotSettings:
    """Validate (FastAPI runs the Pydantic bounds) + UPSERT the config for this tenant.

    `BotSettings` validation IS the gate — an out-of-bounds body is rejected with
    422 before any write. The tenant comes from the session, never the body.
    """
    await bot_settings_service.save_settings(request.app.state.pg_pool, business_id, settings)
    return settings


@router.post("/tryme", response_model=BotTryMeResponse)
async def bot_tryme(
    body: BotTryMeRequest,
    request: Request,
    business_id: str = Depends(current_business),
) -> BotTryMeResponse:
    """Run ONE turn of THIS tenant's bot against the owner's own config (try-me).

    Read-only: it loads this business's settings and runs the PURE bot engine.
    It NEVER writes to the DB (no leads, events, or messages) and never logs the
    message text. The business id comes from the session ONLY — never from the
    body or the conversation state — so there is no path to another tenant's
    config or another conversation's data.
    """
    settings = await bot_settings_service.get_settings(
        request.app.state.pg_pool, business_id
    )
    # A null/empty client state means a fresh conversation.
    state = body.state if body.state else bot_engine.initial_state()
    result = bot_engine.advance(settings, state, body.message)
    return BotTryMeResponse(
        replies=result["replies"],
        state=result["state"],
        event=result["event"],
        lead=result["lead"],
    )


@router.post("/ai/chat", response_model=BotAiChatResponse)
async def bot_ai_chat(
    body: BotAiChatRequest,
    request: Request,
    business_id: str = Depends(current_business),
    user: dict[str, str] = Depends(current_user),
) -> BotAiChatResponse:
    """One AI builder turn: ask Gemini, parse any config changes, persist the chat.

    Flow:
      1. Call the AI service (503 if Gemini unset, 502 if the call fails).
      2. Extract a fenced ```json change block (if any) and smart-merge+validate
         it — invalid changes are dropped (we still return the reply), never persisted
         into settings here (settings are saved via PUT after the user confirms).
      3. Persist BOTH the user message and the assistant reply to
         bot_builder_messages, tenant-scoped.
    """
    # 1) Ask the model. Map the typed errors to clean HTTP codes (no str(e)).
    try:
        reply_text = await bot_builder_ai.generate_reply(body.message, body.current_config)
    except bot_builder_ai.GeminiNotConfiguredError:
        # Validate-at-use: no key configured → service unavailable, not a 500.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI builder is not configured",
        ) from None
    except bot_builder_ai.BotBuilderError:
        log.warning("bot builder ai call failed")  # no message text / no secrets
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI builder is temporarily unavailable",
        ) from None

    # 2) Parse + validate any proposed change (untrusted LLM output).
    changes: dict[str, Any] | None = None
    raw_changes = bot_builder_ai.extract_changes(reply_text)
    if raw_changes is not None:
        try:
            _validated, merged = bot_builder_ai.merge_changes(body.current_config, raw_changes)
            changes = merged
        except (ValidationError, ValueError):
            # The model proposed something out of bounds — drop it. We still
            # return the conversational reply so the chat keeps flowing.
            log.info("bot builder proposed invalid changes; dropped")
            changes = None

    # 3) Build the DISPLAY reply: strip the embedded JSON (the owner never sees
    #    raw JSON — only plain language) and, when a change was applied, append a
    #    short plain-Hebrew summary of what it did.
    display_reply = bot_builder_ai.clean_reply_text(reply_text)
    if changes is not None and raw_changes is not None:
        summary = bot_builder_ai.summarize_changes(raw_changes, changes)
        if summary:
            display_reply = f"{display_reply}\n\n{summary}".strip()
    if not display_reply:
        display_reply = "קיבלתי. אפשר לפרט עוד?"

    # 4) Persist the turn (user + assistant) tenant-scoped. We store the RAW model
    #    reply (the full source, JSON and all) — the clean text is a display
    #    concern, applied on read. Done after a successful call (never a half-turn).
    await _persist_turn(
        request, business_id, user["id"], body.message, reply_text
    )

    return BotAiChatResponse(reply=display_reply, changes=changes)


@router.get("/ai/history", response_model=BotAiHistoryResponse)
async def bot_ai_history(
    request: Request,
    business_id: str = Depends(current_business),
) -> BotAiHistoryResponse:
    """Return recent build-chat messages for this tenant, oldest→newest."""
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        rows = await conn.fetch(
            """
            SELECT role, content, created_at
            FROM bot_builder_messages
            WHERE business_id = $1
            ORDER BY created_at DESC, CASE WHEN role = 'assistant' THEN 0 ELSE 1 END
            LIMIT $2
            """,
            business_id,
            _HISTORY_LIMIT,
        )
    # Fetched newest-first for the LIMIT; reverse so the UI reads oldest→newest.
    messages = [
        BotAiMessage(
            role=row["role"],
            content=row["content"] or "",
            created_at=row["created_at"].isoformat(),
        )
        for row in reversed(rows)
    ]
    return BotAiHistoryResponse(messages=messages)


# --- helpers -----------------------------------------------------------------

async def _persist_turn(
    request: Request,
    business_id: str,
    author_user_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    """Insert the user message + assistant reply in one tenant-scoped transaction.

    RLS scopes the write to this business; `author_user_id` is the verified
    session user. We never log the message bodies.
    """
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        await conn.executemany(
            """
            INSERT INTO bot_builder_messages (business_id, author_user_id, role, content)
            VALUES ($1, $2, $3, $4)
            """,
            [
                (business_id, author_user_id, "user", user_message),
                (business_id, author_user_id, "assistant", assistant_reply),
            ],
        )
