# 0007 — Build M5 (lead memory) + M7 (dashboard) before M6 (WhatsApp)

- **Date:** 2026-06-19
- **Status:** accepted

## Context
The bot can already TALK (M5's pure conversation engine + the "try-me" sandbox are done and committed —
`bot_engine.py`, `/api/bot/tryme`). But two things are missing before it is a usable product:
1. The bot **forgets everything** — a real conversation persists no lead, no funnel, no status.
2. The owner **can't see anything** — there is no dashboard.

Omer chose to build these two now and defer the WhatsApp connection (M6) to next week. M5 is the **write side**
(the bot remembers), M7 is the **read side** (the owner sees). They are complementary: M5 produces the data, M7
displays it. Everything is exercised **without WhatsApp** (an internal, tenant-scoped test path drives the runtime).

No schema migration is needed: the `leads` and `flow_events` tables (migration `0003`) already carry every column
(`status`, `is_test`, encrypted PII, timestamps, `last_step_index`, `cache_chat_ref`), and live chat lives in Redis
(`live_chat.py`, per decision 0006).

## Decision

### M5 — the live runtime + lead lifecycle (no WhatsApp) — 10 goals
1. Conversation state in Redis per `(business_id, conversation_id)` + TTL (extends `live_chat.py`).
2. Lead **create** on flow start (`status='in_progress'`, `is_test`, `cache_chat_ref`).
3. Lead **update + complete** — answers encrypted at rest; `status='new'` + `submitted_at` on finish.
4. **Funnel events** to `flow_events` (started / step / completed / abandoned).
5. **Human-handoff** status (`bot`/`human`/`closed`) in Redis; engine handoff flips to `human`; re-engage flips back.
6. **Abandoned sweep** — single-runner, marks `abandoned` after 60 min idle + a funnel event.
7. The **runner** `run_turn(business_id, conversation_id, message)` = load state → `engine.advance` → persist → reply.
   This is exactly what M6 will wire WhatsApp into.
8. Internal **test-drive endpoint** (session-gated, tenant-scoped, `is_test`) so persistence is provable without
   WhatsApp and M7 has real data. (try-me stays a no-save sandbox.)
9. **Encryption + PII guard** — PII encrypted (`key_version`); nothing sensitive logged; extend the secret guard.
10. **Tests** — create/update/complete/abandon, funnel, handoff, sweep, tenant isolation, regression (M2–M5).

### M7 — the dashboard (back office) — 10 goals
1. Leads read API (`GET /api/leads`) — tenant-scoped, decrypt for the owner, filter period/status/flow.
2. Funnel/stats API (`GET /api/dashboard`) — started → completed → abandoned, per week/month/all.
3. Conversations API (`GET /api/conversations`) + set-status (bot/human/closed).
4. Owner-reply path for a human-handled conversation (queued; WhatsApp send arrives in M6).
5. Publish / go-live control (`PUT is_published`).
6. Dashboard home — KPI cards + real funnel + period filter (extends `DashboardHome`).
7. Leads page — table with all collected details + filter by type (incl. "new"/"open") + abandoned follow-up list.
8. Conversations page — live list + bot↔human toggle + reply UI.
9. Publish toggle + loading / empty / error states across pages.
10. Tests + accessibility (a11y, RTL) + typecheck + regression.

### Agent work-division (run as two Workflows, M5 then M7)
| Order | Agent | Depends on | Parallel? |
|---|---|---|---|
| P0 | `bizzup-data-builder` — verify `leads`/`flow_events` RLS/grants/columns (expect: no migration) | — | serial, first |
| P1 | `bizzup-backend-builder` — M5 persistence layer (Redis state + lead lifecycle + funnel + crypto) | P0 | serial |
| P2 | `bizzup-backend-builder` — M5 runtime (runner + handoff + abandoned sweep + test endpoint) | P1 | serial |
| P3 | `bizzup-test-runner` **+** `security-scanner` — review M5 | P2 | **parallel** (both gate) |
| — | *(main loop: verify + fix M5 green, then launch the M7 Workflow)* | | |
| P4 | `bizzup-backend-builder` — M7 read endpoints (leads/funnel/conversations/status/publish) | M5 green | serial |
| P5 | `bizzup-frontend-builder` — M7 dashboard/leads/conversations UI | P4 contract | serial |
| P6 | `bizzup-test-runner` **+** `security-scanner` — review M7 | P5 | **parallel** (both gate) |

**The gate rule:** a builder finishes, THEN the reviewers (QA + security) must approve before the next phase. No new
temporary agents — the existing five cover it.

## Notes / guardrails
- Every query filters by `business_id` + RLS; PII encrypted at rest; no secrets/PII in logs (decision 0002 / M2).
- try-me remains a **no-save sandbox**; the M5 test-drive endpoint is the one that persists (flagged `is_test`).
- Security follow-up from M5 try-me audit: when the **live** bot runs (M6), it must answer only when `is_published`.

## Consequences
- M6 (WhatsApp connect) becomes a thin transport layer: it just calls the M5 `run_turn` runtime.
- The dashboard finally shows real, tenant-scoped data the owner can act on (leads, abandoners, live chats, go-live).
