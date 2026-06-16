# 0005 — MVP data-model & auth decisions

- **Date:** 2026-06-16
- **Status:** accepted

## Context
The synchronized 3-agent schema design (data → business + security) produced the MVP data model
([`../spec/data-model.md`](../spec/data-model.md)) and raised 9 open questions. Two needed Omer's call;
the rest were taken as sensible defaults.

## Decisions
1. **Auth = Google login via FastAPI** (not Supabase Auth). RLS is wired **by hand**: after Google login the
   backend verifies the user's `business_id` via `business_members`, sets it as a per-request Postgres session
   value, and RLS policies read it via `current_business_id()`. The backend connects as a **non-service role**
   so RLS is enforced. **Trade-off:** more custom security code → this layer **must be covered by tests** (it was
   the old system's #1 failure point).
2. **Include the abandoned-lead funnel in the MVP** → added a lean `flow_events` table (table 12:
   started / step_completed / completed / abandoned, no PII). `abandoned` is set by the 60-min auto-close sweep.

## Defaults taken on the other 7 questions (see data-model.md)
- QR code **not stored** (streamed to the dashboard live).
- `users.email` **not encrypted** (it's the login/unique key — protected by role + RLS).
- `conversations.current_flow_state` **encrypted** (mid-flow answers are PII).
- `conversation_events` **kept** (handoff audit) + `assigned_user_id`/`handoff_at` on conversations.
- `bot_builder_messages` **kept** (resume the AI build session).
- Gateway `accountId` ↔ `business_id` bridge → confirmed during the **build phase**.
- Secret-manager vendor + KMS-vs-app-held KEK → decided with the **`devops_aws`** agent during the AWS phase.

## Consequences
- **12 tables** total for the MVP.
- The auth/RLS bridge is custom → needs dedicated isolation tests before launch.
- The funnel depends on the auto-close sweep marking `abandoned`.
