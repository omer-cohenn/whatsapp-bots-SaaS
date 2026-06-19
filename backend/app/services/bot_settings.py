"""Read/write the per-business `bot_settings` row — tenant-scoped (RLS).

Two functions:
  * `get_settings(pool, business_id)`  → the current config as plain JSON-able
    dicts (tolerant of a brand-new, empty row).
  * `save_settings(pool, business_id, BotSettings)` → UPSERT the validated config.

The `business_id` ALWAYS comes from the caller (the server session via
`current_business`), NEVER from a request body. Every query runs inside
`tenant_connection(...)` so RLS scopes it to exactly this tenant.

Why `get_settings` returns dicts (not a `BotSettings`):
  a brand-new business has `bot_profile = {}`, which is NOT a valid `BotProfile`
  (it has no name/system_prompt yet). The GET endpoint must still be able to
  show that empty state, so reads stay permissive; the strict `BotSettings`
  validation is applied on WRITE (where it's the untrusted-input gate).
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from app.db.session import tenant_connection
from app.models.bot_builder import BotSettings

# Default handoff keywords mirror the DB column default (contract §3).
_DEFAULT_HANDOFF_KEYWORDS = ["נציג", "אדם", "human", "agent"]


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


async def get_settings(pool: asyncpg.Pool, business_id: str) -> dict[str, Any]:
    """Return this tenant's bot config (or sane empties if no row exists yet).

    Shape: {lead_steps, bot_profile, handoff_keywords, is_published}. Permissive
    on purpose — a never-configured business returns empty profile/flows so the
    builder UI can render a blank slate.
    """
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            """
            SELECT lead_steps, bot_profile, handoff_keywords, is_published
            FROM bot_settings
            WHERE business_id = $1
            """,
            business_id,
        )

    if row is None:
        # No config saved yet — return the empty/default slate.
        return {
            "lead_steps": {},
            "bot_profile": {},
            "handoff_keywords": list(_DEFAULT_HANDOFF_KEYWORDS),
            "is_published": False,
        }

    return {
        "lead_steps": _as_obj(row["lead_steps"], {}),
        "bot_profile": _as_obj(row["bot_profile"], {}),
        "handoff_keywords": _as_obj(row["handoff_keywords"], list(_DEFAULT_HANDOFF_KEYWORDS)),
        "is_published": bool(row["is_published"]),
    }


async def save_settings(
    pool: asyncpg.Pool, business_id: str, settings: BotSettings
) -> dict[str, Any]:
    """UPSERT the (already-validated) config for this tenant. Returns the saved shape.

    `settings` MUST be a validated `BotSettings` (the caller validates untrusted
    input before calling here). We serialize via `model_dump(mode="json")` so the
    jsonb columns get clean, contract-shaped payloads — and we write the tenant
    from `business_id` only (never from the body).
    """
    payload = settings.model_dump(mode="json")
    lead_steps_json = json.dumps(payload["lead_steps"], ensure_ascii=False)
    bot_profile_json = json.dumps(payload["bot_profile"], ensure_ascii=False)
    handoff_json = json.dumps(payload["handoff_keywords"], ensure_ascii=False)

    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            """
            INSERT INTO bot_settings
                (business_id, lead_steps, bot_profile, handoff_keywords, is_published, updated_at)
            VALUES ($1, $2::jsonb, $3::jsonb, $4::jsonb, $5, now())
            ON CONFLICT (business_id) DO UPDATE SET
                lead_steps       = EXCLUDED.lead_steps,
                bot_profile      = EXCLUDED.bot_profile,
                handoff_keywords = EXCLUDED.handoff_keywords,
                is_published     = EXCLUDED.is_published,
                updated_at       = now()
            """,
            business_id,
            lead_steps_json,
            bot_profile_json,
            handoff_json,
            payload["is_published"],
        )

    return payload
