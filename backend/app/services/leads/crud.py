# מחברת הלידים — כתיבה: פתיחת ליד, עדכון, השלמה, וקביעת סטטוס לבעלים
"""Lead write side: create / update / complete / set-status (M5).

The durable record of what a conversation collected. Each function takes an
already-open, tenant-bound `asyncpg.Connection` so RLS scopes the write and the
runtime can do a create + log_event in ONE transaction. PII (phone, name, the
whole answers blob, the outcome note) is encrypted at rest via `app/core/crypto`
and NEVER logged. Moved VERBATIM from the old single-file `leads.py` — no logic
change.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from app.core import crypto
from app.services import usage as usage_service
from app.services.leads._common import (
    _NAME_KEYS,
    _PHONE_KEYS,
    _SETTABLE_STATUSES,
    CLOSE_REASON_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
    _answers_json,
    _first_present,
)


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
    # M12 usage: count a new lead for this tenant. Best-effort on the SAME
    # tenant-bound conn (RLS WITH CHECK passes); a counter failure must never
    # break lead creation. Test leads ARE counted here (pure number, no PII) —
    # the admin overview's total_leads still excludes test rows at read time.
    await usage_service.bump_safe(conn, business_id, usage_service.METRIC_LEAD)
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
    even if no prior `update_lead` ran. Also stamps `close_reason='completed'`
    (decision 0021) so the dashboard can label WHY this conversation closed —
    in the SAME UPDATE/transaction as the rest of the finalize. NEVER logs any
    collected value.
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
            close_reason     = $7,
            key_version      = $8,
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
        CLOSE_REASON_COMPLETED,
        crypto.CURRENT_KEY_VERSION,
    )


async def touch_lead_activity(
    conn: asyncpg.Connection,
    business_id: str,
    lead_id: str,
) -> None:
    """Bump `last_activity_at = now()` on an open lead — nothing else (decision 0021).

    The abandoned-sweep clock keys off `last_activity_at`. The bot's `update_lead`
    already bumps it on every answered step, but the SILENT human/waiting path in
    run_turn never calls the engine, so a customer chatting with a HUMAN for >60
    min would wrongly look idle and get swept to 'abandoned'. The runtime calls
    this on EVERY inbound customer message (including that silent path) to reset
    the clock. `business_id` is the caller's verified id and is in the WHERE so
    RLS scopes the UPDATE to this tenant's own row. Touches no PII; logs nothing.
    """
    await conn.execute(
        """
        UPDATE leads
        SET last_activity_at = now()
        WHERE id = $1 AND business_id = $2
        """,
        lead_id,
        business_id,
    )


async def delete_lead(
    conn: asyncpg.Connection,
    business_id: str,
    lead_id: str,
) -> bool:
    """Hard-delete a lead row from the DB (owner action). RLS-scoped.

    Returns True when the row existed and was deleted, False when not found
    (the caller maps False → 404). Cascades: flow_events rows reference leads
    with ON DELETE CASCADE so no orphaned rows remain. Never logs PII.
    """
    result = await conn.execute(
        "DELETE FROM leads WHERE id = $1 AND business_id = $2",
        lead_id,
        business_id,
    )
    # asyncpg returns "DELETE N"; N=0 means nothing matched.
    return result != "DELETE 0"


async def mark_lead_feed_seen(
    conn: asyncpg.Connection,
    business_id: str,
    lead_id: str,
) -> bool:
    """Stamp feed_seen_at = now() on one lead (decision 0022). RLS-scoped.

    Returns True when the row existed, False when not found (→ 404).
    Only updates rows where feed_seen_at IS NULL so re-marking is a no-op.
    No PII touched or logged.
    """
    result = await conn.execute(
        """
        UPDATE leads
        SET feed_seen_at = now()
        WHERE id = $1 AND business_id = $2 AND feed_seen_at IS NULL
        """,
        lead_id,
        business_id,
    )
    # "UPDATE 0" can mean either not found OR already marked; treat as found+ok.
    # Verify existence separately when we need a true 404.
    exists = await conn.fetchval(
        "SELECT 1 FROM leads WHERE id = $1 AND business_id = $2",
        lead_id,
        business_id,
    )
    return exists is not None


async def mark_all_leads_feed_seen(
    conn: asyncpg.Connection,
    business_id: str,
) -> int:
    """Stamp feed_seen_at = now() on ALL unseen leads for this tenant (decision 0022).

    Returns the count of rows updated. RLS-scoped (business_id in WHERE).
    No PII touched or logged.
    """
    result = await conn.execute(
        """
        UPDATE leads
        SET feed_seen_at = now()
        WHERE business_id = $1 AND feed_seen_at IS NULL AND is_test = false
        """,
        business_id,
    )
    # result is e.g. "UPDATE 5"
    try:
        return int(result.split()[-1])
    except (IndexError, ValueError):
        return 0


async def set_lead_status(
    conn: asyncpg.Connection,
    business_id: str,
    lead_id: str,
    status: str,
    note: str | None = None,
    close_reason: str | None = None,
) -> bool:
    """Owner-set a lead's status (e.g. → 'deal' or 'closed'). RLS-scoped.

    `status` must be one of the settable values (in_progress|new|abandoned|deal|
    closed) — anything else is a programming/validation error and raises. The
    `business_id` is the caller's verified id; including it in the WHERE means RLS
    can only ever touch THIS tenant's row. Returns True if a row matched (lead
    exists for this tenant), False otherwise — the caller maps False → 404.

    `note` (the owner's outcome note, e.g. why a deal closed) is OPTIONAL. When
    given it is ENCRYPTED at rest into the `outcome_note` column in the SAME
    UPDATE (and `key_version` is stamped so rotation stays possible) — just like
    phone/answers. The note plaintext is PII and is NEVER logged. When `note` is
    None the existing outcome_note is left untouched.

    `close_reason` (decision 0021, e.g. 'answered' on the manual human-close path)
    is OPTIONAL and structural (no PII). When given it is stamped in the SAME
    UPDATE so "why it closed" is recorded alongside the owner's outcome; when None
    the existing close_reason is left untouched.
    """
    if status not in _SETTABLE_STATUSES:
        raise ValueError(f"invalid lead status: {status!r}")

    # A whitespace-only note carries nothing — treat it as "no note" so it can't
    # silently overwrite a real outcome note that was saved earlier.
    if note is not None:
        note = note.strip() or None

    # Build the SET clause + params dynamically: status + last_activity are always
    # set; outcome_note (encrypted) and close_reason (structural) are added only
    # when supplied so a None never wipes a previously-saved value.
    params: list[Any] = [lead_id, business_id, status]
    set_parts = ["status = $3", "last_activity_at = now()"]

    if note is not None:
        params.append(crypto.encrypt_pii(note))
        set_parts.append(f"outcome_note = ${len(params)}")
        # Restamp key_version whenever we (re)encrypt the note, so rotation works.
        params.append(crypto.CURRENT_KEY_VERSION)
        set_parts.append(f"key_version = ${len(params)}")

    if close_reason is not None:
        params.append(close_reason)
        set_parts.append(f"close_reason = ${len(params)}")

    result = await conn.execute(
        f"""
        UPDATE leads
        SET {', '.join(set_parts)}
        WHERE id = $1 AND business_id = $2
        """,
        *params,
    )
    # asyncpg returns the command tag, e.g. "UPDATE 1" / "UPDATE 0".
    return result.rsplit(" ", 1)[-1] != "0"
