# תמונות הגלריה של העמוד העסקי — אחסון על דיסק השרת (M20)
"""M20 business-page gallery images — PLAIN files on the server's disk.

This module is the physical opposite of `file_storage.py`, and the separation is
the whole point. Read this before touching either file:

    file_storage.py     customer PII      → envelope-ENCRYPTED → private R2 bucket
    business_images.py  public marketing  → PLAINTEXT bytes    → server disk, /media/*

Gallery photos are what a business owner WANTS the world to see: the shop, the
haircut, the cake. Encrypting content whose purpose is to be looked at protects
nobody and forces every page view through a server-side decrypt. So they are
written as-is to a directory that Caddy serves statically (decision 0028).

Why not the existing R2 bucket: "public" in R2 is a BUCKET-level permission, not
a folder-level one. Opening `botik-files` to the world would have published the
customers' damage photos and ID documents sitting in the same bucket. The two
stores are therefore kept physically apart, and NOTHING in this module is ever
reused by the lead-file path (or vice versa).

Safety rules, all enforced here and not merely documented:
  * the file NAME never comes from the client — always a fresh uuid4;
  * the EXTENSION is derived from the mime SNIFFED FROM THE BYTES
    (`file_storage.sniff_mime`), never from the browser's declared type or the
    upload's filename. That is what closes path traversal and an .html file
    disguised as `photo.png`;
  * only JPEG / PNG / WEBP — no gif, no video, and explicitly no SVG (an SVG can
    carry <script> and would run on our own origin);
  * a hard per-image byte cap, enforced on the server;
  * every resolved path is re-checked to be INSIDE the root before any write or
    unlink — defence in depth, even though we generate the names ourselves.

Logging: this module NEVER logs a caption, an original filename, or a path (a
path contains the business_id). Only byte counts and the sniffed mime type.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.file_storage import SNIFF_HEAD_BYTES, sniff_mime

log = get_logger("app.services.business_images")


class ImageRejected(Exception):
    """The bytes are not an image we accept (type or size). Caller → 415 / 413.

    Carries a short Hebrew message safe to show the owner in the UI — it never
    contains a filename, a path, or anything the client sent verbatim.
    """


class ImageStorageError(Exception):
    """The disk itself refused (permissions, full, missing volume). Caller → 500."""


# --- limits + allow-list -----------------------------------------------------

# HARD per-image cap. ~5 MB comfortably holds a phone photo the browser has
# already down-scaled, while 40 images × 5 MB bounds a single tenant at 200 MB
# worst case (realistically ~20 MB — see decision 0028's capacity note). The
# whole image is materialised in RAM once on the way to disk, so this number is
# also what keeps the 1 GB box safe under concurrent uploads.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# How many gallery images ONE business may hold. Enforced SERVER-SIDE in the API
# (the UI limit is a courtesy, not a control).
MAX_IMAGES_PER_BUSINESS = 40

# The ONLY types that may be written to the public directory. Narrower than
# file_storage.ALLOWED_MIME on purpose: this directory is served raw to the
# internet, so nothing that a browser can execute or that carries markup is
# allowed. No SVG (script-bearing), no gif, no video, no documents.
ALLOWED_IMAGE_MIME: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp"}
)

# The extension is chosen from THIS table, keyed by the sniffed type. The
# client's filename never reaches the filesystem, so there is no "." to escape.
_EXT_BY_MIME: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}


# --- the root directory ------------------------------------------------------


def root_dir() -> Path:
    """The storage root, from settings (`BUSINESS_IMAGES_DIR`).

    Read on every call rather than cached at import time so a test can point the
    setting elsewhere via `get_settings.cache_clear()` without reloading this
    module. Resolved so the traversal guard below compares real paths.
    """
    return Path(get_settings().business_images_dir).resolve()


def _safe_target(relative_path: str) -> Path:
    """Resolve `relative_path` under the root, or raise if it escapes.

    We generate every name ourselves, so this can only fire on a bug or on a
    tampered database row — which is exactly when a traversal would be worth
    catching. An absolute path, a `..` segment, or a symlink pointing outside all
    end up failing the prefix check after `resolve()`.
    """
    root = root_dir()
    candidate = (root / relative_path).resolve()
    # STRICTLY inside: the root itself is a directory, never a valid target.
    if root not in candidate.parents:
        # Never echo the offending path — it is attacker-shaped input.
        raise ImageStorageError("refusing to operate outside the image root")
    return candidate


# --- write / delete ----------------------------------------------------------


def save_image(
    business_id: str, raw_bytes: bytes, declared_mime: str | None
) -> tuple[str, str, int]:
    """Validate + write ONE gallery image. Returns `(relative_path, mime, size)`.

    `relative_path` is `{business_id}/{uuid4}.{ext}` — the exact value stored in
    `business_images.storage_path` and the exact suffix of the public URL
    (`/media/{storage_path}`). The caller writes that row; we own only the bytes.

    Raises `ImageRejected` when the content is not an allowed image or is over
    the cap, and `ImageStorageError` when the disk refuses. It NEVER returns a
    path for a file it did not successfully write.
    """
    size = len(raw_bytes)
    if size == 0:
        raise ImageRejected("הקובץ ריק")
    if size > MAX_IMAGE_BYTES:
        raise ImageRejected(
            f"התמונה גדולה מדי (עד {MAX_IMAGE_BYTES // (1024 * 1024)}MB לתמונה)"
        )

    # The DECLARED type is never trusted on its own. sniff_mime reads the magic
    # bytes; for our three types it ignores `declared_mime` entirely and returns
    # what the CONTENT actually is (or None for anything it does not recognise).
    sniffed = sniff_mime(raw_bytes[:SNIFF_HEAD_BYTES], declared_mime)
    if sniffed not in ALLOWED_IMAGE_MIME:
        # Log the DECLARED type only (never the filename) so a legitimate
        # rejection stays diagnosable without recording client text.
        log.warning(
            "gallery image rejected — not an allowed image",
            extra={
                "business_id": business_id,
                "declared_mime": (declared_mime or "")[:100],
                "sniffed_mime": sniffed or "unknown",
            },
        )
        raise ImageRejected("אפשר להעלות רק תמונות מסוג JPG, PNG או WEBP")

    # uuid4 for the name + a table-lookup extension: no part of this string comes
    # from the client, so it cannot contain a separator, a dot-dot, or a null.
    relative_path = f"{business_id}/{uuid.uuid4()}.{_EXT_BY_MIME[sniffed]}"
    target = _safe_target(relative_path)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp name in the SAME directory and rename into place, so a
        # crash mid-write can never leave a half-image being served by Caddy.
        tmp = target.with_name(target.name + ".part")
        with open(tmp, "wb") as fh:
            fh.write(raw_bytes)
        os.replace(tmp, target)
    except OSError as exc:
        log.error(
            "gallery image write failed",
            extra={"business_id": business_id, "reason": type(exc).__name__},
        )
        raise ImageStorageError("failed to store image") from exc

    log.info(
        "gallery image stored",
        extra={"business_id": business_id, "mime_type": sniffed, "size_bytes": size},
    )
    return relative_path, sniffed, size


def delete_image(relative_path: str) -> None:
    """Remove one image file. A MISSING file is not an error.

    The DB row and the file are two separate stores; the row is the source of
    truth. If the file is already gone (a previous half-finished delete, a
    restored volume), the owner's delete must still succeed and drop the row —
    otherwise a stale row becomes permanently undeletable through the UI.

    A real disk failure DOES raise, so we never report a delete that did not
    happen. Never logs the path (it contains the business_id).
    """
    try:
        target = _safe_target(relative_path)
    except ImageStorageError:
        # A row pointing outside the root is corrupt, not deletable. Say so.
        log.error("gallery image delete refused — path outside root")
        raise

    try:
        target.unlink()
    except FileNotFoundError:
        return  # already gone — the desired end state
    except OSError as exc:
        log.error("gallery image delete failed", extra={"reason": type(exc).__name__})
        raise ImageStorageError("failed to delete image") from exc
