"""Request/response models for the internal WhatsApp API (M6b).

The frozen gateway ↔ backend contract (all protected by X-Gateway-Token):

  GET  /internal/wa/sessions            -> WaSessionsResponse
  GET  /internal/wa/creds/{business_id} -> WaCredsResponse
  PUT  /internal/wa/creds/{business_id}    (WaCredsRequest)  -> {"ok": true}
  POST /internal/wa/status/{business_id}   (WaStatusRequest) -> {"ok": true}

`auth_state` is the base64 wire form of the Baileys session bytes. It is the
crown jewel in transit — it is NEVER logged. The phone / qr_data_url are PII /
linking material, likewise never logged.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WaSessionsResponse(BaseModel):
    """The set of businesses the gateway should open a socket for."""

    sessions: list[str] = Field(
        default_factory=list, description="business_id (uuid) per connected business"
    )


class WaCredsResponse(BaseModel):
    """This business's decrypted Baileys auth_state, base64 for JSON transport.

    Both fields are null when the business has no saved session yet.
    """

    auth_state: str | None = Field(
        default=None, description="Base64 of the decrypted auth_state bytes; PII/crown — never logged"
    )
    key_version: int | None = Field(
        default=None, description="KEK version the row was stored under, or null"
    )


class WaCredsRequest(BaseModel):
    """The gateway's save of a business's Baileys auth_state (base64 bytes)."""

    auth_state: str = Field(
        ..., description="Base64 of the raw auth_state bytes; crown jewel — never logged"
    )


class WaStatusRequest(BaseModel):
    """The gateway's status report for one business's socket.

      * status      — the socket state ('connecting' | 'qr' | 'connected' |
                      'disconnected', gateway-defined).
      * phone       — the linked own number once known (PII; encrypted at rest,
                      never logged). Null while still linking.
      * qr_data_url — a PNG data: URL of the current QR to render, or null. Stored
                      transiently in Redis for the owner; never logged.
    """

    status: str = Field(..., description="Socket status reported by the gateway")
    phone: str | None = Field(default=None, description="Linked own number; PII — never logged")
    qr_data_url: str | None = Field(
        default=None, description="Transient QR PNG data URL, or null; never logged"
    )
