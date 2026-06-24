# בק‑אופיס מנהל — אנליטיקה: לידים לפי סוג, הודעות, ai-ops, לפי תוכנית, מגמות
"""Admin analytics routes (M13): the back-office charts.

Read-only platform aggregates behind the router-level current_admin gate — lead
outcomes by type, per-business message volume (billing), platform AI-op volume,
one metric split across plans, and the snapshot trend series. Each calls a
cross-tenant SECURITY DEFINER function on a PLAIN pool connection (never
tenant_connection); a `business_id` never appears here. Moved VERBATIM from the
old single-file `admin.py` — no logic change.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request

from app.api.admin._common import _parse_date_or_422
from app.models.admin import (
    AdminAiOpsPoint,
    AdminAiOpsResponse,
    AdminByPlanResponse,
    AdminByPlanRow,
    AdminLeadsByType,
    AdminMessagesResponse,
    AdminMessagesRow,
    AdminTrendPoint,
    AdminTrendsResponse,
    ByPlanMetric,
)

router = APIRouter()

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
