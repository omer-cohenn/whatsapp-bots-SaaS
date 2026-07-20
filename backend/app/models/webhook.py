"""The FROZEN gateway -> backend webhook contract (M1 landing pad).

Shape (do not change without updating the gateway in lockstep):

    POST /webhook/whatsapp
    header: X-Gateway-Token: <GATEWAY_API_TOKEN>
    body: {
      gateway_account_id, from (E.164), push_name, message_id,
      timestamp, type, text, raw,
      self_test?, conversation_id?, media?
    }

NOTE: `from` is a Python keyword, so it is mapped via an alias to `from_`.
This model only *parses/validates* the envelope — it must never be logged
wholesale (it carries the phone number and the message body).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MediaRef(BaseModel):
    """A reference to ONE already-stored customer file (M16).

    Bounded on purpose: the gateway is trusted, but these values are echoed from
    a message a stranger sent, so the name is capped before it can become a lead
    answer. `mime_type` is the value POST /internal/wa/media returned (sniffed
    from the content), not the sender's declared type. Carries NO bytes.
    """

    model_config = ConfigDict(extra="ignore")

    file_id: str = Field(..., min_length=1, max_length=64)
    mime_type: str = Field(default="", max_length=200)
    name: str = Field(default="", max_length=200, description="File name (PII — never log)")


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

    # --- M16 customer file uploads ------------------------------------------
    # Set by the gateway ONLY after it has downloaded the attachment and stored
    # it via POST /internal/wa/media. Shape: {file_id, mime_type, name} — the
    # server-minted file id plus the SNIFFED mime type the upload API returned
    # (never the type the sender declared). It carries NO bytes.
    #
    # This field is REQUIRED on the model: `extra="ignore"` above means an
    # undeclared key is silently dropped, so without it the gateway's `media`
    # would never reach the engine.
    #
    # `name` is the customer's file name → PII. Like `text`, it must NEVER be
    # logged. Defaults to None so an older gateway payload still parses.
    media: MediaRef | None = Field(
        default=None, description="Stored attachment ref (name is PII — never log)"
    )
