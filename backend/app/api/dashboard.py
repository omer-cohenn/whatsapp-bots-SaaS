"""Protected /api/* READ / back-office router — the owner dashboard (M7).

M5 PERSISTS leads + the funnel + live-chat state; this router EXPOSES them to the
business owner. It is mounted under the gated `/api` group (see app/api/me.py),
so every route here inherits the deny-by-default session gate.

Endpoints:
  GET  /api/leads                          → this tenant's leads (decrypted, full).
  GET  /api/leads/export                   → the same rows as a formatted .xlsx.
  GET  /api/dashboard                      → funnel counts for a period.
  GET  /api/conversations                  → live conversations (Redis), scoped.
  GET  /api/conversations/{id}             → status + linked lead + transcript.
  GET  /api/conversations/{id}/messages    → transcript only (light/poll).
  POST /api/conversations/{id}/status      → set bot|waiting|human|closed.
  POST /api/conversations/{id}/reply       → queue an owner manual reply (M6 sends).
  PUT  /api/bot/publish                    → focused go-live toggle.

Tenant safety on EVERY route:
  * the business id comes from `current_business` (the server session) ONLY —
    never from a path, query, or body;
  * Postgres reads go through `tenant_connection(...)` so RLS scopes them;
  * Redis keys are business-prefixed and re-checked (`_assert_owns`);
  * PII is decrypted for the OWNER in the response and is NEVER logged.

`is_test` rows are EXCLUDED by default; pass `include_test=true` to see them too.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import quote
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import Response

from app.core.config import get_settings
from app.core.crypto import DecryptionError, decrypt_pii
from app.core.deps import current_business
from app.core.logging import get_logger
from app.db.session import tenant_connection
from app.models.dashboard import (
    BotPublishRequest,
    BotPublishResponse,
    ConversationDetail,
    ConversationItem,
    ConversationReplyRequest,
    ConversationReplyResponse,
    ConversationsResponse,
    ConversationStatusRequest,
    ConversationStatusResponse,
    DashboardResponse,
    LeadItem,
    LeadSeenResponse,
    LeadsResponse,
    LeadsSeenAllResponse,
    LeadStatusRequest,
    LeadStatusResponse,
    MessageItem,
    MessagesResponse,
)
from app.services import (
    bot_settings as bot_settings_service,
    conversation_state,
    file_storage,
    leads as leads_service,
    whatsapp as whatsapp_service,
)
from app.services.leads import export as leads_export
from app.services.leads.search import lead_matches

router = APIRouter(tags=["dashboard"])
log = get_logger("app.api.dashboard")

# Ceiling for the .xlsx export. The list view stops at 500 because it renders
# cards in the browser; a download is expected to be complete, so exports use
# this far larger bound instead. It stays a bound on purpose — the rows are
# decrypted one by one and held in memory to build the sheet, so "no limit"
# would let a single large tenant push the backend into swap.
EXPORT_MAX_ROWS = 50_000

# A conversation id is part of the Redis key under this tenant's prefix; bound its
# length/charset so it can't smuggle separators or be unreasonably large.
_CONV_ID_MAX = 200


@router.get("/leads", response_model=LeadsResponse)
async def get_leads(
    request: Request,
    business_id: str = Depends(current_business),
    period: Literal["week", "month", "all"] = Query("all"),
    status_filter: Literal[
        "all", "new", "in_progress", "abandoned", "open", "deal", "closed"
    ] = Query("all", alias="status"),
    flow: str | None = Query(None, max_length=40),
    include_test: bool = Query(False),
) -> LeadsResponse:
    """List this tenant's leads (newest first), decrypted, with ALL answers.

    Filters: period (week|month|all), status (all|new|in_progress|abandoned|open|
    deal|closed, where 'open' = new+in_progress), flow (= lead_name). `is_test`
    excluded unless include_test=true. The tenant is the session's verified
    business; RLS scopes every read. We never log a decrypted value.
    """
    try:
        async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
            rows = await leads_service.list_leads(
                conn,
                business_id,
                period=period,
                status=status_filter,
                flow=flow,
                include_test=include_test,
            )
    except DecryptionError:
        # A key mismatch on a stored value: fail loud-but-generic (no str(e), no
        # plaintext). The owner sees a server error, not a leaked detail.
        log.error("lead decryption failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="could not read leads",
        ) from None

    return LeadsResponse(leads=[LeadItem(**row) for row in rows])


@router.get("/leads/export")
async def export_leads(
    request: Request,
    business_id: str = Depends(current_business),
    period: Literal["week", "month", "all"] = Query("all"),
    status_filter: Literal[
        "all", "new", "in_progress", "abandoned", "open", "deal", "closed"
    ] = Query("all", alias="status"),
    flow: str | None = Query(None, max_length=40),
    include_test: bool = Query(False),
    q: str | None = Query(None, max_length=100),
) -> Response:
    """Download THIS tenant's leads as a formatted .xlsx (M17).

    Same filters as `GET /api/leads` (period / status / flow / include_test) plus
    `q`, a free-text keyword. The rows come from the very same
    `leads_service.list_leads` call — that reuse is what guarantees tenant
    isolation, because `tenant_connection` binds the RLS context and NO new SQL
    is written here. `q` is then applied IN PYTHON via
    `leads.search.lead_matches`, whose rule has a TypeScript twin in the
    dashboard so the download always matches what the owner sees on screen.

    The workbook carries decrypted customer PII: names, phones, answers, and
    hyperlinks to the customer's uploaded files (absolute URLs pointing back at
    the session-gated `/api/leads/files/{id}` route — still no presigned URLs).
    Hence `Cache-Control: private, no-store`, exactly like the file download.

    An empty result set is a 200 with a header-only workbook, never a 404.
    We log a row COUNT and the non-PII filters only — never a name, a phone, an
    answer, or the keyword the owner typed.
    """
    try:
        async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
            rows = await leads_service.list_leads(
                conn,
                business_id,
                period=period,
                status=status_filter,
                flow=flow,
                include_test=include_test,
                # The screen paginates at 500; a download is meant to be the
                # WHOLE book, so we lift the cap here. It is a cap, not "no
                # limit": one tenant's export still has a bounded ceiling, so a
                # runaway account can't pull unbounded rows into memory.
                limit=EXPORT_MAX_ROWS,
            )
    except DecryptionError:
        # Same posture as get_leads: loud-but-generic, no str(e), no plaintext.
        log.error("lead decryption failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="could not read leads",
        ) from None

    if q:
        rows = [row for row in rows if lead_matches(row, q)]

    base_url = get_settings().public_base_url.rstrip("/")
    content = leads_export.build_leads_workbook(
        rows, base_url=base_url, sheet_title=flow or "לידים"
    )
    safe_name = leads_export.build_export_filename(flow=flow, status=status_filter)

    # RFC 5987, same shape as download_lead_file: the ASCII `filename=` fallback
    # for old clients plus `filename*=UTF-8''...` so the Hebrew title survives.
    quoted = quote(safe_name, safe="")
    ascii_fallback = safe_name.encode("ascii", "ignore").decode().strip() or "leads.xlsx"

    log.info(
        "leads exported",
        extra={
            "business_id": business_id,
            "rows": len(rows),
            "period": period,
            "status": status_filter,
            "include_test": include_test,
            "has_query": bool(q),
        },
    )

    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quoted}'
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


# A lead id is a UUID supplied in the path; bound its length so it can't be an
# unreasonably large value (the service still scopes the UPDATE by business_id).
_LEAD_ID_MAX = 64


@router.post("/leads/seen-all", response_model=LeadsSeenAllResponse)
async def mark_all_leads_seen(
    request: Request,
    business_id: str = Depends(current_business),
) -> LeadsSeenAllResponse:
    """Mark ALL unseen leads as read in the home feed (decision 0022). Tenant-scoped.

    Stamps `feed_seen_at = now()` on every row where it was NULL for this tenant.
    Returns the count of rows updated. Idempotent — safe to call multiple times.
    """
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        count = await leads_service.mark_all_leads_feed_seen(conn, business_id)
    return LeadsSeenAllResponse(count=count)


@router.delete("/leads/{lead_id}")
async def delete_lead(
    request: Request,
    lead_id: str = Path(..., min_length=1, max_length=_LEAD_ID_MAX),
    business_id: str = Depends(current_business),
) -> Response:
    """Hard-delete a lead from the DB (owner action). Tenant-scoped.

    Cascades to flow_events (ON DELETE CASCADE). Returns 204 on success; 404 when
    the lead doesn't exist or belongs to another tenant. The business_id comes only
    from the server session — never from the path or body.
    """
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        deleted = await leads_service.delete_lead(conn, business_id, lead_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="lead not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/leads/{lead_id}/seen", response_model=LeadSeenResponse)
async def mark_lead_seen(
    request: Request,
    lead_id: str = Path(..., min_length=1, max_length=_LEAD_ID_MAX),
    business_id: str = Depends(current_business),
) -> LeadSeenResponse:
    """Dismiss one lead from the home feed (decision 0022). Tenant-scoped.

    Stamps `feed_seen_at = now()` on the lead so it no longer appears in the
    home feed. Idempotent — re-marking an already-seen lead is a no-op. 404 when
    the lead doesn't exist or belongs to another tenant.
    """
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        found = await leads_service.mark_lead_feed_seen(conn, business_id, lead_id)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="lead not found"
        )
    return LeadSeenResponse(lead_id=lead_id)


@router.patch("/leads/{lead_id}/status", response_model=LeadStatusResponse)
async def set_lead_status(
    body: LeadStatusRequest,
    request: Request,
    lead_id: str = Path(..., min_length=1, max_length=_LEAD_ID_MAX),
    business_id: str = Depends(current_business),
) -> LeadStatusResponse:
    """Owner-set a lead's status (e.g. → 'deal' or 'closed'), tenant-scoped.

    `status` is validated by the request model (Literal). The optional `note` (the
    owner's outcome note) is passed through and encrypted at rest by the service;
    it is PII and is NEVER logged. The UPDATE is RLS-scoped by the session's
    verified business id (never from the path/body); if no row matched
    (wrong/foreign lead) we return 404.

    close_reason (decision 0021): when the owner closes a lead (status='closed')
    that was being handled by a HUMAN — its live conversation is 'human' or
    'waiting' — this is the "מענה הושלם" path, so we stamp close_reason='answered'.
    We do NOT touch close_reason for any other status (e.g. 'deal' stays a pure
    owner outcome). The Redis status read is tenant-scoped (business-prefixed key).
    """
    redis = request.app.state.redis
    try:
        async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
            close_reason: str | None = None
            if body.status == "closed":
                # Find this lead's conversation and check whether a human was on it.
                conv_id = await leads_service.get_conversation_id_for_lead(
                    conn, business_id, lead_id
                )
                if conv_id is not None:
                    conv_status = await conversation_state.get_status(
                        redis, business_id, conv_id
                    )
                    if conv_status in (
                        conversation_state.STATUS_HUMAN,
                        conversation_state.STATUS_WAITING,
                    ):
                        close_reason = leads_service.CLOSE_REASON_ANSWERED
            updated = await leads_service.set_lead_status(
                conn, business_id, lead_id, body.status,
                note=body.note, close_reason=close_reason,
            )
    except ValueError:
        # Defensive: the Literal already constrains status, so this is unexpected.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid status",
        ) from None

    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="lead not found"
        )
    return LeadStatusResponse(lead_id=lead_id, status=body.status)


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    request: Request,
    business_id: str = Depends(current_business),
    period: Literal["week", "month", "all"] = Query("all"),
    include_test: bool = Query(False),
) -> DashboardResponse:
    """Funnel stats (started/completed/abandoned + total leads) for the period.

    Pulled from flow_events + leads, RLS-scoped, `is_test` excluded by default.
    """
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        stats = await leads_service.funnel_stats(
            conn, business_id, period=period, include_test=include_test
        )
    return DashboardResponse(period=period, **stats)


@router.get("/conversations", response_model=ConversationsResponse)
async def get_conversations(
    request: Request,
    business_id: str = Depends(current_business),
    status_filter: Literal["bot", "waiting", "human", "closed"] | None = Query(
        None, alias="status"
    ),
) -> ConversationsResponse:
    """List this tenant's live conversations from Redis (status + preview + time).

    Strictly business-scoped (see `conversation_state.list_conversations` for the
    per-business index choice). `status` optionally filters to
    bot|waiting|human|closed.

    M18: each row is then enriched with the customer's `contact_name` + `phone`,
    joined from the linked lead in ONE batched, RLS-scoped query — the Redis
    record has no name, and the inbox needs one to render a WhatsApp-style row
    with an avatar. The enrichment is BEST-EFFORT: if the lookup fails the list
    still returns, just without names, because a cosmetic join must never take
    the inbox down. Names/phones are decrypted for the owner and NEVER logged.
    """
    redis = request.app.state.redis
    items = await conversation_state.list_conversations(
        redis, business_id, status=status_filter
    )
    # unread_total is summed across ALL of this tenant's conversations (decision
    # 0021) — independent of any status filter, so the tab badge reflects the
    # whole inbox even when the list view is narrowed.
    total_unread = await conversation_state.unread_total(redis, business_id)

    if items:
        try:
            async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
                contacts = await leads_service.contacts_for_conversations(
                    conn, business_id, [it["conversation_id"] for it in items]
                )
            for item in items:
                found = contacts.get(item["conversation_id"])
                if found:
                    item["contact_name"] = found["contact_name"]
                    item["phone"] = found["phone"]
        except (DecryptionError, OSError, asyncpg.PostgresError):
            # Degrade to an un-named list rather than fail the whole inbox.
            log.warning("conversation contact enrichment failed")

    return ConversationsResponse(
        conversations=[ConversationItem(**item) for item in items],
        unread_total=total_unread,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
)
async def get_conversation(
    request: Request,
    conversation_id: str = Path(..., min_length=1, max_length=_CONV_ID_MAX),
    business_id: str = Depends(current_business),
) -> ConversationDetail:
    """One conversation: live status + transcript (Redis) + its linked lead (PG).

    Status and the transcript come from Redis (business-prefixed, `_assert_owns`
    re-checked in the service). The linked lead is read RLS-scoped via
    `tenant_connection`; if a stored value can't be decrypted we fail generic 500
    exactly like `get_leads` (no str(e), no plaintext). We never log message text.

    Opening a conversation = the owner READING it, so we reset its unread counter
    to 0 here (decision 0021). This is the single, cleanest mark-read hook: the UI
    already calls this GET to open a chat, so no extra endpoint is needed. The
    light /messages poll endpoint deliberately does NOT mark-read (polling
    shouldn't keep clearing the badge while the owner isn't looking).
    """
    redis = request.app.state.redis
    status_value = await conversation_state.get_status(
        redis, business_id, conversation_id
    )
    raw_messages = await conversation_state.get_messages(
        redis, business_id, conversation_id
    )
    # The owner opened this chat → clear its unread badge (tenant-scoped).
    await conversation_state.mark_read(redis, business_id, conversation_id)

    try:
        async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
            lead_row = await leads_service.get_lead_by_conversation(
                conn, business_id, conversation_id
            )
    except DecryptionError:
        log.error("lead decryption failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="could not read conversation",
        ) from None

    return ConversationDetail(
        conversation_id=conversation_id,
        # No status set yet (brand-new chat) defaults to the bot handling it.
        status=status_value or "bot",
        lead=LeadItem(**lead_row) if lead_row is not None else None,
        messages=[MessageItem(**msg) for msg in raw_messages],
    )


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagesResponse,
)
async def get_conversation_messages(
    request: Request,
    conversation_id: str = Path(..., min_length=1, max_length=_CONV_ID_MAX),
    business_id: str = Depends(current_business),
) -> MessagesResponse:
    """Just this conversation's transcript (oldest→newest) from Redis, scoped.

    Business-prefixed key, `_assert_owns` re-checked in the service. No status or
    lead read here — this is the light endpoint for polling the chat. Never logs
    message text.
    """
    raw_messages = await conversation_state.get_messages(
        request.app.state.redis, business_id, conversation_id
    )
    return MessagesResponse(
        conversation_id=conversation_id,
        messages=[MessageItem(**msg) for msg in raw_messages],
    )


@router.post(
    "/conversations/{conversation_id}/status",
    response_model=ConversationStatusResponse,
)
async def set_conversation_status(
    body: ConversationStatusRequest,
    request: Request,
    conversation_id: str = Path(..., min_length=1, max_length=_CONV_ID_MAX),
    business_id: str = Depends(current_business),
) -> ConversationStatusResponse:
    """Set a conversation's status to bot|waiting|human|closed (tenant-scoped).

    The value is validated by the request model (Literal); the service re-checks
    the business prefix on the key, so there is no path to another tenant's chat.
    """
    await conversation_state.set_status(
        request.app.state.redis, business_id, conversation_id, body.status
    )
    return ConversationStatusResponse(
        conversation_id=conversation_id, status=body.status
    )


@router.post(
    "/conversations/{conversation_id}/reply",
    response_model=ConversationReplyResponse,
)
async def reply_to_conversation(
    body: ConversationReplyRequest,
    request: Request,
    conversation_id: str = Path(..., min_length=1, max_length=_CONV_ID_MAX),
    business_id: str = Depends(current_business),
) -> ConversationReplyResponse:
    """Queue the owner's manual reply AND send it to the customer on WhatsApp (M6a.2).

    The reply is FIRST appended to the live conversation record (preview +
    transcript + outbound queue) tenant-scoped, so it is never lost. Then we
    best-effort send it to WhatsApp via the gateway: `conversation_id` IS the
    customer's WhatsApp jid, so it doubles as the send `to`. The send is on TOP of
    the queue — if it fails we still return `queued=True` with `delivered=False`,
    never erroring the owner's request. We never log the reply text.
    """
    await conversation_state.append_reply(
        request.app.state.redis, business_id, conversation_id, body.text
    )
    # Best-effort delivery on top of the queue: the conversation id is the
    # customer's WhatsApp jid, so it doubles as the send target. Never logs text.
    delivered = await whatsapp_service.send_outbound(
        business_id, conversation_id, body.text
    )
    return ConversationReplyResponse(
        conversation_id=conversation_id, queued=True, delivered=delivered
    )


@router.put("/bot/publish", response_model=BotPublishResponse)
async def publish_bot(
    body: BotPublishRequest,
    request: Request,
    business_id: str = Depends(current_business),
) -> BotPublishResponse:
    """Focused go-live toggle: set bot_settings.is_published for this tenant."""
    is_published = await bot_settings_service.set_published(
        request.app.state.pg_pool, business_id, body.is_published
    )
    return BotPublishResponse(is_published=is_published)


# --- M16: owner file download ------------------------------------------------

@router.get("/leads/files/{file_id}")
async def download_lead_file(
    request: Request,
    file_id: str = Path(..., min_length=1, max_length=64),
    business_id: str = Depends(current_business),
) -> Response:
    """Stream ONE customer-uploaded file back to the owner, decrypted.

    NO PRESIGNED URLS, EVER. A presigned URL is a bearer token for the raw object
    that leaks through history, referrers and chat forwards, and it would hand
    out the CIPHERTEXT anyway (the bytes in R2 are envelope-encrypted and useless
    without the KEK). The bytes therefore always flow through this session-gated
    route, which is the only place the decryption happens.

    Tenant wall, three layers:
      1. the router-level session gate (deny-by-default under /api);
      2. `business_id` comes from the verified session ONLY — never the path;
      3. the SELECT runs inside `tenant_connection(pg_pool, business_id)`, so RLS
         (`business_id = current_business_id()`, migration 0028) makes another
         tenant's file_id indistinguishable from a nonexistent one → 404. The
         explicit `AND business_id = $2` is a second, redundant guard.

    Pool/role: `pg_pool` (app_role). This is an OWNER action on the owner's own
    data; app_role holds SELECT on lead_files (0028). The gateway_role pool is
    for the inbound gateway path only and is never touched here.

    Response headers: the real Content-Type, `Content-Disposition: attachment`
    with a sanitized + RFC 5987 encoded filename (Hebrew names are normal here),
    and `Cache-Control: private, no-store` so the decrypted PII is never written
    to a shared cache or a disk cache.
    """
    # A malformed uuid must never reach the query — and must look exactly like a
    # missing file, so this route can't be used to probe id validity.
    try:
        file_id = str(UUID(file_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        row = await conn.fetchrow(
            """
            SELECT storage_key, wrapped_dek, key_version, mime_type, file_name
            FROM lead_files
            WHERE id = $1 AND business_id = $2
            """,
            file_id,
            business_id,
        )

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    try:
        payload = file_storage.get_decrypted(
            row["storage_key"], row["wrapped_dek"], row["key_version"]
        )
    except file_storage.StorageNotConfiguredError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="file storage is not configured",
        ) from None
    except file_storage.StorageError:
        log.error("file download failed", extra={"reason": "storage"})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="file unavailable"
        ) from None
    except DecryptionError:
        # FAIL LOUD: a key mismatch or a tampered object is a real incident. We
        # never hand back the ciphertext as a "file".
        log.error("file download failed", extra={"reason": "decrypt"})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="file could not be decrypted",
        ) from None

    # The stored name is PII ciphertext. If it fails to decrypt we still serve the
    # bytes under a neutral name rather than failing the whole download.
    try:
        raw_name = decrypt_pii(row["file_name"])
    except DecryptionError:
        raw_name = None
    safe_name = file_storage.sanitize_filename(raw_name, fallback=f"file-{file_id[:8]}")

    # RFC 5987: `filename*=UTF-8''<pct-encoded>` carries non-ASCII (Hebrew) names.
    # The plain `filename=` fallback is ASCII-only for old clients. quote() also
    # guarantees no quote/CR/LF can break out of the header value.
    quoted = quote(safe_name, safe="")
    ascii_fallback = safe_name.encode("ascii", "ignore").decode() or "file"

    return Response(
        content=payload,
        media_type=row["mime_type"],
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quoted}'
            ),
            # Decrypted customer PII: no shared cache, no disk cache, ever.
            "Cache-Control": "private, no-store",
            # Belt-and-braces: never let a browser re-interpret the type.
            "X-Content-Type-Options": "nosniff",
        },
    )
