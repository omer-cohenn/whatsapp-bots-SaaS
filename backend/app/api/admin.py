"""Protected /api/admin/* router — the platform-operator back-office (M12).

This is the ONE surface that deliberately crosses the tenant wall. It is mounted
under the gated `/api` group AND carries its OWN router-level
`dependencies=[Depends(current_admin)]` (see app/api/me.py), so every route here
requires BOTH a valid session AND an email on `ADMIN_EMAILS` — deny-by-default,
no per-route opt-in to forget.

How it stays safe (decision 0016):
  * The cross-tenant reads/writes are SECURITY DEFINER functions (migration 0017)
    that bypass RLS by design. We call them on a PLAIN pool connection
    (`pg_pool.acquire()`) — NOT `tenant_connection` — because they intentionally
    span all tenants. `current_admin` is the only guard on them.
  * A `business_id` arrives only in the PATH for the per-business routes, and is
    fed STRAIGHT into an admin-gated SD function — it NEVER reaches a
    tenant_connection and never widens a tenant read.
  * The admin's REAL identity (session user_id = the Google sub in users(id), +
    email) is passed to `admin_set_subscription` for the audit trail — never a
    client-supplied value.

We NEVER log PII or secrets here — only the action + a redacted business id.
"""

from __future__ import annotations

from datetime import date

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.core.deps import current_admin
from app.core.logging import get_logger
from app.models.admin import (
    AdminBusinessDetail,
    AdminBusinessesResponse,
    AdminBusinessRow,
    AdminOverview,
    AdminPlan,
    AdminPlansResponse,
    AdminSubscriptionRequest,
    AdminSubscriptionResponse,
    AdminUsageResponse,
    UsageDayPoint,
)

# Router-level admin gate: EVERY route here requires current_admin (which itself
# requires a valid session). New admin routes inherit it automatically — there is
# no per-route opt-in to forget on the cross-tenant surface.
router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(current_admin)]
)
log = get_logger("app.api.admin")

# A business id arrives in the path as a UUID string. Bound its length defensively
# before it ever reaches an SD function; an unparsable value → the SD function's
# uuid cast raises invalid_text_representation, which we map to 404 (not found).
_BUSINESS_ID_MAX = 64


def _iso(value: object) -> str | None:
    """ISO-8601 a date/timestamptz (or None passes through)."""
    return value.isoformat() if value is not None else None  # type: ignore[attr-defined]


@router.get("/overview", response_model=AdminOverview)
async def admin_overview(request: Request) -> AdminOverview:
    """Platform-wide KPI strip (admin_overview, cross-tenant SD, single row)."""
    async with request.app.state.pg_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM admin_overview()")
    # admin_overview always returns exactly one row.
    return AdminOverview(
        total_businesses=int(row["total_businesses"]),
        active_count=int(row["active_count"]),
        suspended_count=int(row["suspended_count"]),
        cancelled_count=int(row["cancelled_count"]),
        new_7d=int(row["new_7d"]),
        total_leads=int(row["total_leads"]),
        msgs_today=int(row["msgs_today"]),
        msgs_month=int(row["msgs_month"]),
    )


@router.get("/businesses", response_model=AdminBusinessesResponse)
async def admin_list_businesses(
    request: Request,
    search: str | None = Query(None, max_length=200),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AdminBusinessesResponse:
    """List ALL businesses (cross-tenant), with search + paging.

    `search` is an ILIKE over business name / owner email (handled inside the SD
    function). limit/offset are bounded both here AND inside the function (1..200,
    >=0). Returns the page plus the echoed paging so the UI can advance.
    """
    async with request.app.state.pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM admin_list_businesses($1, $2, $3)",
            search,
            limit,
            offset,
        )
    businesses = [
        AdminBusinessRow(
            business_id=str(r["business_id"]),
            name=r["name"],
            owner_email=r["owner_email"],
            created_at=_iso(r["created_at"]),
            last_login_at=_iso(r["last_login_at"]),
            plan_code=r["plan_code"],
            status=r["status"],
            is_active=bool(r["is_active"]),
            leads_count=int(r["leads_count"]),
            msgs_30d=int(r["msgs_30d"]),
        )
        for r in rows
    ]
    return AdminBusinessesResponse(businesses=businesses, limit=limit, offset=offset)


@router.get("/businesses/{business_id}", response_model=AdminBusinessDetail)
async def admin_business_detail(
    request: Request,
    business_id: str = Path(..., min_length=1, max_length=_BUSINESS_ID_MAX),
) -> AdminBusinessDetail:
    """One business profile (cross-tenant SD). 404 if the id matches no business."""
    try:
        async with request.app.state.pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM admin_business_detail($1)", business_id
            )
    except asyncpg.exceptions.DataError:
        # A malformed uuid never matches a business.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        )
    return AdminBusinessDetail(
        business_id=str(row["business_id"]),
        name=row["name"],
        business_type=row["business_type"],
        owner_email=row["owner_email"],
        created_at=_iso(row["created_at"]),
        last_login_at=_iso(row["last_login_at"]),
        plan_code=row["plan_code"],
        status=row["status"],
        is_active=bool(row["is_active"]),
        wa_status=row["wa_status"],
        leads_count=int(row["leads_count"]),
        msgs_30d=int(row["msgs_30d"]),
    )


def _parse_date_or_422(value: str | None, field: str) -> date | None:
    """Parse an ISO YYYY-MM-DD query value to a date, or 422 (None passes through)."""
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid {field} date (expected YYYY-MM-DD)",
        ) from None


@router.get("/businesses/{business_id}/usage", response_model=AdminUsageResponse)
async def admin_business_usage(
    request: Request,
    business_id: str = Path(..., min_length=1, max_length=_BUSINESS_ID_MAX),
    date_from: str | None = Query(None, max_length=10, alias="from"),
    date_to: str | None = Query(None, max_length=10, alias="to"),
) -> AdminUsageResponse:
    """Per-day usage series for one business (cross-tenant SD), for the charts.

    `from`/`to` are ISO YYYY-MM-DD (both optional). The SD function guards the
    range internally (NULLs → last 30d; swaps if to<from; caps the span at 92d),
    so we just parse + forward. The raw (day, metric, count) rows are reshaped
    into one point per day with a metric→count map (see AdminUsageResponse).
    """
    d_from = _parse_date_or_422(date_from, "from")
    d_to = _parse_date_or_422(date_to, "to")

    try:
        async with request.app.state.pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT day, metric, count FROM admin_usage_series($1, $2, $3)",
                business_id,
                d_from,
                d_to,
            )
    except asyncpg.exceptions.DataError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None

    # Reshape: one UsageDayPoint per day, metric→count inside. Rows arrive in
    # (day asc, metric asc) order, so we group sequentially.
    by_day: dict[str, dict[str, int]] = {}
    metrics_present: set[str] = set()
    for r in rows:
        day_iso = r["day"].isoformat()
        metric = r["metric"]
        count = int(r["count"])
        by_day.setdefault(day_iso, {})[metric] = count
        metrics_present.add(metric)

    series = [
        UsageDayPoint(day=day_iso, metrics=metrics)
        for day_iso, metrics in by_day.items()
    ]
    return AdminUsageResponse(
        business_id=business_id,
        metrics_present=sorted(metrics_present),
        series=series,
    )


@router.get("/plans", response_model=AdminPlansResponse)
async def admin_plans(request: Request) -> AdminPlansResponse:
    """The global plan catalog for the subscription dropdown (sorted)."""
    async with request.app.state.pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT code, name, price, sort_order, limits "
            "FROM plans ORDER BY sort_order ASC, code ASC"
        )
    plans = [
        AdminPlan(
            code=r["code"],
            name=r["name"],
            price=float(r["price"]),
            sort_order=int(r["sort_order"]),
            limits=_as_dict(r["limits"]),
        )
        for r in rows
    ]
    return AdminPlansResponse(plans=plans)


def _as_dict(value: object) -> dict:
    """asyncpg returns jsonb as a str; normalize to a dict (default {})."""
    import json

    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)  # type: ignore[arg-type]
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


@router.patch(
    "/businesses/{business_id}/subscription",
    response_model=AdminSubscriptionResponse,
)
async def admin_set_subscription(
    body: AdminSubscriptionRequest,
    request: Request,
    business_id: str = Path(..., min_length=1, max_length=_BUSINESS_ID_MAX),
    admin: dict[str, str] = Depends(current_admin),
) -> AdminSubscriptionResponse:
    """Set a business's plan + status; sync is_active; write the audit row (SD).

    Atomic inside `admin_set_subscription`: it re-validates the status + plan,
    upserts the subscription, syncs `businesses.is_active` (active→true, else
    false — a suspended/cancelled business's bot goes silent), and records an
    `admin_audit` row stamped with the REAL admin identity (the session user_id =
    the Google sub, which exists in users(id), + email) — never a client value.

    Error mapping (from the SD function's RAISE):
      * check_violation        → 422 (bad status)
      * foreign_key_violation  → 404 (unknown business) / 422 (bad plan)
    We inspect the message to tell the two FK cases apart; details are generic.
    """
    try:
        async with request.app.state.pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM admin_set_subscription($1, $2, $3, $4, $5)",
                admin["id"],
                admin["email"],
                business_id,
                body.plan_code,
                body.status,
            )
    except asyncpg.exceptions.CheckViolationError:
        # Bad status (the SD function raised check_violation).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid status",
        ) from None
    except asyncpg.exceptions.ForeignKeyViolationError as exc:
        # Unknown plan_code, unknown business_id, or a non-existent admin_user_id —
        # the SD function raises foreign_key_violation for all three. A bad plan is
        # the caller's input (422); an unknown business is a not-found (404). We do
        # NOT echo the message (no PII / id leak).
        message = str(exc).lower()
        if "plan_code" in message:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="unknown plan",
            ) from None
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None
    except asyncpg.exceptions.DataError:
        # A malformed business uuid never matches a business.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None

    log.info("admin set subscription", extra={"business_id": str(row["business_id"])})
    return AdminSubscriptionResponse(
        business_id=str(row["business_id"]),
        plan_code=row["plan_code"],
        status=row["status"],
        is_active=bool(row["is_active"]),
    )
