# מחברת הלידים — קריאה: רשימת לידים לבעלים + פענוח + שליפה לפי שיחה
"""Lead read side (M7): list + decrypt leads for the owner dashboard.

The owner is the ONE party allowed to see the plaintext: list rows are decrypted
HERE (phone, contact_name, and the whole answers blob) so the API can hand the
dashboard a readable object. Reads are RLS-scoped via the tenant-bound `conn`.
We NEVER log a decrypted value. Moved VERBATIM from the old single-file
`leads.py` — no logic change.
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from app.core import crypto
from app.services.leads._common import (
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    STATUS_ABANDONED,
    STATUS_DEAL,
    STATUS_CLOSED,
    _iso,
    _period_clause,
)

# The status filter vocabulary the dashboard exposes. 'open' is SYNTHETIC:
# new + in_progress (everything still actionable), not a stored status value.
STATUS_OPEN = "open"
_OPEN_STATUSES = (STATUS_NEW, STATUS_IN_PROGRESS)
# The stored status values a caller may filter on directly (a plain `status = $n`).
# 'deal' + 'closed' are owner-set outcomes (M9) and ARE stored values, so they
# belong here too. 'open' stays SYNTHETIC (handled separately above).
_REAL_STATUSES = {
    STATUS_NEW, STATUS_IN_PROGRESS, STATUS_ABANDONED, STATUS_DEAL, STATUS_CLOSED,
}


async def list_leads(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    period: str | None = None,
    status: str | None = None,
    flow: str | None = None,
    include_test: bool = False,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Return this tenant's leads (newest first), decrypted for the owner.

    Filters (all optional):
      * period — 'week' | 'month' | 'all' (anything else == 'all').
      * status — 'new' | 'in_progress' | 'abandoned' | 'deal' | 'closed' |
                 'open' (= new+in_progress); 'all'/None means no status filter.
      * flow   — match a specific `lead_name` (the questionnaire).
      * include_test — when False (default) `is_test` rows are excluded.

    Each returned lead carries ALL its collected answers (full detail for the
    owner). `business_id` is the caller's verified id; it is included in the WHERE
    so RLS's predicate matches the tenant. NEVER logs any decrypted value.
    """
    params: list[Any] = [business_id]
    where = ["business_id = $1"]

    if not include_test:
        where.append("is_test = false")

    status_key = (status or "all").lower()
    if status_key == STATUS_OPEN:
        where.append("status = ANY($%d::text[])" % (len(params) + 1))
        params.append(list(_OPEN_STATUSES))
    elif status_key in _REAL_STATUSES:
        params.append(status_key)
        where.append(f"status = ${len(params)}")
    # 'all'/unknown → no status predicate.

    if flow:
        params.append(flow)
        where.append(f"lead_name = ${len(params)}")

    # Time window is keyed off last_activity_at (the lead's most recent touch).
    period_sql = _period_clause(period, params, "last_activity_at")

    params.append(int(limit))
    sql = (
        "SELECT id, lead_name, phone, contact_name, answers, status, "
        "       outcome_note, last_step_index, is_test, key_version, "
        "       cache_chat_ref, started_at, last_activity_at, submitted_at "
        "FROM leads "
        f"WHERE {' AND '.join(where)}{period_sql} "
        f"ORDER BY last_activity_at DESC "
        f"LIMIT ${len(params)}"
    )
    rows = await conn.fetch(sql, *params)
    return [_decrypt_lead_row(row, business_id) for row in rows]


async def get_lead_by_conversation(
    conn: asyncpg.Connection,
    business_id: str,
    conversation_id: str,
) -> dict[str, Any] | None:
    """Return the lead linked to THIS conversation (decrypted), or None if none.

    A conversation can spawn several lead rows over time (one per flow start), so
    we return the NEWEST match. We join via the same `cache_chat_ref` that
    `create_lead` stamps (the live Redis conversation key). `business_id` is the
    caller's verified id and is in the WHERE so RLS scopes the read to this tenant.
    Reuses `_decrypt_lead_row`, so phone/name/answers come back as plaintext for
    the owner — NEVER logged.
    """
    cache_chat_ref = f"conv:{business_id}:{conversation_id}"
    row = await conn.fetchrow(
        """
        SELECT id, lead_name, phone, contact_name, answers, status,
               outcome_note, last_step_index, is_test, key_version,
               cache_chat_ref, started_at, last_activity_at, submitted_at
        FROM leads
        WHERE business_id = $1 AND cache_chat_ref = $2
        ORDER BY last_activity_at DESC
        LIMIT 1
        """,
        business_id,
        cache_chat_ref,
    )
    return _decrypt_lead_row(row, business_id) if row is not None else None


def _decrypt_lead_row(row: asyncpg.Record, business_id: str) -> dict[str, Any]:
    """Map one leads row → a readable dict with phone/name/answers decrypted.

    The stored `answers` jsonb is the {"_": ciphertext} blob; we decrypt it back
    to the full collected dict. The dedicated phone/contact_name columns are
    decrypted too. A row's own stamped `key_version` selects the key (rotation).

    `conversation_id` is derived from `cache_chat_ref` (which `create_lead` stamps
    as "conv:{business_id}:{conversation_id}") by stripping this tenant's prefix;
    None when there is no ref. `business_id` is the caller's verified id and is
    used only to build that prefix — it never widens the read.
    """
    key_version = row["key_version"] or crypto.CURRENT_KEY_VERSION
    answers_blob = row["answers"]
    if isinstance(answers_blob, str):
        # asyncpg may hand jsonb back as text; normalize to a dict for decrypt.
        try:
            answers_blob = json.loads(answers_blob)
        except (ValueError, TypeError):
            answers_blob = None

    answers = crypto.decrypt_answers(answers_blob, key_version) if answers_blob else {}
    phone = crypto.decrypt_pii(row["phone"], key_version)
    contact_name = crypto.decrypt_pii(row["contact_name"], key_version)
    # The owner's outcome note is encrypted at rest; decrypt for the owner (None
    # when never set). Never logged.
    outcome_note = crypto.decrypt_pii(row["outcome_note"], key_version)

    # Recover the conversation id by stripping this tenant's "conv:{bid}:" prefix
    # from cache_chat_ref. Only strip when the prefix matches (tenant-correct);
    # otherwise leave it None rather than expose a foreign/odd ref.
    cache_chat_ref = row["cache_chat_ref"]
    conversation_id: str | None = None
    if cache_chat_ref:
        prefix = f"conv:{business_id}:"
        if cache_chat_ref.startswith(prefix):
            conversation_id = cache_chat_ref[len(prefix):]

    return {
        "id": str(row["id"]),
        "lead_name": row["lead_name"],
        "phone": phone,
        "contact_name": contact_name,
        "answers": answers,
        "status": row["status"],
        "outcome_note": outcome_note,
        "last_step_index": row["last_step_index"],
        "is_test": row["is_test"],
        "conversation_id": conversation_id,
        "started_at": _iso(row["started_at"]),
        "last_activity_at": _iso(row["last_activity_at"]),
        "submitted_at": _iso(row["submitted_at"]),
    }
