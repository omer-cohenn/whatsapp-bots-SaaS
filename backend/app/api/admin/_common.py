# בק‑אופיס מנהל — עוזרים משותפים (פענוח תאריכים, גבול אורך id, לוגר)
"""Shared admin-router helpers + constants (M12/M13).

The small pieces reused across the admin sub-routers: the per-request logger, the
defensive business-id length bound, and the date/timestamp/jsonb parsers that map
bad input to the right HTTP error. Moved VERBATIM from the old single-file
`admin.py` — no logic change.
"""

from __future__ import annotations

import json
from datetime import date, datetime

from fastapi import HTTPException, status

from app.core.logging import get_logger

log = get_logger("app.api.admin")

# A business id arrives in the path as a UUID string. Bound its length defensively
# before it ever reaches an SD function; an unparsable value → the SD function's
# uuid cast raises invalid_text_representation, which we map to 404 (not found).
_BUSINESS_ID_MAX = 64


def _iso(value: object) -> str | None:
    """ISO-8601 a date/timestamptz (or None passes through)."""
    return value.isoformat() if value is not None else None  # type: ignore[attr-defined]


def _parse_date_or_422(value: str | None, field: str) -> date | None:
    """Parse an ISO YYYY-MM-DD query value to a date, or 422 (None passes through)."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid {field} date (expected YYYY-MM-DD)",
        ) from None


def _parse_timestamp_or_422(value: str | None, field: str) -> datetime | None:
    """Parse an ISO-8601 timestamp body value to a datetime, or 422.

    Used for the CRM `next_followup` (a follow-up reminder time). None / blank
    passes through as None (clears the reminder). The SD function takes a
    timestamptz; asyncpg binds the datetime safely.
    """
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid {field} timestamp (expected ISO-8601)",
        ) from None


def _as_dict(value: object) -> dict:
    """asyncpg returns jsonb as a str; normalize to a dict (default {})."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
