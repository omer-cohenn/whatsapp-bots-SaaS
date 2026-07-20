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

  1. HANDOFF MEANS SILENCE. If the chat's status is 'waiting' (a customer asked
     for a human, nobody has picked up yet) or 'human' (an owner took over), the
     bot does NOT answer at all — it returns no replies and the engine is never
     consulted. BUT we still record the inbound customer message on the transcript
     first, so the owner sees incoming messages while handling the chat.
  2. TEST vs REAL. `is_test=True` (the try-me/sim path) tags every lead + event
     it persists, so sandbox data never pollutes a business's real funnel.

Tenant safety: `business_id` is ALWAYS the caller's already-verified id (from the
server session / a trusted inbound mapping), never a raw client value. Every DB
write goes through `tenant_connection(...)` so RLS scopes it; every Redis key is
business-prefixed and re-checked. We NEVER log message text, replies, or any PII.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import asyncpg
import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import tenant_connection
from app.services import (
    bot_engine,
    booking as booking_service,
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

# If a human-handoff chat has had no activity for this long it is considered
# stale. Used in TWO places (shared, so they can never drift apart):
#   * proactively — `stale_handoff_sweep` closes the chat + sends the closing
#     message once this long passes, WITHOUT waiting for the customer, and
#   * reactively — here in run_turn, if the customer DOES message again after
#     going stale, we reset to a brand-new conversation (greet again).
STALE_HANDOFF_SECONDS = 3600  # 1 hour

# Closing message sent to the customer when a stale handoff is closed (by either
# the proactive sweeper or the reactive reset below).
STALE_CLOSING_MSG = (
    "עקב חוסר מענה הפניה נסגרה. המשך יום טוב! "
    "לפניות נוספות שלח הודעה חוזרת."
)


async def run_turn(
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    business_id: str,
    conversation_id: str,
    message: str,
    is_test: bool = False,
    media: dict[str, Any] | None = None,
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
        media:           OPTIONAL reference to a file the customer attached to
                         this message — `{"file_id","mime_type","name"}`, already
                         stored by the gateway via POST /internal/wa/media. Only
                         the live WhatsApp webhook ever supplies it; try-me and
                         /sim pass None, so those paths are unchanged. It is
                         passed straight through to the pure engine (no bytes, no
                         storage access here) and is NEVER logged.

    Returns:
        {
          "replies": [str, ...],   # what to send back ([] when silent)
          "event":   None | "lead_completed" | "handed_off" | "booking",
          "lead_id": str | None,   # the lead row this turn touched (if any)
          "silent":  bool,         # True ⇒ a human is handling; bot said nothing
        }
    """
    stale_reset = False  # set True when we auto-close a stale handoff this turn

    # 1) Load the chat status. A chat that's 'waiting' (customer asked for a human,
    #    not yet picked up) or 'human' (an owner took over) means the bot stays
    #    completely silent and we don't run the engine. We STILL append the inbound
    #    customer message to the transcript first, so the owner sees what's coming
    #    in while they handle the chat.
    status = await conversation_state.get_status(redis, business_id, conversation_id)
    if status in (conversation_state.STATUS_WAITING, conversation_state.STATUS_HUMAN):
        # Stale-handoff check: if the last activity on this chat was > 1 hour ago,
        # the human never came back. Reset the conversation so the next inbound is
        # treated as a brand-new customer (greeting + menu). The old lead row in
        # Postgres is left intact; only the Redis state is wiped.
        last_activity_str = await conversation_state.get_last_activity_at(
            redis, business_id, conversation_id
        )
        is_stale = False
        if last_activity_str:
            try:
                last_dt = datetime.fromisoformat(last_activity_str)
                elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
                is_stale = elapsed > STALE_HANDOFF_SECONDS
            except (ValueError, TypeError):
                pass

        if is_stale:
            # Wipe the stale handoff — fall through to fresh-start processing below.
            # The closing message is prepended to the bot's greeting replies later.
            await conversation_state.reset_conversation(redis, business_id, conversation_id)
            status = None
            stale_reset = True
        else:
            # Human is actively handling — bot stays silent.
            await conversation_state.append_message(
                redis, business_id, conversation_id, "customer", message
            )
            # Unread badge (decision 0021): every inbound CUSTOMER message bumps the
            # owner's unread counter — even on this silent human/waiting path, since
            # "unread" means the owner hasn't opened the chat, not "the bot answered".
            await conversation_state.incr_unread(redis, business_id, conversation_id)
            # Clock fix (decision 0021): the bot never runs here, so nothing would
            # bump the lead's last_activity_at — a customer chatting with a HUMAN for
            # >60 min would be wrongly swept to 'abandoned'. Reset the clock on the
            # active lead for this conversation (no-op if there is none). Tenant-scoped
            # via tenant_connection + a business_id-filtered UPDATE; touches no PII.
            async with tenant_connection(pool, business_id) as conn:
                active_lead_id = await leads_service.get_active_lead_id_by_conversation(
                    conn, business_id, conversation_id
                )
                if active_lead_id is not None:
                    await leads_service.touch_lead_activity(
                        conn, business_id, active_lead_id
                    )
            return {"replies": [], "event": None, "lead_id": None, "silent": True}

    # 1a) A CLOSED chat that gets a new inbound starts over fresh. We wipe this
    #     conversation's Redis state, transcript, and status hash, then FALL
    #     THROUGH to the normal flow below. Because the reset clears everything,
    #     the rest of run_turn now behaves exactly like a brand-new conversation:
    #     a fresh transcript, get_state → None (→ initial_state), and the engine
    #     emits the greeting+menu open turn. The OLD closed lead row in Postgres
    #     is left untouched, so the finished chat's history is preserved.
    #
    #     Goal 7 (verified, decision 0021): both paths yield greeting+menu —
    #       * a BRAND-NEW number → get_status is None (not waiting/human/closed),
    #         get_state is None → initial_state → the engine's open turn greets.
    #       * a CLOSED chat → this reset wipes state, so it behaves identically to
    #         the brand-new case on the SAME turn (no behavior change, just clarity).
    if status == conversation_state.STATUS_CLOSED:
        await conversation_state.reset_conversation(redis, business_id, conversation_id)

    # 1b) Non-silent turn: record the inbound customer message on the transcript
    #     so the in-app chat view shows it alongside the bot's replies below.
    await conversation_state.append_message(
        redis, business_id, conversation_id, "customer", message
    )
    # Unread badge (decision 0021): bump the owner's unread counter on every
    # inbound CUSTOMER message — the bot answering does NOT mark it read, only the
    # owner opening the chat does (see conversation_state.mark_read). If this is a
    # fresh start after a CLOSED reset (step 1a wiped the counter), it begins at 1.
    await conversation_state.incr_unread(redis, business_id, conversation_id)

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
    result = bot_engine.advance(settings, saved_state, message, media)
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
    # When the engine fires a "booking" event, we rewrite the demo link in the
    # reply with this tenant's REAL public booking URL (fix B7). Resolved inside
    # the transaction (the slug read is RLS-scoped); applied to the replies in
    # step 7 below. None ⇒ no rewrite (not a booking turn).
    real_booking_link: str | None = None
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
            # Keyword/menu handoff → the customer asked for a human. Mark the chat
            # 'waiting' (NOT yet 'human' — nobody has picked up) so the bot goes
            # silent on the NEXT turn; this turn still delivers the handoff notice.
            await conversation_state.set_status(
                redis, business_id, conversation_id, conversation_state.STATUS_WAITING
            )
            # M9: a handoff ALWAYS yields a lead, so the owner sees every "ביקש
            # נציג" request in the leads list. If no lead is open for this chat,
            # create a minimal one first (still inside this tenant transaction),
            # then attach the handoff event to it. lead_name is a generic label
            # (no PII); status defaults to 'in_progress' from create_lead.
            handoff_lead_id = new_lead_id
            if handoff_lead_id is None:
                handoff_lead_id = await leads_service.create_lead(
                    conn,
                    business_id,
                    lead_name="פנייה לנציג",
                    conversation_id=conversation_id,
                    is_test=is_test,
                )
                new_lead_id = handoff_lead_id
            # Log a funnel event so the dashboard can raise a "ביקש נציג" notice.
            # Tenant-scoped via `conn`, is_test honored; carries no PII.
            await leads_service.log_event(
                conn, business_id, handoff_lead_id, None,
                leads_service.EVENT_HANDOFF, step_index=None, is_test=is_test,
            )

        elif event == "booking":
            # M11 (fix B7): a real booking flow. The customer picked the booking
            # option; the bot must send the REAL public booking link (built from
            # booking_settings.slug), not the engine's demo placeholder. We also
            # create/link a LEAD so the request shows in the owner's pipeline
            # (consistent with M9/M10), then the customer books on the web page.
            booking_lead_id = new_lead_id
            if booking_lead_id is None:
                booking_lead_id = await leads_service.create_lead(
                    conn,
                    business_id,
                    lead_name="בקשת תור",
                    conversation_id=conversation_id,
                    is_test=is_test,
                )
                new_lead_id = booking_lead_id
            # Resolve this tenant's public booking slug (RLS-scoped read) and
            # build the real link to swap into the reply in step 7.
            booking_settings = await booking_service.get_settings(conn, business_id)
            slug = booking_settings.get("slug")
            if slug:
                base = get_settings().public_base_url.rstrip("/")
                real_booking_link = f"{base}/book/{slug}"

    # 6) Save the next ConvState back to Redis, re-attaching the active lead_id so
    #    the NEXT turn knows which lead row to grow. (When the flow ended/handed
    #    off the engine returned a fresh menu/handed-off state → lead_id clears.)
    persist_lead_id = new_lead_id if next_state.get("phase") == bot_engine.PHASE_IN_FLOW else None
    state_to_save = dict(next_state)
    state_to_save[_LEAD_ID_FIELD] = persist_lead_id
    await conversation_state.set_state(redis, business_id, conversation_id, state_to_save)

    # 6b) On a booking turn, swap the engine's DEMO link for this tenant's REAL
    #     public booking URL (fix B7). The engine already substituted its demo
    #     placeholder into the reply; we replace that exact placeholder so the
    #     customer receives a working link. If the slug couldn't be resolved we
    #     leave the demo text rather than send a broken URL.
    replies = list(result["replies"])
    # Prepend the closing notice before the bot's greeting when a stale handoff
    # was just auto-reset so the customer understands why the conversation restarted.
    if stale_reset:
        replies = [STALE_CLOSING_MSG] + replies
    if real_booking_link:
        replies = [
            r.replace(bot_engine.DEMO_BOOKING_LINK, real_booking_link) for r in replies
        ]

    # 7) Mirror each bot reply onto the transcript (role="bot") so the owner's
    #    chat view shows the full exchange — customer line + the bot's answers.
    for reply in replies:
        await conversation_state.append_message(
            redis, business_id, conversation_id, "bot", reply
        )

    # 7b) When the bot FINISHES the conversation — a lead questionnaire completed,
    #     or a booking link was delivered — the session is DONE. Mark the chat
    #     'closed' so the NEXT inbound restarts a brand-new conversation (greeting +
    #     fresh transcript + a new lead), per the "each interaction is its own
    #     conversation" rule. The reset itself runs on that next inbound (the
    #     `status == closed` branch in step 1a). The completed lead row stays in
    #     Postgres (the owner reviews it in the leads list). Handoff is excluded —
    #     it goes to 'waiting' so a human can take over, not reset.
    if event in ("lead_completed", "booking"):
        await conversation_state.set_status(
            redis, business_id, conversation_id, conversation_state.STATUS_CLOSED
        )

    return {
        "replies": replies,
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
