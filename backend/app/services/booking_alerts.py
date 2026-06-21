"""Booking alerts inbox (Redis) — owner home notifications for CUSTOMER-initiated
booking changes (M11 follow-up).

When a CUSTOMER cancels or reschedules via the public page (using their
cancel_token), we push a small, PII-FREE alert onto a per-business Redis list. The
owner's home reads it (GET /api/bookings/alerts) and resolves each booking for
display. OWNER-initiated changes (the admin PATCH) do NOT push here — this inbox
is specifically "your customer just changed a booking".

Tenant isolation: the key is business-prefixed and the caller ALWAYS passes an
already-verified business_id (from the resolved slug on the public path, or the
session on the read path). Entries carry only {booking_id, kind, at} — never PII;
the read endpoint re-reads the booking under RLS to decrypt the name for display.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

# Keep the most recent N alerts per business; older ones fall off.
ALERTS_MAX = 50
# Alerts self-expire after ~30 days of no new activity.
ALERTS_TTL_SECONDS = 30 * 24 * 60 * 60

VALID_KINDS = {"cancelled", "rescheduled"}


def _key(business_id: str) -> str:
    """The tenant-scoped Redis list key for this business's booking alerts."""
    return f"booking:alerts:{business_id}"


async def push_alert(
    redis: aioredis.Redis, business_id: str, booking_id: str, kind: str
) -> None:
    """Append one PII-free alert (customer cancelled/rescheduled) for this tenant.

    Trims to the last ALERTS_MAX and refreshes the TTL. `business_id` is the
    caller's verified id; `kind` must be one of VALID_KINDS.
    """
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid booking alert kind: {kind!r}")
    key = _key(business_id)
    entry = json.dumps(
        {
            "booking_id": booking_id,
            "kind": kind,
            "at": datetime.now(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
    )
    await redis.rpush(key, entry)
    await redis.ltrim(key, -ALERTS_MAX, -1)
    await redis.expire(key, ALERTS_TTL_SECONDS)


async def list_alerts(
    redis: aioredis.Redis, business_id: str
) -> list[dict[str, Any]]:
    """Return this tenant's booking alerts, newest first ({booking_id, kind, at}).

    PII-free — the caller resolves each booking under RLS for the display name.
    A single corrupt entry is skipped rather than failing the whole read.
    """
    raw = await redis.lrange(_key(business_id), 0, -1)
    items: list[dict[str, Any]] = []
    for r in raw:
        try:
            item = json.loads(r)
        except (ValueError, TypeError):
            continue
        if isinstance(item, dict):
            items.append(item)
    items.reverse()  # newest first
    return items
