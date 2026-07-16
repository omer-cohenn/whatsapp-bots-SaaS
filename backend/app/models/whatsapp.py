"""Response models for the WhatsApp admin API (M6a / M6a.1, decision 0014).

The frozen owner-facing contract:

  GET  /api/whatsapp/status       -> WhatsAppStatusResponse
  POST /api/whatsapp/link         -> WhatsAppLinkResponse (same shape — status after linking)
  GET  /api/whatsapp/test-numbers -> TestNumbersResponse
  PUT  /api/whatsapp/test-numbers -> TestNumbersRequest (body) -> TestNumbersResponse

`phone` is the owner's OWN linked number; it is the only PII here and is returned
ONLY to the authenticated owner (their own number) — never logged. The
test-numbers `phone`/`label` are likewise PII (the owner's own allow-list) and
are never logged.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WhatsAppStatusResponse(BaseModel):
    """Whether this tenant has linked a WhatsApp account + the live gateway state.

      * linked         — a whatsapp_connections row exists for this business.
      * connected      — the gateway reports an active session for that account.
      * phone          — the linked own number (owner's own; null if unknown).
      * gateway_status — the raw status string from the gateway (e.g.
                         'connected' | 'disconnected' | 'qr' | 'unknown').
    """

    linked: bool = Field(..., description="A connection mapping exists for this business")
    connected: bool = Field(..., description="The gateway session is currently active")
    phone: str | None = Field(default=None, description="Linked own number (owner only)")
    gateway_status: str = Field(..., description="Raw status reported by the gateway")
    # M6b (0027): machine-readable reason a link was refused, e.g.
    # 'phone_conflict' — the scanned number is already linked to ANOTHER
    # business. Null when there is nothing to explain.
    error: str | None = Field(default=None, description="Why the link failed, if it did")


# The link response echoes the same shape (the status AFTER recording the
# mapping), so the frontend can refresh its view from one call.
WhatsAppLinkResponse = WhatsAppStatusResponse


class WhatsAppQrResponse(BaseModel):
    """The current QR for linking, proxied from the gateway.

      * status      — the gateway's status (e.g. 'qr' when a code is ready,
                      'connected' when no code is needed).
      * qr_data_url — a data: URL PNG of the QR to render, or null when none.
    """

    status: str = Field(..., description="Gateway status for the QR flow")
    qr_data_url: str | None = Field(default=None, description="PNG data URL of the QR, or null")


# --- M6a.1: owner's external test allow-list -------------------------------- --

class TestNumber(BaseModel):
    """One entry on the owner's external test allow-list.

      * phone — the test number (digits, with/without '+'; normalized server-side
                so e.g. '054-740-8309' and '+972547408309' compare equal). PII.
      * label — an optional friendly name for the owner's own reference. PII.
    """

    phone: str = Field(..., description="Test phone number (normalized server-side); PII — never logged")
    label: str | None = Field(default=None, description="Optional friendly name; PII — never logged")


class TestNumbersResponse(BaseModel):
    """The owner's saved test allow-list (decrypted, owner-only)."""

    numbers: list[TestNumber] = Field(default_factory=list, description="The saved test numbers")


class TestNumbersRequest(BaseModel):
    """The owner's desired test allow-list (the full set to save).

    Capped at 5 entries (the contract). Each phone is normalized + validated
    server-side; blanks/dupes are dropped before save. A >5 list is rejected
    (422), not silently truncated.
    """

    numbers: list[TestNumber] = Field(
        default_factory=list, max_length=5, description="Up to 5 test numbers to save"
    )
