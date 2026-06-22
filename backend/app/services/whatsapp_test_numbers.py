"""Owner's external test allow-list — the WhatsApp test-numbers service (M6a.1).

The owner may register up to 5 phone numbers (each with an optional label). When
ANY of those numbers messages the owner's WhatsApp, the gateway runs it through
the REAL bot pipeline and replies — exactly like the self-chat, but for external
test phones. Everyone NOT on the list is ignored (silent).

Three tiny, focused jobs:

  1. `get_test_numbers(pool, business_id)` — the OWNER's read for the admin UI.
     Returns the decrypted list ([{phone, label}]), RLS-scoped to this tenant.
  2. `set_test_numbers(pool, business_id, items)` — the OWNER's save. Validates
     (≤5), normalizes each phone, drops blanks/dupes, encrypts phone + label, and
     REPLACES all rows for the business in one tenant_connection.
  3. `is_number_allowed(pool, business_id, raw_from)` — the INBOUND gate. The
     webhook (after resolving the business server-side) asks "is this sender on
     the allow-list?". Normalizes `raw_from` and checks membership.

Non-negotiables (mirroring leads.py / whatsapp.py):
  * RLS, always. Every query goes through `tenant_connection(pool, business_id)`
    so Postgres scopes it to exactly this tenant. `business_id` is the caller's
    already-verified id (the session tenant for the admin paths; the server-side
    `resolve_wa_account` result for the inbound gate) — NEVER a raw client value.
  * PII encrypted at rest, never logged. The normalized phone digits and the
    optional label are ENCRYPTED via `app/core/crypto.py` before they touch the
    DB (the 🔒 bytea columns). We NEVER log a phone number or a label.

Encryption + bytea note: the columns are `bytea` (ciphertext). `encrypt_pii`
returns a Fernet token as an ascii `str`; we `.encode()` it to bytes for the
bytea column on write, and `.decode()` the stored bytes back to that token str
before `decrypt_pii` on read — the same shape google_oauth.py uses for its
envelope-in-bytea column.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from app.core import crypto
from app.db.session import tenant_connection

# Hard cap on how many test numbers a business may register (contract: ≤5).
MAX_TEST_NUMBERS = 5


def normalize(s: str | None) -> str:
    """Normalize a phone to canonical digits so stored ↔ inbound numbers match.

    Rules (THE single source of truth — used on BOTH stored numbers and the
    inbound `from`, so they compare equal):
      * keep digits only (drop spaces, dashes, parentheses, a leading '+', etc.).
      * if the result is 10 digits AND starts with '0' (Israeli local form, e.g.
        '0547408309') → '972' + digits[1:]  →  '972547408309'.
      * otherwise return the digits as-is.

    Examples:
      '+972547408309' → '972547408309'   (already international)
      '054-740-8309'  → '972547408309'   (Israeli local, leading 0)
      ''              → ''               (caller treats empty as "blank, drop")
    """
    digits = "".join(ch for ch in (s or "") if ch.isdigit())
    if len(digits) == 10 and digits.startswith("0"):
        return "972" + digits[1:]
    return digits


def _encrypt_optional(value: str | None) -> bytes | None:
    """Encrypt an optional PII string → bytes for a bytea column (None stays None).

    `encrypt_pii` returns an ascii Fernet token str; we encode it to bytes so it
    lands in the bytea column. A blank/None value stays None (no ciphertext row
    value), so an empty label is stored as SQL NULL — never logged either way.
    """
    if not value:
        return None
    token = crypto.encrypt_pii(value)
    # encrypt_pii only returns None for a falsy input, which we already excluded.
    return token.encode() if token is not None else None


def _decrypt_optional(blob: Any) -> str | None:
    """Decrypt a bytea ciphertext column back to plaintext (None stays None).

    asyncpg hands a bytea back as `bytes` (or memoryview). We normalize to bytes,
    decode to the Fernet token str, then `decrypt_pii`. Raises LOUD on a real
    decrypt failure (no plaintext fallback) — matching crypto.py's contract.
    """
    if blob is None:
        return None
    token = bytes(blob).decode()
    return crypto.decrypt_pii(token)


async def get_test_numbers(
    pool: asyncpg.Pool, business_id: str
) -> list[dict[str, str | None]]:
    """Return this tenant's test allow-list (decrypted), oldest first.

    Each entry is {phone, label}: the normalized phone digits and the optional
    label, both decrypted for the OWNER (the one party allowed to see them).
    `business_id` is the caller's verified session tenant; the read runs inside
    `tenant_connection(...)` so RLS scopes it to this tenant only. NEVER logs a
    phone or a label.
    """
    async with tenant_connection(pool, business_id) as conn:
        rows = await conn.fetch(
            """
            SELECT phone_number, label
            FROM whatsapp_test_numbers
            WHERE business_id = $1
            ORDER BY created_at ASC
            """,
            business_id,
        )

    return [
        {"phone": _decrypt_optional(row["phone_number"]), "label": _decrypt_optional(row["label"])}
        for row in rows
    ]


async def set_test_numbers(
    pool: asyncpg.Pool, business_id: str, items: list[dict[str, str | None]]
) -> list[dict[str, str | None]]:
    """Replace this tenant's whole test allow-list with `items`. Returns the saved shape.

    Cleaning rules (applied before any DB write):
      * normalize each phone (canonical digits); drop entries whose phone is blank
        after normalization.
      * de-duplicate by normalized phone (first occurrence wins, keeping its
        label) so the same number can't appear twice.
      * enforce the ≤5 cap (raises ValueError — the API layer maps that to 422;
        the contract says >5 is rejected, not silently truncated).

    The write is a REPLACE: delete every existing row for the business, then
    insert the cleaned set — all in ONE `tenant_connection` transaction so RLS
    scopes it and the swap is atomic. Phone + label are ENCRYPTED at rest. We
    NEVER log a phone or a label. Returns [{phone, label}] for the saved rows.
    """
    # 1) Clean: normalize, drop blanks, de-dupe by normalized phone (first wins).
    cleaned: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for item in items:
        phone = normalize(item.get("phone"))
        if not phone or phone in seen:
            continue
        seen.add(phone)
        # A blank/whitespace-only label is stored as None (no empty ciphertext).
        label = item.get("label")
        label = label.strip() if isinstance(label, str) else label
        cleaned.append({"phone": phone, "label": label or None})

    # 2) Enforce the cap AFTER cleaning (so dupes/blanks don't count against it).
    if len(cleaned) > MAX_TEST_NUMBERS:
        raise ValueError(f"at most {MAX_TEST_NUMBERS} test numbers are allowed")

    # 3) Atomic replace inside one tenant transaction (RLS-scoped throughout).
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            "DELETE FROM whatsapp_test_numbers WHERE business_id = $1", business_id
        )
        for entry in cleaned:
            await conn.execute(
                """
                INSERT INTO whatsapp_test_numbers (business_id, phone_number, label)
                VALUES ($1, $2, $3)
                """,
                business_id,
                _encrypt_optional(entry["phone"]),
                _encrypt_optional(entry["label"]),
            )

    return cleaned


async def is_number_allowed(
    pool: asyncpg.Pool, business_id: str, raw_from: str
) -> bool:
    """Is `raw_from` on THIS tenant's test allow-list? (the inbound gate).

    The webhook resolves the business server-side (via resolve_wa_account) and
    then asks this. We normalize `raw_from` with the SAME `normalize()` used on
    stored numbers, so '+972547408309' matches a stored '972547408309'. The read
    runs inside `tenant_connection(...)` (RLS-scoped) and decrypts each stored
    number to compare. Returns False for a blank sender or an empty list. NEVER
    logs the phone.
    """
    target = normalize(raw_from)
    if not target:
        return False

    async with tenant_connection(pool, business_id) as conn:
        rows = await conn.fetch(
            "SELECT phone_number FROM whatsapp_test_numbers WHERE business_id = $1",
            business_id,
        )

    # Stored numbers are already normalized at write time, but normalize again on
    # read for safety (idempotent) before the membership check.
    for row in rows:
        stored = _decrypt_optional(row["phone_number"])
        if stored and normalize(stored) == target:
            return True
    return False
