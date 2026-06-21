"""Booking reminders sweep — confirmations + day-before nudges (M11 runtime).

A booked appointment needs two outbound touches the customer cares about:

  * a CONFIRMATION shortly after booking ("your appointment is set"), and
  * a DAY-BEFORE reminder ("see you tomorrow").

WhatsApp sending is M6 (not wired yet), so this sweep does NOT send — it QUEUES
each touch into a Redis OUTBOX (`booking:outbox:{business_id}`), exactly like the
live-chat manual-reply outbox. When M6 lands, its sender drains this list and
delivers for real. The outbox entry carries the booking id + kind + scheduled
time only — NEVER any PII (name/phone/email): the M6 sender re-reads + decrypts
the booking row itself when it sends.

Design (mirrors `abandoned_sweep.py`):

  1. TENANT-LESS read. The sweep has no single tenant, and bookings has RLS
     FORCED under app_role. It calls ONE tightly-scoped SECURITY DEFINER read,
     `bookings_due_for_reminder(window_hours)` (migration 0010), which returns
     ONLY structural fields (id/business_id/scheduled_at/status) — no PII.
  2. EXACTLY-ONCE-ish via Redis markers. Each (booking, kind) gets a `SET NX`
     marker so a touch is queued at most once even across ticks / workers. The
     marker TTL outlives the appointment so it can't re-fire.
  3. ONE runner. A short Redis lock (`SET NX EX`) around each pass so multiple
     workers don't double-queue. A worker that can't get the lock skips the tick.
  4. NEVER crash the loop. Any error in a pass is logged generically (no PII) and
     swallowed so the loop survives for the next tick.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import asyncpg
import redis.asyncio as aioredis

from app.core.logging import get_logger

log = get_logger("app.services.booking_reminders")

# How often the loop wakes up to look for due reminders.
SWEEP_INTERVAL_SECONDS = 5 * 60
# How far ahead we look for appointments needing a touch (covers the day-before
# reminder + new confirmations comfortably).
LOOKAHEAD_HOURS = 48
# Queue the day-before reminder once the appointment is within this many hours.
DAY_BEFORE_HOURS = 24

# Outbox + marker keys (business-prefixed, like the live-chat outbox).
def _outbox_key(business_id: str) -> str:
    return f"booking:outbox:{business_id}"


def _marker_key(booking_id: str, kind: str) -> str:
    # Global marker (booking ids are uuids → globally unique); kind keeps the two
    # touches independent. NOT business-prefixed on purpose: the booking id alone
    # is unique, and the marker holds no tenant-sensitive data.
    return f"booking:reminder:{kind}:{booking_id}"


# A queued touch lives long enough that we never re-queue it for the same booking.
_MARKER_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

# Single-runner lock (auto-expires so a crashed worker can't wedge the sweep).
_SWEEP_LOCK_KEY = "lock:booking_reminders"
_SWEEP_LOCK_TTL_SECONDS = 60


async def run_sweep_once(pool: asyncpg.Pool, redis: aioredis.Redis) -> int:
    """Run ONE reminder pass. Returns how many touches were queued this pass.

    Reads due bookings via the SECURITY DEFINER function (no PII), then for each
    queues a confirmation (always, if not yet queued) and — when the start is
    within DAY_BEFORE_HOURS — a day-before reminder. Each is guarded by a Redis
    `SET NX` marker so it's queued at most once. Test bookings are skipped.
    """
    rows = await _due_bookings(pool)
    now = datetime.now(timezone.utc)
    queued = 0
    for row in rows:
        if row["is_test"]:
            continue
        business_id = str(row["business_id"])
        booking_id = str(row["id"])
        scheduled_at = row["scheduled_at"]

        # Confirmation: queue once per booking (its existence in the window means
        # it's a live, future appointment).
        if await _queue_touch(redis, business_id, booking_id, "confirmation", scheduled_at):
            queued += 1

        # Day-before reminder: only once the appointment is within the window.
        if scheduled_at - now <= timedelta(hours=DAY_BEFORE_HOURS):
            if await _queue_touch(redis, business_id, booking_id, "reminder", scheduled_at):
                queued += 1
    return queued


async def _due_bookings(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Fetch upcoming bookings needing a touch via the definer read (no PII)."""
    async with pool.acquire() as conn:
        return await conn.fetch(
            "SELECT * FROM bookings_due_for_reminder($1)", LOOKAHEAD_HOURS
        )


async def _queue_touch(
    redis: aioredis.Redis,
    business_id: str,
    booking_id: str,
    kind: str,
    scheduled_at: datetime,
) -> bool:
    """Queue ONE outbox touch if not already queued. Returns True if newly queued.

    The `SET NX` marker is the exactly-once guard. The outbox entry is PII-free:
    just the booking id + kind + scheduled time. The M6 sender will re-read the
    booking row and decrypt the customer's details when it actually sends.
    """
    marker = _marker_key(booking_id, kind)
    fresh = await redis.set(marker, "1", nx=True, ex=_MARKER_TTL_SECONDS)
    if not fresh:
        return False
    entry = json.dumps(
        {
            "booking_id": booking_id,
            "kind": kind,  # "confirmation" | "reminder"
            "scheduled_at": scheduled_at.isoformat(),
        },
        ensure_ascii=False,
    )
    await redis.rpush(_outbox_key(business_id), entry)
    return True


async def queue_booking_message(
    redis: aioredis.Redis,
    business_id: str,
    booking_id: str,
    kind: str,
    scheduled_at: datetime | str,
) -> bool:
    """Public one-off enqueue for an event-driven booking message.

    Used when the OWNER confirms a booking (kind="approved") so the customer gets
    a "your appointment is confirmed" message from the business's WhatsApp number.
    Reuses the same outbox + once-marker as the sweep, so re-confirming won't
    double-send. The M6 sender drains the outbox and delivers for real; until then
    the message simply waits in the queue. `scheduled_at` may be a datetime or ISO.
    """
    if isinstance(scheduled_at, str):
        scheduled_at = datetime.fromisoformat(scheduled_at)
    return await _queue_touch(redis, business_id, booking_id, kind, scheduled_at)


async def sweep_loop(pool: asyncpg.Pool, redis: aioredis.Redis) -> None:
    """The forever-loop: every SWEEP_INTERVAL_SECONDS, sweep under a Redis lock.

    Cancelled by the app lifespan on shutdown (CancelledError breaks cleanly).
    Never raises out of the loop body — a failed pass is logged + retried next
    tick. Never logs PII (only a count).
    """
    log.info("booking reminders loop started")
    try:
        while True:
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
            try:
                got_lock = await redis.set(
                    _SWEEP_LOCK_KEY, "1", nx=True, ex=_SWEEP_LOCK_TTL_SECONDS
                )
                if not got_lock:
                    continue
                queued = await run_sweep_once(pool, redis)
                if queued:
                    log.info("booking reminders pass complete", extra={"queued": queued})
            except asyncio.CancelledError:
                raise
            except Exception:
                # Generic, no str(e) / no PII — keep the loop alive for next tick.
                log.warning("booking reminders pass failed")
    except asyncio.CancelledError:
        log.info("booking reminders loop stopped")
        raise
