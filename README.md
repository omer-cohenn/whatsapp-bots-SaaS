# WhatsApp Bots SaaS

A **multi-tenant SaaS platform that lets any business run its own WhatsApp bot** — without writing a
line of code. A business owner signs in with Google, connects their WhatsApp number by scanning a QR
code, and then builds conversational flows in the browser: menus, lead-capture questionnaires,
appointment booking, and hand-off to a human agent. Every conversation, lead and booking is captured
in a dashboard.

The platform is built as a **monorepo of five deployable domains** (FastAPI backend, Node WhatsApp
gateway, React frontend, Docker infra, Postgres migrations) and runs end-to-end with a single
`make dev`.

---

## Table of contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Data model](#data-model)
- [Multi-tenancy and security](#multi-tenancy-and-security)
- [API surface](#api-surface)
- [Frontend routes](#frontend-routes)
- [Testing](#testing)
- [Deployment](#deployment)
- [Development conventions](#development-conventions)

---

## What it does

### For the business owner

| Capability | Description |
|---|---|
| **WhatsApp connection** | Scan a QR code once; the gateway holds the session and reconnects on its own. Session credentials are encrypted at rest with a KEK. |
| **Visual bot builder** | Build the conversation as menus and steps. An AI assistant (Gemini) can draft a whole flow from a plain-language description of the business, but the *runtime* engine stays deterministic. |
| **Lead capture** | Multi-step questionnaires with typed steps — `text`, `phone`, `email`, `choice`, `file`. Completed answers become a lead record. |
| **Appointment booking** | Owner defines services, durations and working hours; the engine computes free slots. Customers book over WhatsApp *or* on a public booking page. Optional two-way Google Calendar + Meet sync. |
| **Human hand-off** | Keywords (or a menu option) pause the bot and push the conversation to a live-chat inbox so a human can take over, then resume. |
| **Dashboard** | Leads feed with search, status pipeline and Excel export; conversations view; appointment calendar; usage counters. |
| **Public business page** | Each tenant gets a slug-based public page (`/book/:slug`) for booking without an account. |
| **Accessibility + i18n** | Hebrew-first RTL UI with an accessibility widget; `i18next` wiring for additional locales. |

### For the platform operator

An admin back-office (`/admin`) with a business directory, per-tenant profiles and usage, plan and
subscription management, platform-wide analytics (message volume, lead types, trends, AI ops) and a
lightweight sales CRM with notes.

---

## Architecture

```
                    ┌───────────────────────────────────────────┐
   WhatsApp  ◄─────►│  gateway/   Node + Baileys                 │
   (customer)       │  · one socket per tenant                   │
                    │  · QR streamed, never written to disk      │
                    │  · single writer per session               │
                    └──────────────┬────────────────────────────┘
                                   │  POST /webhook/whatsapp
                                   │  (frozen contract + shared token)
                                   ▼
   Browser          ┌───────────────────────────────────────────┐
   (owner) ◄───────►│  backend/   Python + FastAPI              │
                    │  ┌─────────────────────────────────────┐  │
                    │  │ bot_engine.py — PURE, deterministic  │  │
                    │  │ (no I/O, no LLM, no clock)           │  │
                    │  └─────────────────────────────────────┘  │
                    │  bot_runtime · leads · booking · auth      │
                    └────────┬──────────────────────┬───────────┘
                             │                      │
                    ┌────────▼────────┐    ┌────────▼────────┐
                    │ Postgres        │    │ Redis           │
                    │ row-level       │    │ conversation    │
                    │ security (RLS)  │    │ state, sessions,│
                    │ per tenant      │    │ live-chat cache │
                    └─────────────────┘    └─────────────────┘

   frontend/  React + Vite + Tailwind  ── owner app, admin back-office,
                                          public booking pages
```

**Key design decisions**

1. **The conversation engine is a pure function.** `backend/app/services/bot_engine.py` takes
   `(settings, state, message)` and returns `(replies, next_state)`. No database, no network, no
   LLM, no clock, no module-level mutable state. This makes bot behaviour fully reproducible in
   tests — and removes any prompt-injection or data-exfiltration path from the message runtime,
   because the engine can only ever echo back the current conversation's own inputs.
2. **AI is confined to authoring time.** Gemini is used by the *bot builder* to draft configuration
   and to generate a booking-page welcome message. It is never in the loop when a customer message
   is answered.
3. **Tenant isolation is enforced by the database, not by application code.** The backend connects
   as a restricted `app_role` and sets the tenant with `SET LOCAL`; Postgres RLS policies do the
   rest. A dedicated isolation test suite runs as that real role and proves one business cannot see
   another's rows.
4. **Fail-closed configuration.** The app refuses to boot without its required secrets rather than
   silently degrading. Optional integrations (Google Calendar, object storage) are validated at use.
5. **The gateway↔backend webhook contract is frozen** and mapped in exactly one place on each side
   (`gateway/src/contract.js`, `backend/app/models/webhook.py`).

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12 · FastAPI 0.115 · Uvicorn/Gunicorn · Pydantic v2 · asyncpg |
| WhatsApp | Node.js · Express 4 · [Baileys](https://github.com/WhiskeySockets/Baileys) 6.7 · pino |
| Frontend | React 18 · TypeScript · Vite · Tailwind CSS · React Router 6 · i18next · react-day-picker |
| Database | PostgreSQL 16 (row-level security) |
| Cache / state | Redis 7 |
| AI | Google Gemini via `google-genai` |
| Integrations | Google OAuth · Google Calendar + Meet · S3-compatible object storage (Cloudflare R2) |
| Crypto | Fernet envelope encryption for PII and WhatsApp credentials; HMAC phone fingerprints |
| Infra | Docker Compose · Caddy (auto-HTTPS in production) · GitHub Actions |

---

## Repository layout

```
.
├── backend/            🧠 FastAPI service — the brain
│   ├── app/
│   │   ├── main.py       app factory + lifespan (Postgres & Redis pools)
│   │   ├── api/          HTTP endpoints (health, webhook, auth, dashboard,
│   │   │                 bot builder, booking, whatsapp, admin/)
│   │   ├── services/     business logic (bot engine & runtime, leads/,
│   │   │                 booking/, whatsapp, google_calendar, auth, usage)
│   │   ├── models/       Pydantic request/response schemas
│   │   ├── core/         config, crypto, auth deps, clients, logging
│   │   └── db/           tenant-scoped session handling (the RLS bridge)
│   └── tests/            strict/ · narrated/ · isolation/
│
├── gateway/            💬 Node + Baileys WhatsApp gateway
│   └── src/              index · socket · webhook · routes · contract
│                         · config · logger
│
├── frontend/           🎨 React owner app, admin back-office, public pages
│   └── src/              pages/ · components/ · dashboard/ · botbuilder/
│                         · admin/ · auth/ · lib/ · i18n/
│
├── infra/              🧱 docker-compose.yml + .env.example
├── supabase/           🗄️ SQL migrations (schema, roles, RLS) + seed
├── tests/              🛡️ cross-cutting runners + Postman collection
├── Makefile            one-command developer verbs
└── ENV_SETUP.md        what every environment variable is and how to generate it
```

Each domain folder carries its own `README.md` with a deeper map.

---

## Quick start

**Prerequisites:** Docker (with Compose v2) and `make`. On Windows, run from Git Bash or WSL2.

```bash
# 1. clone
git clone https://github.com/omer-cohenn/whatsapp-bots-SaaS.git
cd whatsapp-bots-SaaS

# 2. configure — copy the template and fill it in (see ENV_SETUP.md)
cp infra/.env.example infra/.env

# 3. bring the whole stack up (build + health-gated startup)
make dev

# 4. create the schema, roles and RLS policies, then seed demo tenants
make migrate
make seed
```

| Service | URL |
|---|---|
| Owner app / frontend | http://127.0.0.1:5173 |
| Backend API | http://127.0.0.1:8000 |
| Health probe | http://127.0.0.1:8000/healthz |
| WhatsApp QR | http://127.0.0.1:3000/qr |

### Make targets

```
make dev         bring the stack up (build + health-gated)
make down        tear it down (keeps the postgres volume)
make logs        follow logs from all services
make ps          per-service health status
make build       (re)build images without starting
make migrate     apply DB migrations — tables, roles, RLS
make seed        seed the demo tenants
make test        unit + integration tests
make lint        lint backend, gateway and frontend
make isolation   run the multi-tenant isolation suite (the CI gate)
```

You can skip `make` entirely — every recipe is a
`docker compose --env-file infra/.env -f infra/docker-compose.yml …` call.

---

## Configuration

All configuration lives in `infra/.env`, which is git-ignored; only the secret-free
`infra/.env.example` template is tracked. **`ENV_SETUP.md` documents every variable**, including
copy-paste generators for the random ones.

Generate secrets:

```bash
# Fernet keys (PII_DATA_KEY, WA_CRED_KEK)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# random tokens / passwords (everything else)
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Required — the app will not boot without these (fail-closed):**

| Variable | Purpose |
|---|---|
| `GATEWAY_API_TOKEN` | Shared secret on every gateway → backend webhook call |
| `POSTGRES_USER` / `POSTGRES_DB` / `POSTGRES_PASSWORD` | Local Postgres superuser |
| `APP_DB_PASSWORD` | Password for `app_role` — the restricted role RLS is enforced through |
| `GATEWAY_DB_PASSWORD` | Password for `gateway_role` — access limited to the credentials table |
| `REDIS_PASSWORD` | Redis auth |
| `PII_DATA_KEY` | Fernet key encrypting lead PII (name, phone, answers) |
| `WA_CRED_KEK` | Fernet key-encryption-key for WhatsApp session credentials |
| `PHONE_HMAC_KEY` | HMAC key for searchable phone fingerprints |

**External services (needed for real AI + login):** `GEMINI_API_KEY`, `GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`. **Optional:** Google Calendar redirect URI, S3/R2 object-storage
credentials for file steps.

> Never commit a real `.env`. If a secret is ever exposed, rotate it at the provider — removing it
> from the working tree does not remove it from git history.

---

## Data model

Postgres, ~24 tables, all tenant-scoped tables carrying a `business_id` guarded by RLS.

| Group | Tables |
|---|---|
| Tenancy & identity | `businesses`, `users`, `business_members`, `business_images`, `business_page` fields |
| Bot | `bot_settings`, `bot_builder_messages` |
| Leads | `leads`, `lead_files`, `flow_events` |
| Booking | `booking_settings`, `services`, `bookings`, `google_credentials` |
| WhatsApp | `whatsapp_connections`, `whatsapp_credentials`, `whatsapp_test_numbers` |
| Billing & admin | `plans`, `subscriptions`, `usage_daily`, `admin_audit`, `platform_snapshots` |
| CRM | `business_crm`, `crm_notes` |

Migrations are plain, numbered SQL files under `supabase/migrations/` (`0000_init.sql` →
`0031_…`), applied in order. Roles, grants and RLS policies are themselves migrations — the security
model is versioned with the schema.

---

## Multi-tenancy and security

- **RLS everywhere.** The backend never connects as a superuser. It opens a connection as `app_role`
  and issues `SET LOCAL` with the current tenant; every policy keys off that. Application bugs
  cannot leak across tenants because the database refuses the rows.
- **Deny-by-default API.** The `/api/*` router is gated by an auth dependency; endpoints opt *in* to
  being public, never out of being private.
- **Encryption at rest.** Lead PII is Fernet-encrypted; WhatsApp session credentials are wrapped
  with a KEK and stored in the database rather than as loose files on disk. Phone numbers get an
  HMAC fingerprint so lookups work without decrypting.
- **Structured logging with no secrets or PII.** JSON logs, scrubbed.
- **Isolation test suite as a CI gate.** `backend/tests/isolation/` runs as the real restricted role
  and asserts business A cannot read business B. A deliberate-regression demo (`make demo-break`)
  proves the gate actually catches a break.
- **The runtime bot never calls an LLM**, so a customer message cannot steer the model or reach data
  outside its own conversation.

---

## API surface

Base URL `http://127.0.0.1:8000`. Authenticated routes use an opaque session cookie backed by Redis.

**Public / infrastructure**

```
GET    /healthz                          liveness + Postgres & Redis probes
POST   /webhook/whatsapp                 inbound message from the gateway (token-guarded)
GET    /auth/google  ·  /auth/callback   Google OAuth sign-in
POST   /auth/logout
```

**Owner app** (`/api/*`, authenticated)

```
GET    /api/me                           current user + business
GET    /api/dashboard                    dashboard aggregates
GET    /api/conversations                live-chat inbox
GET    /api/leads                        leads feed (search, filter, pagination)
GET    /api/leads/export                 Excel export, one sheet per flow
PATCH  /api/leads/{id}/status            move a lead through the pipeline
POST   /api/leads/{id}/seen · /seen-all  read markers
DELETE /api/leads/{id}
GET    /api/leads/files/{file_id}        download a customer-uploaded file

POST   /api/bot/ai/chat · GET /api/bot/ai/history      AI bot builder
PUT    /api/bot/publish                                publish the flow
POST   /api/bot/tryme · /api/bot/sim                   test the bot in-browser

GET    /api/whatsapp/status · /qr        connection state and QR
POST   /api/whatsapp/link · /disconnect
GET/PUT /api/whatsapp/test-numbers       up to 5 encrypted test numbers

GET/PUT /api/booking/settings            hours, buffers, services
GET/PUT /api/booking/page                public page content
POST   /api/booking/logo · PATCH /api/booking/images/{id}
POST   /api/booking/welcome/generate     AI-drafted welcome copy
GET    /api/bookings · PATCH /api/bookings/{id}
GET    /api/bookings/alerts
GET/POST /api/services · PATCH /api/services/{id}
GET    /api/google/connect · /callback   connect the owner's Google Calendar
```

**Public booking** (no login)

```
GET    /{slug}/page · /services · /availability · /slots
POST   /{slug}/cancel/{token} · /{slug}/reschedule/{token}
```

**Admin back-office** (`/api/admin/*`, admin-gated)

```
GET    /overview · /businesses · /businesses/{id} · /businesses/{id}/usage
DELETE /businesses/{id}
GET    /plans · /sessions · /crm
GET    /analytics/messages · /trends · /leads-by-type · /by-plan · /ai-ops
```

A Postman collection lives in `tests/postman/`.

---

## Frontend routes

| Route | Page |
|---|---|
| `/` | Marketing landing page |
| `/login` | Google sign-in |
| `/bot-builder` | Visual + AI bot builder |
| `/try-me` | Sandbox chat against your own flow |
| `/whatsapp` | Connect / QR / status |
| `/leads` | Leads feed, search, export |
| `/conversations` | Live chat and hand-off |
| `/appointments` | Booking calendar |
| `/settings`, `/settings/calendar` | Business + Google Calendar settings |
| `/book/:slug`, `/book/:slug/manage/:token` | Public booking and self-service manage |
| `/admin`, `/admin/businesses`, `/admin/businesses/:id`, `/admin/billing`, `/admin/crm` | Back-office |
| `/accessibility`, `/terms`, `/privacy` | Accessibility statement and legal pages |

---

## Testing

Three deliberately different suites under `backend/tests/`:

| Suite | Purpose |
|---|---|
| `strict/` | Plain pass/fail pytest — the hard contract per milestone. This is what CI runs. |
| `narrated/` | Explained tests that print *what was tried, why it matters, what happened*. Written to be readable by a non-engineer reviewing behaviour. |
| `isolation/` | The tenant wall. Runs as the real restricted `app_role` and proves cross-tenant reads fail. |

```bash
make test        # unit + integration
make isolation   # the multi-tenant CI gate
make lint        # backend + gateway + frontend
```

Because the conversation engine is pure, the majority of bot behaviour is covered by fast tests with
no containers, no network and no mocks.

---

## Deployment

The stack is deployed as the same Docker Compose bundle on a single Linux host, with **Caddy** in
front as the only public listener, terminating TLS and issuing certificates automatically. Backend,
gateway and frontend are internal services behind it; Postgres and Redis are not exposed.

Rough shape of a deploy:

1. Provision a small Ubuntu host (1 GB RAM is enough with swap configured).
2. Point a domain at it and set `PUBLIC_DOMAIN` plus the Google OAuth redirect URIs.
3. Copy `infra/.env` (never from git — generate fresh production secrets).
4. `make build && make dev`, then `make migrate`.
5. Caddy obtains certificates on first request.

GitHub Actions workflows live in `.github/workflows/`.

---

## Development conventions

- **Milestone-driven.** Work lands as numbered milestones (M0 → M20+), each with an architecture
  decision record and a matching strict test suite. Decisions are written down before code.
- **Frozen contracts.** The gateway↔backend webhook shape and the bot-configuration shape are
  defined once and validated on both sides; changing one without the other is a test failure.
- **Purity where it counts.** Anything that decides bot behaviour stays free of I/O so it can be
  tested exhaustively; side effects live in thin runtime wrappers.
- **Duplicated logic is flagged, not tolerated.** Where a rule must exist on both client and server
  (for example lead search matching, so that an export matches the on-screen list), both copies are
  documented and must change in the same commit.
- **Hebrew-first product, English-first code.** UI copy and product docs are Hebrew/RTL; identifiers,
  commit messages and code comments are English.

---

## License

No license file is currently present — all rights reserved by default. Add a `LICENSE` file if you
intend to allow reuse.
