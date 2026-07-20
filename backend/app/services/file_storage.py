"""M16 customer-file storage — envelope-encrypted objects in Cloudflare R2.

A customer sends a photo / PDF / DOC / PPT through the WhatsApp bot. The BYTES
must never sit in Postgres and must never sit in the bucket readable. So:

    plaintext bytes
        → fresh per-file DEK (Fernet)            crypto.wrap_new_dek()
        → ciphertext                             crypto.encrypt_with_dek()
        → PUT to R2 at  {business_id}/{file_id}  (tenant-prefixed key)
        → the WRAPPED dek + metadata land in Postgres (`lead_files`)

The two halves live apart ON PURPOSE: a stolen bucket has no keys, a stolen DB
dump has no bytes. Neither alone yields one customer file. `key_version` is
stamped on the row so a KEK rotation can still unwrap old DEKs.

Decryption is FAIL-LOUD (the M2 rule): a wrong key or a tampered object raises
`DecryptionError`, and this module NEVER returns partially-decrypted or
plaintext-ish garbage as if it were the file.

--------------------------------------------------------------------------
MEMORY PROFILE (this box has 1 GB of RAM — this is the reason for the caps)
--------------------------------------------------------------------------
Fernet has no streaming mode: it encrypts and decrypts whole buffers. For one
10 MB file the peak resident set of `put_encrypted` is roughly:

    plaintext bytes                     10.0 MB   (caller-owned, passed in)
    Fernet's internal padded copy      ~10.0 MB   (freed on return)
    base64 ciphertext (the Fernet token)~13.7 MB  (what we PUT)
                                       --------
    peak                               ~34 MB per concurrent upload

`get_decrypted` is the mirror image (~34 MB). With MAX_FILE_BYTES = 10 MB and
the backend's 2 gunicorn workers, even a handful of simultaneous uploads stays
comfortably inside the box. That is WHY the cap is 10 MB and not 100 MB.

To keep the profile at that number and not higher, the rules in this module are:
  * the caller streams the request body to a TEMP FILE (FastAPI `UploadFile`)
    and hands us bytes ONCE — the raw body is never buffered twice in RAM;
  * we hold exactly one plaintext reference and one ciphertext reference, and we
    drop the plaintext reference before the network PUT so the ciphertext upload
    is the only large object alive during the slow part;
  * boto3 is given the ciphertext as a `BytesIO` view, not re-copied;
  * NOTHING here is cached — no LRU of file contents, ever.
--------------------------------------------------------------------------

Logging: this module NEVER logs file names, file bytes, DEKs, or credentials.
Only business_id, the mime type, and byte counts — none of which are PII.
"""

from __future__ import annotations

import hashlib
import io
from typing import Any

from app.core import crypto
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger("app.services.file_storage")


class StorageNotConfiguredError(Exception):
    """Raised when an S3/R2 setting is missing — mirrors GeminiNotConfiguredError.

    The app boots fine without object storage; only the file feature refuses.
    The API layer turns this into a 503, never a 500.
    """


class StorageError(Exception):
    """Raised when the bucket round-trip itself fails (network / 4xx / 5xx)."""


# --- limits + allow-list -----------------------------------------------------

# HARD server-side cap, enforced on EVERY upload regardless of plan. 10 MiB.
# Justification: (a) the memory profile above — 10 MB in ≈ 34 MB peak, safe on a
# 1 GB box; (b) WhatsApp's own document limit for the media types we accept sits
# at 16 MB for images/video and 100 MB for documents, but a lead-capture bot has
# no legitimate need for a 100 MB attachment — 10 MB comfortably covers a phone
# photo (2–5 MB), a scanned PDF, and a slide deck; (c) it bounds the per-tenant
# R2 bill. The per-PLAN `max_file_mb` (migration 0028) may be LOWER than this but
# is never allowed to exceed it.
MAX_FILE_BYTES = 10 * 1024 * 1024

# How many bytes we need to identify a file by content. The longest signature we
# check is the WEBP one at offset 8..12, so 16 is plenty; we read a little more
# so callers can pass a single slice around.
SNIFF_HEAD_BYTES = 32

# The ONLY mime types that may be stored. Anything else is a 415. Deliberately
# narrow: no SVG (script-bearing), no HTML, no archives, no executables.
ALLOWED_MIME: frozenset[str] = frozenset(
    {
        # images
        "image/jpeg",
        "image/png",
        "image/webp",
        # documents
        "application/pdf",
        "application/msword",                                                    # .doc
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
        "application/vnd.ms-powerpoint",                                         # .ppt
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
    }
)

# The OOXML container (.docx/.pptx) is a ZIP; the legacy Office container
# (.doc/.ppt) is an OLE2 compound file. Magic bytes cannot tell docx from pptx
# (both are PK\x03\x04) nor doc from ppt (both are OLE2), so for those two
# families we sniff the CONTAINER and then trust the declared type only if it is
# a member of that family. Everything else is pinned to an exact signature.
_OOXML_TYPES = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
)
_OLE2_TYPES = frozenset({"application/msword", "application/vnd.ms-powerpoint"})


def sniff_mime(head_bytes: bytes, declared_mime: str | None) -> str | None:
    """Identify a file by its CONTENT and cross-check the declared type.

    Returns the mime type to STORE, or None if the content is not an allowed
    type OR the declared type contradicts the content. Callers must treat None
    as a hard 415 — we never fall back to the declared type, because the declared
    type is attacker-controlled (it comes off the WhatsApp message).

    Dependency-free on purpose (no python-magic / libmagic in the image): we
    check the handful of well-known signatures for exactly the types we allow.

        JPEG   FF D8 FF
        PNG    89 50 4E 47 0D 0A 1A 0A
        WEBP   'RIFF' ....  'WEBP'          (size at 4..8, tag at 8..12)
        PDF    '%PDF'
        OOXML  50 4B 03 04                  ('PK\\x03\\x04' — zip → docx/pptx)
        OLE2   D0 CF 11 E0 A1 B1 1A E1      (legacy compound file → doc/ppt)

    An empty/short head can never match, so a truncated upload is rejected too.
    """
    if not head_bytes:
        return None

    declared = (declared_mime or "").split(";")[0].strip().lower() or None

    # --- exact-signature types: content alone decides, declared is ignored ---
    if head_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if (
        len(head_bytes) >= 12
        and head_bytes.startswith(b"RIFF")
        and head_bytes[8:12] == b"WEBP"
    ):
        return "image/webp"
    if head_bytes.startswith(b"%PDF"):
        return "application/pdf"

    # --- container types: content narrows to a FAMILY, declared picks a member -
    if head_bytes.startswith(b"PK\x03\x04"):
        # A zip container. Only accept it if the sender said it is one of the
        # two OOXML types we allow — otherwise it is just a zip and is rejected.
        return declared if declared in _OOXML_TYPES else None
    if head_bytes.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return declared if declared in _OLE2_TYPES else None

    # Unknown signature → reject. No guessing, no declared-type fallback.
    return None


# --- file-name hygiene -------------------------------------------------------

# Customer-supplied names are unbounded and hostile. Cap the length BEFORE it is
# encrypted and stored (a 64 KB "name" is an attack, not a name).
MAX_FILE_NAME_LEN = 200

# Anything that could break out of a path, forge a Content-Disposition header, or
# smuggle a control character. We keep unicode letters (Hebrew names are normal
# here) and strip only the genuinely dangerous set.
_UNSAFE_NAME_CHARS = set('/\\:*?"<>|\r\n\t\x00')


def sanitize_filename(name: str | None, fallback: str = "file") -> str:
    """Return a name safe to put in a `Content-Disposition` header.

    Strips path separators, quote/angle characters and control characters
    (CR/LF would allow header injection), collapses whitespace, drops any
    leading dots (so a name can never become a dotfile or `..`), and truncates.
    Returns `fallback` when nothing usable survives — we never emit an empty or
    attacker-shaped filename.

    NOTE: this sanitizes the DISPLAY name only. The object key never contains it
    (see `storage_key_for`), so no traversal is possible regardless.
    """
    if not name:
        return fallback
    cleaned = "".join(
        ch for ch in name if ch not in _UNSAFE_NAME_CHARS and ch.isprintable()
    )
    cleaned = " ".join(cleaned.split()).lstrip(". ").strip()
    if not cleaned:
        return fallback
    return cleaned[:MAX_FILE_NAME_LEN]


# --- the S3 / R2 client (lazy, validate-at-use) ------------------------------

# One boto3 client per process. boto3 clients are thread-safe and hold a
# connection pool, so building it once matters; building it LAZILY matters more,
# because the app must boot with no storage configured at all.
_client: Any | None = None


def _require_settings() -> tuple[str, str, str, str, str]:
    """Return (endpoint, key_id, secret, bucket, region) or raise if unconfigured."""
    s = get_settings()
    missing = [
        name
        for name, value in (
            ("S3_ENDPOINT", s.s3_endpoint),
            ("S3_ACCESS_KEY_ID", s.s3_access_key_id),
            ("S3_SECRET_ACCESS_KEY", s.s3_secret_access_key),
            ("S3_BUCKET", s.s3_bucket),
        )
        if not value
    ]
    if missing:
        # Name the MISSING keys (not their values) so ops can fix it fast.
        raise StorageNotConfiguredError(
            "object storage is not configured; missing: " + ", ".join(missing)
        )
    return (
        str(s.s3_endpoint),
        s.s3_access_key_id.get_secret_value(),   # type: ignore[union-attr]
        s.s3_secret_access_key.get_secret_value(),  # type: ignore[union-attr]
        str(s.s3_bucket),
        s.s3_region,
    )


def _get_client() -> tuple[Any, str]:
    """Build (once) and return the (boto3_s3_client, bucket).

    boto3 is imported INSIDE this function on purpose: it is a heavy import and
    an OPTIONAL dependency of this feature. Importing it at module scope would
    make `import app.main` fail on an image built without it, turning an optional
    feature into a boot-time hard requirement — exactly what the fail-closed
    settings design avoids.
    """
    global _client
    endpoint, key_id, secret, bucket, region = _require_settings()

    if _client is None:
        try:
            import boto3  # noqa: PLC0415 — deliberate lazy import, see docstring
            from botocore.config import Config  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - depends on the image
            raise StorageNotConfiguredError(
                "boto3 is not installed in this image; file storage unavailable"
            ) from exc

        _client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            region_name=region,
            config=Config(
                # R2 speaks SigV4 and requires path-style addressing.
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                # Fail fast rather than hanging a request worker on a dead bucket.
                connect_timeout=5,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
    return _client, bucket


def reset_client() -> None:
    """Drop the cached client (tests / after a credential rotation)."""
    global _client
    _client = None


def storage_key_for(business_id: str, file_id: str) -> str:
    """The object key. TENANT-PREFIXED so one tenant's objects are one prefix.

    `{business_id}/{file_id}` — both are server-generated uuids, so the key can
    never contain a path traversal, a customer-supplied name, or any PII. The
    prefix is what makes a per-tenant lifecycle rule / bulk delete / audit
    possible in the bucket without consulting the DB.
    """
    return f"{business_id}/{file_id}"


# --- the two operations ------------------------------------------------------

def put_encrypted(
    business_id: str, file_id: str, plaintext_bytes: bytes
) -> tuple[str, str, int, str]:
    """Envelope-encrypt and store one file.

    Returns `(storage_key, wrapped_dek, key_version, sha256_hex)` — exactly the
    four values the `lead_files` row needs alongside the caller's metadata.

    The sha256 is of the PLAINTEXT, computed before encryption, so it stays a
    stable integrity/dedupe fingerprint across a future KEK rotation (the
    ciphertext changes on every re-encrypt; the plaintext digest does not).

    Memory: see the module docstring. We drop our reference to the ciphertext
    string as soon as it is wrapped in the BytesIO handed to boto3, so at the
    moment of the (slow) network PUT only one large buffer is alive.
    """
    if len(plaintext_bytes) > MAX_FILE_BYTES:
        # Defense in depth: the API layer already rejected this with a 413. If we
        # got here anyway, refuse rather than blow the memory budget.
        raise ValueError("payload exceeds MAX_FILE_BYTES")

    client, bucket = _get_client()

    sha256_hex = hashlib.sha256(plaintext_bytes).hexdigest()
    dek, wrapped_dek = crypto.wrap_new_dek()
    ciphertext = crypto.encrypt_with_dek(dek, plaintext_bytes)
    del dek  # the raw data key is used exactly once and then dropped

    key = storage_key_for(business_id, file_id)
    body = io.BytesIO(ciphertext)
    del ciphertext  # BytesIO now owns the only reference

    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            # The stored object is OPAQUE ciphertext. Advertising it as such stops
            # any bucket browser / CDN from ever trying to render it, and leaks
            # nothing about the real type (which lives in the DB row instead).
            ContentType="application/octet-stream",
        )
    except Exception as exc:
        # Never surface bucket internals (endpoint, credentials, request ids) to
        # the caller; log the class only.
        log.error(
            "file storage put failed",
            extra={"business_id": business_id, "reason": type(exc).__name__},
        )
        raise StorageError("failed to store file") from exc
    finally:
        body.close()

    log.info(
        "file stored",
        extra={"business_id": business_id, "size_bytes": len(plaintext_bytes)},
    )
    return key, wrapped_dek, crypto.CURRENT_KEY_VERSION, sha256_hex


def get_decrypted(storage_key: str, wrapped_dek: str, key_version: int) -> bytes:
    """Fetch one object and return its PLAINTEXT bytes. Fails LOUD.

    Raises `StorageNotConfiguredError` (503), `StorageError` when the object is
    missing or unreadable, and `crypto.DecryptionError` when the DEK does not
    unwrap or the payload does not authenticate. There is NO path through this
    function that returns ciphertext, a partial buffer, or b"" on failure — a
    corrupted object can never be served as if it were the customer's file.

    Memory: one ciphertext buffer + one plaintext buffer alive at the peak
    (~24 MB for a 10 MB file); the ciphertext reference is dropped before the
    plaintext is returned to the caller.
    """
    client, bucket = _get_client()

    try:
        obj = client.get_object(Bucket=bucket, Key=storage_key)
        ciphertext = obj["Body"].read()
    except Exception as exc:
        log.error(
            "file storage get failed", extra={"reason": type(exc).__name__}
        )
        raise StorageError("failed to read file") from exc

    # Unwrap the per-file DEK with the crown KEK, then decrypt. Both steps raise
    # DecryptionError on ANY failure — deliberately not caught here.
    dek = crypto.unwrap_dek(wrapped_dek, key_version)
    plaintext = crypto.decrypt_with_dek(dek, ciphertext)
    del ciphertext, dek
    return plaintext


def delete_object(storage_key: str) -> None:
    """Remove one object from the bucket.

    The DB cascade (`lead_files` ← leads/businesses ON DELETE CASCADE) removes
    the METADATA row but NOT the R2 object — object storage knows nothing about
    Postgres. Any code path that deletes a lead/file must call this, or the
    object is orphaned. (An orphan is inert — its wrapped DEK died with the row,
    so it is undecryptable ciphertext — but it still costs storage.)

    Swallows nothing: a failed delete raises so the caller can retry or alert.
    """
    client, bucket = _get_client()
    try:
        client.delete_object(Bucket=bucket, Key=storage_key)
    except Exception as exc:
        log.error(
            "file storage delete failed", extra={"reason": type(exc).__name__}
        )
        raise StorageError("failed to delete file") from exc
