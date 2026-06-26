# מחברת הלידים — קבועים ועוזרים משותפים (סטטוסים, אירועי משפך, הצפנה)
"""Shared lead constants + tiny helpers (M5).

The vocabulary and small utilities used across the leads sub-modules: the lead
statuses, the funnel event names, the PII→column key tuples, and the JSON/ISO/
period helpers. They live here so `crud.py`, `query.py`, and `funnel.py` can all
import them without importing each other in a cycle. Moved VERBATIM from the old
single-file `leads.py` — no logic change.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

# Lead statuses (mirrors the leads.status column comment in 0003_tables.sql).
# The status column is free text, so the two OWNER-SETTABLE outcomes below need no
# migration — they are just new string values the owner can stamp from the UI.
STATUS_IN_PROGRESS = "in_progress"
STATUS_NEW = "new"
STATUS_ABANDONED = "abandoned"
STATUS_DEAL = "deal"      # owner marked it won — Hebrew label "בוצעה עסקה".
STATUS_CLOSED = "closed"  # owner closed/dismissed the lead — Hebrew "ליד סגור".

# close_reason values (decision 0021, migration 0023) — WHY a lead/conversation
# closed, separate from the owner OUTCOME above. NULL = not closed yet. These are
# plain string values stamped on the nullable leads.close_reason column (no
# migration needed beyond the additive column; mirrors how status is free text).
CLOSE_REASON_COMPLETED = "completed"  # all flow details collected → status 'new'.
CLOSE_REASON_ABANDONED = "abandoned"  # 60 min silence (stamped by the SD sweep fn).
CLOSE_REASON_ANSWERED = "answered"    # owner finished handling it after human handoff.

# The statuses an owner may manually set on a lead via the dashboard.
_SETTABLE_STATUSES = {
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    STATUS_ABANDONED,
    STATUS_DEAL,
    STATUS_CLOSED,
}

# flow_events.event values (the funnel vocabulary).
EVENT_STARTED = "started"
EVENT_STEP = "step"
EVENT_COMPLETED = "completed"
EVENT_ABANDONED = "abandoned"
# A customer asked for a human (M8 handoff). Logged so the dashboard can surface a
# "ביקש נציג" notification; carries no PII, only the structural signal.
EVENT_HANDOFF = "handed_off"
_VALID_EVENTS = {
    EVENT_STARTED, EVENT_STEP, EVENT_COMPLETED, EVENT_ABANDONED, EVENT_HANDOFF,
}

# Keys inside the engine's `collected` dict that map to dedicated PII columns.
# The engine stores answers under the step's machine `key`; by convention a phone
# step uses one of these keys and a contact-name step uses one of those below.
# English + common Hebrew variants (owners often name fields in Hebrew, e.g. the
# builder's default new-step key "שם_מלא"). Note: a value missed here is NOT lost
# — it still lives in the encrypted `answers` blob; only the dedicated, indexable
# column stays empty. (A fully robust mapping would key off the step `type` —
# future improvement once the runtime threads step types through.)
_PHONE_KEYS = (
    "phone", "phone_number", "tel", "mobile",
    "טלפון", "נייד", "פלאפון", "טלפון_נייד", "מספר_טלפון",
)
_NAME_KEYS = (
    "name", "contact_name", "full_name", "fullname",
    "שם", "שם_מלא", "שם מלא", "שם_פרטי", "שם_הלקוח",
)

# period filter → how far back to look (None == 'all', no time bound). Values are
# datetime.timedelta so asyncpg binds them NATIVELY to a Postgres interval param.
# (A plain str like "7 days" raises a DataError — asyncpg expects a timedelta.)
_PERIOD_INTERVALS = {
    "week": timedelta(days=7),
    "month": timedelta(days=30),
}


def _first_present(collected: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Return the first non-empty value among `keys` in `collected`, else None."""
    for k in keys:
        v = collected.get(k)
        if v:
            return str(v)
    return None


def _period_clause(period: str | None, params: list[Any], col: str) -> str:
    """Append a `>= now() - interval` predicate for `period`, or '' for all.

    Adds the interval to `params` (parameterized, never interpolated) and returns
    the SQL fragment (e.g. " AND last_activity_at >= now() - $2::interval").
    """
    interval = _PERIOD_INTERVALS.get((period or "all").lower())
    if interval is None:
        return ""
    params.append(interval)
    return f" AND {col} >= now() - ${len(params)}::interval"


def _iso(value: Any) -> str | None:
    """ISO-8601 a timestamptz (or None passes through)."""
    return value.isoformat() if value is not None else None


def _answers_json(blob: dict[str, str]) -> str:
    """Serialize the {"_": ct} answers blob for the jsonb column.

    asyncpg sends a Python str to a `$n::jsonb` param as a JSON document, so we
    hand it the JSON text. The blob's only value is already-encrypted ciphertext.
    """
    return json.dumps(blob, ensure_ascii=False, separators=(",", ":"))
