"""The FROZEN gateway -> backend webhook contract (M1 landing pad).

Shape (do not change without updating the gateway in lockstep):

    POST /webhook/whatsapp
    header: X-Gateway-Token: <GATEWAY_API_TOKEN>
    body: {
      gateway_account_id, from (E.164), push_name, message_id,
      timestamp, type, text, raw
    }

NOTE: `from` is a Python keyword, so it is mapped via an alias to `from_`.
This model only *parses/validates* the envelope — it must never be logged
wholesale (it carries the phone number and the message body).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WhatsAppWebhook(BaseModel):
    """Inbound message envelope as posted by the Baileys gateway."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    gateway_account_id: str = Field(..., description="Gateway's per-session account id")
    from_: str = Field(..., alias="from", description="Sender in E.164 (PII — never log)")
    push_name: str | None = Field(default=None, description="WhatsApp display name (PII)")
    message_id: str = Field(..., description="Gateway/WA message id (safe to log)")
    timestamp: int | str | None = Field(default=None, description="Message timestamp")
    type: str = Field(..., description="Message type, e.g. 'text'")
    text: str | None = Field(default=None, description="Message body (PII — never log)")
    raw: Any | None = Field(default=None, description="Original gateway payload (may hold PII)")

    # --- M6a self-test path (decision 0014) ---------------------------------
    # `self_test` is True ONLY when the owner messages their OWN number ("Message
    # Yourself"). The gateway sets it; the backend uses it to gate the live-bot
    # reply path. `conversation_id` is the stable self-chat jid (one per chat),
    # used as the bot runtime's conversation key. Both default to safe values so
    # an older gateway payload (without them) still parses → ack-only.
    self_test: bool = Field(default=False, description="True only for self-chat test messages")
    conversation_id: str | None = Field(
        default=None, description="Stable self-chat conversation id (the chat jid)"
    )
