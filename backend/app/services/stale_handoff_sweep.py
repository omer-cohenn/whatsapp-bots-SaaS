"""Proactive stale-conversation close — a single-runner background loop.

Any still-open conversation (a bot flow the customer abandoned mid-way, or a
'waiting'/'human' handoff nobody answered) that goes silent past
STALE_HANDOFF_SECONDS is closed here — the flowchart rule "closed = no reply for
60 min". This loop PROACTIVELY sends the customer a closing message and marks the
chat 'closed', WITHOUT waiting for the customer to message again. Already-closed
chats are skipped. (`bot_runtime` still handles the REACTIVE case: if the customer
DOES message after going stale, it resets to a fresh conversation.)

It mirrors `abandoned_sweep`'s three correctness concerns:

  1. TENANCY for a tenant-less job. The source of truth here is REDIS (status +
     last_activity), not Postgres — so there is no SECURITY DEFINER function to
     lean on. Instead we SCAN the per-business conversation index keys
     (`convindex:*`) — a cheap background scan — and for each business list its
     own conversations. Every Redis accessor is business-prefixed and re-checked
     (`_assert_owns`); the business_id is parsed from the index key WE own, never
     from a client. No cross-tenant read is possible.

  2. ONE runner, not N. A short Redis lock (`SET NX EX`) guards each pass so two
     workers never double-sweep. Closing is idempotent anyway (a chat flipped to
     'closed' no longer matches 'waiting'/'human'), so a race can't double-send.

  3. NEVER crash the loop. Any error in one pass / one conversation is logged (no
     PII) and swallowed so the loop keeps running for the next tick.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis

from app.core.logging import get_logger
from app.services import conversation_state
from app.services import whatsapp as whatsapp_service
from app.services.bot_runtime import STALE_CLOSING_MSG, STALE_HANDOFF_SECONDS

log = get_logger("app.services.stale_handoff_sweep")

# How often the loop wakes up to look for stale handoffs. Kept short so the close
# fires soon after the threshold (with a 60s threshold: closed ~60–75s after the
# last message). Cheap: one keyspace SCAN + a few Redis reads per business.
SWEEP_INTERVAL_SECONDS = 15

# The per-business conversation index keys are named `convindex:{business_id}`
# (see conversation_state._index_key). We SCAN this prefix to discover every
# business that currently has live conversations.
_INDEX_PREFIX = "convindex:"

# The Redis single-runner lock. Held a bit longer than one pass (sends can take a
# few seconds each); auto-expires so a crashed worker can't wedge the sweep.
_SWEEP_LOCK_KEY = "lock:stale_handoff_sweep"
_SWEEP_LOCK_TTL_SECONDS = 60


def _is_stale(last_activity_at: str | None) -> bool:
    """True if the last activity was more than STALE_HANDOFF_SECONDS ago.

    A missing/unparseable timestamp is treated as NOT stale (we never close a chat
    we can't age) — the reactive path in run_turn is the backstop.
    """
    if not last_activity_at:
        return False
    try:
        last_dt = datetime.fromisoformat(last_activity_at)
    except (ValueError, TypeError):
        return False
    elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
    return elapsed > STALE_HANDOFF_SECONDS


async def _business_ids(redis: aioredis.Redis) -> list[str]:
    """Every business id that currently has a conversation index set in Redis."""
    ids: list[str] = []
    async for key in redis.scan_iter(match=f"{_INDEX_PREFIX}*"):
        # key is "convindex:{business_id}"; strip the known prefix.
        business_id = key[len(_INDEX_PREFIX):]
        if business_id:
            ids.append(business_id)
    return ids


async def run_sweep_once(pool: asyncpg.Pool, redis: aioredis.Redis) -> int:
    """Run ONE sweep pass. Returns how many conversations were closed.

    For every business with live conversations, close each 'waiting'/'human' chat
    that has been silent past the threshold: send the closing message to the
    customer (best-effort — `send_outbound` never raises, returns False on
    failure), mirror it onto the transcript, then mark the chat 'closed' so the
    customer's NEXT message starts a brand-new conversation. Closing regardless of
    send success avoids retrying the same chat forever. Strictly tenant-scoped:
    the business_id comes from the index key, and every Redis accessor re-checks
    the business prefix.
    """
    closed = 0
    for business_id in await _business_ids(redis):
        try:
            convs = await conversation_state.list_conversations(redis, business_id)
        except Exception:
            # One bad business must not abort the whole pass. No PII in the log.
            log.warning("stale handoff sweep: failed to list one business")
            continue

        for conv in convs:
            # Close ANY still-open conversation gone silent past the threshold —
            # a bot flow the customer abandoned, or a waiting/human handoff nobody
            # answered (flowchart: "closed = no reply for 60 min"). Already-closed
            # chats are skipped (idempotent — they won't be re-closed / re-messaged).
            status = conv.get("status") or conversation_state.STATUS_BOT
            if status == conversation_state.STATUS_CLOSED:
                continue
            if not _is_stale(conv.get("last_activity_at")):
                continue

            conversation_id = conv["conversation_id"]
            try:
                # 1) Send the closing message to the customer. conversation_id IS
                #    the customer's WhatsApp jid (best-effort; never raises). M6b:
                #    name the business so the gateway uses its socket.
                await whatsapp_service.send_outbound(
                    business_id, conversation_id, STALE_CLOSING_MSG
                )
                # 2) Mirror it onto the transcript so the owner sees what was sent.
                await conversation_state.append_message(
                    redis, business_id, conversation_id, "bot", STALE_CLOSING_MSG
                )
                # 3) Close the chat → next inbound is treated as a new conversation.
                await conversation_state.set_status(
                    redis, business_id, conversation_id,
                    conversation_state.STATUS_CLOSED,
                )
                closed += 1
            except Exception:
                # Generic, no str(e) / no PII / no jid in the log. Keep sweeping.
                log.warning("stale handoff sweep: failed to close one conversation")

    return closed


async def sweep_loop(pool: asyncpg.Pool, redis: aioredis.Redis) -> None:
    """The forever-loop: every SWEEP_INTERVAL_SECONDS, sweep under a Redis lock.

    Cancelled by the app lifespan on shutdown (a `CancelledError` breaks cleanly).
    Never raises out of the loop body — a failed pass is logged and retried next
    tick, so one bad pass never kills the background task.
    """
    log.info("stale handoff sweep loop started")
    try:
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            try:
                # Single-runner guard: only the worker that wins the lock sweeps.
                got_lock = await redis.set(
                    _SWEEP_LOCK_KEY, "1", nx=True, ex=_SWEEP_LOCK_TTL_SECONDS
                )
                if not got_lock:
                    continue
                closed = await run_sweep_once(pool, redis)
                if closed:
                    # Count only — never conversation ids or any PII.
                    log.info("stale handoff sweep pass complete", extra={"closed": closed})
            except asyncio.CancelledError:
                raise
            except Exception:
                # Generic, no str(e) / no PII — keep the loop alive for next tick.
                log.warning("stale handoff sweep pass failed")
    except asyncio.CancelledError:
        log.info("stale handoff sweep loop stopped")
        raise
