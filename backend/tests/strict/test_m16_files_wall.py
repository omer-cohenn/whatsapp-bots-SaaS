"""M16 — the customer-FILE wall, strict pytest (CI version).

M16 lets a stranger push BYTES into the system for the first time: a customer
sends a photo / PDF / DOC / PPT to the business's WhatsApp number, the gateway
downloads it and POSTs it to `/internal/wa/media`, the backend envelope-encrypts
it into Cloudflare R2 and records the metadata in `lead_files` (migration 0028).
The owner later pulls it back through `GET /api/leads/files/{file_id}`.

Three brand-new attack surfaces come with that, and this suite is the wall around
all three, against the REAL DB / Redis / running app:

  a. `lead_files` RLS      — business B can neither read, update, delete, nor
     FORGE a row belonging to business A, on either pool. Plus the 0028 role
     split: gateway_role has SELECT+INSERT and provably NO update/delete.
  b. OWNER DOWNLOAD        — another tenant's file_id is a flat 404, byte-for-byte
     identical to a file that never existed (never 403, never 500 — a 403 would
     itself confirm "this id exists somewhere", which is an enumeration oracle).
     No session at all → 401.
  c. INTERNAL UPLOAD AUTH  — POST /internal/wa/media is 401 without (or with a
     wrong) X-Gateway-Token, and 422 for a malformed business_id.
  d. CONTENT SNIFFING      — `sniff_mime` decides by MAGIC BYTES, never by the
     attacker-controlled declared type: an EXE renamed .png, an SVG and a bare
     ZIP are all refused; the real signatures are accepted.
  e. FILE-NAME HYGIENE     — `sanitize_filename` neutralizes path traversal, CRLF
     header injection and quotes, while PRESERVING Hebrew (a customer file is
     routinely named "תעודת_זהות.pdf" — mangling it is a real bug, not safety).
  f. NO LEAKS IN LOGS      — a media-bearing webhook and a rejected upload are
     driven while the log stream is captured; the file NAME, the file BYTES, the
     gateway TOKEN and the customer PHONE appear nowhere in it.

NOTE ON SCOPE: R2 is not configured in dev (no S3_* credentials), so the storage
layer raises StorageNotConfiguredError and the byte round-trip cannot run here.
That is deliberate — every property above is proven WITHOUT the bucket. What
still needs real credentials is listed at the bottom of this docstring.

STILL REQUIRES REAL R2 CREDENTIALS (cannot be proven by this file):
  * the encrypt → PUT → GET → decrypt round-trip through the live bucket;
  * that the stored object is CIPHERTEXT at rest in R2;
  * the true 413 on a >10 MB body all the way through the gateway;
  * a live end-to-end from a genuine WhatsApp attachment.

Tenants: the two SEEDED pretend businesses (Avi/Bella). The user's REAL business
(7fca1b13-…) is never read or written. Every row this suite creates is deleted in
a `finally`. No secret or PII is ever asserted-on by value: the canaries are
random markers generated per run.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.logging import JsonFormatter
from app.db.session import tenant_connection
from app.main import app
from app.services import file_storage
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX
from tests.conftest import BIZ_A, BIZ_B

# The user's REAL business — this suite must NEVER touch it.
REAL_BIZ = "7fca1b13-902a-4ce2-a4a4-28ecd48f96eb"

AVI_USER = "google-sub-avi"
AVI_EMAIL = "avi@example.com"
BELLA_USER = "google-sub-bella"
BELLA_EMAIL = "bella@example.com"

GATEWAY_TOKEN = get_settings().gateway_api_token.get_secret_value()
GOOD_HDR = {"X-Gateway-Token": GATEWAY_TOKEN}
BAD_HDR = {"X-Gateway-Token": "totally-wrong"}

# A real 1x1 PNG header is all `sniff_mime` reads, but we use a full valid-enough
# prefix so the payload is honestly a PNG.
PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG_MAGIC = b"\xff\xd8\xff\xe0" + b"\x00" * 28
PDF_MAGIC = b"%PDF-1.7\n" + b"\x00" * 24
WEBP_MAGIC = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 20
ZIP_MAGIC = b"PK\x03\x04" + b"\x00" * 28
OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 24
EXE_MAGIC = b"MZ\x90\x00" + b"\x00" * 28


# --- fixtures (app_pool / gw_pool come from tests/conftest.py) ----------------

@pytest_asyncio.fixture
async def lifespan_app():
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def http(lifespan_app):
    transport = ASGITransport(app=lifespan_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def redis(lifespan_app):
    # Reuse the app's own redis client (created in the lifespan), like the e2e suite.
    return lifespan_app.state.redis


# --- tiny helpers -------------------------------------------------------------

async def _login(redis, http, user_id: str, email: str, business_id: str) -> str:
    """Mint an opaque Redis session + set the cookie, like a logged-in owner."""
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id,
        "email": email,
        "name": user_id,
        "picture": "",
        "business_id": business_id,
        "business_name": "x",
        "created_at": int(time.time()),
    }
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)
    return sid


async def _logout(redis, http, sid: str) -> None:
    await redis.delete(f"{_SESSION_KEY_PREFIX}{sid}")
    http.cookies.clear()


async def _insert_file_row(pool: asyncpg.Pool, business_id: str, **over) -> str:
    """Create ONE lead_files row for `business_id` under its own tenant context.

    No R2 object is created (none is needed for any assertion here) — the
    storage_key points at a key that will never exist, which is exactly what a
    "row without a bucket" looks like and keeps the test self-contained.
    """
    fid = str(uuid.uuid4())
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            """
            INSERT INTO lead_files (
                id, business_id, storage_key, wrapped_dek, key_version,
                mime_type, size_bytes
            ) VALUES ($1, $2, $3, $4, 1, $5, $6)
            """,
            fid,
            business_id,
            over.get("storage_key", f"{business_id}/{fid}"),
            over.get("wrapped_dek", "not-a-real-wrapped-dek"),
            over.get("mime_type", "image/png"),
            over.get("size_bytes", 123),
        )
    return fid


async def _delete_file_row(pool: asyncpg.Pool, business_id: str, file_id: str) -> None:
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            "DELETE FROM lead_files WHERE business_id = $1 AND id = $2",
            business_id,
            file_id,
        )


def _multipart(payload: bytes, name: str = "photo.png", mime: str = "image/png"):
    """The `files=` part, shaped EXACTLY like the gateway sends it.

    gateway/src/internalApi.js uploads the part under the fixed placeholder name
    `upload.bin` — the REAL (PII) file name travels in the `file_name` FORM FIELD
    instead, and the declared type travels in `mime_type`. Mirroring that here
    matters: a test that smuggled the name/type in via the part header would be
    exercising a path production never takes.
    """
    return {"file": ("upload.bin", payload, mime)}


def _form(business_id: str, *, name: str | None = None, mime: str | None = None, **extra):
    """The non-file form fields, in the gateway's own shape."""
    data: dict[str, str] = {"business_id": business_id}
    if mime is not None:
        data["mime_type"] = mime
    if name is not None:
        data["file_name"] = name
    data.update({k: str(v) for k, v in extra.items()})
    return data


# ============================================================================
#  (a) lead_files RLS — B can neither read, change, nor forge A's row
# ============================================================================

async def test_business_b_cannot_read_update_delete_or_forge_a_file_row(app_pool):
    """The full four-verb tenant wall on `lead_files`, as app_role under RLS.

    app_role holds SELECT+INSERT+UPDATE+DELETE (0028), so nothing here is blocked
    by a missing GRANT — what stops B is purely the RLS policy
    (`business_id = current_business_id()`). That is the point: the wall must be
    the policy, not an accident of privileges.
    """
    file_id = await _insert_file_row(app_pool, BIZ_A)
    try:
        # B, explicitly naming A's row id → ZERO rows. Invisible, not forbidden.
        async with tenant_connection(app_pool, BIZ_B) as conn:
            rows = await conn.fetch("SELECT * FROM lead_files WHERE id = $1", file_id)
        assert rows == []

        # B listing EVERYTHING it can see → A's row is not in there either.
        async with tenant_connection(app_pool, BIZ_B) as conn:
            all_rows = await conn.fetch("SELECT id, business_id FROM lead_files")
        assert all(str(r["id"]) != file_id for r in all_rows)
        assert all(str(r["business_id"]) != BIZ_A for r in all_rows)

        # B UPDATE-ing A's row → 0 rows affected (it cannot even see the target).
        async with tenant_connection(app_pool, BIZ_B) as conn:
            status = await conn.execute(
                "UPDATE lead_files SET mime_type = 'image/evil' WHERE id = $1", file_id
            )
        assert status.endswith(" 0"), "B must not be able to rewrite A's file row"

        # B DELETE-ing A's row → 0 rows affected.
        async with tenant_connection(app_pool, BIZ_B) as conn:
            status = await conn.execute("DELETE FROM lead_files WHERE id = $1", file_id)
        assert status.endswith(" 0"), "B must not be able to erase A's file row"

        # B INSERT-ing a row LABELLED as A's → WITH CHECK rejects it outright.
        with pytest.raises(asyncpg.PostgresError):
            async with tenant_connection(app_pool, BIZ_B) as conn:
                await conn.execute(
                    "INSERT INTO lead_files (business_id, storage_key, wrapped_dek, "
                    "mime_type, size_bytes) VALUES ($1, 'poison', 'poison', "
                    "'image/png', 1)",
                    BIZ_A,
                )

        # A's row survived every one of B's attempts, byte for byte.
        async with tenant_connection(app_pool, BIZ_A) as conn:
            row = await conn.fetchrow(
                "SELECT mime_type FROM lead_files WHERE id = $1", file_id
            )
        assert row is not None, "B's DELETE must not have removed A's row"
        assert row["mime_type"] == "image/png", "B's UPDATE must not have landed"
    finally:
        await _delete_file_row(app_pool, BIZ_A, file_id)


async def test_no_tenant_context_sees_no_files_at_all(app_pool):
    """app_role with NO app.business_id set → deny-by-default, zero rows.

    A forgotten `tenant_connection` must fail CLOSED (an empty result), never
    open into a cross-tenant listing.
    """
    async with app_pool.acquire() as conn:  # no tenant_connection on purpose
        rows = await conn.fetch("SELECT id FROM lead_files")
    assert rows == []


async def test_gateway_role_can_insert_and_select_but_never_update_or_delete(gw_pool):
    """The 0028 role split, proven at the GRANT level.

    The gateway is reachable with one shared token. If that token ever leaks, the
    blast radius must stop at "can add a file row" — it must never extend to
    rewriting or erasing the record of a file that already exists.
    """
    file_id = await _insert_file_row(gw_pool, BIZ_A)  # INSERT: granted
    try:
        async with tenant_connection(gw_pool, BIZ_A) as conn:
            got = await conn.fetchrow("SELECT id FROM lead_files WHERE id = $1", file_id)
        assert got is not None  # SELECT: granted

        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with tenant_connection(gw_pool, BIZ_A) as conn:
                await conn.execute(
                    "UPDATE lead_files SET mime_type = 'x' WHERE id = $1", file_id
                )
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            async with tenant_connection(gw_pool, BIZ_A) as conn:
                await conn.execute("DELETE FROM lead_files WHERE id = $1", file_id)
    finally:
        # gateway_role provably CANNOT delete (that is the assertion above), so
        # cleanup has to run as app_role on its own short-lived pool.
        pool = await asyncpg.create_pool(
            dsn=os.environ["DATABASE_URL"], min_size=1, max_size=1
        )
        try:
            await _delete_file_row(pool, BIZ_A, file_id)
        finally:
            await pool.close()


async def test_gateway_role_cannot_forge_a_row_for_another_tenant(gw_pool):
    """Even the trusted upload path cannot write INTO a business it is not scoped to."""
    with pytest.raises(asyncpg.PostgresError):
        async with tenant_connection(gw_pool, BIZ_B) as conn:
            await conn.execute(
                "INSERT INTO lead_files (business_id, storage_key, wrapped_dek, "
                "mime_type, size_bytes) VALUES ($1, 'k', 'd', 'image/png', 1)",
                BIZ_A,
            )


# ============================================================================
#  (b) OWNER DOWNLOAD — another tenant's file is INDISTINGUISHABLE from missing
# ============================================================================

async def test_download_without_a_session_is_rejected(http):
    """No cookie → the /api gate bounces it before any file logic runs."""
    r = await http.get(f"/api/leads/files/{uuid.uuid4()}")
    assert r.status_code in (401, 302, 307), r.status_code
    # Whatever the shape, it must NOT be a file and must not be a 404/200 that
    # implies the lookup ran.
    assert r.status_code != 200


async def test_download_of_another_tenants_file_is_a_flat_404(http, redis, app_pool):
    """B's file, requested by A, is a 404 — the SAME answer as a nonexistent id.

    This is the enumeration guard. A 403 ("forbidden") would confirm the id is
    real and owned by somebody, which is itself a leak; a 500 would confirm the
    row was found and then failed. Only a 404 reveals nothing.

    The control in the same test is A's OWN file: it must NOT 404, proving the
    404 above is genuinely the tenant wall and not a broken route that 404s for
    everyone (which would make this test vacuous).
    """
    b_file = await _insert_file_row(app_pool, BIZ_B)
    a_file = await _insert_file_row(app_pool, BIZ_A)
    sid = await _login(redis, http, AVI_USER, AVI_EMAIL, BIZ_A)
    try:
        # 1) B's real file id, asked for by A.
        cross = await http.get(f"/api/leads/files/{b_file}")
        # 2) An id that exists nowhere.
        missing = await http.get(f"/api/leads/files/{uuid.uuid4()}")

        assert cross.status_code == 404, (
            f"another tenant's file must be 404, got {cross.status_code}"
        )
        assert missing.status_code == 404
        # Byte-identical bodies: no oracle in the message either.
        assert cross.content == missing.content

        # 3) CONTROL — A's own file is FOUND (the row lookup succeeded), so the
        #    404 above was the tenant wall, not a dead route. With no R2 creds in
        #    dev the found path stops at 503 (storage not configured); with real
        #    creds it becomes a 200. Either way it is NOT a 404.
        own = await http.get(f"/api/leads/files/{a_file}")
        assert own.status_code != 404, (
            "A's own file must be found — otherwise the cross-tenant 404 proves nothing"
        )
        assert own.status_code in (200, 502, 503), own.status_code
    finally:
        await _logout(redis, http, sid)
        await _delete_file_row(app_pool, BIZ_B, b_file)
        await _delete_file_row(app_pool, BIZ_A, a_file)


async def test_download_of_a_malformed_file_id_is_also_a_404(http, redis):
    """A non-uuid path segment is a 404 too — no 422, no id-validity oracle."""
    sid = await _login(redis, http, AVI_USER, AVI_EMAIL, BIZ_A)
    try:
        r = await http.get("/api/leads/files/not-a-uuid")
        assert r.status_code == 404, r.status_code
    finally:
        await _logout(redis, http, sid)


async def test_download_never_touches_the_real_business(http, redis, app_pool):
    """A session for A can never reach a row belonging to the user's REAL business.

    We do not (and must not) create anything under REAL_BIZ. We only assert that
    whatever files it may already own are unreachable: we list A's visible ids
    under A's context and confirm none of them belong to REAL_BIZ.
    """
    async with tenant_connection(app_pool, BIZ_A) as conn:
        rows = await conn.fetch("SELECT business_id FROM lead_files")
    assert all(str(r["business_id"]) == BIZ_A for r in rows)
    assert all(str(r["business_id"]) != REAL_BIZ for r in rows)


# ============================================================================
#  (c) INTERNAL UPLOAD AUTH — token first, then input validation
# ============================================================================

async def test_media_upload_rejects_missing_or_wrong_token(http):
    """POST /internal/wa/media → 401 with no token AND with a wrong token.

    The body is deliberately WELL-FORMED (a real business_id, a real file part)
    so the request actually reaches the handler — otherwise FastAPI's own 422 for
    a missing form field would mask whether the token gate fired at all.
    """
    missing = await http.post(
        "/internal/wa/media",
        data=_form(BIZ_A, name="photo.png", mime="image/png"),
        files=_multipart(PNG_MAGIC),
    )
    wrong = await http.post(
        "/internal/wa/media",
        headers=BAD_HDR,
        data=_form(BIZ_A, name="photo.png", mime="image/png"),
        files=_multipart(PNG_MAGIC),
    )
    assert missing.status_code == 401, missing.status_code
    assert wrong.status_code == 401, wrong.status_code


async def test_media_upload_rejects_a_malformed_business_id(http):
    """A valid token but a non-uuid business_id → 422, before any DB or storage."""
    r = await http.post(
        "/internal/wa/media",
        headers=GOOD_HDR,
        data=_form("not-a-uuid", name="photo.png", mime="image/png"),
        files=_multipart(PNG_MAGIC),
    )
    assert r.status_code == 422, r.status_code


async def test_media_upload_rejects_a_disallowed_type_before_storage(http):
    """An EXE renamed .png is a 415 — and a 415 is reached BEFORE storage.

    This also proves ordering: with no R2 configured a request that got past the
    sniff would answer 503. Getting a 415 means the content check ran first, so a
    hostile payload never reaches the encryption/upload path at all.
    """
    r = await http.post(
        "/internal/wa/media",
        headers=GOOD_HDR,
        data=_form(BIZ_A, name="totally-a-photo.png", mime="image/png"),
        files=_multipart(EXE_MAGIC),
    )
    assert r.status_code == 415, r.status_code


async def test_media_upload_rejects_an_empty_file(http):
    """A zero-byte body can never be sniffed → 422, never a stored empty object."""
    r = await http.post(
        "/internal/wa/media",
        headers=GOOD_HDR,
        data=_form(BIZ_A, name="empty.png", mime="image/png"),
        files=_multipart(b""),
    )
    assert r.status_code == 422, r.status_code


async def test_media_upload_with_a_good_file_stops_at_storage_not_configured(http):
    """A LEGITIMATE PNG passes every gate and stops only at the missing bucket.

    503 (not 500) is the contract: the app is healthy, the feature is simply not
    configured. This is the test that will turn into a 200 the day real R2
    credentials land — see the docstring's credentials list.
    """
    r = await http.post(
        "/internal/wa/media",
        headers=GOOD_HDR,
        data=_form(
            BIZ_A, name="real.png", mime="image/png",
            message_id=f"m16-{secrets.token_hex(8)}",
        ),
        files=_multipart(PNG_MAGIC),
    )
    assert r.status_code in (200, 503), r.status_code
    if r.status_code == 503:
        # Never leak WHICH setting is missing (endpoint/keys) to a caller.
        body = r.text.lower()
        assert "s3_secret" not in body and "access_key" not in body


# ============================================================================
#  (d) CONTENT SNIFFING — magic bytes decide, the declared type never does
# ============================================================================

@pytest.mark.parametrize(
    ("payload", "declared", "why"),
    [
        (EXE_MAGIC, "image/png", "a Windows EXE renamed .png"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/svg+xml", "an SVG (script-bearing)"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "image/png", "an SVG claiming to be a PNG"),
        (ZIP_MAGIC, "application/zip", "a bare ZIP archive"),
        (ZIP_MAGIC, "image/png", "a ZIP claiming to be a PNG"),
        (b"<!doctype html><script>alert(1)</script>", "text/html", "an HTML page"),
        (b"#!/bin/sh\nrm -rf /", "application/pdf", "a shell script claiming to be a PDF"),
        (b"", "image/png", "an empty body"),
        (b"\x89PN", "image/png", "a TRUNCATED png signature"),
        (OLE2_MAGIC, "application/pdf", "an OLE2 file claiming to be a PDF"),
        (b"GIF89a" + b"\x00" * 20, "image/gif", "a GIF (not on the allow-list)"),
        (b"\x1f\x8b\x08\x00", "application/gzip", "a gzip archive"),
    ],
)
def test_sniff_mime_rejects_hostile_or_unlisted_content(payload, declared, why):
    """None means "hard 415" — there is no declared-type fallback anywhere."""
    assert file_storage.sniff_mime(payload, declared) is None, f"accepted {why}"


@pytest.mark.parametrize(
    ("payload", "declared", "expected"),
    [
        (JPEG_MAGIC, "image/jpeg", "image/jpeg"),
        (PNG_MAGIC, "image/png", "image/png"),
        (WEBP_MAGIC, "image/webp", "image/webp"),
        (PDF_MAGIC, "application/pdf", "application/pdf"),
    ],
)
def test_sniff_mime_accepts_the_real_signatures(payload, declared, expected):
    got = file_storage.sniff_mime(payload, declared)
    assert got == expected
    assert got in file_storage.ALLOWED_MIME


def test_sniff_mime_trusts_content_over_a_LYING_declared_type():
    """A real PNG declared as a PDF is stored as a PNG — content is the authority.

    The declared type comes off a message a stranger sent. If it could override
    the signature, an attacker would choose the Content-Type the owner's browser
    later renders with.
    """
    assert file_storage.sniff_mime(PNG_MAGIC, "application/pdf") == "image/png"
    assert file_storage.sniff_mime(PDF_MAGIC, "image/png") == "application/pdf"


def test_container_types_need_a_matching_declared_member():
    """PK/OLE2 containers narrow to a FAMILY; the declared type picks the member.

    Magic bytes cannot tell .docx from .pptx (both are ZIPs). So a ZIP is accepted
    ONLY when the sender named one of the two OOXML types we allow — and a ZIP
    named anything else (or nothing) is refused.
    """
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    pptx = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    assert file_storage.sniff_mime(ZIP_MAGIC, docx) == docx
    assert file_storage.sniff_mime(ZIP_MAGIC, pptx) == pptx
    assert file_storage.sniff_mime(ZIP_MAGIC, None) is None
    assert file_storage.sniff_mime(ZIP_MAGIC, "application/x-zip") is None

    assert file_storage.sniff_mime(OLE2_MAGIC, "application/msword") == "application/msword"
    assert file_storage.sniff_mime(OLE2_MAGIC, None) is None


def test_every_sniffable_result_is_on_the_allow_list():
    """`sniff_mime` can never return a type the storage layer would then refuse."""
    for payload, declared in (
        (JPEG_MAGIC, "image/jpeg"),
        (PNG_MAGIC, "image/png"),
        (WEBP_MAGIC, "image/webp"),
        (PDF_MAGIC, "application/pdf"),
        (ZIP_MAGIC, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        (OLE2_MAGIC, "application/vnd.ms-powerpoint"),
    ):
        got = file_storage.sniff_mime(payload, declared)
        assert got is not None and got in file_storage.ALLOWED_MIME


def test_the_allow_list_excludes_the_dangerous_families():
    """A standing guard: no SVG, HTML, archive or executable may ever be added."""
    for banned in (
        "image/svg+xml",
        "text/html",
        "application/zip",
        "application/x-msdownload",
        "application/octet-stream",
        "application/javascript",
    ):
        assert banned not in file_storage.ALLOWED_MIME


def test_the_hard_size_cap_is_ten_mib():
    """The 413 boundary is a constant, not a per-plan value — pin it."""
    assert file_storage.MAX_FILE_BYTES == 10 * 1024 * 1024


# ============================================================================
#  (e) FILE-NAME HYGIENE — dangerous shapes out, Hebrew in
# ============================================================================

@pytest.mark.parametrize(
    ("hostile", "why"),
    [
        ("../../etc/passwd", "unix path traversal"),
        ("..\\..\\windows\\system32\\config\\sam", "windows path traversal"),
        ("/etc/shadow", "absolute path"),
        ("C:\\Users\\a\\secret.pdf", "windows absolute path"),
        ("evil\r\nX-Injected: yes", "CRLF header injection"),
        ("evil\nSet-Cookie: a=b", "LF header injection"),
        ('a"; filename="b.exe', "Content-Disposition quote break-out"),
        ("na\x00me.png", "NUL byte"),
        ("tab\tsep.png", "control character"),
        ("....//....//x", "dot-segment smuggling"),
    ],
)
def test_sanitize_filename_neutralizes_hostile_names(hostile, why):
    """The result may never carry a separator, a quote, or a control character."""
    safe = file_storage.sanitize_filename(hostile)
    for ch in '/\\:*?"<>|\r\n\t\x00':
        assert ch not in safe, f"{why}: {ch!r} survived sanitization"
    assert not safe.startswith("."), f"{why}: produced a dotfile / dot-segment"
    assert safe.strip() == safe
    assert safe, "sanitization must never produce an empty name"


def test_sanitize_filename_preserves_hebrew_and_normal_names():
    """Hebrew is NORMAL here — mangling it would be a bug, not security."""
    assert file_storage.sanitize_filename("תעודת_זהות.pdf") == "תעודת_זהות.pdf"
    assert file_storage.sanitize_filename("חשבונית ינואר.pdf") == "חשבונית ינואר.pdf"
    assert file_storage.sanitize_filename("invoice-Cohen_2026.pdf") == "invoice-Cohen_2026.pdf"
    # A traversal prefix is stripped but the real (Hebrew) name is kept.
    assert "תעודה.pdf" in file_storage.sanitize_filename("../../תעודה.pdf")


def test_sanitize_filename_falls_back_when_nothing_survives():
    """Empty / all-hostile input yields the caller's fallback, never ''."""
    assert file_storage.sanitize_filename(None) == "file"
    assert file_storage.sanitize_filename("") == "file"
    assert file_storage.sanitize_filename("///") == "file"
    assert file_storage.sanitize_filename("...") == "file"
    assert file_storage.sanitize_filename("\r\n\t") == "file"
    assert file_storage.sanitize_filename(None, fallback="file-abc123") == "file-abc123"


def test_sanitize_filename_truncates_an_absurd_name():
    """A 64 KB "name" is an attack; the stored value is bounded."""
    safe = file_storage.sanitize_filename("א" * 50_000)
    assert len(safe) <= file_storage.MAX_FILE_NAME_LEN


def test_storage_key_never_contains_the_customers_name():
    """The object key is two server-minted uuids — traversal is impossible by shape."""
    key = file_storage.storage_key_for(BIZ_A, "ffffffff-1111-2222-3333-444444444444")
    assert key == f"{BIZ_A}/ffffffff-1111-2222-3333-444444444444"
    assert ".." not in key
    assert key.count("/") == 1


# ============================================================================
#  (f) NO PII / SECRETS IN THE LOG STREAM (mirrors test_log_pii_guard.py)
# ============================================================================

# Loggers belonging to the TEST DRIVER, not the app under test.
_NON_APP_LOGGER_PREFIXES = ("httpx", "httpcore", "asyncio", "urllib3")


class _Capture(logging.Handler):
    """Collects the ACTUAL serialized JSON lines the app would emit to stdout."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.split(".")[0] in _NON_APP_LOGGER_PREFIXES:
            return
        self.lines.append(self.format(record))


@pytest.fixture
def captured_logs():
    handler = _Capture()
    root = logging.getLogger()
    prev_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_level)


async def test_media_paths_never_leak_the_name_bytes_token_or_phone(http, captured_logs):
    """Drive a media webhook + a rejected upload; assert the log stream is clean.

    The four canaries are the four things that must never be greppable out of a
    log aggregator after M16:
      * FILE NAME  — customer files are named "תעודת_זהות.pdf"; the name IS PII
        (which is why the column stores it as ciphertext).
      * FILE BYTES — the content itself, obviously.
      * GATEWAY TOKEN — the shared secret that opens every /internal route.
      * CUSTOMER PHONE — PII on every inbound message.
    """
    file_name_canary = "LEAKFILENAME_" + secrets.token_hex(6) + "_תעודה.png"
    file_bytes_canary = "LEAKFILEBYTES_" + secrets.token_hex(6)
    phone_canary = "+97250" + secrets.token_hex(4)
    file_id_canary = "LEAKFILEID_" + secrets.token_hex(6)

    # 1) A REJECTED upload (an EXE wearing a .png name). The rejection is logged —
    #    the log line must name the declared TYPE and nothing else.
    hostile = EXE_MAGIC + file_bytes_canary.encode()
    rejected = await http.post(
        "/internal/wa/media",
        headers=GOOD_HDR,
        data=_form(
            BIZ_A,
            name=file_name_canary,
            mime="image/png",
            message_id=f"m16-log-{secrets.token_hex(6)}",
        ),
        files=_multipart(hostile),
    )
    assert rejected.status_code == 415, rejected.status_code

    # 2) A MEDIA-BEARING webhook. A random gateway_account_id maps to no business,
    #    so the bot stays silent; the point is that the media ref + phone never
    #    reach the log stream on the way through.
    await http.post(
        "/webhook/whatsapp",
        headers=GOOD_HDR,
        json={
            "gateway_account_id": "unmapped-" + secrets.token_hex(8),
            "from": phone_canary,
            "push_name": "Leaky Customer",
            "message_id": "wamid." + secrets.token_hex(6),
            "type": "image",
            "text": "",
            "media": {
                "file_id": file_id_canary,
                "mime_type": "image/png",
                "name": file_name_canary,
            },
        },
    )

    blob = "\n".join(captured_logs.lines)
    # Sanity: the guard is not a no-op — we really captured the app's own lines.
    assert "app.request" in blob or "request" in blob, "no logs captured — check wiring"

    forbidden = {
        "file name": file_name_canary,
        "file bytes": file_bytes_canary,
        "file id": file_id_canary,
        "customer phone": phone_canary,
        "gateway token": GATEWAY_TOKEN,
    }
    leaked = [label for label, value in forbidden.items() if value in blob]
    assert not leaked, f"log stream leaked: {', '.join(leaked)}"


async def test_a_rejected_upload_logs_the_declared_type_but_not_the_name(
    http, captured_logs
):
    """A legitimate rejection must stay DIAGNOSABLE without becoming a leak.

    The operator needs to know "somebody sent something we refused, they called it
    image/png". They do not need — and must not get — the file's name or bytes.
    """
    name_canary = "LEAKNAME_" + secrets.token_hex(6) + ".png"
    r = await http.post(
        "/internal/wa/media",
        headers=GOOD_HDR,
        data=_form(BIZ_A, name=name_canary, mime="image/gif"),
        files=_multipart(b"GIF89a" + b"\x00" * 20, mime="image/gif"),
    )
    assert r.status_code == 415

    blob = "\n".join(captured_logs.lines)
    assert name_canary not in blob, "the rejected file's NAME reached the log"
    assert "image/gif" in blob, "the rejection should still be diagnosable by type"


async def test_the_415_response_body_does_not_echo_the_file_name(http):
    """The error the gateway (and any proxy log) sees carries no customer data."""
    name_canary = "ECHONAME_" + secrets.token_hex(6) + ".png"
    r = await http.post(
        "/internal/wa/media",
        headers=GOOD_HDR,
        data=_form(BIZ_A, name=name_canary, mime="image/png"),
        files=_multipart(EXE_MAGIC),
    )
    assert r.status_code == 415
    assert name_canary not in r.text
