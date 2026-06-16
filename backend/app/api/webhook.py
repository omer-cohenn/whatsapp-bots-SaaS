"""POST /webhook/whatsapp — the M1 receive landing pad.

Flow:
  1. Verify header `X-Gateway-Token` == GATEWAY_API_TOKEN (constant-time) -> 401 else.
  2. Parse the FROZEN contract body (app/models/webhook.py).
  3. Log that a message arrived — REDACTED: gateway_account_id + message_id +
     type + text *length* only. NEVER the phone (`from`), push_name, text, or raw.
  4. Return {"status": "received"}.

This is the receive spike: its whole job is to prove a message reached the
backend without leaking any of the message's PII into the logs.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.webhook import WhatsAppWebhook

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
) -> dict[str, str]:
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
    #    Explicitly excluded: from (phone), push_name, text, raw.
    log.info(
        "whatsapp message received",
        extra={
            "gateway_account_id": msg.gateway_account_id,
            "message_id": msg.message_id,
            "type": msg.type,
            "text_len": len(msg.text or ""),
        },
    )

    # 4) Ack. No echo of any inbound content.
    return {"status": "received"}
