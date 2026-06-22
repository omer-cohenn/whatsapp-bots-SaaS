"""Owner-facing WhatsApp admin API (M6a, decision 0014).

Mounted under the gated /api group (app/api/me.py), so every route here inherits
the deny-by-default session gate. The tenant is ALWAYS the verified session
business (`current_business`) — never a client value.

Routes (frozen contract):

  GET  /api/whatsapp/status       -> { linked, connected, phone, gateway_status }
  POST /api/whatsapp/link         -> { linked, connected, phone, gateway_status }
  GET  /api/whatsapp/qr           -> { status, qr_data_url }
  GET  /api/whatsapp/test-numbers -> { numbers: [{ phone, label }] }
  PUT  /api/whatsapp/test-numbers -> { numbers: [{ phone, label }] }

`status` + `qr` proxy the Node gateway over the internal Docker network
(GATEWAY_BASE_URL); `link` reads the gateway's account id + own number from
/info, then records the business_id ↔ account mapping via the whatsapp service
(phone encrypted at rest). `test-numbers` manages the owner's external test
allow-list (up to 5 numbers, each encrypted at rest). The owner's own phone and
the test numbers/labels are the only PII and are NEVER logged. Gateway failures
degrade gracefully to a "disconnected"/"unknown" view rather than 500ing the
owner's dashboard.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status as http_status

from app.core.config import get_settings
from app.core.deps import current_business
from app.core.logging import get_logger
from app.db.session import tenant_connection
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

# Internal gateway calls should be fast (same Docker network); fail rather than
# hang the owner's dashboard. Matches the google_oauth timeout convention.
_HTTP_TIMEOUT = 5.0


async def _gateway_info() -> dict[str, Any]:
    """GET {GATEWAY_BASE_URL}/info → {account_id, status, phone} (best-effort).

    Returns the gateway's view of the single session. On ANY failure (gateway
    down, timeout, bad shape) we degrade to a safe "unknown/disconnected" view so
    the dashboard still renders. Never logs the phone or any response body.
    """
    base = get_settings().gateway_base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(f"{base}/info")
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001 — degrade gracefully; never leak details.
        log.warning("gateway /info unreachable")
        return {"account_id": None, "status": "unknown", "phone": None}

    return {
        "account_id": data.get("account_id"),
        "status": data.get("status") or "unknown",
        # phone = the gateway's view of the linked own number (PII — never logged).
        "phone": data.get("phone"),
    }


def _is_connected(gateway_status: str) -> bool:
    """The session is live only when the gateway explicitly says 'connected'."""
    return gateway_status == "connected"


async def _linked(request: Request, business_id: str) -> bool:
    """Does this tenant have a connection mapping yet? RLS-scoped read."""
    async with tenant_connection(request.app.state.pg_pool, business_id) as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM whatsapp_connections WHERE business_id = $1",
            business_id,
        )
    return exists is not None


@router.get("/status", response_model=WhatsAppStatusResponse)
async def whatsapp_status(
    request: Request,
    business_id: str = Depends(current_business),
) -> WhatsAppStatusResponse:
    """Return whether this tenant has linked WhatsApp + the live gateway state."""
    info = await _gateway_info()
    gateway_status = info["status"]
    return WhatsAppStatusResponse(
        linked=await _linked(request, business_id),
        connected=_is_connected(gateway_status),
        phone=info["phone"],
        gateway_status=gateway_status,
    )


@router.post("/link", response_model=WhatsAppLinkResponse)
async def whatsapp_link(
    request: Request,
    business_id: str = Depends(current_business),
) -> WhatsAppLinkResponse:
    """Record the business_id ↔ gateway-account mapping for THIS tenant.

    Pulls the gateway's account id + own number from /info, then upserts the
    mapping under the verified session tenant (phone encrypted at rest). Returns
    the resulting status shape so the frontend can refresh in one call.
    """
    info = await _gateway_info()
    gateway_status = info["status"]
    account_id = info["account_id"]
    phone = info["phone"]

    # Only record a mapping when the gateway actually reported an account id.
    # Without it there is nothing to bridge inbound messages to.
    if account_id:
        await whatsapp_service.upsert_connection(
            request.app.state.pg_pool,
            business_id,
            gateway_account_id=account_id,
            phone=phone,
            status=gateway_status,
        )
        linked = True
    else:
        # Gateway not reachable / no account yet — nothing recorded.
        linked = await _linked(request, business_id)

    return WhatsAppLinkResponse(
        linked=linked,
        connected=_is_connected(gateway_status),
        phone=phone,
        gateway_status=gateway_status,
    )


@router.get("/qr", response_model=WhatsAppQrResponse)
async def whatsapp_qr(
    business_id: str = Depends(current_business),
) -> WhatsAppQrResponse:
    """Proxy the gateway's current QR (for linking) to the owner.

    The QR itself carries no tenant data; the gate ensures only an authenticated
    owner can fetch it. Degrades to {status:'unknown', qr_data_url:null} if the
    gateway is unreachable. Never logs the response.
    """
    base = get_settings().gateway_base_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            # /qr.json returns JSON {status, qr_data_url}; the plain /qr route is
            # an HTML dev page (not parseable here).
            resp = await client.get(f"{base}/qr.json")
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001 — degrade gracefully; never leak details.
        log.warning("gateway /qr unreachable")
        return WhatsAppQrResponse(status="unknown", qr_data_url=None)

    return WhatsAppQrResponse(
        status=data.get("status") or "unknown",
        qr_data_url=data.get("qr_data_url"),
    )


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
