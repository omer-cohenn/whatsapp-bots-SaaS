"""POST /webhook/whatsapp — the gateway → backend receive endpoint.

Flow:
  1. Verify header `X-Gateway-Token` == GATEWAY_API_TOKEN (constant-time) -> 401 else.
  2. Parse the FROZEN contract body (app/models/webhook.py).
  3. Log that a message arrived — REDACTED: gateway_account_id + message_id +
     type + text *length* only. NEVER the phone (`from`), push_name, text, or raw.
  4. Branch on the message kind:
       * SELF-TEST (`self_test=True`, decision 0014 / M6a): the owner messaged
         their OWN number. Run it through the REAL bot pipeline and reply in the
         same self-chat. See `_handle_self_test` below.
       * Otherwise (real customer inbound): ack-only for now — M6b wires the live
         customer path. We still log the redacted receipt.

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

    # 4) Self-test path (M6a): the owner messaged their own number. Run the REAL
    #    bot and reply in the same self-chat. Anything else stays ack-only (M6b).
    if msg.self_test:
        return await _handle_self_test(request, msg)

    # 4b) Real customer inbound — ack-only for now (M6b wires the live path).
    #     Stable response shape: a status + an (empty) replies list.
    return {"status": "received", "replies": []}


async def _handle_self_test(request: Request, msg: WhatsAppWebhook) -> dict[str, Any]:
    """Run a self-chat message through the real bot pipeline and return replies.

    Steps (tenant id is resolved SERVER-SIDE, never from the body):
      1. Resolve the gateway account → business_id via the `resolve_wa_account`
         SECURITY DEFINER lookup (the webhook has NO session, so there is no
         tenant context to scope a normal read). No mapping → silent, replies=[].
      2. Gate on `is_published`: the LIVE bot answers ONLY when the owner has
         published their bot. Not published → silent, replies=[].
      3. Run the full bot turn via `bot_runtime.run_turn(..., is_test=False)` —
         REAL data. `run_turn` opens its own `tenant_connection(business_id)` so
         every write (leads + funnel) is RLS-scoped to this tenant.

    Returns the frozen webhook shape { status, replies }. NEVER logs the phone,
    text, replies, or token.
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
        log.info("self-test: no business for account")
        return {"status": "no business", "replies": []}

    # 2) The live bot answers ONLY when the bot is published (gate BEFORE run_turn).
    settings = await bot_settings_service.get_settings(pool, business_id)
    if not settings.get("is_published"):
        log.info("self-test: bot not published")
        return {"status": "not published", "replies": []}

    # 3) The conversation key is the stable self-chat id. Fall back to the gateway
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

    # Return the replies for the gateway to send back into the self-chat. Never
    # log the reply text (PII / content) — only that we handled the turn.
    log.info("self-test handled", extra={"reply_count": len(result["replies"])})
    return {"status": "ok", "replies": result["replies"]}
