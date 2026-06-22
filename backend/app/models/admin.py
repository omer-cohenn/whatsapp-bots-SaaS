"""Pydantic models for the M12 platform-operator back-office (/api/admin/*).

These are the FROZEN response/request shapes the admin frontend builds against.
They mirror the columns the admin SECURITY DEFINER functions return (migration
0017). A `business_id` only ever appears in a PATH for the per-business routes
and is fed STRAIGHT to an admin-gated SD function — never to a tenant_connection.

No PII / secrets live here: the back-office shows identity + aggregate counters
(emails, plan/status, leads_count, message volume), never lead/booking content.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The subscription status vocabulary the DB CHECK + admin_set_subscription enforce.
SubscriptionStatus = Literal["active", "suspended", "cancelled"]


# --- GET /api/admin/overview -------------------------------------------------


class AdminOverview(BaseModel):
    """Platform-wide KPI strip (one row from admin_overview()). All counts."""

    total_businesses: int
    active_count: int
    suspended_count: int
    cancelled_count: int
    new_7d: int
    total_leads: int
    msgs_today: int
    msgs_month: int


# --- GET /api/admin/businesses ----------------------------------------------


class AdminBusinessRow(BaseModel):
    """One row of the all-businesses table (from admin_list_businesses)."""

    business_id: str
    name: str | None = None
    owner_email: str | None = None
    created_at: str | None = None
    last_login_at: str | None = None
    plan_code: str
    status: str  # active | suspended | cancelled
    is_active: bool
    leads_count: int
    msgs_30d: int


class AdminBusinessesResponse(BaseModel):
    """GET /api/admin/businesses — the page of businesses + the echoed paging."""

    businesses: list[AdminBusinessRow]
    limit: int
    offset: int


# --- GET /api/admin/businesses/{id} -----------------------------------------


class AdminBusinessDetail(BaseModel):
    """A single business profile (from admin_business_detail)."""

    business_id: str
    name: str | None = None
    business_type: str | None = None
    owner_email: str | None = None
    created_at: str | None = None
    last_login_at: str | None = None
    plan_code: str
    status: str  # active | suspended | cancelled
    is_active: bool
    wa_status: str  # connected | connecting | disconnected
    leads_count: int
    msgs_30d: int


# --- GET /api/admin/businesses/{id}/usage -----------------------------------


class UsageDayPoint(BaseModel):
    """One day in the usage series: the date + a metric→count map for that day.

    The raw (day, metric, count) rows from admin_usage_series are reshaped into
    ONE object per day, with a `metrics` dict keyed by metric name (msg_in,
    msg_out, lead, booking, login). Missing metrics simply do not appear in the
    dict for that day (the frontend defaults them to 0). This is chart-friendly:
    each point is one x-axis tick, with the per-series values inside.
    """

    day: str  # ISO date, e.g. "2026-06-22"
    metrics: dict[str, int] = Field(default_factory=dict)


class AdminUsageResponse(BaseModel):
    """GET /api/admin/businesses/{id}/usage — the per-day usage series.

    `metrics_present` lists every metric name that appears anywhere in the
    window (so the chart knows which series/lines to draw). `series` is the
    per-day points in ascending date order.
    """

    business_id: str
    metrics_present: list[str]
    series: list[UsageDayPoint]


# --- GET /api/admin/plans ----------------------------------------------------


class AdminPlan(BaseModel):
    """One catalog plan (for the subscription dropdown)."""

    code: str
    name: str | None = None
    price: float
    sort_order: int
    limits: dict = Field(default_factory=dict)


class AdminPlansResponse(BaseModel):
    """GET /api/admin/plans — the global plan catalog (sorted)."""

    plans: list[AdminPlan]


# --- PATCH /api/admin/businesses/{id}/subscription ---------------------------


class AdminSubscriptionRequest(BaseModel):
    """Set a business's plan + status. Both required; validated to the catalog set.

    `status` is constrained to the allowed values here as a first gate; the SD
    function re-validates it (and the plan_code against the catalog) atomically.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    plan_code: str = Field(..., min_length=1, max_length=64)
    status: SubscriptionStatus


class AdminSubscriptionResponse(BaseModel):
    """The new subscription state after admin_set_subscription (echo)."""

    business_id: str
    plan_code: str
    status: str
    is_active: bool
