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
    """Platform-wide KPI strip (one row from admin_overview()). All counts.

    M13 adds two LTV fields (from admin_ltv_summary()), kept OPTIONAL so the M12
    frontend reads that ignore them keep working unchanged.
    """

    total_businesses: int
    active_count: int
    suspended_count: int
    cancelled_count: int
    new_7d: int
    total_leads: int
    msgs_today: int
    msgs_month: int
    # M13 (additive): money rollups across all businesses; "estimate" — no real
    # billing yet (plan price x tenure). None if the summary could not be read.
    avg_ltv: float | None = None
    total_ltv: float | None = None


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


class AdminBusinessCrm(BaseModel):
    """The CRM corner of a business detail (from admin_business_extra). M13.

    `stage` is the sales pipeline column (new|contacted|warming|won|lost), or None
    if the business has no CRM row yet. The two timestamps are ISO strings (or None).
    """

    stage: str | None = None
    last_contacted_at: str | None = None
    next_followup_at: str | None = None


class AdminBusinessDetail(BaseModel):
    """A single business profile (from admin_business_detail).

    M13 merges in three additive fields from admin_business_extra() — an LTV
    estimate, the cumulative ai_calls counter, and the nested `crm` block — all
    OPTIONAL so the M12 frontend reads that ignore them keep working.
    """

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
    # M13 (additive): money + AI usage + sales-pipeline state for this business.
    ltv_estimate: float | None = None
    ai_calls: int | None = None
    crm: AdminBusinessCrm | None = None


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


# === M13: back-office analytics ==============================================

# The metric vocabulary admin_by_plan accepts (mirrors the SD function's CHECK).
# Whitelisted via Literal so a junk metric is rejected at the edge with 422.
ByPlanMetric = Literal["msg_in", "msg_out", "lead", "booking", "login", "ai_call"]

# The period window the leads-by-type + by-plan SD functions accept.
AnalyticsPeriod = Literal["week", "month", "all"]


# --- GET /api/admin/analytics/leads-by-type ----------------------------------


class AdminLeadsByType(BaseModel):
    """Lead counts split by the three bot outcomes (from admin_leads_by_type).

    booking = appointments, lead = collected leads, handoff = "פנייה לנציג"
    (human-handoff) requests. All non-test, scoped to the requested period/plan.
    """

    booking: int
    lead: int
    handoff: int


# --- GET /api/admin/analytics/messages (billing view) ------------------------


class AdminMessagesRow(BaseModel):
    """One business's message volume (from admin_messages_by_business). Billing."""

    business_id: str
    name: str | None = None
    plan_code: str
    msg_in: int
    msg_out: int
    total: int


class AdminMessagesResponse(BaseModel):
    """GET /api/admin/analytics/messages — per-business volume, busiest first."""

    businesses: list[AdminMessagesRow]


# --- GET /api/admin/analytics/ai-ops -----------------------------------------


class AdminAiOpsPoint(BaseModel):
    """One day's total ai_call count across the platform (from admin_ai_ops_series)."""

    day: str  # ISO date, e.g. "2026-06-22"
    count: int


class AdminAiOpsResponse(BaseModel):
    """GET /api/admin/analytics/ai-ops — the per-day ai_call series (ascending)."""

    series: list[AdminAiOpsPoint]


# --- GET /api/admin/analytics/by-plan ----------------------------------------


class AdminByPlanRow(BaseModel):
    """One plan's value for the chosen metric (from admin_by_plan)."""

    plan_code: str
    value: int


class AdminByPlanResponse(BaseModel):
    """GET /api/admin/analytics/by-plan — a metric split across plans.

    `metric` + `period` echo the request so the chart can label itself; `rows` is
    the per-plan breakdown.
    """

    metric: str
    period: str
    rows: list[AdminByPlanRow]


# --- GET /api/admin/analytics/trends -----------------------------------------


class AdminTrendPoint(BaseModel):
    """One snapshot day (from admin_trends_series / platform_snapshots).

    `mrr` is the estimated monthly recurring revenue for that day; the rest are
    counts. Trends accrue forward from when M13 shipped — no history before it.
    """

    day: str  # ISO date
    total_businesses: int
    active_count: int
    paid_count: int
    mrr: float
    churn_count: int


class AdminTrendsResponse(BaseModel):
    """GET /api/admin/analytics/trends — the snapshot series (ascending)."""

    series: list[AdminTrendPoint]


# === M13: platform-level sales CRM ===========================================

# The sales-pipeline stages business_crm.stage allows (mirrors the DB CHECK). The
# SD function re-validates; a bad stage there raises check_violation → 422.
CrmStage = Literal["new", "contacted", "warming", "won", "lost"]


# --- GET /api/admin/crm (the pipeline board) ---------------------------------


class AdminCrmRow(BaseModel):
    """One card on the sales board (from admin_crm_list).

    Every business appears once; `stage` defaults to "new" inside the SD function
    when there is no CRM row yet. `note_count` shows how much history exists.
    """

    business_id: str
    name: str | None = None
    plan_code: str
    stage: str
    last_contacted_at: str | None = None
    next_followup_at: str | None = None
    note_count: int


class AdminCrmListResponse(BaseModel):
    """GET /api/admin/crm — every business as a pipeline card."""

    businesses: list[AdminCrmRow]


# --- PATCH /api/admin/businesses/{id}/crm ------------------------------------


class AdminCrmStageRequest(BaseModel):
    """Move a business to a new sales stage, with an optional follow-up reminder.

    `stage` is whitelisted here (first gate); the SD function re-validates it.
    `next_followup` is an OPTIONAL ISO-8601 timestamp (when to chase this lead
    again) — null/omitted clears it.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    stage: CrmStage
    next_followup: str | None = Field(default=None, max_length=40)


class AdminCrmStageResponse(BaseModel):
    """The new CRM state after admin_set_crm_stage (echo)."""

    business_id: str
    stage: str
    next_followup_at: str | None = None


# --- POST /api/admin/businesses/{id}/crm/notes -------------------------------


class AdminCrmNoteRequest(BaseModel):
    """Add a free-text sales note to a business's CRM log.

    The note is owner-business sales context (not end-customer PII), but it is
    still never logged. Capped at 2000 chars; blank is rejected (the SD function
    also raises check_violation on blank → 422).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    note: str = Field(..., min_length=1, max_length=2000)


class AdminCrmNoteCreatedResponse(BaseModel):
    """POST .../crm/notes — the id of the note just written."""

    note_id: str


class AdminCrmNote(BaseModel):
    """One entry in a business's CRM note log (from admin_crm_notes)."""

    id: str
    admin_email: str | None = None
    note: str
    created_at: str | None = None


class AdminCrmNotesResponse(BaseModel):
    """GET .../crm/notes — the note log, newest first."""

    notes: list[AdminCrmNote]


# === M13: hard-delete a business =============================================


class AdminDeleteResponse(BaseModel):
    """DELETE /api/admin/businesses/{id} — confirmation of the wiped business.

    `deleted` is always True on success (a missing business is a 404, not a
    False); `name` echoes the deleted business name (for the success toast).
    """

    deleted: bool = True
    name: str | None = None
