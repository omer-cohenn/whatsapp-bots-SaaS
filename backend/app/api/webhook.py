"""POST /webhook/whatsapp — the gateway → backend receive endpoint.

Flow:
  1. Verify header `X-Gateway-Token` == GATEWAY_API_TOKEN (constant-time) -> 401 else.
  2. Parse the FROZEN contract body (app/models/webhook.py).
  3. Log that a message arrived — REDACTED: gateway_account_id + message_id +
     type + text *length* only. NEVER the phone (`from`), push_name, text, or raw.
  4. Branch on the message kind:
       * SELF-TEST (`self_test=True`, decision 0014 / M6a): the owner messaged
         their OWN number. Run it through the REAL bot pipeline and reply in the
         same self-chat. The owner is ALWAYS allowed.
       * ALLOW-LIST INBOUND (`self_test=False`, M6a.1): a message from any other
         phone. We resolve the business server-side, then run the REAL bot ONLY
         when the sender is on that business's test allow-list. Everyone else is
         ignored (silent, replies=[]). Blank/non-text messages are ack-only.
     Both run paths share ONE core (`_run_bot_turn`): resolve → published →
     run_turn. They differ ONLY in the allow gate (self-test: always allowed;
     inbound: must be on the allow-list).

The response contract (BOTH branches return this shape):
  { "status": str, "replies": [str, ...] }
`replies` is `[]` whenever the bot stays silent (no mapping / not published /
ack-only), so the gateway has one stable shape to handle.

Security: the webhook is PUBLIC (shared service token, no user session). We NEVER
trust a business id from the body — for the self-test path the tenant is resolved
SERVER-SIDE from the gateway account id (see `_handle_self_test`). We never log
the phone, the message text, the replies, or the token.
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.webhook import WhatsAppWebhook
from app.services import bot_runtime, bot_settings as bot_settings_service
from app.services import whatsapp as whatsapp_service
from app.services import whatsapp_test_numbers as test_numbers_service

router = APIRouter(tags=["webhook"])
log = get_logger("app.webhook")


def _token_ok(provided: str | None) -> bool:
    """Constant-time compare the provided token against the configured one."""
    if not provided:
        return False
    expected = get_settings().gateway_api_token.get_secret_value()
    return hmac.compare_digest(provided, expected)


@router.post("/webhook/whatsapp")
async def whatsapp_webhook(
    request: Request,
    x_gateway_token: str | None = Header(default=None, alias="X-Gateway-Token"),
) -> dict[str, Any]:
    # 1) Authenticate the gateway. Reject before reading/parsing the body.
    if not _token_ok(x_gateway_token):
        # Never echo the provided token or any header value.
        log.warning("webhook auth failed")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid gateway token"
        )

    # 2) Parse the frozen contract. Malformed -> 422 (handled by FastAPI).
    body = await request.json()
    msg = WhatsAppWebhook.model_validate(body)

    # 3) REDACTED receipt log. Only non-PII fields + the *length* of the text.
    #    Explicitly excluded: from (phone), push_name, text, raw, conversation_id.
    log.info(
        "whatsapp message received",
        extra={
            "gateway_account_id": msg.gateway_account_id,
            "message_id": msg.message_id,
            "type": msg.type,
            "text_len": len(msg.text or ""),
            "self_test": msg.self_test,
        },
    )

    # 4) Self-test path (M6a): the owner messaged their own number. The owner is
    #    ALWAYS allowed — run the REAL bot and reply in the same self-chat.
    if msg.self_test:
        return await _handle_self_test(request, msg)

    # 4b) Allow-list inbound (M6a.1): a message from any OTHER phone. Run the REAL
    #     bot ONLY when the sender is on the resolved business's test allow-list;
    #     everyone else is silent. Blank/non-text messages stay ack-only.
    return await _handle_allowlist_inbound(request, msg)


async def _run_bot_turn(
    request: Request, msg: WhatsAppWebhook, *, log_label: str
) -> dict[str, Any]:
    """Shared core for both run paths: resolve → published → run_turn.

    Steps (tenant id is resolved SERVER-SIDE, never from the body):
      1. Resolve the gateway account → business_id via the `resolve_wa_account`
         SECURITY DEFINER lookup (the webhook has NO session, so there is no
         tenant context to scope a normal read). No mapping → silent, replies=[].
      2. Gate on `is_published`: the LIVE bot answers ONLY when the owner has
         published their bot. Not published → silent, replies=[].
      3. Run the full bot turn via `bot_runtime.run_turn(..., is_test=False)` —
         REAL data. `run_turn` opens its own `tenant_connection(business_id)` so
         every write (leads + funnel) is RLS-scoped to this tenant.

    The CALLER is responsible for the allow gate BEFORE invoking this (self-test:
    always allowed; inbound: must be on the allow-list). Returns the frozen
    webhook shape { status, replies }. NEVER logs the phone, text, replies, or
    token — only the redacted `log_label` + a reply count.
    """
    pool = request.app.state.pg_pool
    redis = request.app.state.redis

    # 1) Account → business (server-side; bypasses RLS via the definer fn, and
    #    exposes ONLY the business_id for that exact account — nothing else).
    business_id = await whatsapp_service.get_connection_by_account(
        pool, msg.gateway_account_id
    )
    if business_id is None:
        # No business has linked this gateway account → the bot stays silent.
        log.info("%s: no business for account", log_label)
        return {"status": "no business", "replies": []}

    # 2) The live bot answers ONLY when the bot is published (gate BEFORE run_turn).
    settings = await bot_settings_service.get_settings(pool, business_id)
    if not settings.get("is_published"):
        log.info("%s: bot not published", log_label)
        return {"status": "not published", "replies": []}

    # 3) The conversation key is the stable chat id. Fall back to the gateway
    #    account id if the gateway didn't send one, so a turn still has a stable
    #    key (scoped under business_id inside run_turn).
    conversation_id = msg.conversation_id or msg.gateway_account_id

    # Run the WHOLE bot (engine + leads + funnel + handoff + booking link). REAL
    # data: is_test=False. run_turn opens its own tenant_connection for RLS.
    result = await bot_runtime.run_turn(
        pool,
        redis,
        business_id=business_id,
        conversation_id=conversation_id,
        message=msg.text or "",
        is_test=False,
    )

    # Return the replies for the gateway to send back. Never log the reply text
    # (PII / content) — only that we handled the turn.
    log.info("%s handled", log_label, extra={"reply_count": len(result["replies"])})
    return {"status": "ok", "replies": result["replies"]}


async def _handle_self_test(request: Request, msg: WhatsAppWebhook) -> dict[str, Any]:
    """Self-chat path: the owner is ALWAYS allowed — run the shared bot core."""
    return await _run_bot_turn(request, msg, log_label="self-test")


async def _handle_allowlist_inbound(
    request: Request, msg: WhatsAppWebhook
) -> dict[str, Any]:
    """Inbound from another phone: run the bot ONLY if the sender is allow-listed.

    Order matters and mirrors the contract:
      * Blank/non-text inbound → ack-only ("received", replies=[]); we don't even
        resolve a business for an empty message.
      * Resolve the business server-side (resolve_wa_account). No mapping →
        "no business", silent.
      * Check the allow-list INSIDE this tenant (RLS-scoped). Not on the list →
        "not allowed", silent. The sender phone is NEVER logged.
      * Allowed → hand to the shared core (published gate + run_turn).
    """
    # Blank/whitespace-only or non-text messages get a stable ack, no bot run.
    if not (msg.text or "").strip():
        return {"status": "received", "replies": []}

    pool = request.app.state.pg_pool

    # Resolve the business server-side BEFORE the allow-list check (the allow-list
    # is read inside this tenant's RLS scope).
    business_id = await whatsapp_service.get_connection_by_account(
        pool, msg.gateway_account_id
    )
    if business_id is None:
        log.info("inbound: no business for account")
        return {"status": "no business", "replies": []}

    # The allow gate: only senders on THIS business's test allow-list are run.
    # `from_` is the sender phone (PII) — passed to the service, NEVER logged.
    allowed = await test_numbers_service.is_number_allowed(
        pool, business_id, msg.from_
    )
    if not allowed:
        log.info("inbound: sender not on allow-list")
        return {"status": "not allowed", "replies": []}

    # Allowed → shared core (re-resolves the business; cheap definer lookup, keeps
    # one code path for resolve → published → run_turn).
    return await _run_bot_turn(request, msg, log_label="inbound")
