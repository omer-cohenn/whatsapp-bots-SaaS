# Bizz_up — Codebase Documentation (folder-by-folder)

> Full, detailed map of everything built so far, organized by folder and subfolder.
> Generated 2026-06-21. Companion to [`STATUS.md`](STATUS.md) (resume point) and
> [`spec/mvp-checklist.md`](spec/mvp-checklist.md) (milestone checklist).

## What this project is
**Bizz_up** is a multi-tenant WhatsApp-bot SaaS. A business owner logs in (Google), builds a
conversational bot with an AI assistant, tests it ("try-me"), connects WhatsApp (QR), and then real
customer messages are captured as **encrypted leads**, handled by a **bot ↔ human handoff** live chat,
and turned into **appointments/bookings** (with an optional public booking page + Google Calendar). The
owner sees everything in a back-office dashboard.

**Build status:** M0–M5, M7, M8, M9, M10, M11 (incl. M11.1/M11.2) are **done & committed on `main`**.
The remaining gap is **M6 — connect WhatsApp for real** (multi-tenant), and a separate **AWS deploy**
track — both planned in [`decisions/0013`](decisions/0013-whatsapp-multitenant-and-aws-roadmap.md) but
not built yet.

## Top-level layout
```
bizz_up/
├── backend/        FastAPI app (Python 3.12) — API, services, the bot engine, DB access, tests
├── frontend/       React 18 + TypeScript + Tailwind (RTL Hebrew) — the owner web app + public booking page
├── gateway/        Node.js + Baileys — the WhatsApp gateway (QR connect, inbound→webhook) [single-session spike]
├── infra/          docker-compose, .env templates, Makefile, run.bat/stop.bat — local stack orchestration
├── supabase/       PostgreSQL migrations (0000–0012) + seed.sql — schema, RLS, roles, functions
├── docs/           Living docs: STATUS, spec/, decisions/, system-map/, prototype/, CODEBASE.md (this file)
├── tests/          Double-click .bat runners for the milestone test suites (run inside Docker)
├── .claude/        AI control room: specialist agents, workflows, skills, settings (last_bo write-deny)
├── CLAUDE.md       Master rulebook every AI agent reads first
├── README.md       Project overview
└── run.bat / stop.bat   Start / stop the whole stack on Windows
```

## Cross-cutting principles (enforced everywhere)
- **Multi-tenant isolation by `business_id`** — RLS on every tenant table via `current_business_id()`;
  the backend opens a `tenant_connection(...)` that sets `app.business_id` per transaction; the id comes
  ONLY from the verified server session (admin) or a resolved public slug — never from the client.
- **Two non-service DB roles** — `app_role` (RLS-scoped, the app) and `gateway_role` (crown-jewel only:
  the WhatsApp `whatsapp_credentials` table). `app_role` has ZERO access to the crown jewel.
- **PII encrypted at rest, never logged** — leads + booking client data + outcome notes encrypted with a
  Fernet PII key; WhatsApp creds + Google refresh token use envelope encryption (KEK). Decryption is
  fail-loud. Logs are allow-listed (no secrets/tokens/PII/message bodies).
- **Deny-by-default auth** — the whole `/api/*` group is gated by an opaque Redis-backed session cookie.
- **Secrets in env only** (`infra/.env.local`, git-ignored); the app fails closed if a required one is missing.
- **The originals are read-only** — `last_bo/` and `qr_wa_scanner/` are never modified (also enforced in `.claude/settings.json`).

---

## Backend (`backend/`)

FastAPI app (Python 3.12). Deny-by-default, multi-tenant. Core services are either **pure** (`bot_engine`)
or **thin orchestrators** (`bot_runtime`, the domain services). Started minimally in M0+M1 and grown per milestone.

### `app/main.py`
- FastAPI app + lifespan: validates settings (fail-closed), opens the asyncpg pool + Redis client, registers the Google Calendar hook, starts background sweeps (abandoned leads, booking reminders), and mounts all routers (health, webhook, auth, public booking, and the gated `/api` group).

### `app/core/` — configuration & infrastructure
- `config.py` — Fail-closed settings: required secrets have no defaults (GATEWAY_API_TOKEN, DATABASE_URL, REDIS_URL, encryption keys, Google OAuth); optional features (GEMINI_API_KEY, calendar redirect) are validate-at-use.
- `clients.py` — asyncpg pool factory + async Redis client; `ping_postgres()`/`ping_redis()` for `/healthz`.
- `crypto.py` — App-layer encryption (Fernet): a PII key (lead phone/name/answers) and a crown KEK (envelope-encrypt WhatsApp creds / Google token); fail-loud decryption (`DecryptionError`); keyed HMAC for deterministic phone hashing.
- `deps.py` — Auth dependencies: `current_session()` (resolve the cookie from Redis — the `/api` gate), `current_user()`, `current_business()` (verified tenant id, server-side only).
- `logging.py` — Structured JSON logging with an allow-list for `extra`; never logs secrets/tokens/PII/message bodies.

### `app/db/` — database & tenancy
- `session.py` — `tenant_connection(pool, business_id)`: opens a transaction and `set_config('app.business_id', ..., is_local=true)` so RLS scopes everything; the heart of multi-tenant isolation.

### `app/api/` — HTTP routers
- `health.py` — Public `GET /healthz` (200 + per-dependency detail; 503 otherwise; secret-free).
- `webhook.py` — Public `POST /webhook/whatsapp` (M1): verifies `X-Gateway-Token` (constant-time), parses the frozen `WhatsAppWebhook` contract, logs a redacted receipt. (M6 will route it to a business + run the bot.)
- `auth.py` — Public `/auth/*` (Google login/callback/logout): consent redirect with Redis CSRF state; provision owner+business; create opaque session; logout destroys it. Never logs codes/tokens.
- `me.py` — The gated `/api` router group (deny-by-default via `current_session`); `GET /api/me`; mounts the bot-builder, dashboard, booking, and Google-calendar sub-routers.
- `bot_builder.py` — `/api/bot/*` (M4): `GET/PUT /settings`, `POST /tryme` (pure sandbox), `POST /sim` (full runtime, is_test), `POST /ai/chat` (Gemini, 503 if unset), `GET /ai/history`.
- `dashboard.py` — `/api/*` back-office (M7+): `GET /leads`, `GET /dashboard` (funnel + orders), `GET /conversations[/{id}[/messages]]`, `POST /conversations/{id}/status|reply`, `PATCH /leads/{id}/status`, `GET /bookings/alerts`, `PUT /bot/publish`.
- `booking.py` — `/api/*` booking admin (M11): `GET/PUT /booking/settings`, services CRUD (`/services[/{id}]`), `GET/PATCH /bookings[/{id}]`, `POST /booking/welcome/generate` (AI). Fires the Google hook after mutations.
- `public_booking.py` — PUBLIC `/api/book/*` (no session): tenant resolved from the **slug**; `GET /{slug}/services|slots|availability`, `POST /{slug}` (rate-limited, double-booking guard, encrypted PII), `POST /{slug}/cancel|reschedule/{token}`.
- `google_oauth.py` — `/api/google/*` (M11): `connect` (consent URL), `callback` (store KEK-encrypted refresh token), `status`, `disconnect`. Validate-at-use (503 if unconfigured); tokens never logged/returned.

### `app/services/` — business logic
- `bot_engine.py` — The **pure** conversation engine: (settings, state, message) → replies + next state, with ZERO I/O. Handles menu, step validation (text/phone/email/choice), flow transitions, handoff, booking.
- `bot_runtime.py` — Thin orchestrator: load state (Redis) + config (Postgres) → run engine → persist leads/funnel (one tenant transaction) → save state. Enforces "handoff = silence" and is_test.
- `conversation_state.py` — Conversation state + chat_status in Redis. **TTL by status**: bot = ~60-min sliding; waiting/human = persist; closed = 30 days. Tenant id baked into every key + re-checked.
- `leads.py` — Lead lifecycle (Postgres, RLS): create→new/abandoned, funnel `flow_events`, encrypted PII, `key_version`, is_test honored, owner statuses (deal/closed), `outcome_note`.
- `booking.py` — Booking domain: settings/services/slots/bookings + the slot algorithm (split hours, per-service duration, buffer/min-notice/max-days, Asia/Jerusalem→UTC), availability, double-booking guard; fires the decoupled Google hook after commit.
- `booking_reminders.py` — Background sweep (single-runner, Redis lock) that queues confirmations + day-before reminders into `booking:outbox:{business_id}` (M6 will send).
- `booking_alerts.py` — PII-free Redis inbox for customer-initiated cancel/reschedule → the home "booking updates" feed.
- `booking_welcome.py` — Focused Gemini proxy that writes the public-page welcome message (validate-at-use, grounded, no PII logged).
- `bot_builder_ai.py` — AI bot-builder Gemini proxy (M4): grounded; LLM output re-validated against the Pydantic bounds before merge; 503 if no key.
- `bot_settings.py` — get/upsert the `bot_settings` row (RLS, tenant_connection).
- `google_calendar.py` — Google Calendar + Meet sync hook (create/patch/delete events, invite by email, Meet link); degrades gracefully (a Google failure never breaks a booking); test seam for no-network tests.
- `google_oauth.py` — Calendar OAuth connect: KEK-encrypted refresh token per business, CSRF state in Redis, validate-at-use.
- `live_chat.py` — Earlier ephemeral live-chat cache (Redis), business-prefixed keys (superseded in places by `conversation_state`).
- `abandoned_sweep.py` — Background sweep (single-runner) flipping idle `in_progress` leads → abandoned via a SECURITY DEFINER function (cross-tenant but each row keeps its own business_id).
- `auth.py` — Google OAuth + opaque server-side sessions (Redis), CSRF state, never logs codes/tokens.

### `app/models/` — Pydantic contracts (no `business_id` ever)
- `auth.py` — `/api/me` shapes (user, business, WhatsApp connection).
- `health.py` — `/healthz` shapes.
- `webhook.py` — the FROZEN gateway→backend `WhatsAppWebhook` contract.
- `bot_builder.py` — `BotSettings`/`BotProfile`/`Flow`/`Step` with bounds (≤20 flows, ≤30 steps/flow, choice ≤12, etc.); `is_published`.
- `dashboard.py` — `LeadItem`/`LeadsResponse`, conversation + message shapes, booking-alert shapes (PII decrypted for the owner only).
- `booking.py` — booking settings/service/booking + public shapes + welcome-generate; bounded fields; `image_url` (≤2,000,000 for a resized data URL).
- `google.py` — Google connect/status/disconnect shapes (no tokens).

### `backend/` build files
- `pyproject.toml` — pinned deps (FastAPI, asyncpg, redis, cryptography, Pydantic v2, google-genai, google-api-python-client) + dev (pytest, ruff).
- `requirements.lock` — fully-pinned transitive lockfile; Dockerfile installs with `--no-deps`.
- `Dockerfile` — python:3.12-slim, non-root, gunicorn+uvicorn workers, port 8000, no `--reload`.

### `backend/tests/` — backend test suites
- `isolation/test_tenant_wall.py` — the M2 hard gate: RLS reads only own rows, cross-tenant read/insert blocked, no-session → zero rows (connects as the real non-service roles).
- `test_auth_gate.py` — M3 deny-by-default gate (401 for missing/expired sessions, `provision_owner` idempotency) against the real ASGI app via httpx.
- `test_secret_guard.py` — asserts secrets/PII never appear in logs/responses.
- Milestone narrated suites: `m2_full_test.py`, `m3_full_test.py`, `m5_full_test.py`/`m5b_full_test.py`, `m7_full_test.py`, `m8_full_test.py`, `m9_full_test.py`, `m10_full_test.py`, `m11_full_test.py`, `m11_1_full_test.py`, `m11_2_full_test.py` — plain-language end-to-end stories per milestone.
- Strict pytest suites: `test_bot_builder.py`, `test_bot_tryme.py`, `test_bot_sim.py`, `test_dashboard.py`, `test_lead_status.py`, `test_m8.py`, `test_m9.py`, `test_m10.py`, `test_m11.py`, `test_m11_1.py`, `test_m11_2.py`, plus `demo_isolation.py`.

---

## Frontend (`frontend/`)

React 18 + TypeScript + Tailwind + React Router v6 (Vite). **RTL Hebrew** throughout; accessible (jsx-a11y,
aria-live, landmarks, skip-links). Docker dev server on :5173 (Windows host → `usePolling:true` for HMR).

### Config
- `package.json` — React 18.3, react-router 6.28, date-fns 3.6, react-day-picker 8.10, Tailwind, TS, ESLint + a11y.
- `vite.config.js` — dev server (host/port 5173), proxy `/api`,`/auth`,`/webhook`,`/healthz` → backend; file-watch polling for Windows.
- `tailwind.config.js` — palette (`brand` WhatsApp teal, `leaf` greens), Heebo Hebrew font.
- `Dockerfile` — node:20-slim, healthcheck on `/`, runs `vite --host`.

### Entry & auth
- `src/main.tsx` — React 18 root.
- `src/App.tsx` — Router + AuthProvider. Public routes: `/login`, `/terms`, `/privacy`, `/book/:slug`, `/book/:slug/manage/:token`. Protected (AuthGate + DashboardLayout): `/`, `/bot-builder`, `/try-me`, `/leads`, `/conversations`, `/appointments`, `/settings/calendar`.
- `src/auth/AuthContext.tsx` — calls `GET /api/me`; holds user/business/connection; `logout()`; 401 → unauthenticated.
- `src/auth/types.ts` — User/Business/Connection/Me types.

### Pages (`src/pages/`)
- `LoginPage.tsx` — hero + "sign in with Google" (real navigation to `/auth/google`).
- `LegalPage.tsx` / `TermsPage.tsx` / `PrivacyPage.tsx` — legal pages shell + content.
- `DashboardHome.tsx` — greeting, publish toggle, funnel KPIs (period filter), "waiting for you" conversations, **booking-update alerts**, and the `ActivityFeed`.
- `BotBuilderPage.tsx` — the AI bot builder: profile + flow tabs + steps editor + type selector + save/publish + the AI chat panel.
- `TryMePage.tsx` — WhatsApp-style sandbox chat (`POST /api/bot/tryme`), lead card on completion, handoff note.
- `LeadsPage.tsx` — filterable leads (status incl. deal/closed; flow), KPI cards, abandoned follow-up list; per-lead expand + actions.
- `ConversationsPage.tsx` — live conversation accordion (filter by status), inline `ChatPanel`, deep-link support.
- `AppointmentsPage.tsx` — two tabs: "פגישות" (`BookingsPanel`) and "הגדרות תורים" (`BookingSettingsPanel`); also the Google-OAuth return at `/settings/calendar`.
- `PublicBookingPage.tsx` — public `/book/:slug`: loads services + welcome, renders `<BookingFlow mode="live">`.
- `PublicManagePage.tsx` — public cancel/reschedule via the customer's token.

### Components — UI kit (`src/components/ui/`)
- `Button`, `Card`, `Field`, `Textarea`, `Select`, `Badge`, `Alert`, `Spinner`, `Tabs`, `CopyButton`, `Icon` (Tabler-style inline SVG set, aria-hidden by default).

### Components — shell & dashboard (`src/components/` + `dashboard/`)
- `AuthGate.tsx` — gate protected routes (spinner while loading; redirect to `/login`).
- `DashboardLayout.tsx` — RTL sidebar shell + `OwnerHeader` + `<main>` landmark.
- `OwnerHeader.tsx` — brand, WhatsApp connection pill, user chip, logout.
- `dashboard/StatCard.tsx`, `SegmentedControl.tsx`, `ActivityFeed.tsx`, `PublishToggle.tsx`.
- `dashboard/LeadCard.tsx` — full lead detail + in-app chat button + deal/closed actions (open `OutcomeNoteDialog`).
- `dashboard/ConversationCard.tsx` — accordion row + inline `ChatPanel` + status controls.
- `dashboard/ChatPanel.tsx` — WhatsApp-style transcript (polls every 4s), owner reply (optimistic), empty fallback from lead answers.
- `dashboard/EmojiPicker.tsx`, `dashboard/OutcomeNoteDialog.tsx` (mandatory note on deal/closed).

### Components — booking (`src/components/booking/`)
- `BookingFlow.tsx` — the reusable public booking experience (welcome hero, service cards w/ description+price+image, custom month calendar, slots, summary, confirmation); `mode: live | preview`.
- `AvailabilityCalendar.tsx` — custom month grid driven by `/availability`; `BookingsCalendar.tsx` — owner month/week/day calendar of bookings.
- `BookingsPanel.tsx` — owner bookings list/calendar + manage (status/reschedule); `BookingCard.tsx`.
- `BookingSettingsPanel.tsx` — working hours, rules, Meet toggle, **welcome message + "נסח עם AI"**, services CRUD, Google connect, and a **live preview** of `BookingFlow`.
- `ServicesEditor.tsx` — services CRUD incl. description, price, and **image upload** (client-side resize → data URL).
- `WorkingHoursEditor.tsx` (split hours), `AvailabilityRulesEditor.tsx`, `GoogleConnectPanel.tsx`, `DatePicker.tsx`, `SlotGrid.tsx`, `RescheduleDialog.tsx`, `PublicBookingLayout.tsx`.

### Components — bot builder (`src/components/botbuilder/`)
- `FlowTabs`/`FlowTypeSelector` (lead/human_handoff/booking), `StepsEditor` (accordion; pencil-gated type change), `AIChatPanel` (`/api/bot/ai/chat` + history; applies validated changes live).

### Lib (`src/lib/`)
- `apiClient.ts` — fetch wrapper (same-origin, credentials, timeout, `ApiError`, 401 detection).
- `dashboardClient.ts`, `botClient.ts`, `bookingClient.ts` (admin), `publicBookingClient.ts` (public) — typed endpoint wrappers.
- `formatDate.ts`, `friendlyError.ts` (Hebrew error i18n), `waLink.ts` (wa.me), `bookingDates.ts` (calendar math), `imageResize.ts` (canvas resize → compressed data URL).

### Types (`src/dashboard/`, `src/botbuilder/`)
- `dashboard/types.ts` — M7 contract mirror (Lead, DashboardStats, Conversation, Message…).
- `dashboard/appointmentTypes.ts` — M11 contract mirror (BookingSettings, ServiceItem incl. description/price/image_url, PublicService, BookingItem, BookingAlert…).
- `botbuilder/types.ts` + `config.ts` — M4 contract mirror + builder helpers (defaults, empty flow/step, normalize).

---

## Gateway, Infra & Database

### Gateway (`gateway/`)
Node.js + Baileys WhatsApp gateway — currently a **single-session spike** that proves the receive path.
- `src/index.js` — boot, Baileys connection + QR generation, inbound `messages.upsert` → forward to backend, dev-only endpoints, reconnect.
- `src/config.js` — fail-closed config (requires `GATEWAY_API_TOKEN`; `BACKEND_WEBHOOK_URL` default `http://backend:8000/webhook/whatsapp`; `authDir` default `./auth`; account id `'spike'`).
- `src/contract.js` — the frozen webhook payload builder: Baileys msg → `{gateway_account_id, from (E.164), push_name, message_id, timestamp, type, text, raw}`.
- `src/logger.js` — Pino with hard redaction (never logs token/QR/body/phone).
- `Dockerfile` — node:20-slim, creates `/app/auth` (spike creds), healthcheck on `/healthz`.
- **Flow:** QR rendered at `GET /qr` (dev) → scan → `connection='open'` → inbound forwarded with `X-Gateway-Token`. Creds persist in `auth/` (gitignored, plaintext — M6 moves them to the encrypted DB).
- **Dev-only endpoints** (remove/secure for prod): `GET /qr`, `GET /inbox`, `GET|POST /send`; plus `GET /healthz`.
- **Single-session today** — M6 makes it one socket per business keyed by `gateway_account_id`.

### Infra (`infra/`)
- `docker-compose.yml` — health-gated stack (no blind sleeps):
  - `postgres:16-alpine` (volume `pg_data`, `pg_isready` healthcheck) · `redis:7-alpine` (password, ephemeral cache) · `migrate` (one-shot: applies `supabase/migrations/*.sql`, creates roles) · `backend:8000` (gunicorn, depends on pg+redis+migrate healthy) · `gateway:3000` (depends on backend) · `frontend:5173` (vite, anon `node_modules` volume).
- `.env.local.example` — secret-name template, grouped: gateway↔backend (`GATEWAY_API_TOKEN`, `BACKEND_WEBHOOK_URL`), Postgres (`POSTGRES_USER/PASSWORD/DB`), Redis (`REDIS_PASSWORD`), DB roles (`APP_DB_PASSWORD`, `GATEWAY_DB_PASSWORD`), encryption (`PII_DATA_KEY`, `WA_CRED_KEK`, `PHONE_HMAC_KEY`), auth (`SESSION_SECRET`, `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI`, `GOOGLE_CALENDAR_REDIRECT_URI`), AI (`GEMINI_API_KEY`).
- `Makefile` — `make dev/down/logs/ps/build/migrate/seed/isolation/test/demo-isolation/demo-break`.
- `run.bat` / `stop.bat` — Windows start/stop (auto-generates `.env.local` if missing); URLs: frontend :5173, gateway QR :3000/qr, backend :8000.

### Database (`supabase/`)
PostgreSQL with RLS + role isolation. Migrations (applied in order by `migrate`):
- `0000_init.sql` — empty marker.
- `0001_roles_extensions.sql` — pgcrypto + roles `app_role` / `gateway_role`.
- `0002_rls_bridge.sql` — `current_business_id()` (reads `app.business_id`; NULL ⇒ deny-by-default).
- `0003_tables.sql` — the 9 tables: `users`, `businesses`, `business_members`, `whatsapp_connections` (🔒 phone), `whatsapp_credentials` (🔒🔒 crown jewel), `bot_settings`, `leads` (🔒 PII), `bot_builder_messages`, `flow_events`.
- `0004_rls_policies_grants.sql` — ENABLE+FORCE RLS + `p_tenant_isolation` (USING+WITH CHECK) on every tenant table; least-privilege grants (crown jewel = gateway_role only).
- `0005_auth_bootstrap.sql` — SECURITY DEFINER `provision_owner(...)` + `get_user_businesses(...)`.
- `0006_abandoned_sweep.sql` — SECURITY DEFINER `sweep_abandoned_leads(idle_minutes)`.
- `0007_outcome_note.sql` — `leads.outcome_note` (🔒).
- `0008_booking.sql` — booking tables: `booking_settings`, `services`, `bookings` (🔒 client PII), `google_credentials` (🔒 KEK).
- `0009_rls_booking.sql` — RLS + grants for the 4 booking tables (app_role CRUD; gateway_role none).
- `0010_booking_slug_resolve.sql` — SECURITY DEFINER `resolve_booking_slug(slug)` + `bookings_due_for_reminder(window_hours)` (PII-free).
- `0011_booking_service_extras.sql` — `services.description`, `services.price`, `booking_settings.welcome_message`.
- `0012_service_image.sql` — `services.image_url` (http(s) URL or resized data URL).
- `seed.sql` — two dev tenants (Avi Insurance, Bella Barber) with bot config; idempotent.

---

## Docs, Tests, AI Control Room & Root

### Documentation (`docs/`)
- `STATUS.md` — resume-point: phase, what's done (M0–M11.2), how to run/test, what's next.
- `00_overview.md` — plain-English tour of the system + the 4 conversation paths.
- `bugs.md` / `security-issues.md` — consolidated bug + security-finding logs (incl. per-milestone audit appends).
- `spec/` — the blueprint: `roadmap.md`, `mvp-checklist.md`, `build-guide.md`, `architecture.md`, `data-model.md`, `bot-config-contract.md`, and `roadmap-parts/*` (per-domain plans incl. `devops-aws.md` = the full managed-AWS plan for scale).
- `decisions/` — locked decision records:
  - 0001 Baileys QR gateway canonical · 0002 multi-tenant required · 0003 default AI model (`gemini-3.1-flash-lite`) · 0004 MVP scope · 0005 data-model + auth · 0006 live chat in Redis · 0007 M5+M7 build plan · 0008 M8 handoff chat · 0009 M9 lead outcomes · 0010 M10 chat persistence + notes · 0011 M11 appointments & booking · 0012 M11.1 public booking polish · 0013 WhatsApp multi-tenant (M6) + AWS roadmap (planned).
- `system-map/` — read-only map of the ORIGINAL system (`last_bo` + `qr_wa_scanner`): backend-map, frontend-map, whatsapp-gateway, infrastructure, etc.
- `prototype/bizzup-prototype.html` — approved UI mock (the booking page design source).
- `CODEBASE.md` — this document.

### Test runners (`tests/`)
Double-click `.bat` scripts (run inside Docker: migrate → seed → run suite → regress prior milestones):
- `test_m2.bat` (tenant wall) · `test_m3.bat` (login/gate) · `test_m4.bat` (AI builder) · `test_m5.bat`/`test_m5b.bat` (try-me / lead memory) · `test_m7.bat`/`test_m7b.bat` (dashboard / polish) · `test_m8.bat` (handoff chat) · `test_m9.bat` (lead outcomes) · `test_m10.bat` (TTL + notes) · `test_m11.bat` (booking) · `test_m11_1.bat` (booking polish) · `test_m11_2.bat` (service image). Latest full strict bundle: **190 passed**.

### AI control room (`.claude/`)
- `agents/` — specialist sub-agents: read-only scanners (`business-logic-scanner`, `frontend-mapper`, `whatsapp-scanner`, `infra-scanner`, `security-scanner`, `docs-assembler`, `data-architect`, `devops_aws`) and the builders used this build (`bizzup-data-builder`, `bizzup-backend-builder`, `bizzup-frontend-builder`, `bizzup-test-runner`).
- `workflows/` — `scan-existing-system.md` (run scanners + consolidate).
- `skills/progress_report/SKILL.md` — drafts a Hebrew WhatsApp progress update for Omer's mentor. (A user-level `plan_milestone` skill lives in `~/.claude/skills/`.)
- `settings.json` — project settings incl. the **write-deny on `last_bo/**` and `qr_wa_scanner/**`**.

### Root files
- `CLAUDE.md` — the master rulebook (golden rules, folder map, coding standards, locked decisions, how to work with Omer).
- `README.md` — project overview + tech stack.
- `run.bat` / `stop.bat` — start/stop the stack on Windows.
- `.gitignore` — ignores `node_modules`, `__pycache__`, `.env*`, gateway `auth/`, etc.
