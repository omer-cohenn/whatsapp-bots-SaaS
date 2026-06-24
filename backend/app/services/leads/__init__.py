# מחברת הלידים — חבילה: מאחדת crud/query/funnel לממשק יציב אחד
"""Lead lifecycle (Postgres) — the bot's long-term notebook (M5).

Where `conversation_state.py` holds the HOT, ephemeral turn-state in Redis, THIS
package persists the durable record of what a conversation collected: a `leads`
row that walks through its lifecycle...

    in_progress  → (more answers arrive, lead grows)
    in_progress  → new        (questionnaire completed, ready for the owner)
    in_progress  → abandoned  (swept later by the runner — not built here)

...plus a `flow_events` funnel trail (started / step / completed / abandoned).

This package was split out of the old single-file `leads.py` for readability
(M15 cleanup) WITHOUT any behavior change. The code now lives in three focused
sub-modules, and this `__init__` re-exports the FULL public surface so every
existing caller keeps working unchanged — both
`from app.services import leads; leads.X()` and
`from app.services.leads import X`.

Sub-modules:
  * crud.py   — create / update / complete / set-status (the write side)
  * query.py  — list / get / decrypt for the owner dashboard (the read side)
  * funnel.py — flow_events writes + funnel_stats aggregates

Two non-negotiables baked into every function here (unchanged):

  1. RLS, always. Every write goes through `tenant_connection(pool/conn, ...)` so
     Postgres scopes it to exactly this tenant. The `business_id` is the caller's
     already-verified id (never a raw client value) — and we STILL pass it in the
     INSERT/UPDATE so RLS's WITH CHECK matches.
  2. PII encrypted at rest, never logged. `phone`, `contact_name`, and the whole
     `answers` blob are encrypted via `app/core/crypto.py` before they touch the
     DB; `key_version` is stamped so rotation stays possible. We NEVER log a phone,
     a name, or an answer value.

`is_test` (the "try-me" flag) is honored throughout: a test lead and its events
are tagged `is_test = true` so they can be filtered out of real funnel metrics.

Note on the `conn` argument: each function takes an already-open, tenant-bound
`asyncpg.Connection` (the one yielded by `tenant_connection`). This lets the
runtime agent do a create + log_event in ONE transaction, and keeps RLS context
attached to the same connection as the query.
"""

from __future__ import annotations

from app.services.leads._common import (
    EVENT_ABANDONED,
    EVENT_COMPLETED,
    EVENT_HANDOFF,
    EVENT_STARTED,
    EVENT_STEP,
    STATUS_ABANDONED,
    STATUS_CLOSED,
    STATUS_DEAL,
    STATUS_IN_PROGRESS,
    STATUS_NEW,
)
from app.services.leads.crud import (
    complete_lead,
    create_lead,
    set_lead_status,
    update_lead,
)
from app.services.leads.funnel import funnel_stats, log_event
from app.services.leads.query import (
    STATUS_OPEN,
    get_lead_by_conversation,
    list_leads,
)

__all__ = [
    # status vocabulary
    "STATUS_IN_PROGRESS",
    "STATUS_NEW",
    "STATUS_ABANDONED",
    "STATUS_DEAL",
    "STATUS_CLOSED",
    "STATUS_OPEN",
    # funnel event vocabulary
    "EVENT_STARTED",
    "EVENT_STEP",
    "EVENT_COMPLETED",
    "EVENT_ABANDONED",
    "EVENT_HANDOFF",
    # write side
    "create_lead",
    "update_lead",
    "complete_lead",
    "set_lead_status",
    # read side
    "list_leads",
    "get_lead_by_conversation",
    # funnel
    "log_event",
    "funnel_stats",
]
