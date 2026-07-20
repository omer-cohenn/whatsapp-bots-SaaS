"""Internal media API — the gateway → backend file upload channel (M16).

When a customer sends a photo / PDF / DOC / PPT to the business's WhatsApp
number, the Node gateway downloads the media off Baileys and POSTs it here. This
router is the ONLY way bytes enter the system.

Trust model — IDENTICAL to app/api/internal_wa.py (deliberately, so there is one
rule to reason about):
  * PUBLIC-path route, mounted on the app root OUTSIDE the gated /api group (the
    gateway has no user session), protected by the SAME shared X-Gateway-Token
    header with a constant-time compare. 401 BEFORE any work if the token is bad.
  * `business_id` is a FORM FIELD supplied by the TRUSTED gateway (unlike owner
    routes, where it comes from the verified session). We still validate it is a
    well-formed uuid, and the DB write runs through `tenant_connection` on the
    gateway_role pool, so RLS scopes the INSERT to that one business.

Pool choice: `app.state.gw_pool` (gateway_role). Migration 0028 grants
gateway_role SELECT + INSERT on `lead_files` and nothing else — the gateway can
record a file but can never rewrite or erase one. Owner-side reads/updates/
deletes go through app_role on `pg_pool` instead.

Defence order on every upload (cheapest + most dangerous checks first):
  1. token        → 401
  2. business_id  → 422
  3. size         → 413   (streamed, capped BEFORE the whole body is in RAM)
  4. content sniff→ 415   (magic bytes, NOT the declared type)
  5. idempotency  → 200 with the EXISTING file_id, no second R2 object
  6. encrypt + PUT + INSERT

Logging: we NEVER log the file name, the bytes, the token, or the storage key —
only business_id, the sniffed mime type, and the byte count.
"""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)

from app.api.internal_wa import _require_token, _valid_business_id
from app.core import crypto
from app.core.logging import get_logger
from app.db.session import tenant_connection
from app.services import file_storage

router = APIRouter(prefix="/internal/wa", tags=["internal-wa"])
log = get_logger("app.internal_media")

# How many bytes we pull off the stream per chunk while enforcing the size cap.
# 64 KiB keeps the loop cheap without adding a meaningful buffer of its own.
_CHUNK = 64 * 1024

# Bound the free-text identifiers the gateway sends so they can never become a
# giant column value. These are WhatsApp ids, which are short.
_ID_MAX = 200


async def _read_capped(upload: UploadFile) -> bytes:
    """Read the upload into memory, aborting with 413 the moment it exceeds the cap.

    FastAPI's `UploadFile` has already SPOOLED the body to a temp file on disk
    (it only keeps a small in-memory buffer), so the raw request never sat whole
    in RAM. Here we materialise it once — bounded by MAX_FILE_BYTES — because
    Fernet cannot encrypt a stream. We stop reading at the first chunk that
    crosses the cap, so an oversized upload never allocates past the limit.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > file_storage.MAX_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="file too large",
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="empty file"
        )
    return b"".join(chunks)


@router.post("/media")
async def upload_media(
    request: Request,
    business_id: str = Form(...),
    file: UploadFile = File(...),
    conversation_id: str | None = Form(default=None),
    message_id: str | None = Form(default=None),
    mime_type: str | None = Form(default=None),
    file_name: str | None = Form(default=None),
    x_gateway_token: str | None = Header(default=None, alias="X-Gateway-Token"),
) -> dict[str, object]:
    """Store one customer file: validate → sniff → dedupe → encrypt → R2 → row.

    Returns `{"file_id", "mime_type", "size_bytes"}` on both a fresh store and an
    idempotent hit, so the gateway does not have to branch on which happened.

    The `mime_type` returned is the SNIFFED one (what we actually stored), which
    may differ from what the gateway declared — the gateway should use OUR value
    when it builds the lead answer.
    """
    _require_token(x_gateway_token)
    business_id = _valid_business_id(business_id)

    # Bound the free-text ids before they reach a query or a column.
    conversation_id = (conversation_id or None) and conversation_id[:_ID_MAX]
    message_id = (message_id or None) and message_id[:_ID_MAX]

    gw_pool = request.app.state.gw_pool

    # --- idempotency FIRST: a Baileys re-emit must not re-upload or re-bill ---
    # Cheapest possible short-circuit — before we read the body, before crypto,
    # before the network PUT. The partial unique index (0028) backs this lookup.
    if message_id:
        async with tenant_connection(gw_pool, business_id) as conn:
            existing = await conn.fetchrow(
                "SELECT id, mime_type, size_bytes FROM lead_files "
                "WHERE business_id = $1 AND message_id = $2",
                business_id,
                message_id,
            )
        if existing is not None:
            log.info(
                "media upload deduped",
                extra={"business_id": business_id, "mime_type": existing["mime_type"]},
            )
            return {
                "file_id": str(existing["id"]),
                "mime_type": existing["mime_type"],
                "size_bytes": int(existing["size_bytes"]),
            }

    # --- size cap (413) ------------------------------------------------------
    payload = await _read_capped(file)

    # --- content sniff (415). The DECLARED type is never trusted on its own. --
    sniffed = file_storage.sniff_mime(
        payload[: file_storage.SNIFF_HEAD_BYTES], mime_type
    )
    if sniffed is None or sniffed not in file_storage.ALLOWED_MIME:
        # Log the DECLARED type (not the name, not the bytes) so a legitimate
        # rejection is diagnosable.
        log.warning(
            "media upload rejected — type not allowed",
            extra={"business_id": business_id, "declared_mime": (mime_type or "")[:100]},
        )
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="file type not allowed",
        )

    # --- encrypt + store -----------------------------------------------------
    file_id = str(uuid.uuid4())
    try:
        storage_key, wrapped_dek, key_version, sha256_hex = file_storage.put_encrypted(
            business_id, file_id, payload
        )
    except file_storage.StorageNotConfiguredError:
        # The feature is off (no bucket configured) — the app is healthy, the
        # door is just shut. Same shape as the Gemini-not-configured path.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="file storage is not configured",
        ) from None
    except file_storage.StorageError:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="file storage unavailable"
        ) from None

    size_bytes = len(payload)
    del payload  # drop the plaintext before the DB round-trip

    # The customer's file name is PII → sanitize, then store as CIPHERTEXT.
    safe_name = file_storage.sanitize_filename(file_name, fallback="file")
    encrypted_name = crypto.encrypt_pii(safe_name)

    try:
        async with tenant_connection(gw_pool, business_id) as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO lead_files (
                    id, business_id, conversation_id, message_id, storage_key,
                    wrapped_dek, key_version, mime_type, file_name, size_bytes, sha256
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (business_id, message_id) WHERE message_id IS NOT NULL
                DO NOTHING
                RETURNING id
                """,
                file_id,
                business_id,
                conversation_id,
                message_id,
                storage_key,
                wrapped_dek,
                key_version,
                sniffed,
                encrypted_name,
                size_bytes,
                sha256_hex,
            )
    except Exception:
        # The object is already in R2 but the row failed — clean up so we never
        # leave a paid-for object nobody can ever reference or decrypt.
        try:
            file_storage.delete_object(storage_key)
        except Exception:  # noqa: BLE001 — best-effort cleanup, never mask the 500
            log.error("orphaned object cleanup failed", extra={"business_id": business_id})
        log.error("media row insert failed", extra={"business_id": business_id})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="failed to record file",
        ) from None

    if row is None:
        # A concurrent duplicate won the race between our probe and this INSERT.
        # Drop the object we just wrote and return the winner's id.
        try:
            file_storage.delete_object(storage_key)
        except Exception:  # noqa: BLE001
            log.error("duplicate object cleanup failed", extra={"business_id": business_id})
        async with tenant_connection(gw_pool, business_id) as conn:
            winner = await conn.fetchrow(
                "SELECT id, mime_type, size_bytes FROM lead_files "
                "WHERE business_id = $1 AND message_id = $2",
                business_id,
                message_id,
            )
        if winner is None:  # pragma: no cover — cannot happen with the index
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="failed to record file",
            )
        return {
            "file_id": str(winner["id"]),
            "mime_type": winner["mime_type"],
            "size_bytes": int(winner["size_bytes"]),
        }

    log.info(
        "media stored",
        extra={
            "business_id": business_id,
            "mime_type": sniffed,
            "size_bytes": size_bytes,
        },
    )
    return {"file_id": file_id, "mime_type": sniffed, "size_bytes": size_bytes}
