# לוגיקת התורים — הגדרות עמוד התורים + ניהול השירותים (CRUD) + פתרון slug
"""Booking settings + services CRUD + public slug/name helpers (M11).

Holds the owner-facing configuration of the booking page (working hours, notice,
buffer, etc.), the per-business services catalog (CRUD), the non-guessable slug
generation, and the two public-page lookups (resolve a slug → business_id, and a
cosmetic display name). All RLS-scoped via the tenant-bound `conn` (except
`resolve_slug`, which has no tenant context yet — it uses the SECURITY DEFINER
function by design). Moved VERBATIM from the old single-file `booking.py` — no
logic change.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import asyncpg

from app.services.booking._helpers import (
    _DEFAULT_WORKING_HOURS,
    _SLUG_BYTES,
    _as_obj,
    _iso,
)


# ============================================================================
# booking_settings — get / update (auto-generate slug on first save)
# ============================================================================

async def get_settings(conn: asyncpg.Connection, business_id: str) -> dict[str, Any]:
    """Return this tenant's booking settings, creating a default row if missing.

    On first read we INSERT a default row (with a fresh non-guessable slug) so a
    business always has a usable public page. RLS-scoped via `conn`; business_id
    is the caller's verified id and is in the WHERE/VALUES so the policy matches.
    """
    row = await conn.fetchrow(
        """
        SELECT business_id, timezone, working_hours, min_notice_minutes,
               buffer_minutes, max_days_ahead, meet_enabled, welcome_message,
               slug, updated_at
        FROM booking_settings
        WHERE business_id = $1
        """,
        business_id,
    )
    if row is None:
        row = await _create_default_settings(conn, business_id)
    return _settings_to_dict(row)


async def _create_default_settings(
    conn: asyncpg.Connection, business_id: str
) -> asyncpg.Record:
    """Insert a default settings row with a fresh unique slug; return the row."""
    slug = await _unique_slug(conn)
    row = await conn.fetchrow(
        """
        INSERT INTO booking_settings
            (business_id, working_hours, slug)
        VALUES ($1, $2::jsonb, $3)
        ON CONFLICT (business_id) DO UPDATE SET updated_at = now()
        RETURNING business_id, timezone, working_hours, min_notice_minutes,
                  buffer_minutes, max_days_ahead, meet_enabled, welcome_message,
                  slug, updated_at
        """,
        business_id,
        json.dumps(_DEFAULT_WORKING_HOURS, ensure_ascii=False),
        slug,
    )
    return row


async def update_settings(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    working_hours: dict[str, Any],
    min_notice_minutes: int,
    buffer_minutes: int,
    max_days_ahead: int,
    meet_enabled: bool,
    welcome_message: str | None,
) -> dict[str, Any]:
    """UPSERT the editable booking settings for this tenant; return the saved row.

    The slug + timezone are SERVER-OWNED: a new row gets a fresh slug, and an
    existing row keeps its slug/timezone untouched (the body can't change them).
    `welcome_message` is owner-authored public copy (NOT PII) — persisted as-is.
    RLS-scoped; business_id is the verified id and is written from here only.
    """
    # Ensure a slug exists (first save creates the row + slug); then update the
    # editable fields. We do this as a single UPSERT so it's race-safe.
    slug = await _unique_slug(conn)
    row = await conn.fetchrow(
        """
        INSERT INTO booking_settings
            (business_id, working_hours, min_notice_minutes, buffer_minutes,
             max_days_ahead, meet_enabled, welcome_message, slug, updated_at)
        VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7, $8, now())
        ON CONFLICT (business_id) DO UPDATE SET
            working_hours      = EXCLUDED.working_hours,
            min_notice_minutes = EXCLUDED.min_notice_minutes,
            buffer_minutes     = EXCLUDED.buffer_minutes,
            max_days_ahead     = EXCLUDED.max_days_ahead,
            meet_enabled       = EXCLUDED.meet_enabled,
            welcome_message    = EXCLUDED.welcome_message,
            updated_at         = now()
        RETURNING business_id, timezone, working_hours, min_notice_minutes,
                  buffer_minutes, max_days_ahead, meet_enabled, welcome_message,
                  slug, updated_at
        """,
        business_id,
        json.dumps(working_hours, ensure_ascii=False),
        min_notice_minutes,
        buffer_minutes,
        max_days_ahead,
        meet_enabled,
        welcome_message,
        slug,
    )
    return _settings_to_dict(row)


async def _unique_slug(conn: asyncpg.Connection) -> str:
    """Generate a non-guessable slug not already in use (tiny retry loop).

    NOTE: the SELECT here runs under RLS as app_role, but the public uniqueness
    of slugs is enforced by the UNIQUE constraint on the column regardless. The
    check is best-effort to avoid a collision retry; the constraint is the real
    guarantee. Collisions on a 12-char url-safe token are astronomically rare.
    """
    for _ in range(5):
        candidate = secrets.token_urlsafe(_SLUG_BYTES)
        # The function bypasses RLS to check global uniqueness of the public slug.
        taken = await conn.fetchval("SELECT resolve_booking_slug($1)", candidate)
        if taken is None:
            return candidate
    # Extremely unlikely; fall back to a longer token.
    return secrets.token_urlsafe(_SLUG_BYTES * 2)


def _settings_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Map a booking_settings row → a JSON-able dict (working_hours normalized)."""
    return {
        "slug": row["slug"],
        "timezone": row["timezone"],
        "working_hours": _as_obj(row["working_hours"], {}),
        "min_notice_minutes": int(row["min_notice_minutes"]),
        "buffer_minutes": int(row["buffer_minutes"]),
        "max_days_ahead": int(row["max_days_ahead"]),
        "meet_enabled": bool(row["meet_enabled"]),
        "welcome_message": row["welcome_message"],
        "updated_at": _iso(row["updated_at"]),
    }


# ============================================================================
# services — CRUD
# ============================================================================

async def list_services(
    conn: asyncpg.Connection, business_id: str, *, active_only: bool = False
) -> list[dict[str, Any]]:
    """List this tenant's services (newest first). RLS-scoped via `conn`."""
    where = "business_id = $1"
    if active_only:
        where += " AND active = true"
    rows = await conn.fetch(
        f"""
        SELECT id, name, duration_minutes, active, description, price,
               image_url, created_at
        FROM services
        WHERE {where}
        ORDER BY created_at DESC
        """,
        business_id,
    )
    return [_service_to_dict(r) for r in rows]


async def get_service(
    conn: asyncpg.Connection, business_id: str, service_id: str
) -> dict[str, Any] | None:
    """Return one service for this tenant, or None (caller maps None → 404)."""
    row = await conn.fetchrow(
        """
        SELECT id, name, duration_minutes, active, description, price,
               image_url, created_at
        FROM services
        WHERE id = $1 AND business_id = $2
        """,
        service_id,
        business_id,
    )
    return _service_to_dict(row) if row is not None else None


async def create_service(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    name: str,
    duration_minutes: int,
    active: bool,
    description: str | None,
    price: int | None,
    image_url: str | None,
) -> dict[str, Any]:
    """Insert a new service for this tenant; return it. RLS WITH CHECK matches."""
    row = await conn.fetchrow(
        """
        INSERT INTO services
            (business_id, name, duration_minutes, active, description, price,
             image_url)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id, name, duration_minutes, active, description, price,
                  image_url, created_at
        """,
        business_id,
        name,
        duration_minutes,
        active,
        description,
        price,
        image_url,
    )
    return _service_to_dict(row)


async def update_service(
    conn: asyncpg.Connection,
    business_id: str,
    service_id: str,
    *,
    name: str | None,
    duration_minutes: int | None,
    active: bool | None,
    description: str | None,
    price: int | None,
    image_url: str | None,
    set_description: bool = False,
    set_price: bool = False,
    set_image_url: bool = False,
) -> dict[str, Any] | None:
    """Partial-update a service (only provided fields). None if no row matched.

    Builds a dynamic SET from just the supplied fields; the WHERE includes
    business_id so RLS scopes the write to this tenant. Returns the updated row,
    or None when the id doesn't exist for this tenant (caller → 404).

    description/price/image_url are nullable columns, so "set to NULL" (clear)
    must be distinguishable from "omitted". The caller passes `set_description` /
    `set_price` / `set_image_url` = True when the field was present in the PATCH
    body (even if its value is None), so an explicit null actually clears the
    column.
    """
    sets: list[str] = []
    params: list[Any] = [service_id, business_id]
    if name is not None:
        params.append(name)
        sets.append(f"name = ${len(params)}")
    if duration_minutes is not None:
        params.append(duration_minutes)
        sets.append(f"duration_minutes = ${len(params)}")
    if active is not None:
        params.append(active)
        sets.append(f"active = ${len(params)}")
    if set_description:
        params.append(description)
        sets.append(f"description = ${len(params)}")
    if set_price:
        params.append(price)
        sets.append(f"price = ${len(params)}")
    if set_image_url:
        params.append(image_url)
        sets.append(f"image_url = ${len(params)}")

    if not sets:
        # Nothing to change → just return the current row (or None if absent).
        return await get_service(conn, business_id, service_id)

    row = await conn.fetchrow(
        f"""
        UPDATE services SET {', '.join(sets)}
        WHERE id = $1 AND business_id = $2
        RETURNING id, name, duration_minutes, active, description, price,
                  image_url, created_at
        """,
        *params,
    )
    return _service_to_dict(row) if row is not None else None


async def delete_service(
    conn: asyncpg.Connection, business_id: str, service_id: str
) -> bool:
    """Delete a service for this tenant. Returns True if a row was removed.

    Existing bookings keep their history: the FK is ON DELETE SET NULL, so a
    deleted service simply nulls `bookings.service_id` (the booking row stays).
    """
    result = await conn.execute(
        "DELETE FROM services WHERE id = $1 AND business_id = $2",
        service_id,
        business_id,
    )
    return result.rsplit(" ", 1)[-1] != "0"


def _service_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "duration_minutes": int(row["duration_minutes"]),
        "active": bool(row["active"]),
        "description": row["description"],
        "price": int(row["price"]) if row["price"] is not None else None,
        "image_url": row["image_url"],
        "created_at": _iso(row["created_at"]),
    }


# ============================================================================
# public page helpers (resolve slug → business; public business name)
# ============================================================================

async def resolve_slug(pool: asyncpg.Pool, slug: str) -> str | None:
    """Resolve a public booking slug → business_id, or None (caller → 404).

    Uses the `resolve_booking_slug` SECURITY DEFINER function (migration 0010),
    which bypasses RLS to look up the slug→business mapping when there is NO
    tenant context yet (the public page has no session). It exposes ONLY the
    business id for that exact slug — nothing else. The caller then opens a
    normal tenant_connection bound to that id so EVERY subsequent read/write is
    RLS-scoped exactly like an authenticated request.
    """
    async with pool.acquire() as conn:
        business_id = await conn.fetchval("SELECT resolve_booking_slug($1)", slug)
    return str(business_id) if business_id is not None else None


async def business_display_name(conn: asyncpg.Connection, business_id: str) -> str:
    """Best-effort business display name for the public page header.

    Read RLS-scoped; businesses has RLS, so this returns the name only because
    the tenant context is set on `conn`. Never raises — falls back to "".
    """
    try:
        name = await conn.fetchval(
            "SELECT name FROM businesses WHERE id = $1", business_id
        )
        return name or ""
    except Exception:  # noqa: BLE001 — header is cosmetic; never break the page
        return ""
