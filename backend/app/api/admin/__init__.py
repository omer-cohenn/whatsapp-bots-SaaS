# בק‑אופיס מנהל — חבילה: מרכיבה את ה‑router הראשי תחת /admin עם שער current_admin
"""Protected /api/admin/* router — the platform-operator back-office (M12/M13).

This is the ONE surface that deliberately crosses the tenant wall. It is mounted
under the gated `/api` group AND carries its OWN router-level
`dependencies=[Depends(current_admin)]`, so every route here requires BOTH a valid
session AND an email on `ADMIN_EMAILS` — deny-by-default, no per-route opt-in to
forget.

This package was split out of the old single-file `admin.py` for readability
(M15 cleanup) WITHOUT any behavior change. The route handlers now live in three
focused sub-modules, each defining its own bare `APIRouter()`; this `__init__`
builds the ONE top-level `router` (prefix + admin gate) and `include_router`s
each. `from app.api.admin import router` keeps working exactly as before.

Sub-modules:
  * businesses.py — overview / list / detail / usage / plans / subscription / delete
  * analytics.py  — leads-by-type / messages / ai-ops / by-plan / trends
  * crm.py        — the sales pipeline: list / stage / notes

How it stays safe (decision 0016):
  * The cross-tenant reads/writes are SECURITY DEFINER functions (migration 0017)
    that bypass RLS by design. We call them on a PLAIN pool connection
    (`pg_pool.acquire()`) — NOT `tenant_connection` — because they intentionally
    span all tenants. `current_admin` is the only guard on them.
  * A `business_id` arrives only in the PATH for the per-business routes, and is
    fed STRAIGHT into an admin-gated SD function — it NEVER reaches a
    tenant_connection and never widens a tenant read.
  * The admin's REAL identity (session user_id = the Google sub in users(id), +
    email) is passed to the audited writers — never a client-supplied value.

We NEVER log PII or secrets here — only the action + a redacted business id.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.admin import analytics, businesses, crm
from app.core.deps import current_admin

# Router-level admin gate: EVERY route here requires current_admin (which itself
# requires a valid session). New admin routes inherit it automatically — there is
# no per-route opt-in to forget on the cross-tenant surface.
router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(current_admin)]
)

# Compose the sub-routers in the same relative order as the old single file
# (businesses → analytics → CRM). Each sub-router is bare (no prefix), so the
# full paths + the router-level admin gate are identical to before.
router.include_router(businesses.router)
router.include_router(analytics.router)
router.include_router(crm.router)
