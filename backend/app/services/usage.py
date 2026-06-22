"""Usage counters — the per-business, per-day, per-metric tally (M12).

`usage_daily` is a TENANT table of PURE NUMBERS (zero content, zero PII): one row
per (business_id, day, metric). The admin back-office sums these for its KPI strip
and per-business charts. Metrics (free text, migration 0016): `msg_in` · `msg_out`
· `lead` · `booking` · `login`.

Two non-negotiables:
  1. RLS, always. A bump is a write on a tenant table whose WITH CHECK enforces
     `business_id = current_business_id()`. So `bump(...)` MUST run on a
     tenant-bound connection (the one yielded by `tenant_connection`) — it takes
     the already-open `conn`, never the pool, so the caller owns the RLS context.
  2. NEVER break the real request. A counter is telemetry; a failure to bump must
     never abort the customer message / lead / booking / login it rode on. Use
     `bump_safe(...)` for that — it swallows + logs (class only) any error.

`business_id` is ALWAYS the caller's already-verified tenant id (the server
session, or the webhook's server-resolved business) — never a raw client value.
We never log a metric value beyond the metric NAME (which carries no PII).
"""

from __future__ import annotations

import asyncpg

from app.core.logging import get_logger

log = get_logger("app.services.usage")

# The known metric vocabulary (mirrors migration 0016). Free text in the DB, but
# we keep the canonical names here so call sites use a stable constant.
METRIC_MSG_IN = "msg_in"
METRIC_MSG_OUT = "msg_out"
METRIC_LEAD = "lead"
METRIC_BOOKING = "booking"
METRIC_LOGIN = "login"


async def bump(
    conn: asyncpg.Connection,
    business_id: str,
    metric: str,
    n: int = 1,
) -> None:
    """UPSERT +n onto today's (business_id, metric) counter (RLS-scoped via `conn`).

    `conn` MUST be a tenant-bound connection (from `tenant_connection`) so the
    table's WITH CHECK (`business_id = current_business_id()`) passes. We include
    `business_id` in the INSERT so the row matches the tenant policy. On conflict
    we add to the existing count. This is the RAW bump — it will RAISE on error;
    real call sites should prefer `bump_safe(...)`.
    """
    await conn.execute(
        """
        INSERT INTO usage_daily (business_id, day, metric, count)
        VALUES ($1, current_date, $2, $3)
        ON CONFLICT (business_id, day, metric)
        DO UPDATE SET count = usage_daily.count + EXCLUDED.count
        """,
        business_id,
        metric,
        int(n),
    )


async def bump_safe(
    conn: asyncpg.Connection,
    business_id: str,
    metric: str,
    n: int = 1,
) -> None:
    """Best-effort `bump`: a counter failure NEVER breaks the real request.

    Wraps `bump(...)` and swallows ANY exception, logging only the metric NAME
    (no PII, no value, no error detail). Use this at every wiring point — the
    inbound/outbound message, the lead, the booking, the login — so telemetry can
    never abort the thing it is measuring.

    NOTE: this reuses the caller's already-open tenant `conn`. If that connection
    is inside a transaction that later fails for an UNRELATED reason, a bump done
    earlier may roll back with it — acceptable for telemetry. Where a clean,
    independent bump matters, the caller opens its own short tenant_connection.
    """
    try:
        await bump(conn, business_id, metric, n)
    except Exception:  # noqa: BLE001 — telemetry must never break the request.
        log.warning("usage bump failed", extra={"metric": metric})
