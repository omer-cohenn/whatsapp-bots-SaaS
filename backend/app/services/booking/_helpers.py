# לוגיקת התורים — קבועים ועוזרים משותפים (אזור זמן, סטטוסים, סריאליזציה)
"""Shared booking constants + tiny serialization helpers (M11).

These are the cross-module pieces of the booking domain (timezone, active-status
set, default working hours, slug/token sizes, and the small JSON/ISO helpers).
They live here so `settings.py`, `slots.py`, and `crud.py` can all import them
without importing each other in a cycle. Moved VERBATIM from the old single-file
`booking.py` — no logic change.
"""

from __future__ import annotations

import json
from typing import Any
from zoneinfo import ZoneInfo

# The fixed business timezone (decision 0011). Stored times are UTC; the owner's
# working hours + the public page speak this local wall-clock.
BUSINESS_TZ = ZoneInfo("Asia/Jerusalem")

# A booked slot that is NOT one of these is "live" and blocks its time. A
# cancelled booking frees its slot again.
_ACTIVE_BOOKING_STATUSES = ("pending", "confirmed", "completed")

# Sensible default working hours for a brand-new business (so the page isn't
# empty before the owner configures anything): Sun–Thu 09:00–17:00. The owner
# overrides this in settings. Weekday "0"=Sun .. "6"=Sat.
_DEFAULT_WORKING_HOURS = {
    "0": [{"s": "09:00", "e": "17:00"}],
    "1": [{"s": "09:00", "e": "17:00"}],
    "2": [{"s": "09:00", "e": "17:00"}],
    "3": [{"s": "09:00", "e": "17:00"}],
    "4": [{"s": "09:00", "e": "17:00"}],
}

# The slug is the public, non-guessable booking-page handle. token_urlsafe(9)
# gives ~12 url-safe chars — short enough to share, long enough to be unguessable.
_SLUG_BYTES = 9
# The cancel_token must be unguessable (a customer cancels with ONLY this token).
_CANCEL_TOKEN_BYTES = 24


def _as_obj(value: Any, default: Any) -> Any:
    """asyncpg returns jsonb as a str; normalize to a Python object."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _iso(value: Any) -> str | None:
    """ISO-8601 a timestamptz (or None passes through)."""
    return value.isoformat() if value is not None else None
