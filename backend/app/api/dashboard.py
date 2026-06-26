"""Protected /api/* READ / back-office router — the owner dashboard (M7).

M5 PERSISTS leads + the funnel + live-chat state; this router EXPOSES them to the
business owner. It is mounted under the gated `/api` group (see app/api/me.py),
so every route here inherits the deny-by-default session gate.

Endpoints:
  GET  /api/leads                          → this tenant's leads (decrypted, full).
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

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.core.crypto import DecryptionError
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
    LeadsResponse,
    LeadStatusRequest,
    LeadStatusResponse,
    MessageItem,
    MessagesResponse,
)
from app.services import (
    bot_settings as bot_settings_service,
    conversation_state,
    leads as leads_service,
    whatsapp as whatsapp_service,
)

router = APIRouter(tags=["dashboard"])
log = get_logger("app.api.dashboard")

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


# A lead id is a UUID supplied in the path; bound its length so it can't be an
# unreasonably large value (the service still scopes the UPDATE by business_id).
_LEAD_ID_MAX = 64


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
    """
    redis = request.app.state.redis
    items = await conversation_state.list_conversations(
        redis, business_id, status=status_filter
    )
    # unread_total is summed across ALL of this tenant's conversations (decision
    # 0021) — independent of any status filter, so the tab badge reflects the
    # whole inbox even when the list view is narrowed.
    total_unread = await conversation_state.unread_total(redis, business_id)
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
    delivered = await whatsapp_service.send_outbound(conversation_id, body.text)
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
