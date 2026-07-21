# לוגיקת התורים — העמוד העסקי: שדות המיתוג + רשומות תמונות הגלריה (M20)
"""Business-page settings + gallery image rows (M20, decision 0028).

Two things live here, both hanging off the tenant the caller already verified:

  * the PAGE fields on `booking_settings` (tagline / about / address / the four
    contact fields / logo / page_theme) — migration 0029 added them to the row
    that already holds the slug, so there is no new 1:1 table;
  * CRUD over `business_images`, the metadata rows for the gallery. The BYTES
    are not here at all: they sit on the server's disk via
    `app.services.business_images`, and the row only carries the relative path.

Every function takes an already tenant-bound `conn` (from `tenant_connection`),
so RLS scopes every statement; `business_id` is additionally in each WHERE /
VALUES so the policy's USING and WITH CHECK both match. No function here ever
accepts a business_id from a request body.

🔓 Deliberate non-encryption: address/phone/whatsapp/instagram_url/waze_url are
stored as plaintext, unlike `bookings.client_phone`. These are the BUSINESS's own
contact details, whose entire purpose is to be published on a public page —
see the header of migration 0029. Customer PII stays encrypted as always.

Nothing here is ever logged: captions are owner-authored free text and paths
contain the business_id.
"""

from __future__ import annotations

import json
from typing import Any

import asyncpg

from app.services.booking._helpers import _as_obj, _iso


# The page columns, in one place so the SELECT list and the partial UPDATE can
# never drift apart. `page_theme` is handled separately (it is jsonb).
_PAGE_TEXT_COLUMNS = (
    "tagline",
    "about",
    "address",
    "phone",
    "whatsapp",
    "instagram_url",
    "waze_url",
    "logo_url",
)

_PAGE_SELECT = (
    "business_id, slug, tagline, about, address, phone, whatsapp, "
    "instagram_url, waze_url, logo_url, page_theme, updated_at"
)


# ============================================================================
# booking_settings — the page fields
# ============================================================================

async def get_page(conn: asyncpg.Connection, business_id: str) -> dict[str, Any]:
    """Return this tenant's page fields, creating the settings row if missing.

    Reuses `settings.get_settings` for the create-on-first-read behaviour so a
    business that has never opened the booking tab still gets a slug + a row,
    and there is exactly ONE place that knows how to bootstrap it.
    """
    row = await conn.fetchrow(
        f"SELECT {_PAGE_SELECT} FROM booking_settings WHERE business_id = $1",
        business_id,
    )
    if row is None:
        # Delegate the bootstrap (slug generation + defaults) to the settings
        # module, then re-read the page columns it just created.
        from app.services.booking.settings import get_settings as _get_settings

        await _get_settings(conn, business_id)
        row = await conn.fetchrow(
            f"SELECT {_PAGE_SELECT} FROM booking_settings WHERE business_id = $1",
            business_id,
        )
    return _page_to_dict(row)


async def rename_business(
    conn: asyncpg.Connection, business_id: str, name: str
) -> None:
    """Rename the business itself (M20 revision).

    The account is auto-created at first login from the Google profile, so a solo
    owner ends up with their PERSONAL name — "עמר כהן" — as the business name on
    a public page that should say "הגבריה — מספרת גברים". So the name has to be
    editable, and it lives on `businesses`, not on `booking_settings`.

    This is the ONE field here that writes outside `booking_settings`, and it is
    the same value the dashboard header shows — renaming here renames it
    everywhere, which is the intent.

    RLS-scoped: `business_id` is the caller's verified id and is in the WHERE, so
    the tenant policy matches. Blank input is rejected by the model, not here.
    """
    await conn.execute(
        "UPDATE businesses SET name = $2 WHERE id = $1", business_id, name
    )


async def update_page(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    fields: dict[str, Any],
    page_theme: dict[str, Any] | None = None,
    set_page_theme: bool = False,
) -> dict[str, Any] | None:
    """Partial-update the page fields. Returns the saved row, or None if absent.

    `fields` holds ONLY the text columns the PATCH body actually carried — the
    caller builds it from `model_fields_set`, exactly like the services PATCH
    does for description/price. That is what makes an explicit `null` CLEAR a
    column while an omitted key leaves it untouched: a cleared field is present
    in `fields` with the value None.

    `page_theme` is jsonb and gets the same treatment through its own flag, since
    `None` is a meaningful "clear back to {}" there too.
    """
    sets: list[str] = []
    params: list[Any] = [business_id]

    for column in _PAGE_TEXT_COLUMNS:
        if column in fields:
            params.append(fields[column])
            sets.append(f"{column} = ${len(params)}")

    if set_page_theme:
        # NOT NULL DEFAULT '{}' in the schema — a cleared theme means "back to
        # the default palette", which is the empty object, not SQL NULL.
        params.append(json.dumps(page_theme or {}, ensure_ascii=False))
        sets.append(f"page_theme = ${len(params)}::jsonb")

    if not sets:
        return await get_page(conn, business_id)


    # Make sure the row exists first (a brand-new business may never have opened
    # the booking tab), then update — get_page bootstraps it via the settings
    # module so the slug is generated exactly once, in one place.
    await get_page(conn, business_id)

    row = await conn.fetchrow(
        f"""
        UPDATE booking_settings SET {', '.join(sets)}, updated_at = now()
        WHERE business_id = $1
        RETURNING {_PAGE_SELECT}
        """,
        *params,
    )
    return _page_to_dict(row) if row is not None else None


def _page_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Map a booking_settings row → the page dict (page_theme normalized to a dict)."""
    return {
        "slug": row["slug"],
        "tagline": row["tagline"],
        "about": row["about"],
        "address": row["address"],
        "phone": row["phone"],
        "whatsapp": row["whatsapp"],
        "instagram_url": row["instagram_url"],
        "waze_url": row["waze_url"],
        "logo_url": row["logo_url"],
        "page_theme": _as_obj(row["page_theme"], {}),
        "updated_at": _iso(row["updated_at"]),
    }


# ============================================================================
# business_images — the gallery rows
# ============================================================================

async def list_images(
    conn: asyncpg.Connection, business_id: str
) -> list[dict[str, Any]]:
    """This tenant's gallery rows in DISPLAY order (sort_order, then oldest first).

    `created_at` is the tiebreaker so two images sharing a sort_order keep a
    stable order between requests instead of shuffling on every page load.
    """
    rows = await conn.fetch(
        """
        SELECT id, storage_path, caption, sort_order, mime_type, size_bytes,
               created_at
        FROM business_images
        WHERE business_id = $1
        ORDER BY sort_order ASC, created_at ASC
        """,
        business_id,
    )
    return [_image_to_dict(r) for r in rows]


async def count_images(conn: asyncpg.Connection, business_id: str) -> int:
    """How many gallery images this tenant already has — the 40-cap check.

    Counted in the DATABASE under RLS, not from a client-supplied number, and
    read inside the same request that inserts. Two simultaneous uploads at the
    boundary could in theory both pass; the consequence is one image over the
    cap, which is a cosmetic overshoot rather than a security hole.
    """
    return int(
        await conn.fetchval(
            "SELECT count(*) FROM business_images WHERE business_id = $1",
            business_id,
        )
    )


async def create_image(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    storage_path: str,
    mime_type: str,
    size_bytes: int,
    caption: str | None,
    sort_order: int | None,
) -> dict[str, Any]:
    """Insert one gallery row for a file already written to disk.

    When `sort_order` is omitted the image lands at the END of the gallery: we
    take max(sort_order)+1 under the same RLS-scoped connection, so the owner's
    existing order is never disturbed by an upload.
    """
    if sort_order is None:
        current_max = await conn.fetchval(
            "SELECT max(sort_order) FROM business_images WHERE business_id = $1",
            business_id,
        )
        sort_order = 0 if current_max is None else int(current_max) + 1

    row = await conn.fetchrow(
        """
        INSERT INTO business_images
            (business_id, storage_path, caption, sort_order, mime_type, size_bytes)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, storage_path, caption, sort_order, mime_type, size_bytes,
                  created_at
        """,
        business_id,
        storage_path,
        caption,
        sort_order,
        mime_type,
        size_bytes,
    )
    return _image_to_dict(row)


async def update_image(
    conn: asyncpg.Connection,
    business_id: str,
    image_id: str,
    *,
    caption: str | None,
    sort_order: int | None,
    set_caption: bool = False,
) -> dict[str, Any] | None:
    """Partial-update one image's caption and/or position. None if not this tenant's.

    `caption` is nullable, so "clear the caption" must be distinguishable from
    "leave it alone" — the caller passes `set_caption=True` when the key was in
    the PATCH body, exactly like the services PATCH. The WHERE carries
    business_id so a foreign id simply matches no row → the caller returns 404
    (never a 403, which would confirm the id exists elsewhere).
    """
    sets: list[str] = []
    params: list[Any] = [image_id, business_id]
    if set_caption:
        params.append(caption)
        sets.append(f"caption = ${len(params)}")
    if sort_order is not None:
        params.append(sort_order)
        sets.append(f"sort_order = ${len(params)}")

    if not sets:
        return await get_image(conn, business_id, image_id)

    row = await conn.fetchrow(
        f"""
        UPDATE business_images SET {', '.join(sets)}
        WHERE id = $1 AND business_id = $2
        RETURNING id, storage_path, caption, sort_order, mime_type, size_bytes,
                  created_at
        """,
        *params,
    )
    return _image_to_dict(row) if row is not None else None


async def get_image(
    conn: asyncpg.Connection, business_id: str, image_id: str
) -> dict[str, Any] | None:
    """Return one gallery row for this tenant, or None (caller maps None → 404)."""
    row = await conn.fetchrow(
        """
        SELECT id, storage_path, caption, sort_order, mime_type, size_bytes,
               created_at
        FROM business_images
        WHERE id = $1 AND business_id = $2
        """,
        image_id,
        business_id,
    )
    return _image_to_dict(row) if row is not None else None


async def delete_image_row(
    conn: asyncpg.Connection, business_id: str, image_id: str
) -> str | None:
    """Delete one gallery row and RETURN its storage_path (or None if no match).

    The path comes back so the caller can then unlink the file — the row is
    dropped first because the row is the source of truth: an orphaned file is
    invisible clutter, while an orphaned row would render as a broken image.
    """
    path = await conn.fetchval(
        """
        DELETE FROM business_images
        WHERE id = $1 AND business_id = $2
        RETURNING storage_path
        """,
        image_id,
        business_id,
    )
    return str(path) if path is not None else None


def _image_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "storage_path": row["storage_path"],
        "caption": row["caption"],
        "sort_order": int(row["sort_order"]),
        "mime_type": row["mime_type"],
        "size_bytes": int(row["size_bytes"]),
        "created_at": _iso(row["created_at"]),
    }
