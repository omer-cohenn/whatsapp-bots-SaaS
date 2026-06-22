"""Response models for the WhatsApp admin API (M6a, decision 0014).

The frozen owner-facing contract:

  GET  /api/whatsapp/status -> WhatsAppStatusResponse
  POST /api/whatsapp/link   -> WhatsAppLinkResponse (same shape — the status after linking)

`phone` is the owner's OWN linked number; it is the only PII here and is returned
ONLY to the authenticated owner (their own number) — never logged.
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
