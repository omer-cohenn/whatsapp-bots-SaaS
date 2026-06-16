# Roadmap — INFRA (local dev) slice

> **Domain:** developer setup, local run, secrets handling, CI, and the multi-tenant
> **isolation test harness**. The "make it runnable, repeatable, and safe to develop on" layer.
> **Author:** INFRA (local dev) agent. **Date:** 2026-06-16.
> **Scope note:** this is *local dev + CI*. Cloud provisioning (ALB/TLS/DNS, ElastiCache,
> Secrets Manager/KMS vendor, ECS/Fargate, CloudFront) belongs to the **`devops_aws`** agent —
> cross-referenced where the local choice must line up with prod, never built here.
>
> Grounded in: `spec/architecture.md` (the 7 parts), `spec/data-model.md` (9 tables + Redis,
> the isolation rules), `decisions/0001–0006`, `bugs.md` (B2/B13/B14 + the infra cluster
> B11/B12/B16/B24/B25), `security-issues.md` (C1/M3 secrets, the crown-jewel KEK rule).

---

## What "the setup" must become (the target, one screen)

The old system (`last_bo` + `qr_wa_scanner`) ran from machine-specific `.bat`/`.ps1` scripts that
were **slow, fragile, and non-portable** — the three bugs this slice exists to kill:

- **B2** — `run.bat:7` runs `pip install -r requirements.txt` (heavy, **unpinned** deps) on *every*
  launch; first run also downloads an embedding model. Slowest, flakiest step in the system.
- **B13** — `setup.bat:11,17` (and `run_ngrok.ps1`, `start.bat`) use **blind `timeout`/`Start-Sleep`**
  waits (7s + 10s) instead of health checks → races when a service is slower than the fixed sleep.
- **B14** — hardcoded `C:\Users\B08F~1\Desktop\last_bo` paths + dev-mode servers (`uvicorn --reload`,
  Vite dev) baked into the scripts → breaks on any other host, not a production process model (B25).

**Replacement:** one `docker-compose up` brings the whole stack up locally — **FastAPI backend +
Node Baileys gateway + Redis + Supabase (local) + the React frontend** — with **health-gated
startup ordering** (no blind sleeps), **pinned/locked dependencies baked into images** (no per-run
install), **portable relative paths** (no user-specific paths), **secrets loaded from a manager with
fail-on-missing and zero `change-me` defaults**, and a **CI pipeline** that lints + tests + runs the
**multi-tenant isolation harness** on every push. Local mirrors prod's shape so "works on my machine"
means "works in the container."

**The 6 local services** (from `architecture.md` "The 7 parts"; the secrets manager is the 7th and is
config, not a long-running container):

| Service | Image / base | Port (local) | Role | Health signal |
|---|---|---|---|---|
| `backend` | python:3.12-slim + locked deps | 8000 | FastAPI brain/API/webhook/flows | `GET /healthz` (200 + deps OK) |
| `gateway` | node:20-slim + locked deps | 3000 | Baileys, one session/business | `GET /healthz` (no QR/secret) |
| `frontend` | node build → static (nginx/vite preview) | 5173 | React+Tailwind owner app | static 200 |
| `redis` | redis:7-alpine | 6379 (internal) | live-chat cache (last ~10 msgs + status) | `redis-cli PING` |
| `supabase` | Supabase CLI local stack | 54321/54322 | Postgres + RLS (+ pgvector reserved) | `pg_isready` |
| *secrets* | (not a container) | — | env injected from a manager / `.env.local` git-ignored | startup assertion |

---

## Phase 0 — Foundations (the dev platform; everything depends on it)

> Goal: a fresh clone runs **`make dev`** (→ `docker-compose up`) and the whole stack is healthy,
> reproducibly, on any host — and CI is green on day one. This is the slice that unblocks every other
> agent's Phase 1 work, so it goes first.

### P0-1 — Monorepo structure (backend + frontend + gateway)
- **What:** one repo, three app dirs + shared infra, matching the 7-parts architecture:
  ```
  bizz_up/
    backend/        FastAPI app, pyproject.toml, Dockerfile
    gateway/        Node Baileys gateway, package.json, Dockerfile
    frontend/       React+Tailwind, package.json, Dockerfile (build→static)
    infra/
      docker-compose.yml        # backend+gateway+frontend+redis+supabase
      docker-compose.test.yml   # CI overlay: ephemeral DB, seeded tenants
      .env.example              # NAMES only, no values, no change-me defaults
    supabase/       migrations/ (RLS policies live here), seed/
    tests/isolation/            # the multi-tenant isolation harness (P0-7)
    .github/workflows/ci.yml
    Makefile        # dev / test / lint / isolation / down
    README.md       # one-command setup
  ```
- **Why:** the old layout was two unrelated folders on a desktop with no shared run story (infra map
  §"two unreconciled paths"). A single tree with one compose file is what makes B14 (machine-specific
  scripts) go away and lets gateway↔backend finally be wired and tested together (decision 0001).
- **Depends on:** the locked decisions (0001–0006) — done.
- **Effort:** S
- **Risk:** bikeshedding structure; mitigate by freezing this layout in Phase 0 and not relitigating.

### P0-2 — docker-compose local stack with **health-gated** startup (kills B13)
- **What:** `infra/docker-compose.yml` defining the 6 services above. Replace **every blind sleep**
  with real readiness: each service gets a `healthcheck`; dependents use
  `depends_on: { <svc>: { condition: service_healthy } }`. backend waits on `supabase` + `redis`
  healthy; gateway waits on `backend` healthy; frontend waits on `backend`. Add **`GET /healthz`** to
  both backend and gateway (cheap, checks its own deps, returns **no secrets / no QR**). One
  `make dev` brings it all up; `make down` tears it down.
- **Why:** directly retires **B13** — the 17s of `timeout /t` racing — with deterministic ordering, and
  retires the ngrok-in-startup pattern (B15) for local (gateway holds its own session; no public
  tunnel needed in dev). Health endpoints double as the probes `devops_aws` will reuse for ECS/ALB.
- **Depends on:** P0-1.
- **Effort:** M
- **Risk:** the **Supabase local stack is heavy** (several containers) — first pull is slow and can
  strain a solo dev laptop; mitigate by documenting `supabase start` via the CLI as the supported path
  and keeping its containers out of the app compose where the CLI manages them better. *needs
  verification: confirm Supabase-CLI-managed Postgres vs. a plain `postgres:16` + migrations is the
  smoother local DB for the isolation tests (a plain Postgres image is lighter for CI).*

### P0-3 — **Pinned, baked-in dependencies** — no per-run install (kills B2)
- **What:** lockfiles everywhere and **install at image-build time, never at run time**:
  - backend: `pyproject.toml` + a lock (uv/poetry/pip-tools `requirements.lock`), pinned exact
    versions; deps `RUN`-installed in the Dockerfile layer, cached. **Drop the dead heavy deps** the
    MVP doesn't need yet — `sentence-transformers`, `crawl4ai`, `langchain-text-splitters` are RAG
    (Phase 3); the embedding-model download (infra map §5) goes with them. Migrate the Gemini SDK off
    deprecated `google.generativeai` → `google-genai` (**B16**).
  - gateway: commit `package-lock.json`; `npm ci` in the Dockerfile (not `npm install`).
  - frontend: commit `package-lock.json`; `npm ci` + **`vite build`** to static (not Vite dev) so the
    container matches prod (**B25**).
- **Why:** **B2** is named the slowest, most fragile step in the whole system. Pinning + baking makes
  builds reproducible and startup near-instant; trimming RAG-only deps shrinks the image and removes
  the cold-start model download from the MVP entirely.
- **Depends on:** P0-1.
- **Effort:** M
- **Risk:** pinning surfaces real version conflicts that the unpinned setup hid (esp. around the
  Gemini SDK swap, B16); budget time to resolve. Keep `pyproject` ranges + a separate lock so security
  bumps stay easy.

### P0-4 — **Secrets out of `.env` into a manager**, fail-on-missing, no `change-me` defaults (C1/M3)
- **What:** a single **config-loader module** (backend) + the gateway equivalent that reads **all**
  secrets from the environment, injected from a manager — **not** a committed `.env`. Local: a
  git-ignored `.env.local` (developer-held, never committed) loaded by compose; an
  **`.env.example` listing names only** (no values). Prod: AWS Secrets Manager / SSM (the
  `devops_aws` agent wires the actual source; the loader interface is identical). **Three hard rules,
  enforced in code + CI:**
  1. **Fail-closed on startup** — if any required secret is missing/empty, the process **exits
     non-zero with a clear message** (lists the missing names). No silent boot.
  2. **No `change-me` / known-constant defaults** — kills `SESSION_SECRET="change-me-in-env"` (**M3**),
     `WEBHOOK_VERIFY_TOKEN=secret` (L2), gateway `my-secret-token` (C6). A default that is a real
     secret value is banned; the only allowed default is *absent → crash*.
  3. **Secrets never logged / never echoed** — startup may print *names present/absent*, never values
     (retires gateway token-logging L1); a CI grep test (P1-CI) fails the build if a known secret
     appears in logs or any API response.
- **Required-secret set** (names from `architecture.md`/`data-model.md`): `DATABASE_URL` (non-service
  role), `REDIS_URL` + Redis auth, `SESSION_SECRET`, `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI`,
  `GEMINI_API_KEY`, **`PII_DATA_KEY`** (lead PII), **`WA_CRED_KEK`** (crown-jewel Baileys KEK — KMS in
  prod, separate from PII key), **`PHONE_HMAC_KEY`** (keyed HMAC for `customer_phone_hash` lookups),
  and the gateway↔backend shared auth token.
- **Why:** **C1** ("all live secrets in plaintext `.env`") is the system's #1 security finding; **M3**
  (known-constant fallback) defeats auth on its own. Fail-on-missing + no-defaults is the cheapest,
  highest-leverage guardrail and it has to exist from the first commit so no agent ever adds a
  `change-me`.
- **Depends on:** P0-1. **Coordinates with:** `devops_aws` (manager vendor + KMS-vs-app-held KEK —
  open question #1 in `data-model.md`).
- **Effort:** M
- **Risk:** the **crown-jewel KEK** (`WA_CRED_KEK`, decrypts every business's WhatsApp session) must be
  *separate* from the ordinary PII key and, in prod, live in KMS — getting the local stand-in right so
  the prod swap is trivial needs care (`data-model.md` "How the WhatsApp key is protected"). Note: the
  current `.env` values are **compromised** and must be rotated, not reused, even locally.

### P0-5 — Portable entrypoints + `Makefile` (kills B14, B24, B25 for dev)
- **What:** delete the `B08F~1`-path scripts; replace with container entrypoints + a `Makefile`
  (`make dev|test|lint|isolation|migrate|seed|down`). **Relative paths / env-driven URLs only** — no
  hardcoded `localhost:3000` in the frontend (env var), no machine paths. Entry commands use the
  **production process model**: `uvicorn`/`gunicorn` **without `--reload`** in the image (a dev-only
  reload override stays in compose), `vite build` static for the frontend (**B25**). **Do not port the
  dead startup steps:** no FAISS-index cleanup (**B24** — live path is pgvector), no ngrok in dev.
- **Why:** **B14** makes the old setup unrunnable anywhere but Omer's laptop; a Makefile + entrypoints
  is the portable, documented "one command" replacement and gives every later agent the same verbs.
- **Depends on:** P0-1, P0-2.
- **Effort:** S
- **Risk:** Windows-host friction (the dev is on Windows 11) with Docker Desktop/WSL2 line-endings and
  volume perf; mitigate with `.gitattributes` (LF), a documented WSL2 path, and named volumes over
  bind mounts for `node_modules`/venv.

### P0-6 — DB **migrations + RLS bootstrap** + least-privilege roles (local mirror of the security model)
- **What:** versioned SQL migrations under `supabase/migrations/` that create the **9 tables**
  (`data-model.md`) **with their RLS policies and the two DB roles in the same migration** — so RLS is
  *never* an afterthought. Specifically the local DB must reproduce the production isolation model:
  - **RLS on every tenant table** (read `USING` + write `WITH CHECK` on `business_id`), reading
    `current_business_id()` from the per-request `SET LOCAL app.business_id` (decision 0005).
  - **A non-service `dashboard` role** the backend connects as (so RLS is *live* — the old service-key
    bypass was the core bug) and a separate **`gateway` role** that is the **only** grantee on
    `whatsapp_credentials`; the dashboard role has **no grant, not even SELECT**, on that crown-jewel
    table (`data-model.md` "isolation by DB role").
  - A `make migrate` / `make seed` that applies migrations and seeds two demo tenants.
- **Why:** the hand-wired RLS is, per decision 0005, "the old system's #1 failure point" and **must be
  covered by tests** — the harness (P0-7) can only test isolation if the local DB *has* the policies
  and roles. Putting RLS in the migration (not a manual step) is what guarantees CI tests the real
  thing. This is INFRA's job only insofar as **making the local/CI DB faithfully carry the security
  model**; the policy *content* is co-owned with the data/security agents.
- **Depends on:** P0-1; the schema in `data-model.md` (final).
- **Effort:** M
- **Risk:** local RLS silently not enforced (e.g. CI connects as a superuser/owner that bypasses RLS)
  → tests pass but prod leaks. Mitigate: the harness explicitly connects as the **non-service
  `dashboard` role** and includes a canary test that confirms RLS is *on*.

### P0-7 — **Multi-tenant ISOLATION test harness** (the flagship deliverable)
- **What:** a dedicated `tests/isolation/` suite — run by `make isolation` and **gating CI** — that
  proves one business can **never** see/modify/leak another's data, across **all three isolation
  layers** the architecture relies on:
  1. **DB / RLS layer:** seed tenant A and tenant B; connect as the **non-service dashboard role**
     with `app.business_id = A`; assert every tenant table returns **only A's rows** and that
     `INSERT/UPDATE` with B's `business_id` is **rejected by `WITH CHECK`** (covers C2/C3). Include a
     **forgotten-`WHERE` canary**: run a query *without* an explicit `business_id` filter and assert
     RLS still returns zero of B's rows (the safety-net the spec promises).
  2. **App / API layer:** with A's session, hit the `/api/*` routes (leads, conversations, bot config,
     bookings later) and assert **no anonymous fallback tenant** (the old leak) and that a
     **client-supplied `business_id` is never trusted** — passing B's id as a param must 404/403, not
     leak (covers C2/C4; the `PATCH /api/bookings/{id}` IDOR pattern). Assert unauthenticated calls are
     **rejected**, not silently scoped to a shared tenant.
  3. **Redis cache layer (no RLS — app-enforced):** assert cache keys are `chat:{business_id}:…`,
     that a read/write under A **cannot** touch B's key, and that key access **re-checks** the caller's
     business (`data-model.md` "Cache security"). Assert TTL/auto-expiry behaves (the 60-min close).
  - **Crown-jewel guard:** an assertion that the **dashboard role cannot read `whatsapp_credentials`
    at all**, and a **secret/PII-never-in-output** test — grep API responses + logs for the Baileys
    `auth_state`, decrypted PII, or any known secret, **failing the build** if found (`data-model.md`
    "never exposed … a CI test fails the build if it ever appears in a response or log").
  - **Fixtures:** factory helpers that create tenants/users/leads, tagged `is_test=true` so they never
    pollute real stats (the `is_test` flag exists for exactly this).
- **Why:** isolation is the product's core promise and the **explicit testing mandate** of decisions
  0002, 0005, 0006 and the entire `security-issues.md` C2–C6 cluster. Because RLS is hand-wired, an
  automated harness is the only thing that keeps a future refactor from silently re-opening a
  cross-tenant leak. This is the single highest-value thing INFRA ships.
- **Depends on:** P0-6 (RLS + roles in the local DB), P0-4 (the HMAC/PII keys so encrypted lookups
  work), P0-2 (Redis up). Co-owned with the **data** and **security** agents for assertion content.
- **Effort:** L
- **Risk:** **false confidence** — a harness that connects with too-high privileges, or seeds with the
  app's own helpers (which already inject `business_id`), proves nothing. Must test at the **role/RLS
  boundary**, include the forgotten-`WHERE` canary, and assert RLS is actually *on*. This risk is the
  top risk of the whole slice.

### P0-8 — **CI pipeline** (lint + tests + isolation gate)
- **What:** `.github/workflows/ci.yml` running on every push/PR: (a) **lint/format** — `ruff` +
  `black`/format-check (Python), `eslint` + `prettier` (gateway + frontend), type checks where cheap;
  (b) **unit/integration tests** for all three apps; (c) **the isolation harness (P0-7)** against an
  **ephemeral Postgres + Redis** spun up via `docker-compose.test.yml` with migrations applied; (d)
  the **secret-leak grep** gate (P0-4 rule 3); (e) build all three Docker images to prove they still
  build. **The isolation suite and the secret-leak check are required, blocking checks** — a red
  isolation test cannot merge.
- **Why:** solo + Claude pace means CI *is* the second pair of eyes; making isolation + secret-leak
  **blocking** is what operationalizes "RLS must be covered by tests" (0005) so it can't rot.
- **Depends on:** P0-3 (lockfiles → reproducible CI installs), P0-6, P0-7.
- **Effort:** M
- **Risk:** CI flakiness/slowness from spinning the DB/Redis each run (esp. if the heavy Supabase
  stack is used in CI) → people start skipping it. Mitigate: in CI use a **lightweight `postgres:16` +
  `redis:7` service container + migrations**, not the full Supabase stack; cache lock-installed deps;
  keep the isolation suite fast.

---

## Phase 1 — MVP (infra support for leads + handoff + bot builder + try-me)

> Goal: the Phase-0 platform stays honest as the MVP features land, and the *one real end-to-end
> inbound test* on the Baileys gateway (the unverified receive path, decision 0001) gets a home.

### P1-1 — Gateway↔backend **wired & health-gated** in compose (with the end-to-end receive test)
- **What:** make the compose stack the place where the **missing gateway→backend link** (B1/B3) is
  exercised: gateway forwards inbound to the backend webhook over the internal network; a scripted
  **end-to-end smoke** (`make e2e` / a CI job behind a flag) proves a message in → backend parses it →
  reply path out, against a *test/staging* WhatsApp session. Persist the registered webhook URL via
  config (not RAM, B3) and seed it on boot. **One real receive test** is the decision-0001 priority.
- **Why:** decision 0001 calls the inbound path **unverified end-to-end**; the MVP can't claim "leads
  on WhatsApp work" until this is green. Compose is where the two halves finally meet.
- **Depends on:** P0-2, P0-5; the gateway rebuild (other agent's domain) providing `/healthz` + the
  per-business session mapping (`whatsapp_connections.gateway_account_id`).
- **Effort:** M
- **Risk:** Baileys is **unofficial with ban risk** (decision 0001) — the e2e test must use a
  **throwaway/test number** and sane rate limits, never a real business's session, or it risks a ban.
  *needs verification: a safe test-number strategy with Omer.*

### P1-2 — Local **Redis live-chat** wiring + the abandoned-lead sweep, with isolation coverage
- **What:** stand up Redis in compose (done in P0-2) as the **live-chat cache** (`chat:{business_id}:…`,
  last ~10 msgs + status, ~60-min sliding TTL) and provide the **periodic "abandoned" sweep** runner
  (in_progress leads idle > 60 min → `abandoned` + `flow_events`) as a backend background task that is
  **safe to run in the container** and idempotent. Extend P0-7 to cover the cache-isolation + TTL
  cases against real Redis.
- **Why:** decision 0006 makes Redis **required in dev and prod**; the sweep is what powers the
  abandoned-lead follow-up list (the MVP's funnel value). Both must run inside the local stack so
  they're tested before AWS.
- **Depends on:** P0-2, P0-7; the cache/key design in `data-model.md`.
- **Effort:** S
- **Risk:** the sweep + TTL expiry can **double-fire** across multiple backend workers/instances
  (race) → duplicate `flow_events`; make it idempotent / single-flight now so it survives horizontal
  scaling later (the very reason Redis was chosen over process RAM).

### P1-3 — Externalize **OAuth CSRF state** + Gemini SDK migration (close the infra-bug tail)
- **What:** move the in-RAM OAuth `_pending_states` (B12) into Redis with a TTL (so login survives
  restart and works multi-instance), and confirm the **`google-genai`** SDK migration from P0-3 is the
  one used by the bot-builder + reply paths (B16). These are the remaining infra-flavored bugs that
  block clean multi-instance running.
- **Why:** B11 (volatile chat state) is resolved by Redis; **B12** (volatile OAuth state) is the
  twin and must move too or login degrades under >1 worker. B16 removes the EOL-SDK FutureWarning.
- **Depends on:** P0-2 (Redis), P0-3 (SDK pin).
- **Effort:** S
- **Risk:** low; OAuth-state TTL must be tuned (too short → login fails mid-flow).

### P1-4 — **Compliance touch-points (infra side):** static legal pages, cookie/session, data-deletion hook
- **What (the infra share of the launch-compliance requirement):**
  - **Terms + Privacy Policy must be servable** — wire routes/static hosting + a build slot for
    `/terms` and `/privacy` so the legal pages (content owned by product/legal) ship with the
    frontend; ensure the **accessibility (נגישות/WCAG)** build doesn't break them (lint/build config
    only — the a11y *implementation* is the frontend agent's).
  - **Session/cookie hygiene** — secure/HttpOnly/SameSite session cookies driven by the
    fail-on-missing `SESSION_SECRET` (no `change-me`), so the cookie story is launch-grade.
  - **Israeli-privacy-law data handling hooks** — make sure the schema/infra supports a **per-business
    + per-data-subject delete/export path** (the `ON DELETE CASCADE` chains in `data-model.md` already
    line up; add a documented `make`/script hook and a test that a tenant delete removes leads,
    funnel, config, creds, and **flushes that tenant's Redis keys**).
- **Why:** launch compliance is **required** (accessibility, Terms, Privacy, Israeli data protection).
  INFRA owns the *plumbing* — that the pages are servable, cookies are safe, and "delete my data"
  actually clears every store (incl. the Redis cache that has no RLS). The legal/a11y *content* is not
  ours; the *mechanism* is.
- **Depends on:** P0-5 (frontend build), P0-6 (cascade schema), P0-2 (Redis to flush).
- **Effort:** S–M
- **Risk:** a tenant/data deletion that clears Postgres but **forgets Redis** leaves PII in the cache —
  the deletion test must assert the cache is flushed too (Redis has no RLS, so nothing else catches it).

---

## Phase 2+ — post-MVP (back-office, booking, RAG, scale)

> Infra support as features grow. The heavy cloud lift (provisioning, autoscale, the secret-manager
> vendor, KMS) is **`devops_aws`'s** roadmap; below is the *local-dev + CI + isolation* share.

### P2-1 — **Back-office:** the admin/impersonate path in local dev + isolation harness (the infra share)
- **What:** the full back-office (manage businesses & users, billing **VIEW**, support + **impersonate**,
  platform metrics) needs an infra spine even though the *features* are other agents' work:
  - a **third DB role / a `platform_admin` concept** distinct from the tenant `dashboard` role, added
    to migrations (P0-6) with its own RLS posture (admin can cross tenants **by design**, audited).
  - **extend the isolation harness (P0-7)** with back-office cases: a normal tenant **cannot** reach
    `/admin/*` or impersonate; an admin's **impersonation is scoped + audited** (sets
    `app.business_id` to the impersonated tenant, logged), and impersonation **cannot** silently widen
    to other tenants. This is the modern, *authenticated, role-checked* replacement for the old
    **unauthenticated, globally destructive `/admin/*`** endpoints (security C3) — so the harness must
    prove the old C3 hole stays closed.
  - **platform-metrics** queries run as the admin role over a tenant-aware view, tested for not
    leaking per-tenant PII into aggregate metrics.
- **Why:** the back-office is explicitly **FULL** scope post-MVP and impersonation is the single most
  dangerous capability in the product (it deliberately crosses tenants). It *must* land with isolation
  tests from day one, or it re-creates C3. INFRA owns the role/RLS plumbing + the test coverage.
- **Depends on:** P0-6, P0-7; the back-office feature agents.
- **Effort:** M
- **Risk:** impersonation is a **deliberate tenant-isolation bypass** — a bug here is a cross-tenant
  breach. The harness must treat admin/impersonate as a first-class isolation surface, not an
  exception to it.
- **Billing-engine note:** per Omer, the billing **engine is DEFERRED** — do **not** provision
  payment infra now. INFRA only **reserves a hook**: a place in compose/config + a `billing` table/role
  slot left unwired, and the isolation harness is structured so billing tables (when added) inherit the
  same `business_id`+RLS treatment by default. Invoicing/VAT (Israeli compliance) rides with billing
  later — not built here.

### P2-2 — **Booking (Phase 2):** local infra + isolation for the bookings table
- **What:** when booking lands (fixing the "chat flow doesn't actually book" bug B7), add the
  `bookings` table to migrations **with RLS + `business_id`** and **extend the isolation harness** to
  cover it — explicitly the **`PATCH /api/bookings/{id}` cross-tenant (IDOR)** case from security C4
  (assert a tenant can't modify another's booking) and the **public `/book/{slug}`** write path
  (assert `slug`→`business_id` is a *provisioned* business before accepting writes, security M4).
- **Why:** booking introduces a **public, unauthenticated write path** and the exact IDOR (C4) the
  harness exists to prevent; it must be wired into CI isolation the moment the table appears.
- **Depends on:** P0-6, P0-7; the booking feature agent.
- **Effort:** S (infra share only)
- **Risk:** the public booking write path is an easy place to re-introduce a cross-tenant or
  unprovisioned-`slug` write (M4) — keep it under the harness.

### P2-3 — **RAG (Phase 3):** re-introduce the heavy deps behind a build flag + pgvector locally
- **What:** RAG returns the deps trimmed in P0-3 (`sentence-transformers`/embeddings, an extractor
  stack) — re-add them **isolated** (a separate `backend-rag` image layer / optional compose profile)
  so they **don't slow the core MVP build**, enable **pgvector** in the local Supabase, and add
  `brain_chunks`-style tables to migrations **with `business_id` + RLS** (RAG content is per-tenant).
  **Do not** resurrect the dead `rag_data/`/FAISS path (B6/B24); the live path is pgvector + Storage.
- **Why:** RAG is Phase 3 and its dependency weight is precisely the **B2** problem — keep it
  quarantined so the MVP image stays lean; its per-tenant chunks need the same isolation guarantees.
- **Depends on:** P0-3, P0-6; the RAG feature agent.
- **Effort:** M
- **Risk:** the embedding-model download + heavy ML deps re-bloat build/CI time and can re-create
  the cold-start cost; keep them behind a profile and out of the default `make dev`/CI path.

### P2-4 — **Hand-off to `devops_aws`:** local-mirrors-prod parity checklist
- **What:** a documented parity contract so the cloud migration is mechanical, not a rewrite:
  the same `/healthz` probes (→ ALB/ECS health checks), the same config-loader interface (local
  `.env.local` → Secrets Manager/SSM, **KEK → KMS**), the same migrations (local Supabase →
  managed Postgres), the same Redis interface (local container → ElastiCache), the same
  `vite build` static (→ CloudFront/S3), and the **isolation harness runnable against a staging
  environment**. Flag the **biggest cloud blocker** for them: Baileys creds are **stateful
  single-socket sessions** that resist horizontal scaling and need durable, single-writer storage
  (infra map §"Biggest blocker").
- **Why:** Phase 0 deliberately shaped local to mirror prod; this captures that contract so
  `devops_aws` can provision against a known target and re-run the isolation harness in staging.
- **Depends on:** all of Phase 0/1; **owned jointly with `devops_aws`**.
- **Effort:** S (the doc/contract; the provisioning is their roadmap)
- **Risk:** drift — if local and prod diverge, the isolation guarantees proven in CI don't hold in
  prod. The parity checklist + running the harness in staging is the guard.

---

## RETURN — tight summary

**Phases**
- **Phase 0 (Foundations):** the dev platform — monorepo + one-command **docker-compose** stack
  (backend/gateway/frontend/Redis/Supabase) with **health-gated startup** (kills B13), **pinned
  baked-in deps** (kills B2), **portable entrypoints/Makefile** (kills B14/B24/B25), **secrets in a
  manager with fail-on-missing + no `change-me`** (C1/M3), **RLS + least-privilege roles in
  migrations**, the **multi-tenant isolation harness**, and **CI** that gates on it.
- **Phase 1 (MVP):** keep the platform honest as leads+handoff+bot-builder+try-me land — wire & smoke
  the **gateway↔backend receive path** (decision 0001), Redis live-chat + abandoned-sweep, move OAuth
  state off RAM (B12) + finish the `google-genai` swap (B16), and the **infra share of launch
  compliance** (servable Terms/Privacy, safe session cookies, a data-deletion hook that also flushes
  Redis).
- **Phase 2+ (post-MVP):** infra share of **back-office** (admin/impersonate role + isolation tests —
  the safe replacement for the old C3 hole; billing engine **deferred**, only a hook reserved),
  **booking** (bookings table + RLS + the C4 IDOR test), **RAG** (heavy deps quarantined behind a
  profile + pgvector), and the **parity hand-off to `devops_aws`**.

**The 5–8 biggest tasks**
1. **Multi-tenant ISOLATION harness (P0-7, L)** — proves DB/RLS + API + Redis isolation, the
   crown-jewel `whatsapp_credentials` no-read guard, and the secret/PII-never-in-output check;
   blocking in CI. The flagship deliverable.
2. **docker-compose local stack with health-gated startup (P0-2, M)** — one command, deterministic
   ordering, `/healthz` on backend+gateway; retires the blind-sleep B13.
3. **Pinned, baked-in dependencies (P0-3, M)** — lockfiles + install-at-build, drop RAG-only heavy
   deps, migrate off the EOL Gemini SDK; retires the slow per-run-install B2.
4. **Secrets manager + fail-on-missing + no `change-me` (P0-4, M)** — config-loader that crashes on a
   missing secret and bans known-constant defaults; retires C1/M3/L2 and the gateway default token.
5. **DB migrations + RLS bootstrap + least-privilege roles (P0-6, M)** — local DB faithfully carries
   the production isolation model (non-service `dashboard` role, gateway-only crown-jewel grant) so the
   harness tests the real thing.
6. **CI pipeline (P0-8, M)** — lint + tests + the isolation harness + secret-leak grep, all blocking,
   on a lightweight ephemeral Postgres+Redis.
7. **Gateway↔backend wired + end-to-end receive smoke (P1-1, M)** — the missing link from decision
   0001, finally exercised in the local stack (on a throwaway number).
8. **Back-office admin/impersonate role + isolation coverage (P2-1, M)** — the audited, role-checked
   replacement for the old unauthenticated `/admin/*` (C3), proven by the harness.

**Top risk**
**False confidence in the isolation harness.** Tenant isolation is hand-wired (decision 0005's named
#1 failure point), so the harness in P0-7 is the *only* thing standing between a refactor and a silent
cross-tenant leak. If it connects with too-high DB privileges, seeds via the app's own
`business_id`-injecting helpers, or never asserts RLS is actually *on*, it will pass while prod leaks —
exactly the C2/C3/C4 class of bug it exists to prevent. Mitigation: test strictly at the
**non-service-role / RLS boundary**, include a **forgotten-`WHERE` canary** and an **RLS-is-enabled
canary**, assert the **dashboard role cannot read `whatsapp_credentials`**, grep responses+logs for
secrets/PII, and make the whole suite a **blocking CI gate** that every future feature (booking, RAG,
back-office, **impersonation**) must extend before it merges.
