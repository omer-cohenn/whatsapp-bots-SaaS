"""The abandoned-lead sweep — a single-runner background loop (M5 runtime).

A customer can start a lead questionnaire and then go quiet. That lead row sits
at status 'in_progress' forever unless something cleans it up. This module is
that something: every ~60s it flips in_progress leads idle longer than
ABANDONED_AFTER_MINUTES to 'abandoned' (and drops an 'abandoned' funnel event),
so the owner can follow up and the funnel reflects reality. It mirrors the
original `last_bo` `auto_close_loop` pattern (a plain `while True` + sleep task
started/cancelled by the app lifespan).

THREE correctness concerns, each handled explicitly:

  1. RLS / tenancy for a TENANT-LESS job. The backend connects as `app_role`,
     which has RLS FORCED on `leads`/`flow_events` — so a normal query is scoped
     to ONE tenant via `app.business_id`. The sweep has no request and no single
     tenant. Rather than bypass RLS in Python (we never do), it calls ONE tightly
     scoped SECURITY DEFINER function, `sweep_abandoned_leads(p_idle_minutes)`
     (migration 0006), which runs with the owner's rights and so can flip idle
     leads across ALL businesses — while keeping each row's OWN business_id and
     writing each funnel event under that same business_id (tenant-correct). The
     function touches only the status column + the structural event (NO PII).

  2. ONE runner, not N. If two backend workers each run this loop, they'd both
     try to sweep. The DB UPDATE is itself idempotent (a row already flipped to
     'abandoned' no longer matches `status='in_progress'`), so double-sweep can't
     corrupt data — but to avoid two workers doing redundant work (and two log
     lines), we take a short Redis lock (`SET NX EX`) around each pass. A worker
     that can't get the lock simply skips this tick.

  3. NEVER crash the loop. Any error in one pass is logged (no secrets, no PII)
     and swallowed so the loop keeps running for the next tick.
"""

from __future__ import annotations

import asyncio

import asyncpg
import redis.asyncio as aioredis

from app.core.logging import get_logger
from app.services import conversation_state

log = get_logger("app.services.abandoned_sweep")

# How often the loop wakes up to look for idle leads.
SWEEP_INTERVAL_SECONDS = 60
# A lead idle (no new answer) for longer than this is considered abandoned.
ABANDONED_AFTER_MINUTES = 60

# The Redis single-runner lock. Held just longer than one pass takes; it auto-
# expires so a crashed worker can never wedge the sweep permanently.
_SWEEP_LOCK_KEY = "lock:abandoned_sweep"
_SWEEP_LOCK_TTL_SECONDS = 30


def _split_chat_ref(chat_ref: str) -> tuple[str, str] | None:
    """Parse a lead's `cache_chat_ref` into (business_id, conversation_id).

    The ref is stamped by `create_lead` as ``conv:{business_id}:{conversation_id}``.
    business_id is a UUID (it never contains a colon), so we split on the FIRST
    two colons: ``conv`` / business_id / the REST (the conversation id, which CAN
    itself contain colons, e.g. a WhatsApp LID jid). This is tenant-safe because
    the ref comes from the lead's OWN row (read by the SECURITY DEFINER fn), never
    from a client. Returns None for a malformed/empty ref (skip it, don't guess).
    """
    if not chat_ref:
        return None
    parts = chat_ref.split(":", 2)
    if len(parts) != 3 or parts[0] != "conv" or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


async def run_sweep_once(pool: asyncpg.Pool, redis: aioredis.Redis) -> int:
    """Run ONE sweep pass. Returns how many leads were marked abandoned.

    Delegates the cross-tenant write to the `sweep_abandoned_leads` SECURITY
    DEFINER function (see migrations 0006/0023 + this module's docstring). app_role
    has EXECUTE on it; no `app.business_id` context is needed because the function
    keeps every row tenant-correct internally. As of decision 0021 the function
    RETURNS one row per just-abandoned lead — `(lead_id, conversation_id)` where
    conversation_id is the lead's `cache_chat_ref` (the live Redis key pointer,
    possibly NULL) — and ALSO stamps close_reason='abandoned' on the row itself.

    For each returned row that has a chat ref, we close the matching Redis
    conversation (set its status to 'closed', which applies the closed TTL) so the
    customer's NEXT message starts a brand-new conversation. The chat ref carries
    its OWN business_id (parsed out of the ref), so each close stays strictly
    tenant-scoped — we never trust or invent a business_id. The loop is crash-safe:
    one bad row is logged (no PII) and swallowed, never aborting the whole pass.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT lead_id, conversation_id FROM sweep_abandoned_leads($1)",
            ABANDONED_AFTER_MINUTES,
        )

    for row in rows:
        chat_ref = row["conversation_id"]
        if not chat_ref:
            # The lead never had a linked conversation → nothing to close in Redis.
            continue
        try:
            parsed = _split_chat_ref(chat_ref)
            if parsed is None:
                # Malformed ref — skip rather than guess a (business_id, conv) split.
                log.warning("abandoned sweep: skipped malformed chat ref")
                continue
            business_id, conversation_id = parsed
            # Tenant-scoped close: set_status re-checks the business prefix on the
            # key (`_assert_owns`) and applies the closed TTL (decision 0010).
            await conversation_state.set_status(
                redis, business_id, conversation_id, conversation_state.STATUS_CLOSED
            )
        except Exception:
            # Never let one bad conversation crash the whole sweep pass. Generic,
            # no str(e) / no PII / no chat ref in the log.
            log.warning("abandoned sweep: failed to close one conversation")

    return len(rows)


async def sweep_loop(pool: asyncpg.Pool, redis: aioredis.Redis) -> None:
    """The forever-loop: every SWEEP_INTERVAL_SECONDS, sweep under a Redis lock.

    Cancelled by the app lifespan on shutdown (a `CancelledError` breaks cleanly).
    Never raises out of the loop body — a failed pass is logged and retried next
    tick, so one bad pass never kills the background task.
    """
    log.info("abandoned sweep loop started")
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
                swept = await run_sweep_once(pool, redis)
                if swept:
                    # Count only — never lead ids, names, or any PII.
                    log.info("abandoned sweep pass complete", extra={"swept": swept})
            except asyncio.CancelledError:
                raise
            except Exception:
                # Generic, no str(e) / no PII — keep the loop alive for next tick.
                log.warning("abandoned sweep pass failed")
    except asyncio.CancelledError:
        log.info("abandoned sweep loop stopped")
        raise
