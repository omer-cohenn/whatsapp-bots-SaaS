"""Lead lifecycle (Postgres) — the bot's long-term notebook (M5).

Where `conversation_state.py` holds the HOT, ephemeral turn-state in Redis, THIS
module persists the durable record of what a conversation collected: a `leads`
row that walks through its lifecycle...

    in_progress  → (more answers arrive, lead grows)
    in_progress  → new        (questionnaire completed, ready for the owner)
    in_progress  → abandoned  (swept later by the runner — not built here)

...plus a `flow_events` funnel trail (started / step / completed / abandoned).

Two non-negotiables baked into every function here:

  1. RLS, always. Every write goes through `tenant_connection(pool/conn, ...)` so
     Postgres scopes it to exactly this tenant. The `business_id` is the caller's
     already-verified id (never a raw client value) — and we STILL pass it in the
     INSERT/UPDATE so RLS's WITH CHECK matches.
  2. PII encrypted at rest, never logged. `phone`, `contact_name`, and the whole
     `answers` blob are encrypted via `app/core/crypto.py` before they touch the
     DB; `key_version` is stamped so rotation stays possible. We NEVER log a phone,
     a name, or an answer value.

`is_test` (the "try-me" flag) is honored throughout: a test lead and its events
are tagged `is_test = true` so they can be filtered out of real funnel metrics.

Note on the `conn` argument: each function takes an already-open, tenant-bound
`asyncpg.Connection` (the one yielded by `tenant_connection`). This lets the
runtime agent do a create + log_event in ONE transaction, and keeps RLS context
attached to the same connection as the query.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import asyncpg

from app.core import crypto

# Lead statuses (mirrors the leads.status column comment in 0003_tables.sql).
STATUS_IN_PROGRESS = "in_progress"
STATUS_NEW = "new"
STATUS_ABANDONED = "abandoned"

# flow_events.event values (the funnel vocabulary).
EVENT_STARTED = "started"
EVENT_STEP = "step"
EVENT_COMPLETED = "completed"
EVENT_ABANDONED = "abandoned"
_VALID_EVENTS = {EVENT_STARTED, EVENT_STEP, EVENT_COMPLETED, EVENT_ABANDONED}

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


def _first_present(collected: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Return the first non-empty value among `keys` in `collected`, else None."""
    for k in keys:
        v = collected.get(k)
        if v:
            return str(v)
    return None


async def create_lead(
    conn: asyncpg.Connection,
    business_id: str,
    lead_name: str,
    conversation_id: str,
    is_test: bool,
) -> str:
    """Open a fresh lead row for a conversation that just started a flow.

    Status starts at 'in_progress'; `started_at`/`last_activity_at` default to now.
    `cache_chat_ref` points back at the live Redis conversation key so the owner's
    UI can join the durable lead to its hot live-chat entry.

    Returns the new lead's id (str). RLS-scoped via the tenant-bound `conn`.
    """
    cache_chat_ref = f"conv:{business_id}:{conversation_id}"
    row = await conn.fetchrow(
        """
        INSERT INTO leads
            (business_id, lead_name, status, is_test, key_version,
             cache_chat_ref, started_at, last_activity_at)
        VALUES ($1, $2, $3, $4, $5, $6, now(), now())
        RETURNING id
        """,
        business_id,
        lead_name,
        STATUS_IN_PROGRESS,
        is_test,
        crypto.CURRENT_KEY_VERSION,
        cache_chat_ref,
    )
    return str(row["id"])


async def update_lead(
    conn: asyncpg.Connection,
    business_id: str,
    lead_id: str,
    collected: dict[str, Any],
    last_step_index: int,
) -> None:
    """Persist progress on an in-progress lead (still status 'in_progress').

    Encrypts the PII at rest: `phone` + `contact_name` are promoted to their own
    encrypted columns when present in `collected`, and the WHOLE `collected` dict
    is encrypted as the `{"_": ciphertext}` answers blob. `last_activity_at` is
    bumped (so the abandoned-sweep clock resets) and `key_version` is stamped.

    The `business_id` is included in the WHERE so RLS scopes the update to this
    tenant's own row. NEVER logs any of the collected values.
    """
    phone_ct = crypto.encrypt_pii(_first_present(collected, _PHONE_KEYS))
    name_ct = crypto.encrypt_pii(_first_present(collected, _NAME_KEYS))
    answers_blob = crypto.encrypt_answers(collected)

    await conn.execute(
        """
        UPDATE leads
        SET phone            = $3,
            contact_name     = $4,
            answers          = $5::jsonb,
            last_step_index  = $6,
            key_version      = $7,
            last_activity_at = now()
        WHERE id = $1 AND business_id = $2
        """,
        lead_id,
        business_id,
        phone_ct,
        name_ct,
        _answers_json(answers_blob),
        last_step_index,
        crypto.CURRENT_KEY_VERSION,
    )


async def complete_lead(
    conn: asyncpg.Connection,
    business_id: str,
    lead_id: str,
    collected: dict[str, Any],
) -> None:
    """Mark a lead finished: final encrypt, status → 'new', stamp `submitted_at`.

    'new' means "completed and waiting for the owner to read it". Re-encrypts the
    final `collected` (and the PII columns) so a completed lead is fully captured
    even if no prior `update_lead` ran. NEVER logs any collected value.
    """
    phone_ct = crypto.encrypt_pii(_first_present(collected, _PHONE_KEYS))
    name_ct = crypto.encrypt_pii(_first_present(collected, _NAME_KEYS))
    answers_blob = crypto.encrypt_answers(collected)

    await conn.execute(
        """
        UPDATE leads
        SET phone            = $3,
            contact_name     = $4,
            answers          = $5::jsonb,
            status           = $6,
            key_version      = $7,
            last_activity_at = now(),
            submitted_at     = now()
        WHERE id = $1 AND business_id = $2
        """,
        lead_id,
        business_id,
        phone_ct,
        name_ct,
        _answers_json(answers_blob),
        STATUS_NEW,
        crypto.CURRENT_KEY_VERSION,
    )


async def log_event(
    conn: asyncpg.Connection,
    business_id: str,
    lead_id: str | None,
    flow_key: str | None,
    event: str,
    step_index: int | None,
    is_test: bool,
) -> None:
    """Append one funnel event for this lead/flow (RLS-scoped via `conn`).

    `event` must be one of started|step|completed|abandoned. `lead_id` may be None
    for an event that predates a lead row (defensive). No PII is recorded here —
    only the structural funnel signal (which flow, which step, test or not).
    """
    if event not in _VALID_EVENTS:
        raise ValueError(f"invalid flow event: {event!r}")

    await conn.execute(
        """
        INSERT INTO flow_events
            (business_id, lead_id, flow_key, event, step_index, is_test)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        business_id,
        lead_id,
        flow_key,
        event,
        step_index,
        is_test,
    )


# --- READ side (M7): list + decrypt leads for the owner dashboard ------------
#
# The owner is the ONE party allowed to see the plaintext: list rows are decrypted
# HERE (phone, contact_name, and the whole answers blob) so the API can hand the
# dashboard a readable object. Reads are RLS-scoped via the tenant-bound `conn`.
# We NEVER log a decrypted value.

# period filter → how far back to look (None == 'all', no time bound). Values are
# datetime.timedelta so asyncpg binds them NATIVELY to a Postgres interval param.
# (A plain str like "7 days" raises a DataError — asyncpg expects a timedelta.)
_PERIOD_INTERVALS = {
    "week": timedelta(days=7),
    "month": timedelta(days=30),
}

# The status filter vocabulary the dashboard exposes. 'open' is SYNTHETIC:
# new + in_progress (everything still actionable), not a stored status value.
STATUS_OPEN = "open"
_OPEN_STATUSES = (STATUS_NEW, STATUS_IN_PROGRESS)
_REAL_STATUSES = {STATUS_NEW, STATUS_IN_PROGRESS, STATUS_ABANDONED}


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
      * status — 'new' | 'in_progress' | 'abandoned' | 'open' (= new+in_progress);
                 'all'/None means no status filter.
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
        "       last_step_index, is_test, key_version, "
        "       started_at, last_activity_at, submitted_at "
        "FROM leads "
        f"WHERE {' AND '.join(where)}{period_sql} "
        f"ORDER BY last_activity_at DESC "
        f"LIMIT ${len(params)}"
    )
    rows = await conn.fetch(sql, *params)
    return [_decrypt_lead_row(row) for row in rows]


def _decrypt_lead_row(row: asyncpg.Record) -> dict[str, Any]:
    """Map one leads row → a readable dict with phone/name/answers decrypted.

    The stored `answers` jsonb is the {"_": ciphertext} blob; we decrypt it back
    to the full collected dict. The dedicated phone/contact_name columns are
    decrypted too. A row's own stamped `key_version` selects the key (rotation).
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

    return {
        "id": str(row["id"]),
        "lead_name": row["lead_name"],
        "phone": phone,
        "contact_name": contact_name,
        "answers": answers,
        "status": row["status"],
        "last_step_index": row["last_step_index"],
        "is_test": row["is_test"],
        "started_at": _iso(row["started_at"]),
        "last_activity_at": _iso(row["last_activity_at"]),
        "submitted_at": _iso(row["submitted_at"]),
    }


async def funnel_stats(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    period: str | None = None,
    include_test: bool = False,
) -> dict[str, int]:
    """Return funnel counts (started/completed/abandoned + total leads) for a period.

    started/completed/abandoned come from `flow_events` (the funnel trail);
    `total_leads` counts the lead ROWS in the window. `is_test` rows are excluded
    unless `include_test` is True. RLS-scoped via the tenant-bound `conn`.
    """
    # Funnel event counts (one scan of flow_events, grouped by event).
    ev_params: list[Any] = [business_id]
    ev_where = ["business_id = $1"]
    if not include_test:
        ev_where.append("is_test = false")
    ev_period = _period_clause(period, ev_params, "created_at")
    ev_rows = await conn.fetch(
        "SELECT event, count(*)::int AS n FROM flow_events "
        f"WHERE {' AND '.join(ev_where)}{ev_period} "
        "GROUP BY event",
        *ev_params,
    )
    by_event = {r["event"]: r["n"] for r in ev_rows}

    # Total lead rows in the same window (keyed off started_at).
    ld_params: list[Any] = [business_id]
    ld_where = ["business_id = $1"]
    if not include_test:
        ld_where.append("is_test = false")
    ld_period = _period_clause(period, ld_params, "started_at")
    total_leads = await conn.fetchval(
        f"SELECT count(*)::int FROM leads WHERE {' AND '.join(ld_where)}{ld_period}",
        *ld_params,
    )

    return {
        "started": int(by_event.get(EVENT_STARTED, 0)),
        "completed": int(by_event.get(EVENT_COMPLETED, 0)),
        "abandoned": int(by_event.get(EVENT_ABANDONED, 0)),
        "total_leads": int(total_leads or 0),
    }


# --- helpers ----------------------------------------------------------------

def _iso(value: Any) -> str | None:
    """ISO-8601 a timestamptz (or None passes through)."""
    return value.isoformat() if value is not None else None


def _answers_json(blob: dict[str, str]) -> str:
    """Serialize the {"_": ct} answers blob for the jsonb column.

    asyncpg sends a Python str to a `$n::jsonb` param as a JSON document, so we
    hand it the JSON text. The blob's only value is already-encrypted ciphertext.
    """
    return json.dumps(blob, ensure_ascii=False, separators=(",", ":"))
