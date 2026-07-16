"""Owner-facing WhatsApp admin API (M6a → M6b per-business, decision 0014).

Mounted under the gated /api group (app/api/me.py), so every route here inherits
the deny-by-default session gate. The tenant is ALWAYS the verified session
business (`current_business`) — never a client value.

Routes (frozen contract):

  GET  /api/whatsapp/status       -> { linked, connected, phone, gateway_status }
  POST /api/whatsapp/link         -> { linked, connected, phone, gateway_status }
  GET  /api/whatsapp/qr           -> { status, qr_data_url }
  GET  /api/whatsapp/test-numbers -> { numbers: [{ phone, label }] }
  PUT  /api/whatsapp/test-numbers -> { numbers: [{ phone, label }] }

M6b makes this fully PER-BUSINESS: there is no longer a single global gateway
session to proxy. `status` reads THIS tenant's own `whatsapp_connections` row
(RLS-scoped); `qr` reads the transient QR the gateway stashed in Redis for this
business (`wa:qr:{business_id}`); `link` means "start/ensure a session for MY
business" — it guarantees a connection row exists so `wa_list_sessions()`
includes this tenant and the gateway opens a socket + produces a QR.
`test-numbers` manages the owner's external test allow-list (up to 5 numbers,
each encrypted at rest). The owner's own phone and the test numbers/labels are
the only PII and are NEVER logged.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status as http_status

from app.core.deps import current_business
from app.core.logging import get_logger
from app.models.whatsapp import (
    TestNumber,
    TestNumbersRequest,
    TestNumbersResponse,
    WhatsAppLinkResponse,
    WhatsAppQrResponse,
    WhatsAppStatusResponse,
)
from app.services import whatsapp as whatsapp_service
from app.services import whatsapp_test_numbers as test_numbers_service

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])
log = get_logger("app.whatsapp")


def _qr_key(business_id: str) -> str:
    """Redis key where the gateway stashes THIS business's transient QR.

    Mirrors app/api/internal_wa.py::_qr_key — the gateway writes it via the
    internal status endpoint, the owner reads it here.
    """
    return f"wa:qr:{business_id}"


def _status_shape(
    state: dict[str, str | None] | None,
) -> WhatsAppStatusResponse:
    """Build the frozen status response from this tenant's connection row.

      * linked         — a whatsapp_connections row exists for this business.
      * connected      — that row's status is 'connected'.
      * phone          — the decrypted own number (owner-only; null if unknown).
      * gateway_status — the raw connection status ('disconnected' if unlinked).
    """
    if state is None:
        return WhatsAppStatusResponse(
            linked=False, connected=False, phone=None, gateway_status="disconnected"
        )
    gateway_status = state["status"] or "disconnected"
    return WhatsAppStatusResponse(
        linked=True,
        connected=gateway_status == "connected",
        phone=state["phone"],
        gateway_status=gateway_status,
        # e.g. 'phone_conflict' → the UI explains the refused link (0027).
        error=state.get("last_error"),
    )


@router.get("/status", response_model=WhatsAppStatusResponse)
async def whatsapp_status(
    request: Request,
    business_id: str = Depends(current_business),
) -> WhatsAppStatusResponse:
    """Return this tenant's own WhatsApp link state (RLS-scoped, per-business)."""
    state = await whatsapp_service.get_connection_state(
        request.app.state.pg_pool, business_id
    )
    return _status_shape(state)


@router.post("/link", response_model=WhatsAppLinkResponse)
async def whatsapp_link(
    request: Request,
    business_id: str = Depends(current_business),
) -> WhatsAppLinkResponse:
    """Start/ensure a WhatsApp session for THIS business (M6b).

    Guarantees a `whatsapp_connections` row exists for this tenant (marked
    'connecting' unless already connected). That row is what makes
    `wa_list_sessions()` include this business, so the gateway opens a socket and
    produces a QR the owner can scan. Returns the resulting status shape so the
    frontend can refresh in one call.
    """
    await whatsapp_service.ensure_session(request.app.state.pg_pool, business_id)
    state = await whatsapp_service.get_connection_state(
        request.app.state.pg_pool, business_id
    )
    return _status_shape(state)


@router.get("/qr", response_model=WhatsAppQrResponse)
async def whatsapp_qr(
    request: Request,
    business_id: str = Depends(current_business),
) -> WhatsAppQrResponse:
    """Return THIS business's current QR (from Redis) for linking.

    `qr_data_url` comes from the transient Redis key the gateway writes via the
    internal status endpoint (null when there is no pending code); `status` is
    this tenant's connection status. The QR is never logged.
    """
    state = await whatsapp_service.get_connection_state(
        request.app.state.pg_pool, business_id
    )
    status_str = (state["status"] if state else None) or "disconnected"
    qr_data_url = await request.app.state.redis.get(_qr_key(business_id))
    return WhatsAppQrResponse(status=status_str, qr_data_url=qr_data_url)


# --- M6a.1: owner's external test allow-list -------------------------------- --

@router.get("/test-numbers", response_model=TestNumbersResponse)
async def get_test_numbers(
    request: Request,
    business_id: str = Depends(current_business),
) -> TestNumbersResponse:
    """Return this tenant's test allow-list (decrypted, owner-only).

    The tenant is always the verified session business; the read is RLS-scoped
    inside the service. Phone numbers and labels are never logged.
    """
    numbers = await test_numbers_service.get_test_numbers(
        request.app.state.pg_pool, business_id
    )
    return TestNumbersResponse(
        numbers=[TestNumber(phone=n["phone"], label=n["label"]) for n in numbers]
    )


@router.put("/test-numbers", response_model=TestNumbersResponse)
async def put_test_numbers(
    request: Request,
    body: TestNumbersRequest,
    business_id: str = Depends(current_business),
) -> TestNumbersResponse:
    """Replace this tenant's whole test allow-list with `body.numbers`.

    The pydantic model already caps the list at 5 (a >5 body → 422 before we get
    here). The service normalizes each phone, drops blanks/dupes, and rejects a
    too-long cleaned set (ValueError → 422 here). Phone numbers and labels are
    encrypted at rest and never logged.
    """
    items = [{"phone": n.phone, "label": n.label} for n in body.numbers]
    try:
        saved = await test_numbers_service.set_test_numbers(
            request.app.state.pg_pool, business_id, items
        )
    except ValueError:
        # Too many numbers after cleaning. Generic message — never echo input.
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="at most 5 test numbers are allowed",
        )

    return TestNumbersResponse(
        numbers=[TestNumber(phone=n["phone"], label=n["label"]) for n in saved]
    )
