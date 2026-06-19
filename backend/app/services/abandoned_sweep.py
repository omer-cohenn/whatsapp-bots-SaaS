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

log = get_logger("app.services.abandoned_sweep")

# How often the loop wakes up to look for idle leads.
SWEEP_INTERVAL_SECONDS = 60
# A lead idle (no new answer) for longer than this is considered abandoned.
ABANDONED_AFTER_MINUTES = 60

# The Redis single-runner lock. Held just longer than one pass takes; it auto-
# expires so a crashed worker can never wedge the sweep permanently.
_SWEEP_LOCK_KEY = "lock:abandoned_sweep"
_SWEEP_LOCK_TTL_SECONDS = 30


async def run_sweep_once(pool: asyncpg.Pool) -> int:
    """Run ONE sweep pass. Returns how many leads were marked abandoned.

    Delegates the cross-tenant write to the `sweep_abandoned_leads` SECURITY
    DEFINER function (see migration 0006 + this module's docstring). app_role has
    EXECUTE on it; no `app.business_id` context is needed because the function
    keeps every row tenant-correct internally.
    """
    async with pool.acquire() as conn:
        swept = await conn.fetchval(
            "SELECT sweep_abandoned_leads($1)", ABANDONED_AFTER_MINUTES
        )
    return int(swept or 0)


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
                swept = await run_sweep_once(pool)
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
