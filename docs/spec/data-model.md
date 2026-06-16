# Data Model — Bizz_up MVP (Phase 1)

> **Status:** FINAL for Phase 1. **Updated 2026-06-16** to move live chat into a **Redis cache** (decision 0006).
> **Scope:** lead collection + human handoff + AI bot builder + try-me test, multi-tenant.
> **Out of scope (later):** booking (Phase 2), RAG / pgvector (Phase 3).
>
> **The split:** **9 persisted tables in Supabase/Postgres** + **live chat in Redis** (an in-memory cache, not the DB).
> This is a clean redesign, not a migration: the tenant is a real `businesses` row with a **UUID** id (the old
> system wrongly used the owner's email / a flat `"client_001"`, which caused the cross-tenant leaks).

---

## The tenant rule (read this first)

Bizz_up is **multi-tenant**: many businesses share one database, and **one business must never see another's
data.** Guaranteed everywhere by: every tenant table carries a **`business_id`** (UUID → `businesses.id`), **every
query filters on it**, and behind that, **Row-Level Security (RLS)** — a database rule that only returns/accepts
rows whose `business_id` matches the logged-in business. For RLS to work the app connects as a **non-service role**
(the old service key bypassed RLS — the core bug), and it verifies a `business_id` belongs to the user via
`business_members`, **never trusting a `business_id` from the browser.** One line: **`business_id` everywhere +
filter + RLS + verify ownership.**

**Auth (decision 0005):** Google OAuth inside FastAPI. After login the backend verifies the user's business via
`business_members`, sets it as a per-request Postgres session value (`SET LOCAL app.business_id = '<uuid>'`), and
RLS reads it via `current_business_id()`. Hand-wired → **must be covered by isolation tests.**

**The Redis cache is NOT a tenant table** — Redis has no RLS. Its isolation is enforced in the **app layer**: every
cache key is prefixed with `business_id`, and every cache access re-checks the caller's business. See *Live chat*.

---

## What's persisted vs what's ephemeral

- 💾 **Persisted (Postgres):** accounts, the WhatsApp connection + key, the bot config, and the **leads + funnel** —
  the data that matters long-term.
- ⚡ **Ephemeral (Redis cache):** the live chat itself — the **last ~10 messages** + the `bot/human/closed` status —
  auto-expiring. **We keep the lead data, not the raw chatter.**

---

## Tables (Postgres) — 9

Legend: 🏢 = `business_id` tenant key · 🔒 = encrypted at rest · 🔒🔒 = crown-jewel. PKs are `uuid` (except `users`).
Timestamps are `timestamptz` default `now()`.

### 1. `users` — login identity (Google) · GLOBAL, no tenant key
Who the owner is. Identity only — **not** the tenant.

| Column | Type | Notes |
|---|---|---|
| `id` | `text` **PK** | Google OpenID `sub`. |
| `email` | `text` UNIQUE NOT NULL | login email (stays queryable for login). |
| `name` | `text` | display name. |
| `picture` | `text` | avatar URL. |
| `created_at` / `last_login_at` | `timestamptz` | |

- **PK:** `id` · **🔒:** none · **Tenant key:** N/A (global).

### 2. `businesses` — the tenant (this `id` IS `business_id`)
| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` **PK** | **THE `business_id`.** |
| `name` | `text` NOT NULL | business display name. |
| `business_type` | `text` | `insurance` / `service_pro`, etc. |
| `created_by` | `text` → `users(id)` | owner, `ON DELETE SET NULL`. |
| `created_at` / `updated_at` | `timestamptz` | |

- **PK:** `id` · **🔒:** none · **Tenant key:** defines it.

### 3. `business_members` — who may access a business · tenant table
The user↔business map — how the app answers "does this `business_id` belong to the logged-in user?" (the check the
old system lacked). One owner per business for MVP; room for staff later.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` **PK** | |
| `business_id` 🏢 | `uuid` → `businesses(id)` NOT NULL | `ON DELETE CASCADE`. |
| `user_id` | `text` → `users(id)` NOT NULL | `ON DELETE CASCADE`. |
| `role` | `text` NOT NULL def `'owner'` | `owner` (room for `staff`/`agent`). |
| `created_at` | `timestamptz` | |

- **PK:** `id` · **Unique:** `(business_id, user_id)` · **Tenant key:** `business_id`.

### 4. `whatsapp_connections` — per-business connection status · tenant table
The connection **state machine** the dashboard shows while linking via QR. **Holds no secret key** (that's table 5).

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` **PK** | |
| `business_id` 🏢 | `uuid` → `businesses(id)` NOT NULL **UNIQUE** | one session per business, `ON DELETE CASCADE`. |
| `gateway_account_id` | `text` UNIQUE | bridges the Baileys gateway's `accountId` → routes inbound to the right business. |
| `status` | `text` NOT NULL def `'disconnected'` | `disconnected` / `connecting` / `qr_pending` / `connected`. |
| `phone_number` | `text` 🔒 | the linked WhatsApp number (PII). |
| `last_connected_at` / `last_error` | | dashboard info, no secrets. |
| `created_at` / `updated_at` | `timestamptz` | |

- **🔒:** `phone_number` · **Tenant key:** `business_id`.
- The live QR is **streamed to the dashboard over the authed channel, never stored** (it's session-hijack material).

### 5. `whatsapp_credentials` — the Baileys session KEY 🔒🔒 · CROWN JEWEL
The most sensitive table. Holds the Baileys **auth state** (the keys that *are* the WhatsApp session). Its own table.

| Column | Type | Notes |
|---|---|---|
| `business_id` 🏢 | `uuid` → `businesses(id)` **PK** | tenant key **and** PK, `ON DELETE CASCADE`. |
| `auth_state` | `bytea` 🔒🔒 | the **encrypted** Baileys auth state. Ciphertext only, never plaintext. |
| `key_version` | `int` NOT NULL def `1` | which key encrypted it → rotation + fail-closed decrypt. |
| `rotated_at` / `created_at` / `updated_at` | `timestamptz` | |

- **🔒🔒:** `auth_state` (always) · **Tenant key:** `business_id`. See *How the WhatsApp key is protected*.

### 6. `bot_settings` — the bot's brain config (TWO jsonb fields) · tenant table
The per-business config that **moves off disk into the DB** (old `system_prompt.json` + `menus_chat.json`).

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` **PK** | |
| `business_id` 🏢 | `uuid` → `businesses(id)` NOT NULL **UNIQUE** | one config per business, `ON DELETE CASCADE`. |
| `lead_steps` | `jsonb` NOT NULL def `'[]'` | **(1)** the questionnaire: ordered steps (key, question, type, validation, required, options). |
| `bot_profile` | `jsonb` NOT NULL def `'{}'` | **(2)** `name`, `system_prompt`, `tone` ("warm and pleasant"), language. |
| `handoff_keywords` | `jsonb` def `'["נציג","אדם","human","agent"]'` | words that trigger handoff. |
| `is_published` | `boolean` NOT NULL def `false` | drives **try-me vs live**. |
| `created_at` / `updated_at` | `timestamptz` | |

- **🔒:** none (the business's own config, not customer PII) · **Tenant key:** `business_id`.

### 7. `leads` — collected leads + the abandoned-follow-up record 🔒 · tenant table
Every lead the bot captures. **Created the moment the questionnaire starts** (so abandoners are recoverable), then
updated as answers come in. All PII encrypted. **This is the table that lets the owner see who dropped off and call
them back.**

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` **PK** | |
| `business_id` 🏢 | `uuid` → `businesses(id)` NOT NULL | `ON DELETE CASCADE`. |
| `phone` | `text` 🔒 | customer phone. **Encrypted.** |
| `contact_name` | `text` 🔒 | customer name. **Encrypted.** |
| `answers` | `jsonb` 🔒 | answers so far (partial or full). **Encrypted blob.** Keys map to `bot_settings.lead_steps`. |
| `status` | `text` NOT NULL def `'in_progress'` | **`in_progress`** (started) → **`new`** (completed) / **`abandoned`** (dropped); then `read` / `archived`. |
| `last_step_index` | `int` | how far they got (for the funnel + "resume" follow-up). |
| `is_test` | `boolean` NOT NULL def `false` | try-me leads excluded from real stats. |
| `key_version` | `int` NOT NULL def `1` | PII key version → clean rotation + fail-closed decrypt. |
| `cache_chat_ref` | `text` | the live Redis chat key while active (no FK; just a pointer). |
| `started_at` | `timestamptz` | when the questionnaire began. |
| `last_activity_at` | `timestamptz` | last answer time → drives the **abandoned** sweep (in_progress + idle > 60 min ⇒ abandoned). |
| `submitted_at` | `timestamptz` | when completed (null if abandoned/in_progress). |

- **🔒:** `phone`, `contact_name`, `answers` · **Tenant key:** `business_id`.
- **Indexes:** `(business_id, status)` (the "abandoned leads to follow up" list); `(business_id, submitted_at DESC)`; `(business_id, last_activity_at)` (the abandoned sweep).

### 8. `bot_builder_messages` — AI-assist bot-builder chat · tenant table · OPTIONAL
The owner's chat with the AI assistant (proxied to Gemini) that writes `bot_settings`. Lets the owner **resume a
build session**. Owner-facing, not customer PII.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` **PK** | |
| `business_id` 🏢 | `uuid` → `businesses(id)` NOT NULL | `ON DELETE CASCADE`. |
| `author_user_id` | `text` → `users(id)` | who typed it (null for assistant). |
| `role` | `text` NOT NULL | `user` / `assistant`. |
| `content` | `text` | the build-chat message (not customer PII). |
| `created_at` | `timestamptz` | |

- **🔒:** none · **Tenant key:** `business_id`. Drop if the builder is stateless.

### 9. `flow_events` — lead funnel (started / completed / abandoned) · tenant table
Lightweight, append-only funnel log, **linked to the lead** so the dashboard shows drop-offs and the owner can act.
No customer PII — just which step and what happened.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` **PK** | |
| `business_id` 🏢 | `uuid` → `businesses(id)` NOT NULL | `ON DELETE CASCADE`. |
| `lead_id` | `uuid` → `leads(id)` | which lead/customer this event belongs to, `ON DELETE CASCADE`. |
| `flow_key` | `text` | which questionnaire. |
| `event` | `text` NOT NULL | `started` / `step_completed` / `completed` / `abandoned`. |
| `step_index` | `int` | how far they got. |
| `is_test` | `boolean` NOT NULL def `false` | keeps try-me out of funnel stats. |
| `created_at` | `timestamptz` | |

- **🔒:** none · **Tenant key:** `business_id`.
- **`abandoned`** is logged by the 60-min sweep (an `in_progress` lead idle too long). Dashboard funnel = started vs
  completed vs abandoned; "abandoned" rows point at a `lead` that holds the phone + partial answers to follow up.

---

## Live chat → Redis cache (NOT the database)

The live conversation runs in **Redis** — a fast, in-memory cache shared across all server instances — **not** in
Postgres. We keep only what a live chat needs, briefly:

- **Key:** `chat:{business_id}:{customer_phone_hash}` → a small record holding:
  - `status` (`bot` / `human` / `closed`), `assigned_user_id` (who's handling a handoff),
  - `last_activity_at`,
  - **the last ~10 messages** only (`role`, `body`, `ts`) — older messages roll off.
- **TTL ~60 min sliding:** if the customer goes quiet, the entry **auto-expires = the conversation auto-closes.**
- **Shared across workers/instances:** this is *why* it's Redis and not plain process memory — at scale (multiple
  AWS instances) the bot process and the dashboard API must see the **same** live chat; process RAM wouldn't.
- **Handoff:** the dashboard reads/writes the same Redis key (via the backend), so the owner sees the recent chat
  and replies; flipping `status` to `human`/`bot` is a cache write.
- **What is NOT in Redis:** anything long-term. Lead answers → `leads` (Postgres). Funnel → `flow_events`. The raw
  chat is **deliberately discarded** when the cache entry expires.

**Cache security (important — Redis has no RLS):**
- Runs on a **private network only** (never exposed to the internet), with **auth (password/ACL)** and **TLS** in transit.
- **Tenant isolation is enforced in the app layer:** the `business_id` is baked into every key and re-checked on every
  access (the DB's RLS safety-net does not extend to Redis, so the code is the guard here).
- Holds **minimal, short-lived** data; sensitive message bodies may also be encrypted in cache. Small blast radius.

---

## How the WhatsApp key is protected (top concern)

The Baileys **auth state** is the single most dangerous thing — reading it = full account takeover. Today it's
**plaintext JSON on disk**. The new model:

- **Its own table** (`whatsapp_credentials`), separate from the frequently-read status table.
- **Envelope encryption:** `auth_state` stores **ciphertext only**; encrypted with a per-business data key (DEK)
  that is itself wrapped by a **master key (KEK) in a secret manager / KMS — never in the DB, never in `.env`.** A
  stolen database dump is useless without the KEK. The KEK is **separate** from the ordinary PII key.
- **Key versioning + rotation** via `key_version`; **decrypt fails loud** (never falls back to raw bytes).
- **Isolation by DB role:** only the **gateway role** can read/write it; the **dashboard/API role has no grant — not
  even SELECT.** Missing grant first, RLS second.
- **Never exposed:** never returned by any API, never serialized, **never logged**. A CI test fails the build if it
  ever appears in a response or log.

---

## How sensitive data is kept from leaking (defense-in-depth)

- **PII encrypted at rest:** `leads.phone`, `leads.contact_name`, `leads.answers`, and `whatsapp_connections.phone_number`
  are 🔒 before insert, with a **PII data key** (separate from the WhatsApp KEK) in the secret manager; `key_version`
  enables rotation. (Live message bodies live only in the short-lived Redis cache.)
- **Decryption fails loud — no plaintext fallback** (the old `decrypt()` silently returned ciphertext; banned here).
- **Lookups without plaintext:** `customer_phone_hash` is a **keyed HMAC** (its key is a real secret in the manager).
- **RLS on every tenant table** (read `USING` + write `WITH CHECK`), so a forgotten `business_id` predicate still can't
  leak across tenants. The app connects as a **non-service role** so RLS is live.
- **Cache isolation in the app layer** — `business_id` in every Redis key + re-checked (Redis has no RLS).
- **Mandatory auth + ownership check** on every `/api/*` route; **no anonymous fallback tenant** (the old leak); never
  trust a client-supplied `business_id`; no unauthenticated/global-admin endpoints.
- **Least privilege:** a **gateway role** (only one that touches `whatsapp_credentials`) and a **dashboard role**
  (everything else, tenant-scoped, non-service). No service-role key in the app.
- **Secrets only in a manager** (PII key, crown KEK, HMAC key, DB creds, Redis auth, session/OAuth secrets); app
  **fails to start** if a secret is missing (no `change-me` defaults). Old `.env` values are treated as compromised.
- **Test data tagged** (`is_test` on `leads`, `flow_events`) and **logs never carry secrets or raw PII.**

> **Belongs to the gateway/transport rebuild (flagged, not table design):** gateway token / CORS / `/status`
> hardening (old C6), the session-secret default (M3), never logging secrets (L1).

---

## Open questions for Omer
1. **Secret-manager vendor + KMS-vs-app-held KEK** for the crown jewel → decide with the `devops_aws` agent in the AWS phase (KMS strongly preferred).
2. **Gateway `accountId` ↔ `business_id` bridge** → confirm during the build phase (wrong mapping = cross-tenant inbound).
3. **Keep `bot_builder_messages`?** Only if "resume your build session" is wanted in MVP; else the builder is stateless.
4. **Encrypt message bodies inside Redis too?** Default: rely on private-network + short TTL; encrypt if you want belt-and-suspenders.
