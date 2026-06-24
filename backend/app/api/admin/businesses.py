# בק‑אופיס מנהל — עסקים: סקירה, רשימה, פרופיל, שימוש, מנוי, מחיקה
"""Admin business routes (M12/M13): overview, list, detail, usage, subscription.

The platform-operator views over the businesses themselves — the KPI strip, the
searchable list, one business's full profile, its per-day usage series, the plan
catalog, the subscription editor (audited), and the hard-delete (cascade,
audited). Every route runs cross-tenant SECURITY DEFINER functions on a PLAIN
pool connection (never tenant_connection) behind the router-level current_admin
gate. Moved VERBATIM from the old single-file `admin.py` — no logic change.
"""

from __future__ import annotations

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.api.admin._common import (
    _BUSINESS_ID_MAX,
    _as_dict,
    _iso,
    _parse_date_or_422,
    log,
)
from app.core.deps import current_admin, current_business
from app.models.admin import (
    AdminBusinessCrm,
    AdminBusinessDetail,
    AdminBusinessesResponse,
    AdminBusinessRow,
    AdminDeleteResponse,
    AdminOverview,
    AdminPlan,
    AdminPlansResponse,
    AdminSubscriptionRequest,
    AdminSubscriptionResponse,
    AdminUsageResponse,
    UsageDayPoint,
)

router = APIRouter()


@router.get("/overview", response_model=AdminOverview)
async def admin_overview(request: Request) -> AdminOverview:
    """Platform-wide KPI strip (admin_overview, cross-tenant SD, single row).

    M13: there is no scheduler yet, so EACH overview view first stamps today's
    `platform_snapshots` row (admin_upsert_today_snapshot — idempotent) so the
    trend history accrues. That stamp is BEST-EFFORT: a snapshot failure must
    never 500 the overview, so we swallow it (log the class only, never PII). We
    also merge in admin_ltv_summary() for the avg/total LTV estimate.
    """
    async with request.app.state.pg_pool.acquire() as conn:
        # Best-effort daily snapshot (history accrues on view; never blocks the KPI).
        try:
            await conn.execute("SELECT admin_upsert_today_snapshot()")
        except Exception:  # noqa: BLE001 — telemetry; never break the overview.
            log.warning("admin snapshot upsert failed")
        row = await conn.fetchrow("SELECT * FROM admin_overview()")
        ltv = await conn.fetchrow("SELECT * FROM admin_ltv_summary()")
    # admin_overview always returns exactly one row; admin_ltv_summary too.
    return AdminOverview(
        total_businesses=int(row["total_businesses"]),
        active_count=int(row["active_count"]),
        suspended_count=int(row["suspended_count"]),
        cancelled_count=int(row["cancelled_count"]),
        new_7d=int(row["new_7d"]),
        total_leads=int(row["total_leads"]),
        msgs_today=int(row["msgs_today"]),
        msgs_month=int(row["msgs_month"]),
        avg_ltv=float(ltv["avg_ltv"]) if ltv and ltv["avg_ltv"] is not None else None,
        total_ltv=(
            float(ltv["total_ltv"]) if ltv and ltv["total_ltv"] is not None else None
        ),
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
    """One business profile (cross-tenant SD). 404 if the id matches no business.

    M13: after the base detail we ALSO call admin_business_extra(id) and merge the
    LTV estimate, the cumulative ai_calls counter, and a nested `crm` block (the
    sales-pipeline state). These are additive/optional so the M12 frontend read is
    unaffected. The extra call is best-effort — if it fails the detail still
    returns (with the M13 fields left None).
    """
    try:
        async with request.app.state.pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM admin_business_detail($1)", business_id
            )
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="business not found",
                )
            # The id already matched a business, so admin_business_extra is safe to
            # call. Best-effort: an extra failure must not drop the base detail.
            try:
                extra = await conn.fetchrow(
                    "SELECT * FROM admin_business_extra($1)", business_id
                )
            except Exception:  # noqa: BLE001 — additive enrichment; never block.
                log.warning("admin business extra failed")
                extra = None
    except asyncpg.exceptions.DataError:
        # A malformed uuid never matches a business.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None

    crm: AdminBusinessCrm | None = None
    ltv_estimate: float | None = None
    ai_calls: int | None = None
    if extra is not None:
        ltv_estimate = (
            float(extra["ltv_estimate"])
            if extra["ltv_estimate"] is not None
            else None
        )
        ai_calls = int(extra["ai_calls"]) if extra["ai_calls"] is not None else None
        crm = AdminBusinessCrm(
            stage=extra["crm_stage"],
            last_contacted_at=_iso(extra["last_contacted_at"]),
            next_followup_at=_iso(extra["next_followup_at"]),
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
        ltv_estimate=ltv_estimate,
        ai_calls=ai_calls,
        crm=crm,
    )


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


@router.delete("/businesses/{business_id}", response_model=AdminDeleteResponse)
async def admin_delete_business(
    request: Request,
    business_id: str = Path(..., min_length=1, max_length=_BUSINESS_ID_MAX),
    admin: dict[str, str] = Depends(current_admin),
    own_business_id: str = Depends(current_business),
) -> AdminDeleteResponse:
    """HARD-delete a business and ALL its data (cascade), audited. Admin-only.

    Destructive + irreversible: removes the businesses row, which CASCADES to
    every tenant table (members, bot, leads, bookings, usage, subscription, crm,
    whatsapp creds, …). The admin_delete_business SD function audits BEFORE the
    delete (the admin_audit row has no FK to businesses, so it survives).

    Guard: an admin may NOT delete the business tied to their OWN session — that
    would orphan their own login → 400. Everything else maps:
      * own business                                   → 400
      * foreign_key_violation / DataError (unknown id) → 404
    The business id flows ONLY into the admin-gated SD function (never a
    tenant_connection). We log the action + the redacted id, never PII.
    """
    if business_id == own_business_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot delete your own business",
        )
    try:
        async with request.app.state.pg_pool.acquire() as conn:
            name = await conn.fetchval(
                "SELECT admin_delete_business($1, $2, $3)",
                admin["id"],
                admin["email"],
                business_id,
            )
    except asyncpg.exceptions.ForeignKeyViolationError:
        # Unknown business (the SD function raises foreign_key_violation).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None
    except asyncpg.exceptions.DataError:
        # A malformed business uuid never matches a business.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None
    log.info("admin deleted a business", extra={"business_id": business_id})
    return AdminDeleteResponse(deleted=True, name=name)
