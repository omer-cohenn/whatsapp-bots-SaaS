"""The bot RUNTIME — where the pure engine meets the persistence layer (M5).

`bot_engine.advance(...)` is a pure function: it turns one message + the current
conversation state into replies + the next state, with ZERO I/O. `run_turn(...)`
here is the thin orchestrator that wraps it with the real world:

  * it LOADS the conversation's state + status from Redis
    (`conversation_state`),
  * it LOADS this tenant's bot config from Postgres (`bot_settings_service`),
  * it RUNS the engine,
  * it PERSISTS the engine's result — the lead lifecycle + funnel events — into
    Postgres (`leads`), inside ONE tenant-scoped transaction, and
  * it SAVES the next conversation state back to Redis.

Two product rules are enforced here, not in the engine:

  1. HUMAN HANDOFF MEANS SILENCE. If the chat's status is 'human' (an owner took
     over), the bot does NOT answer at all — it returns no replies. The engine is
     never even consulted. The owner is driving; the bot must not talk over them.
  2. TEST vs REAL. `is_test=True` (the try-me/sim path) tags every lead + event
     it persists, so sandbox data never pollutes a business's real funnel.

Tenant safety: `business_id` is ALWAYS the caller's already-verified id (from the
server session / a trusted inbound mapping), never a raw client value. Every DB
write goes through `tenant_connection(...)` so RLS scopes it; every Redis key is
business-prefixed and re-checked. We NEVER log message text, replies, or any PII.
"""

from __future__ import annotations

from typing import Any

import asyncpg
import redis.asyncio as aioredis

from app.core.logging import get_logger
from app.db.session import tenant_connection
from app.services import (
    bot_engine,
    bot_settings as bot_settings_service,
    conversation_state,
    leads as leads_service,
)

log = get_logger("app.services.bot_runtime")

# We stash the active lead's id ON the persisted ConvState under this key. The
# pure engine never sees or touches it (it normalizes the state to its own four
# known fields), so this is purely a runtime bookkeeping field that rides along
# in Redis between turns. None ⇒ no lead row open yet for this conversation.
_LEAD_ID_FIELD = "lead_id"


async def run_turn(
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    business_id: str,
    conversation_id: str,
    message: str,
    is_test: bool = False,
) -> dict[str, Any]:
    """Run ONE conversation turn end-to-end (load → engine → persist → save).

    Args:
        pool:            the asyncpg pool (a tenant connection is opened inside).
        redis:           the async Redis client (engine-state + chat-status store).
        business_id:     the caller's already-VERIFIED tenant id (never client-supplied).
        conversation_id: stable id for this conversation (e.g. a phone hash, or a
                         sim/try-me conversation id). Scoped under `business_id`.
        message:         the inbound text from the customer.
        is_test:         True for the /sim test path → persisted rows are tagged
                         is_test so they never mix with real leads/funnel.

    Returns:
        {
          "replies": [str, ...],   # what to send back ([] when silent)
          "event":   None | "lead_completed" | "handed_off" | "booking",
          "lead_id": str | None,   # the lead row this turn touched (if any)
          "silent":  bool,         # True ⇒ a human is handling; bot said nothing
        }
    """
    # 1) Load the chat status. A handed-off chat ('human') means the OWNER is
    #    driving — the bot stays completely silent and we don't run the engine.
    status = await conversation_state.get_status(redis, business_id, conversation_id)
    if status == conversation_state.STATUS_HUMAN:
        return {"replies": [], "event": None, "lead_id": None, "silent": True}

    # 2) Load the saved engine state (fall back to a fresh conversation) + pull
    #    the runtime-only active lead_id that rides along on it.
    saved_state = await conversation_state.get_state(redis, business_id, conversation_id)
    if saved_state is None:
        saved_state = bot_engine.initial_state()
    active_lead_id = saved_state.get(_LEAD_ID_FIELD)
    active_lead_id = str(active_lead_id) if active_lead_id else None

    # 3) Load this tenant's bot config (permissive read — empty for a new business).
    settings = await bot_settings_service.get_settings(pool, business_id)

    # 4) Run the PURE engine. Same inputs → same outputs; no I/O happens here.
    result = bot_engine.advance(settings, saved_state, message)
    next_state = result["state"]
    event = result["event"]

    # Did this turn START a brand-new lead flow? (We were at the menu / no lead
    # open, and the engine has now entered an in-flow phase.) The engine sets
    # phase=in_flow only when a lead questionnaire begins.
    entered_flow = (
        active_lead_id is None
        and next_state.get("phase") == bot_engine.PHASE_IN_FLOW
    )

    # 5) PERSIST everything this turn implies, in ONE tenant-scoped transaction so
    #    a create + its 'started' event (etc.) commit together or not at all.
    new_lead_id = active_lead_id
    async with tenant_connection(pool, business_id) as conn:
        if entered_flow:
            new_lead_id = await _start_lead(
                conn, business_id, conversation_id, next_state, is_test
            )

        elif active_lead_id is not None and next_state.get("phase") == bot_engine.PHASE_IN_FLOW:
            # An answered step inside an already-open lead → grow the lead + funnel.
            await _record_step(conn, business_id, active_lead_id, next_state, is_test)

        if event == "lead_completed":
            # The questionnaire finished. The completed answers are result["lead"].
            # Pass new_lead_id (not active_lead_id) so a lead created earlier in
            # THIS same turn is still finalized, not just one from a prior turn.
            new_lead_id = await _complete_lead(
                conn, business_id, new_lead_id, result, is_test
            )

        elif event == "handed_off":
            # Keyword/menu handoff → mark the chat 'human' so the bot goes silent
            # on the NEXT turn (this turn still delivered the handoff notice).
            await conversation_state.set_status(
                redis, business_id, conversation_id, conversation_state.STATUS_HUMAN
            )
        # event == "booking": Phase-2 stub in the engine; nothing to persist (M5).

    # 6) Save the next ConvState back to Redis, re-attaching the active lead_id so
    #    the NEXT turn knows which lead row to grow. (When the flow ended/handed
    #    off the engine returned a fresh menu/handed-off state → lead_id clears.)
    persist_lead_id = new_lead_id if next_state.get("phase") == bot_engine.PHASE_IN_FLOW else None
    state_to_save = dict(next_state)
    state_to_save[_LEAD_ID_FIELD] = persist_lead_id
    await conversation_state.set_state(redis, business_id, conversation_id, state_to_save)

    return {
        "replies": result["replies"],
        "event": event,
        "lead_id": new_lead_id,
        "silent": False,
    }


# --- persistence helpers (each takes the shared tenant-bound conn) ------------

async def _start_lead(
    conn: asyncpg.Connection,
    business_id: str,
    conversation_id: str,
    state: dict[str, Any],
    is_test: bool,
) -> str:
    """Open a lead row for a flow that just started + log the 'started' event."""
    flow_key = state.get("active_flow")
    lead_id = await leads_service.create_lead(
        conn,
        business_id,
        lead_name=flow_key or "",
        conversation_id=conversation_id,
        is_test=is_test,
    )
    await leads_service.log_event(
        conn, business_id, lead_id, flow_key, leads_service.EVENT_STARTED,
        step_index=state.get("step_index"), is_test=is_test,
    )
    return lead_id


async def _record_step(
    conn: asyncpg.Connection,
    business_id: str,
    lead_id: str,
    state: dict[str, Any],
    is_test: bool,
) -> None:
    """Persist progress on an open lead + log a 'step' funnel event."""
    flow_key = state.get("active_flow")
    await leads_service.update_lead(
        conn, business_id, lead_id,
        collected=state.get("collected") or {},
        last_step_index=state.get("step_index") or 0,
    )
    await leads_service.log_event(
        conn, business_id, lead_id, flow_key, leads_service.EVENT_STEP,
        step_index=state.get("step_index"), is_test=is_test,
    )


async def _complete_lead(
    conn: asyncpg.Connection,
    business_id: str,
    lead_id: str | None,
    result: dict[str, Any],
    is_test: bool,
) -> str | None:
    """Finalize a completed lead (status → 'new') + log the 'completed' event.

    `lead_id` is the row to finalize — the runtime passes `new_lead_id`, which
    covers a row created in a prior turn AND one created earlier in this same
    transaction. If it's None (no row at all) we log a structural event only.
    """
    collected = result.get("lead") or {}
    if lead_id is not None:
        await leads_service.complete_lead(conn, business_id, lead_id, collected)
    await leads_service.log_event(
        conn, business_id, lead_id, None, leads_service.EVENT_COMPLETED,
        step_index=None, is_test=is_test,
    )
    return lead_id
