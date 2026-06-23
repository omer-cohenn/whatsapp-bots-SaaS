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

from datetime import date, datetime
from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.core.deps import current_admin, current_business
from app.core.logging import get_logger
from app.models.admin import (
    AdminAiOpsPoint,
    AdminAiOpsResponse,
    AdminBusinessCrm,
    AdminBusinessDetail,
    AdminBusinessesResponse,
    AdminBusinessRow,
    AdminByPlanResponse,
    AdminByPlanRow,
    AdminCrmListResponse,
    AdminCrmNote,
    AdminCrmNoteCreatedResponse,
    AdminCrmNoteRequest,
    AdminCrmNotesResponse,
    AdminCrmRow,
    AdminCrmStageRequest,
    AdminCrmStageResponse,
    AdminDeleteResponse,
    AdminLeadsByType,
    AdminMessagesResponse,
    AdminMessagesRow,
    AdminOverview,
    AdminPlan,
    AdminPlansResponse,
    AdminSubscriptionRequest,
    AdminSubscriptionResponse,
    AdminTrendPoint,
    AdminTrendsResponse,
    AdminUsageResponse,
    ByPlanMetric,
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


def _parse_timestamp_or_422(value: str | None, field: str) -> datetime | None:
    """Parse an ISO-8601 timestamp body value to a datetime, or 422.

    Used for the CRM `next_followup` (a follow-up reminder time). None / blank
    passes through as None (clears the reminder). The SD function takes a
    timestamptz; asyncpg binds the datetime safely.
    """
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid {field} timestamp (expected ISO-8601)",
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


# === M13: back-office analytics ==============================================
# Every route below inherits the router-level current_admin gate and calls a
# cross-tenant SD function on a PLAIN pool connection (never tenant_connection).
# The `business_id` (when present) only ever flows into an admin-gated SD function.


@router.get("/analytics/leads-by-type", response_model=AdminLeadsByType)
async def admin_leads_by_type(
    request: Request,
    period: Literal["week", "month", "all"] = Query("month"),
    plan: str = Query("all", max_length=64),
) -> AdminLeadsByType:
    """Lead outcomes split by type (appointment / lead / handoff), per period+plan.

    `period` is whitelisted via Literal (default 'month'); `plan` is a plan code or
    'all' (default), bounded in length — the SD function treats an unknown plan as
    an empty filter. Cross-tenant SD (admin_leads_by_type), single aggregate row.
    """
    async with request.app.state.pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM admin_leads_by_type($1, $2)", period, plan
        )
    # admin_leads_by_type always returns exactly one aggregate row.
    return AdminLeadsByType(
        booking=int(row["booking_count"]),
        lead=int(row["lead_count"]),
        handoff=int(row["handoff_count"]),
    )


@router.get("/analytics/messages", response_model=AdminMessagesResponse)
async def admin_messages(
    request: Request,
    period: Literal["week", "month", "all"] = Query("month"),
) -> AdminMessagesResponse:
    """Per-business message volume for billing (admin_messages_by_business).

    One row per business with msg_in / msg_out / total, ordered busiest-first. This
    is the BILLING view — pure counters, no message content. `period` whitelisted.
    """
    async with request.app.state.pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM admin_messages_by_business($1)", period
        )
    businesses = [
        AdminMessagesRow(
            business_id=str(r["business_id"]),
            name=r["name"],
            plan_code=r["plan_code"],
            msg_in=int(r["msg_in"]),
            msg_out=int(r["msg_out"]),
            total=int(r["total"]),
        )
        for r in rows
    ]
    return AdminMessagesResponse(businesses=businesses)


@router.get("/analytics/ai-ops", response_model=AdminAiOpsResponse)
async def admin_ai_ops(
    request: Request,
    date_from: str | None = Query(None, max_length=10, alias="from"),
    date_to: str | None = Query(None, max_length=10, alias="to"),
) -> AdminAiOpsResponse:
    """Platform-wide ai_call count per day (admin_ai_ops_series).

    `from`/`to` are ISO YYYY-MM-DD (both optional; a bad date → 422). The SD
    function range-guards internally (NULLs → a default window; swaps/caps the
    span), so we just parse + forward and return the ascending per-day series.
    """
    d_from = _parse_date_or_422(date_from, "from")
    d_to = _parse_date_or_422(date_to, "to")
    async with request.app.state.pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT day, count FROM admin_ai_ops_series($1, $2)", d_from, d_to
        )
    series = [
        AdminAiOpsPoint(day=r["day"].isoformat(), count=int(r["count"])) for r in rows
    ]
    return AdminAiOpsResponse(series=series)


@router.get("/analytics/by-plan", response_model=AdminByPlanResponse)
async def admin_by_plan(
    request: Request,
    metric: ByPlanMetric = Query(...),
    period: Literal["week", "month", "all"] = Query("month"),
) -> AdminByPlanResponse:
    """One usage metric split across plans (admin_by_plan).

    `metric` is whitelisted to the usage vocabulary via Literal (msg_in | msg_out |
    lead | booking | login | ai_call) — anything else is 422 before the SD call.
    `period` whitelisted too. Returns one row per plan with the summed value.
    """
    async with request.app.state.pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT plan_code, value FROM admin_by_plan($1, $2)", metric, period
        )
    return AdminByPlanResponse(
        metric=metric,
        period=period,
        rows=[
            AdminByPlanRow(plan_code=r["plan_code"], value=int(r["value"]))
            for r in rows
        ],
    )


@router.get("/analytics/trends", response_model=AdminTrendsResponse)
async def admin_trends(
    request: Request,
    date_from: str | None = Query(None, max_length=10, alias="from"),
    date_to: str | None = Query(None, max_length=10, alias="to"),
) -> AdminTrendsResponse:
    """The snapshot trend series — MRR / active / paid / churn per day.

    Reads platform_snapshots via admin_trends_series. `from`/`to` are ISO
    YYYY-MM-DD (both optional; a bad date → 422). History accrues forward only (a
    snapshot is stamped on each overview view), so early days may be sparse.
    """
    d_from = _parse_date_or_422(date_from, "from")
    d_to = _parse_date_or_422(date_to, "to")
    async with request.app.state.pg_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM admin_trends_series($1, $2)", d_from, d_to
        )
    series = [
        AdminTrendPoint(
            day=r["day"].isoformat(),
            total_businesses=int(r["total_businesses"]),
            active_count=int(r["active_count"]),
            paid_count=int(r["paid_count"]),
            mrr=float(r["mrr"]),
            churn_count=int(r["churn_count"]),
        )
        for r in rows
    ]
    return AdminTrendsResponse(series=series)


# === M13: platform-level sales CRM ===========================================
# The CRM tables (business_crm, crm_notes) have NO direct app_role grant — they
# are reachable ONLY through these admin-gated SD functions. The two writers stamp
# the admin's REAL identity (session user_id = the Google sub in users(id), +
# email) for the FK + audit trail — never a client value. Note text is never logged.


@router.get("/crm", response_model=AdminCrmListResponse)
async def admin_crm_list(request: Request) -> AdminCrmListResponse:
    """The sales pipeline board: every business as a card with its stage (SD).

    admin_crm_list returns every business once (stage defaults to 'new' when there
    is no CRM row), with the last-contacted / next-follow-up timestamps and the
    note count. Cross-tenant SD on a plain pool connection.
    """
    async with request.app.state.pg_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM admin_crm_list()")
    businesses = [
        AdminCrmRow(
            business_id=str(r["business_id"]),
            name=r["name"],
            plan_code=r["plan_code"],
            stage=r["stage"],
            last_contacted_at=_iso(r["last_contacted_at"]),
            next_followup_at=_iso(r["next_followup_at"]),
            note_count=int(r["note_count"]),
        )
        for r in rows
    ]
    return AdminCrmListResponse(businesses=businesses)


@router.patch(
    "/businesses/{business_id}/crm", response_model=AdminCrmStageResponse
)
async def admin_set_crm_stage(
    body: AdminCrmStageRequest,
    request: Request,
    business_id: str = Path(..., min_length=1, max_length=_BUSINESS_ID_MAX),
    admin: dict[str, str] = Depends(current_admin),
) -> AdminCrmStageResponse:
    """Move a business to a new sales stage (+ optional follow-up), and audit it.

    admin_set_crm_stage upserts business_crm.stage, sets next_followup_at, and
    writes an admin_audit row stamped with the REAL admin identity (admin['id'] =
    the session Google sub in users(id), + email) — never a client value.

    Error mapping (from the SD function's RAISE):
      * check_violation       → 422 (bad stage — also pre-gated by the Literal)
      * foreign_key_violation → 404 (unknown business)
    `next_followup` is an optional ISO-8601 timestamp; a bad value → 422.
    """
    next_followup = _parse_timestamp_or_422(body.next_followup, "next_followup")
    try:
        async with request.app.state.pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM admin_set_crm_stage($1, $2, $3, $4, $5)",
                admin["id"],
                admin["email"],
                business_id,
                body.stage,
                next_followup,
            )
    except asyncpg.exceptions.CheckViolationError:
        # The SD function rejected the stage (defense in depth behind the Literal).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invalid stage",
        ) from None
    except asyncpg.exceptions.ForeignKeyViolationError:
        # Unknown business (the SD function raises foreign_key_violation). We do not
        # echo the message (no id leak).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None
    except asyncpg.exceptions.DataError:
        # A malformed business uuid never matches a business.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None

    log.info("admin set crm stage", extra={"business_id": str(row["business_id"])})
    return AdminCrmStageResponse(
        business_id=str(row["business_id"]),
        stage=row["stage"],
        next_followup_at=_iso(row["next_followup_at"]),
    )


@router.post(
    "/businesses/{business_id}/crm/notes",
    response_model=AdminCrmNoteCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_add_crm_note(
    body: AdminCrmNoteRequest,
    request: Request,
    business_id: str = Path(..., min_length=1, max_length=_BUSINESS_ID_MAX),
    admin: dict[str, str] = Depends(current_admin),
) -> AdminCrmNoteCreatedResponse:
    """Append a sales note to a business's CRM log (admin_add_crm_note).

    The note is stamped with the REAL admin identity (admin['id'] = the session
    Google sub in users(id), + email) — never a client value. The note text is
    NEVER logged (owner-business sales data).

    Error mapping:
      * check_violation       → 422 (blank note — also pre-gated by min_length)
      * foreign_key_violation → 404 (unknown business)
    """
    try:
        async with request.app.state.pg_pool.acquire() as conn:
            note_id = await conn.fetchval(
                "SELECT admin_add_crm_note($1, $2, $3, $4)",
                admin["id"],
                admin["email"],
                business_id,
                body.note,
            )
    except asyncpg.exceptions.CheckViolationError:
        # Blank note (defense in depth behind the Pydantic min_length).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="note must not be blank",
        ) from None
    except asyncpg.exceptions.ForeignKeyViolationError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None
    except asyncpg.exceptions.DataError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="business not found"
        ) from None

    log.info("admin add crm note", extra={"business_id": business_id})
    return AdminCrmNoteCreatedResponse(note_id=str(note_id))


@router.get(
    "/businesses/{business_id}/crm/notes", response_model=AdminCrmNotesResponse
)
async def admin_crm_notes(
    request: Request,
    business_id: str = Path(..., min_length=1, max_length=_BUSINESS_ID_MAX),
) -> AdminCrmNotesResponse:
    """A business's CRM note log, newest first (admin_crm_notes).

    A malformed/unknown business id simply yields an empty log (the SD function
    matches no notes). The note text is part of the response (it is owner-business
    sales context, shown only to the admin) but is NEVER logged here.
    """
    try:
        async with request.app.state.pg_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, admin_email, note, created_at FROM admin_crm_notes($1)",
                business_id,
            )
    except asyncpg.exceptions.DataError:
        # A malformed uuid never matches notes → an empty log (not a 404).
        return AdminCrmNotesResponse(notes=[])
    notes = [
        AdminCrmNote(
            id=str(r["id"]),
            admin_email=r["admin_email"],
            note=r["note"],
            created_at=_iso(r["created_at"]),
        )
        for r in rows
    ]
    return AdminCrmNotesResponse(notes=notes)


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
