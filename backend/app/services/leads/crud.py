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


async def set_lead_status(
    conn: asyncpg.Connection,
    business_id: str,
    lead_id: str,
    status: str,
    note: str | None = None,
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
    """
    if status not in _SETTABLE_STATUSES:
        raise ValueError(f"invalid lead status: {status!r}")

    # A whitespace-only note carries nothing — treat it as "no note" so it can't
    # silently overwrite a real outcome note that was saved earlier.
    if note is not None:
        note = note.strip() or None

    if note is not None:
        # Encrypt the outcome note + restamp key_version in the same UPDATE.
        note_ct = crypto.encrypt_pii(note)
        result = await conn.execute(
            """
            UPDATE leads
            SET status = $3,
                outcome_note = $4,
                key_version = $5,
                last_activity_at = now()
            WHERE id = $1 AND business_id = $2
            """,
            lead_id,
            business_id,
            status,
            note_ct,
            crypto.CURRENT_KEY_VERSION,
        )
    else:
        result = await conn.execute(
            """
            UPDATE leads
            SET status = $3, last_activity_at = now()
            WHERE id = $1 AND business_id = $2
            """,
            lead_id,
            business_id,
            status,
        )
    # asyncpg returns the command tag, e.g. "UPDATE 1" / "UPDATE 0".
    return result.rsplit(" ", 1)[-1] != "0"
