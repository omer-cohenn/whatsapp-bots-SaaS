# Roadmap — BACKEND (Python / FastAPI / LangGraph)

> My domain's slice of the production roadmap for the **Bizz_up rebuild**.
> Author: BACKEND agent. Date: 2026-06-16. Grounded in `00_overview.md`, `spec/architecture.md`,
> `spec/data-model.md`, `spec/database-schema-security-review.md`, decisions 0001–0006, `bugs.md`,
> `security-issues.md`, and the `system-map/*` scanner reports.
>
> **Scope I own:** the FastAPI app + module structure; the conversation engine (LangGraph) for
> lead collection + human handoff running on the **Redis live-chat cache**; the lead lifecycle
> (create at questionnaire start → `new`/`abandoned`) + the 60-min abandoned sweep; the AI-assist
> endpoints (Gemini proxy for the bot builder); the inbound **webhook receiver** + outbound
> **sender** wired to the Baileys gateway; multi-tenant request handling (verify ownership + set
> the `business_id` session var for RLS); and the **back-office** backend APIs (manage
> businesses/users, support/impersonate **with audit logging**, platform metrics).
>
> **Not mine (hand-off boundaries):** the Baileys gateway internals (Node service — *gateway/devops*);
> Postgres schema DDL, RLS policy SQL, and migrations authoring (*data + security agents* — I
> **consume** the schema and wire the app to it); React UI (*frontend*); secret-manager/KMS vendor,
> Redis/Postgres provisioning, deploy/process model (*devops_aws*). Where a task needs them I mark
> the dependency.
>
> Effort key: **S** = ≤1 day · **M** = 2–4 days · **L** = ≥1 week (solo + Claude pace).

---

## Locked context I am building to (do not re-litigate)

- **Stack:** FastAPI + Google OAuth (hand-wired RLS, **not** Supabase Auth) — decision 0005.
- **WhatsApp:** Baileys QR gateway is canonical (decision 0001); one session per business; the
  backend talks to it via an HTTP webhook in + `/send` out. Meta Cloud API / PyWa is **dropped**.
- **AI model:** `gemini-3.1-flash-lite` (decision 0003); migrate to the `google-genai` SDK (old
  `google.generativeai` is EOL — B16).
- **Data:** 9 Postgres tables + **live chat in Redis** (last ~10 msgs + status, ~60-min sliding TTL)
  — decision 0006. Persist the lead, throw away the chatter.
- **Tenancy:** `business_id` (UUID) everywhere + app-level filter + RLS + verify ownership via
  `business_members`; app connects as a **non-service** DB role; **no anonymous fallback tenant**.
- **Crypto:** PII encrypted at rest with a PII data key; the Baileys `auth_state` is the crown jewel
  (envelope-encrypted, KEK in a secret manager, separate DB role). **Decrypt fails LOUD — no
  plaintext fallback** (kills M2). This is a clean redesign → there are no legacy plaintext rows.

---

# PHASE 0 — Foundations

The skeleton everything else hangs on. The goal of Phase 0 is: *an authenticated request reaches a
tenant-scoped DB session with RLS live, and a stranger gets nothing.* Get this wrong and we rebuild
the old #1 failure.

### 0.1 — App skeleton + module structure
- **What:** Replace the one-giant-`main.py` with a package: `app/main.py` (FastAPI factory + lifespan),
  `app/api/` (routers per concern: `auth`, `dashboard`, `leads`, `conversations`, `bot_builder`,
  `whatsapp`, `webhook`, `backoffice`), `app/core/` (config, security, db session, redis client,
  logging), `app/services/` (engine, leads, crypto, gemini, gateway client, sweep), `app/models/`
  (pydantic schemas), `app/db/` (queries/repos). Settings via `pydantic-settings`, loaded from the
  secret manager / env — **fail to start if a required secret is missing** (no `change-me` defaults).
- **Why:** The old `main.py` mixed webhook, every REST route, login, and the sweep loop in one file —
  untestable and the root of the auth-skip bug (C2: per-route opt-in some routes forgot). A package
  with a single deny-by-default auth dependency is the structural fix.
- **Depends on:** nothing (can start immediately).
- **Effort:** **M** · **Risk:** over-engineering the layout before features exist — keep it thin,
  let routers drive it.

### 0.2 — Config + secrets loader (fail-closed)
- **What:** A typed settings object that pulls **all** secrets (DB creds for the non-service role,
  PII data key, crown KEK handle, HMAC key, Redis auth, session secret, Google OAuth client
  id/secret, Gemini key, gateway shared token) from the secret manager. App **refuses to boot** if
  any is absent. No secret ever logged.
- **Why:** Kills C1 (everything in plaintext `.env`) and M3 (`SESSION_SECRET` default constant).
  Treat all old `.env` values as compromised.
- **Depends on:** secret-manager vendor decision (*devops_aws* — KMS strongly preferred). Until then,
  read from env with a hard "must be set" check so the seam is right.
- **Effort:** **S** · **Risk:** vendor choice is deferred — code against an interface
  (`get_secret(name)`) so swapping KMS/Vault/SSM later is a one-file change.

### 0.3 — DB session as a NON-service role + per-request `business_id`
- **What:** A request-scoped DB connection (async `psycopg`/SQLAlchemy core) that connects as the
  **non-service** role and, after auth, runs `SET LOCAL app.business_id = '<uuid>'` inside the
  request's transaction so RLS `current_business_id()` resolves. Pool sized for the worker model.
- **Why:** The old system used the Supabase **service key** which bypasses RLS entirely — that one
  fact made every policy dead (C1/C2 root cause). RLS only works if we connect as a role it applies
  to and set the session var per request.
- **Depends on:** RLS policies + roles + `current_business_id()` SQL (*data/security agents*); 0.1.
- **Effort:** **M** · **Risk:** `SET LOCAL` must run in the **same transaction** as the queries or
  RLS reads a stale/empty var → connection-pool leakage of tenant context. Pin this with a test that
  proves a connection reused from the pool never carries a prior tenant's id.

### 0.4 — Google OAuth login + session + ownership resolution
- **What:** Port `auth.py` to the new package: auth URL → code exchange → userinfo → upsert `users`
  → resolve the user's business via `business_members` → establish a session. **OAuth CSRF `state`
  in Redis with a TTL** (not the old in-RAM set that broke across workers — B12). One enforced
  `current_user` dependency; a `current_business` dependency that verifies membership and yields the
  verified `business_id`.
- **Why:** Decision 0005 (Google-via-FastAPI). The membership check is the table the old system
  lacked; it's what stops tenant A passing tenant B's id. **Never trust a client-supplied
  `business_id`.**
- **Depends on:** 0.2 (OAuth secrets), 0.3 (to set the session var), Redis client; `users` +
  `business_members` tables.
- **Effort:** **M** · **Risk:** multi-worker session/state correctness — everything shared goes in
  Redis, nothing in process RAM.

### 0.5 — Crypto module (PII data key + envelope crypto for the crown jewel) — FAIL LOUD
- **What:** Two key domains. (a) **PII field crypto** for `leads.phone`, `leads.contact_name`,
  `leads.answers`, `whatsapp_connections.phone_number`, with `key_version` for rotation. (b)
  **Envelope encryption** for `whatsapp_credentials.auth_state` (per-business DEK wrapped by a KEK in
  the secret manager). (c) **Keyed HMAC** for `customer_phone_hash` (lookup without plaintext). Every
  decrypt path raises + alerts on failure — **never returns ciphertext-as-plaintext** (the banned M2
  behaviour). No plaintext fallback (clean redesign = no legacy rows).
- **Why:** Closes C1/M1/M2 at the code layer; the schema review names the loud-fail decrypt as the
  single highest-priority carry-over.
- **Depends on:** 0.2 (keys from manager); KEK custody decision (*devops_aws* — KMS vs app-held).
- **Effort:** **M** · **Risk:** key rotation correctness; getting envelope wrap/unwrap right.
  Mitigate with unit tests for encrypt→decrypt round-trip per `key_version` and a "wrong key ⇒ raises"
  test.

### 0.6 — Redis live-chat cache layer (tenant-isolated in app code)
- **What:** A `LiveChat` service over Redis: key `chat:{business_id}:{customer_phone_hash}` → small
  record `{status, assigned_user_id, last_activity_at, messages:[≤10]}`, **~60-min sliding TTL**.
  Helpers: `get/append_message`, `get/set_status`, `touch` (resets TTL), `assign`. **`business_id` is
  baked into every key and re-checked on every access** (Redis has no RLS). Optional at-rest
  encryption of message bodies in cache (default: rely on private net + short TTL — Omer's open Q4).
- **Why:** Decision 0006; fixes B11 (volatile process-RAM, breaks with >1 worker). This is the live
  conversation substrate the engine runs on.
- **Depends on:** Redis provisioning (*devops_aws*); 0.5 (HMAC for the phone hash, optional body
  crypto).
- **Effort:** **M** · **Risk:** cache-key tenant isolation is the only fence here — a missing prefix
  = cross-tenant leak. Centralize key construction in one function; never build a key inline.

### 0.7 — Structured logging + error hygiene + CI secret/PII guard
- **What:** JSON logging that **never** emits secrets, the crown-jewel `auth_state`, a QR, or raw
  PII (phones/message bodies). Generic client error responses (no `str(e)` leakage — old L3). A
  **CI test** that fails the build if `auth_state`, decrypted creds, or a QR appear in any response
  body or log line.
- **Why:** Old system logged raw phone+message (audit #9) and returned raw exceptions (L3); the
  schema review mandates the CI grep guard.
- **Depends on:** 0.1.
- **Effort:** **S** · **Risk:** low; the discipline is the point.

### 0.8 — Test harness + tenant-isolation test suite (FOUNDATIONAL, not optional)
- **What:** pytest + a throwaway Postgres (with the real RLS policies + non-service role) + a Redis
  (real or `fakeredis`). The headline suite: **isolation tests** proving tenant A cannot read/write
  tenant B's leads/conversations/config/cache via API, via a forged `business_id`, or via a
  pooled-connection reuse; plus crypto round-trip + fail-loud tests.
- **Why:** Decision 0005 calls the hand-wired RLS layer the old system's **#1 failure point** and
  says it **must be covered by tests**. This suite is the contract that lets every later phase move
  fast without re-leaking.
- **Depends on:** 0.3, 0.4, 0.5, 0.6; the RLS SQL from data/security.
- **Effort:** **M** · **Risk:** if skipped/deferred, the whole security thesis is unverified. Treat
  as a Phase-0 exit gate.

**Phase 0 exit gate:** an authenticated request reaches a tenant-scoped DB session with RLS live;
isolation tests are green; no secret/PII in logs; app fails to boot without its secrets.

---

# PHASE 1 — MVP

The customer-facing bot (leads + handoff) **and** the owner tooling to create and run it (AI bot
builder + try-me + connect-WhatsApp + minimal dashboard) — decision 0004. Everything multi-tenant.

### 1.1 — Bot config service (`bot_settings`) — read/write the bot's brain
- **What:** CRUD for `bot_settings` (`lead_steps` questionnaire, `bot_profile` =
  name/system_prompt/tone/language, `handoff_keywords`, `is_published`). Validate `lead_steps`
  shape (ordered steps: key, question, type, validation, required, options). This is the config the
  engine + builder + try-me all read.
- **Why:** Replaces the old per-user JSON-on-disk config (`system_prompt.json` + `menus_chat.json`)
  with the DB (decision: config moves to Supabase). Removes the duplicated `_config_dir` logic
  (B30) and on-disk state that didn't survive multi-instance.
- **Depends on:** 0.3, 0.4; `bot_settings` table.
- **Effort:** **M** · **Risk:** schema-of-the-jsonb drift between engine, builder, and frontend —
  define one pydantic model for `lead_steps`/`bot_profile` and share it as the contract.

### 1.2 — Conversation engine: lead-collection flow (LangGraph) on Redis
- **What:** Rebuild the questionnaire engine as a LangGraph flow that reads/writes the **Redis** live
  chat, not process RAM. Per inbound message: load live-chat record → route → for an active flow,
  **validate → normalize → store the answer → advance**; ask the next step or complete. State
  (current step, partial answers) lives in the Redis record + the `in_progress` lead, **not** an
  in-memory dict. Router order preserved: closed/human guard → handoff keyword → menu → active step
  → trigger → default LLM.
- **Why:** Core MVP capability. Fixes B11 (volatile state) and the single-worker limitation; this is
  the path that produces leads.
- **Depends on:** 0.6 (Redis), 1.1 (config), 1.4 (lead lifecycle), 1.7 (Gemini for the default-LLM
  leaf + greetings).
- **Effort:** **L** · **Risk:** correctly modelling mid-flow state across the Redis record vs the
  `leads` row without storing cleartext mid-flow PII (schema review Gap B: encrypt partial answers in
  `leads.answers`, keep only a non-PII cursor in cache). Get the validate/normalize parity with the
  old behaviour without porting its bugs.

### 1.3 — Conversation engine: human handoff
- **What:** Handoff-keyword detection (configurable `handoff_keywords`) flips the live-chat `status`
  to `human` in Redis → bot goes silent → dashboard reads the recent chat and the owner replies
  (dashboard → backend → gateway `/send`); owner can flip back to `bot`. Track `assigned_user_id` in
  the cache record. The 60-min sliding TTL handles auto-close (cache entry expires = conversation
  closes).
- **Why:** MVP capability; the cheap, natural companion to leads (decision 0004). The Redis status +
  TTL is the clean replacement for the old `conversations` table + 60s DB loop.
- **Depends on:** 0.6, 1.2.
- **Effort:** **M** · **Risk:** the dashboard and the bot worker must see the **same** live chat —
  this is exactly why it's Redis not RAM. Race between an incoming bot message and an owner takeover —
  guard with the status check at send time.

### 1.4 — Lead lifecycle: create-at-start → `new`/`abandoned` (+ funnel events)
- **What:** Create a `leads` row the **moment the questionnaire starts** (`status='in_progress'`,
  `started_at`, `last_step_index=0`, encrypted partial `answers`), update it as answers arrive
  (`last_activity_at`), mark `new` on completion (`submitted_at`), and emit `flow_events`
  (`started` / `step_completed` / `completed`). Encrypt `phone`, `contact_name`, `answers`; set
  `customer_phone_hash`; tag `is_test` for try-me leads. Link the live Redis key via `cache_chat_ref`.
- **Why:** Decision 0006's whole point — keep the lead even if the customer drops off, so the owner
  gets an **abandoned-lead follow-up list**. The old system only saved a lead on **completion**, so
  drop-offs were lost.
- **Depends on:** 0.3, 0.5 (PII crypto + HMAC), 1.2; `leads` + `flow_events` tables.
- **Effort:** **M** · **Risk:** double-writing (cache vs DB) consistency; making sure every partial
  answer is encrypted before insert and `is_test` is honoured so try-me never pollutes real stats.

### 1.5 — Abandoned-lead sweep (60-min) — periodic, multi-instance safe
- **What:** A periodic job that finds `in_progress` leads idle > 60 min (`last_activity_at`) and
  marks them `abandoned` + emits a `flow_events('abandoned')`. **Single-runner** under multiple
  instances (Redis lock / advisory lock / external scheduler) — not the old in-process `asyncio` loop
  that would run N times under N workers.
- **Why:** Decision 0005/0006 — `abandoned` is set by this sweep and it powers the funnel
  (started vs completed vs abandoned). The cache entry already auto-expires; this is the **durable**
  marker on the `leads` row so the owner sees who to call back.
- **Depends on:** 1.4; the worker/scheduler model (*devops_aws* — could be APScheduler with a lock,
  a cron container, or a Lambda).
- **Effort:** **S–M** · **Risk:** running it N× under N workers (double events / races) — must be a
  single runner. Old code's `INTERVAL '%s minutes'` was malformed (B26) — use `make_interval`.

### 1.6 — Inbound webhook receiver (Baileys → backend) + tenant routing
- **What:** `POST /webhook/whatsapp` that accepts the **Baileys flat payload**
  (`{accountId, phone, from, pushName, messageId, text, type, raw}`), **authenticates the gateway**
  (shared secret / HMAC — not the old unsigned Meta webhook, C5), maps `accountId →
  whatsapp_connections.gateway_account_id → business_id`, sets the tenant context, and dispatches to
  the engine. Idempotency on `messageId`. Bound/validate inbound text length before it reaches the
  engine/LLM (M4).
- **Why:** This is **the missing wire** in the old system (B1: the two halves never talked; payload
  shapes incompatible). Routing by `accountId` is what makes inbound **multi-tenant** (fixes B18 —
  the old flat-config single-tenant inbound).
- **Depends on:** the gateway's `accountId↔business_id` contract (Omer open Q2 / decision 0005
  "confirm during build phase" — **wrong mapping = cross-tenant inbound**); 0.3, 1.2;
  `whatsapp_connections` table.
- **Effort:** **M** · **Risk:** **the `accountId↔business_id` bridge is a tenant-isolation
  dependency** — verify the gateway derives `accountId` from `business_id`. Also: the old receive
  path on Baileys was **never tested** (decision 0001) — this needs one real end-to-end inbound test
  (baked into decision 0004).

### 1.7 — Outbound sender (backend → gateway `/send`) + Gemini reply generation
- **What:** A gateway client that calls the Baileys `/send {to, message, accountId}` with the
  business's session, with retry/timeout and **never logging the message body**. Plus the Gemini
  caller on the **`google-genai`** SDK (B16) for the default-LLM leaf and greeting/persona replies —
  system prompt built from `bot_settings.bot_profile`. (RAG tool round-trip is **deferred to
  Phase 3** — MVP bot answers from persona + runs the lead flow; no knowledge base yet.)
- **Why:** Completes the message loop (in 1.6, out 1.7). The old outbound used PyWa→Meta which is
  dropped; sends now go through the canonical Baileys gateway.
- **Depends on:** 1.6 (to know which `accountId`), 0.2 (Gemini key + gateway token); the gateway
  `/send` contract.
- **Effort:** **M** · **Risk:** gateway reliability (no retry/dead-letter on the gateway side per
  WA audit — the backend must tolerate gateway downtime gracefully). Standardize the role vocabulary
  (B27 — `user`/`assistant`/`model`) in one place.

### 1.8 — WhatsApp connection lifecycle API (QR link state machine)
- **What:** Endpoints the dashboard uses to link a number: start connect (gateway creates the
  account/session), **stream the live QR to the dashboard over the authed channel** (never persist
  it — schema review), reflect `disconnected/connecting/qr_pending/connected` from
  `whatsapp_connections`, and persist the **envelope-encrypted** `auth_state` into
  `whatsapp_credentials` via the **gateway DB role only**. Disconnect/relink.
- **Why:** "Connect WhatsApp via QR" is a required MVP capability (decision 0004). Fixes M1 (creds
  were plaintext JSON on disk) by routing the auth state into the crown-jewel table.
- **Depends on:** 0.5 (envelope crypto), gateway↔backend protocol for QR + creds persistence
  (*gateway/devops*); `whatsapp_connections` + `whatsapp_credentials` tables + the gateway role.
- **Effort:** **M** · **Risk:** the QR is session-hijack material (gateway C6 leaked it on an
  unauthed `/status`) — it must only ever travel the authed owner channel and never be stored. The
  `auth_state` must never be returned by any API or logged (CI guard from 0.7).

### 1.9 — AI-assist endpoints (Gemini proxy for the bot builder)
- **What:** Port `/api/ai/chat` and `/api/ai/validate` (+ the builder's config round-trip): the owner
  describes the bot in natural language → backend proxies to Gemini → returns a proposed
  `lead_steps` + `bot_profile` that writes `bot_settings`. Optionally persist the build chat in
  `bot_builder_messages` for "resume your build session" (decision 0005 kept it; Omer open Q3 — drop
  if stateless). **Auth-gated, tenant-scoped, input-bounded.**
- **Why:** "Without this there is no MVP — it's how a bot gets created" (decision 0004). These were
  unauthenticated in the old system (C2).
- **Depends on:** 0.4 (auth), 1.1 (writes config), 1.7 (Gemini client); optional
  `bot_builder_messages` table.
- **Effort:** **M** · **Risk:** prompt-injection / cost abuse — bound input, rate-limit per business,
  treat LLM output as untrusted and validate it against the `lead_steps` schema before saving.

### 1.10 — Try-me test-mode endpoint (same engine, no WhatsApp)
- **What:** A test conversation endpoint that runs the **same** engine (1.2/1.3) against a test
  live-chat key, producing replies the React app shows — **no gateway involved**. Leads/events
  created here are tagged `is_test=true` so they're excluded from real stats.
- **Why:** "Try-me test mode is a first-class part of the build loop" (architecture) and a required
  MVP capability (decision 0004) — the owner trusts the bot before going live.
- **Depends on:** 1.2, 1.3, 1.4 (with `is_test`), 1.7.
- **Effort:** **S–M** · **Risk:** test traffic leaking into real funnels — enforce `is_test`
  end-to-end (leads + flow_events) and exclude it in every stats query.

### 1.11 — Dashboard read APIs (leads list, abandoned list, live conversations)
- **What:** `GET /api/leads` (incl. the **abandoned-leads-to-follow-up** view via
  `(business_id, status)` index), lead detail (decrypted server-side for the owner), the funnel
  summary (started/completed/abandoned from `flow_events`), the live-conversations list + recent
  chat (from Redis), and the bot↔human toggle (1.3). All **auth-gated, RLS-scoped, decrypted
  server-side only for the authed owner**.
- **Why:** The "minimal dashboard" half of MVP (decision 0004). These are the read paths that were
  correctly tenant-scoped in the old system but anonymous (C2) — now behind enforced auth.
- **Depends on:** 0.4, 1.4, 1.3.
- **Effort:** **M** · **Risk:** N+1 decryption cost on large lead lists; never returning ciphertext
  or another tenant's rows (covered by the 0.8 isolation suite).

### 1.12 — Enforced-auth middleware + rate limiting + input bounds (cross-cutting)
- **What:** One deny-by-default auth dependency on **every** `/api/*` and `/webhook/*` and
  `/backoffice/*` route (public booking is Phase 2). Per-tenant rate limits on AI + webhook +
  public-write paths. Global input length/shape validation.
- **Why:** C2's structural flaw was per-route opt-in that routes forgot. A single enforced gate with
  **no anonymous fallback tenant** is the fix; rate limits blunt cost/DoS abuse (AI + webhook).
- **Depends on:** 0.4; touches every router.
- **Effort:** **M** · **Risk:** accidentally gating the genuinely public routes (none in MVP) or
  leaving a new route off the gate — enforce via a router-level dependency, not per-endpoint.

**Phase 1 exit gate:** an owner can log in → build a bot with the AI assistant → try it in try-me →
connect WhatsApp by QR → a real inbound message collects an encrypted lead (and an abandoned one is
swept) → the owner sees leads + live chat and can take over. One **real end-to-end inbound test** on
the Baileys gateway passes (decision 0001/0004).

---

# PHASE 2+ — Post-MVP

Grouped: **2A back-office (FULL — required by Omer)**, **2B compliance (launch-required where it
touches the backend)**, **2C booking (Phase 2 feature)**, **3 RAG (Phase 3)**, **4 scale/hardening**.

## 2A — BACK-OFFICE backend (FULL — manage businesses/users, support+impersonate, metrics)

> Omer: back-office is **FULL**. Billing **engine is DEFERRED** — only reserve hooks; do **not** build
> payments now. This is a **separate trust boundary**: platform-staff/superadmin, not tenant owners.

### 2A.1 — Platform-admin auth + role model + DB access path
- **What:** A `platform_admin` concept (a staff allow-list / role distinct from tenant `business_members`)
  and a back-office auth dependency separate from the tenant gate. Decide the back-office DB access
  path: a **scoped admin role** for cross-tenant reads that is **still not the service role** and is
  **audited**, with cross-tenant queries confined to `/backoffice/*` handlers — never reachable from a
  tenant request.
- **Why:** Back-office is inherently cross-tenant, which is the exact power that leaked in the old
  system (C3 unauthenticated global admin). It must be a deliberate, auth'd, audited boundary — not a
  service-key backdoor.
- **Depends on:** 0.3, 0.4; a staff/role source (new small table or allow-list) + data/security sign-off
  on the cross-tenant access path.
- **Effort:** **M** · **Risk:** this is the highest-blast-radius surface in the system. Cross-tenant
  read power must be tightly scoped and fully audited; a leak here is total.

### 2A.2 — Manage businesses & users (CRUD + lifecycle)
- **What:** List/search businesses + their members + WhatsApp connection status; view a business's
  config/leads/usage at a glance; suspend/reactivate/delete a business; manage members (invite,
  change role, remove). Read-mostly with guarded mutations.
- **Why:** Core "manage businesses & users" back-office requirement.
- **Depends on:** 2A.1; `businesses`, `business_members`, `whatsapp_connections`.
- **Effort:** **M** · **Risk:** destructive ops (delete/suspend) cascade across a tenant's data —
  require confirmation + audit + soft-delete where possible.

### 2A.3 — Support / impersonate WITH audit logging
- **What:** Let an authorized staff member act **as** a business owner for support (a scoped,
  time-boxed impersonation session that sets the tenant context for *that* business) — **every action
  while impersonating is written to an append-only audit log** (who, which business, when, what
  changed, session start/stop). Impersonation never grants crown-jewel (`auth_state`) access.
- **Why:** Omer explicitly requires "support + impersonate **WITH audit logging**." Impersonation
  without an immutable trail is the worst-case insider-risk + privacy-law problem.
- **Depends on:** 2A.1, 0.3 (tenant-context mechanism reused); an **audit-log table** (new — flag to
  *data agent*).
- **Effort:** **M–L** · **Risk:** an impersonation session that outlives its purpose or isn't fully
  logged. Time-box it, scope it to one business, log start/stop + every mutation, and exclude
  `whatsapp_credentials` entirely. This intersects compliance (2B) directly.

### 2A.4 — Platform metrics
- **What:** Aggregate platform-wide metrics: active businesses, messages/day, leads collected,
  conversion (started→completed) funnel across tenants, WhatsApp-connection health, AI usage/cost.
  Read-only aggregates (consider a metrics view / periodic rollup, not heavy live cross-tenant scans).
- **Why:** "Platform metrics" back-office requirement; also the data Omer needs to run the business.
- **Depends on:** 2A.1; `flow_events`, `leads`, `whatsapp_connections`; usage counters from 1.7/1.9.
- **Effort:** **M** · **Risk:** cross-tenant aggregation cost + accidentally exposing per-tenant PII
  in an "aggregate" — aggregates must be PII-free.

### 2A.5 — Billing **VIEW** + deferred-engine hooks (NO payments now)
- **What:** A read-only billing **view** (plan/status placeholder per business) and **reserve seams**
  for the future engine: a usage-metering hook on message/AI calls, a `plan`/`subscription_status`
  placeholder, and a clearly-marked "billing engine TBD" boundary. **Do not** build payment
  processing, invoicing, or VAT now.
- **Why:** Omer: billing **VIEW** is in back-office, but the **engine is DEFERRED**; invoicing/VAT
  compliance rides with billing later. Reserving hooks now avoids a later rewrite.
- **Depends on:** 2A.1, 2A.4 (usage data).
- **Effort:** **S** (just the view + hooks) · **Risk:** scope creep into building real billing —
  resist; this is hooks + a read-only view only.

## 2B — COMPLIANCE (launch-required) — backend slice

> Omer: accessibility (WCAG), Terms + Privacy Policy, Israeli data-protection — **required for
> launch**. Accessibility is mostly frontend; the **data-protection** parts are mine.

### 2B.1 — Data-subject rights: export + delete (Israeli privacy law)
- **What:** Backend support for **export all of a customer's / a business's data** and **hard-delete
  on request** (right to erasure), honoring encryption (export decrypts for the authorized requester
  only) and cascading correctly across `leads`, `flow_events`, Redis cache, and (Phase 2) bookings.
  Plus a documented **data-retention** policy enforced in code (e.g. the Redis TTL already discards
  raw chat; define retention for `leads`/`flow_events`).
- **Why:** Israeli Privacy Protection Law (and the spirit of GDPR) requires access + deletion. The
  product stores customer PII (phones, names, answers) — this is a launch blocker, not a nice-to-have.
- **Depends on:** 0.5 (crypto), 1.4 (leads), 2A.1 (a deletion request may come via back-office).
- **Effort:** **M** · **Risk:** an incomplete delete that misses the Redis cache or `flow_events` =
  a compliance gap. Centralize "delete everything for X" so no store is forgotten.

### 2B.2 — Consent + audit trail + privacy-by-design checks
- **What:** Record consent context where the bot collects PII (a consent flag/timestamp on the lead /
  questionnaire start), keep the back-office **audit log** (2A.3) immutable, and ensure logs/metrics
  carry **no raw PII** (ties to 0.7). Surface the Terms/Privacy content via a small public endpoint if
  the frontend needs it served.
- **Why:** Data-protection compliance: lawful basis/consent for collecting customer PII, auditability
  of access (especially impersonation), and the no-PII-in-logs principle.
- **Depends on:** 1.4, 2A.3, 0.7.
- **Effort:** **S–M** · **Risk:** treating consent as an afterthought — bake the consent timestamp in
  at questionnaire start (1.4) so it's there from row one.

> **Accessibility (WCAG):** primarily a *frontend* responsibility. Backend touchpoint is minor:
> serve clean, correct content for screen readers and keep API errors/messages localizable (Hebrew).
> Flagged here as a cross-team item; the heavy lifting is frontend's.

## 2C — Booking (Phase 2 feature)

### 2C.1 — Real booking engine (fix the old B7) + tenant-safe APIs
- **What:** Bring back booking as a **real** flow: `booking_settings` (working days/hours, slot
  duration) + `bookings` with availability math, a conversational flow that **actually creates a
  `bookings` row** (not the old free-text-lead fake — B7), and tenant-safe `/api/bookings*` that
  **always filter `business_id`** (fixes the old IDOR C4). **Encrypt booking client PII** (name/
  email/phone) — the old system stored it in plaintext (M5).
- **Why:** Booking is Phase 2 (decision 0004); the service-pro customer needs it. Must not reintroduce
  the old booking bugs/leaks.
- **Depends on:** new `booking_settings` + `bookings` tables (with `business_id` + RLS, *data agent*);
  the engine (1.2).
- **Effort:** **L** · **Risk:** re-introducing C4 (IDOR) / M5 (plaintext PII) / B7 (fake booking).
  Apply the same `business_id`+RLS+encrypt rules from day one.

### 2C.2 — Public booking page API (the one allowed unauthenticated path)
- **What:** Public `GET /book/{slug}/slots` + `POST /book/{slug}` for customers — the **only**
  unauthenticated write path. Verify the `slug` maps to a **real provisioned business** before
  accepting writes, validate/bound all fields (email/phone/length), add rate-limit + anti-abuse
  (captcha/throttle), and use a **non-guessable** slug (the old one was an email-derived guessable id).
- **Why:** Public booking is needed, but it was the old system's worst public-write surface (M4: any
  slug, no validation, no rate-limit, guessable). Rebuild it safe.
- **Depends on:** 2C.1; 1.12 (rate limiting).
- **Effort:** **M** · **Risk:** it's a public write endpoint — the usual abuse vectors (spam
  bookings, enumeration). Validate, throttle, and verify the business exists.

## 3 — RAG (Phase 3)

### 3.1 — RAG ingestion + retrieval (pgvector), grounded answering
- **What:** Per-business RAG: upload (pdf/docx/xlsx/txt/md — and decide PPT/PPTX, B10) to Supabase
  Storage, extract→chunk→embed (sentence-transformers, 384-dim) into `brain_chunks` (business-scoped),
  a `search_knowledge_base` Gemini tool with the **hard-grounding override** (answer only from
  retrieved text; fixed "no info" reply), and a `/api/rag/*` management surface — all **auth-gated,
  tenant-scoped**. Drop the old dead `rag_data/` path entirely (B6).
- **Why:** RAG is Phase 3 (decision 0004). The old pipeline existed and was mostly sound but its mgmt
  endpoints were anonymous (C2) and it carried dead/broken code (B5/B6).
- **Depends on:** pgvector enabled (reserved in `architecture.md`); Storage; 1.7 (Gemini tool
  round-trip); new `brain_chunks` + `rag_sources` tables.
- **Effort:** **L** · **Risk:** retrieval scoping (every query `WHERE business_id`), embedding model
  cost/cold-start, and keeping grounding strict (zero invention).

## 4 — Scale & hardening (post-MVP, with devops_aws)

### 4.1 — Production process model + horizontal scale correctness
- **What:** Gunicorn/uvicorn workers (no `--reload`), stateless app instances (all shared state in
  Redis/Postgres — already true by design from Phase 0), the abandoned sweep as a single runner
  (1.5), health/readiness endpoints, graceful shutdown.
- **Why:** Old system ran dev servers in "prod" (B25) and kept state in process RAM (B11). Decisions
  0006 + the architecture explicitly target multiple AWS instances.
- **Depends on:** *devops_aws* for the deploy substrate; 0.6.
- **Effort:** **M** · **Risk:** any hidden process-local state breaks at >1 instance — audit for it.

### 4.2 — Resilience: gateway downtime, retries, idempotency, key rotation drills
- **What:** Tolerate gateway outages (the gateway has no retry/dead-letter per WA audit — backend
  retries/queues outbound, dedupes inbound by `messageId`), exercise PII-key + KEK **rotation** end
  to end (`key_version`), and add observability/alerting on decrypt-fail and crown-jewel access.
- **Why:** The canonical Baileys gateway is an unofficial lib (ban risk, decision 0001) and unreliable
  by the audit; key rotation must be proven before it's needed in anger.
- **Depends on:** 0.5, 1.6, 1.7.
- **Effort:** **M** · **Risk:** rotation done wrong locks out data — drill it on non-prod first.

---

# RETURN — tight summary

## Phases
- **Phase 0 — Foundations:** app/package skeleton, fail-closed secrets, **non-service DB role + per-request `business_id` for RLS**, Google OAuth + ownership check, crypto (PII + crown-jewel envelope, **fail-loud decrypt**), Redis live-chat layer, logging/CI secret-guard, and the **tenant-isolation test suite** (the old #1 failure point — gated).
- **Phase 1 — MVP:** bot-config service; the **conversation engine (LangGraph on Redis)** for lead-collection + handoff; the **lead lifecycle** (create-at-start → new/abandoned) + the **60-min abandoned sweep**; **inbound webhook** (Baileys, tenant-routed by `accountId`) + **outbound sender** + Gemini (`google-genai`); WhatsApp **QR connect** lifecycle; **AI-assist** endpoints; **try-me**; dashboard read APIs; one enforced **auth gate** + rate limits.
- **Phase 2+ —** **2A back-office (FULL):** platform-admin auth, manage businesses/users, **support+impersonate WITH audit log**, platform metrics, billing **VIEW + deferred hooks (no payments)**. **2B compliance:** data export/delete + retention, consent + audit (Israeli privacy law). **2C booking** (real engine, fixes old IDOR/plaintext/fake-booking). **3 RAG** (pgvector, grounded). **4 scale/hardening.**

## The 5–8 biggest tasks
1. **Conversation engine on Redis (LangGraph)** — lead-collection + handoff, state in cache not RAM (**L**, 1.2/1.3).
2. **Non-service DB role + per-request `business_id` + RLS wiring + isolation test suite** — the security thesis of the whole rebuild (**M×2**, 0.3/0.8).
3. **Inbound webhook + outbound sender wired to the Baileys gateway** — the *missing link* in the old system, tenant-routed by `accountId` (**M×2**, 1.6/1.7).
4. **Lead lifecycle (create-at-start) + 60-min abandoned sweep** — the abandoned-follow-up feature; sweep must be single-runner (**M**, 1.4/1.5).
5. **Crypto: PII data key + crown-jewel envelope encryption, fail-loud** — kills C1/M1/M2 (**M**, 0.5).
6. **Back-office support + impersonate WITH audit logging** — highest-blast-radius surface; cross-tenant power, must be authd + fully audited (**M–L**, 2A.3).
7. **AI-assist (Gemini proxy) + try-me** — "no MVP without it"; how a bot gets created and trusted (**M + S/M**, 1.9/1.10).
8. **Data-subject export/delete + consent (compliance)** — launch-blocker under Israeli privacy law (**M**, 2B.1).

## Top risk
**The hand-wired multi-tenant isolation (non-service role + per-request `SET LOCAL app.business_id` + RLS), and its two highest-stakes extensions: the webhook `accountId↔business_id` mapping and back-office cross-tenant/impersonation access.** This exact layer was the old system's #1 failure (anonymous shared-tenant leaks, service-key bypass, single-tenant inbound mis-attribution). If the session var leaks across pooled connections, the gateway maps a message to the wrong business, or back-office uses a service-key backdoor, we reproduce the original cross-tenant data leak — now with a back-office that can touch *every* tenant. Mitigation: treat the Phase-0 isolation test suite as a hard exit gate, confirm the `accountId↔business_id` contract with the gateway before wiring 1.6, and make every cross-tenant/impersonation action in back-office authd + append-only audited and excluded from the crown jewel.

> **Needs verification / cross-team:** `accountId↔business_id` bridge (gateway/devops, Omer open Q2); secret-manager vendor + KMS-vs-app-held KEK (devops_aws); keep `bot_builder_messages`? (Omer open Q3); encrypt Redis message bodies? (Omer open Q4); the back-office cross-tenant DB access path + new audit-log table (data/security sign-off).
