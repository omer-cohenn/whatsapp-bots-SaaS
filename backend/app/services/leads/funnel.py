# מחברת הלידים — המשפך: רישום אירועי flow_events + ספירת סטטיסטיקות משפך
"""Funnel trail: flow_events writes + funnel_stats reads (M5/M7).

`log_event` appends one structural funnel signal (started / step / completed /
abandoned / handed_off) for a lead — NO PII, only the flow + step. `funnel_stats`
aggregates those events plus the lead-row + orders counts for a period, for the
owner dashboard. All RLS-scoped via the tenant-bound `conn`. Moved VERBATIM from
the old single-file `leads.py` — no logic change.
"""

from __future__ import annotations

from typing import Any

import asyncpg

from app.services.leads._common import (
    EVENT_ABANDONED,
    EVENT_COMPLETED,
    EVENT_STARTED,
    _VALID_EVENTS,
    _period_clause,
)


async def log_event(
    conn: asyncpg.Connection,
    business_id: str,
    lead_id: str | None,
    flow_key: str | None,
    event: str,
    step_index: int | None,
    is_test: bool,
) -> None:
    """Append one funnel event for this lead/flow (RLS-scoped via `conn`).

    `event` must be one of started|step|completed|abandoned. `lead_id` may be None
    for an event that predates a lead row (defensive). No PII is recorded here —
    only the structural funnel signal (which flow, which step, test or not).
    """
    if event not in _VALID_EVENTS:
        raise ValueError(f"invalid flow event: {event!r}")

    await conn.execute(
        """
        INSERT INTO flow_events
            (business_id, lead_id, flow_key, event, step_index, is_test)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        business_id,
        lead_id,
        flow_key,
        event,
        step_index,
        is_test,
    )


async def funnel_stats(
    conn: asyncpg.Connection,
    business_id: str,
    *,
    period: str | None = None,
    include_test: bool = False,
) -> dict[str, int]:
    """Return funnel counts (started/completed/abandoned + total + orders) for a period.

    started/completed/abandoned come from `flow_events` (the funnel trail);
    `total_leads` counts the lead ROWS in the window; `orders` counts the lead rows
    the owner marked as a closed deal (status='deal'). `is_test` rows are excluded
    unless `include_test` is True. RLS-scoped via the tenant-bound `conn`.
    """
    # Funnel event counts (one scan of flow_events, grouped by event).
    ev_params: list[Any] = [business_id]
    ev_where = ["business_id = $1"]
    if not include_test:
        ev_where.append("is_test = false")
    ev_period = _period_clause(period, ev_params, "created_at")
    ev_rows = await conn.fetch(
        "SELECT event, count(*)::int AS n FROM flow_events "
        f"WHERE {' AND '.join(ev_where)}{ev_period} "
        "GROUP BY event",
        *ev_params,
    )
    by_event = {r["event"]: r["n"] for r in ev_rows}

    # Total lead rows in the same window (keyed off started_at).
    ld_params: list[Any] = [business_id]
    ld_where = ["business_id = $1"]
    if not include_test:
        ld_where.append("is_test = false")
    ld_period = _period_clause(period, ld_params, "started_at")
    total_leads = await conn.fetchval(
        f"SELECT count(*)::int FROM leads WHERE {' AND '.join(ld_where)}{ld_period}",
        *ld_params,
    )

    # Orders = leads the owner marked as a won deal, in the SAME window + is_test
    # filter as total_leads (own param list — its own period interval bind).
    or_params: list[Any] = [business_id]
    or_where = ["business_id = $1", "status = 'deal'"]
    if not include_test:
        or_where.append("is_test = false")
    or_period = _period_clause(period, or_params, "started_at")
    orders = await conn.fetchval(
        f"SELECT count(*)::int FROM leads WHERE {' AND '.join(or_where)}{or_period}",
        *or_params,
    )

    # Meetings = bookings CREATED in the window that weren't cancelled (M11 data,
    # surfaced on the home funnel as "פגישות"). Same is_test discipline; keyed off
    # created_at so it reads "meetings booked this period", like the other cards.
    mt_params: list[Any] = [business_id]
    mt_where = ["business_id = $1", "status <> 'cancelled'"]
    if not include_test:
        mt_where.append("is_test = false")
    mt_period = _period_clause(period, mt_params, "created_at")
    meetings = await conn.fetchval(
        f"SELECT count(*)::int FROM bookings WHERE {' AND '.join(mt_where)}{mt_period}",
        *mt_params,
    )

    return {
        "started": int(by_event.get(EVENT_STARTED, 0)),
        "completed": int(by_event.get(EVENT_COMPLETED, 0)),
        "abandoned": int(by_event.get(EVENT_ABANDONED, 0)),
        "total_leads": int(total_leads or 0),
        "orders": int(orders or 0),
        "meetings": int(meetings or 0),
    }
