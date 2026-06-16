# Roadmap — DATA layer (Bizz_up)

> **Owner:** DATA agent. **Date:** 2026-06-16. **Status:** plan, ready for build sequencing.
> **Scope of this slice:** Supabase migrations for the 9 tables; RLS + the `current_business_id()` bridge;
> field-encryption helpers + key management (PII key + WhatsApp KEK, fail-loud, `key_version` rotation);
> Redis for live chat + the abandoned-lead sweep; seed/test fixtures; the back-office's data needs
> (safe cross-tenant admin reads); and data-protection compliance **at the data layer**.
>
> **Grounds:** `spec/data-model.md` (FINAL, 9 tables + Redis), `spec/database-schema-security-review.md`
> (the MUST list), decisions 0002 / 0004 / 0005 / 0006, `security-issues.md` (C1–C6, M1–M5, L1).
> The data-model.md is the source of truth; the earlier `database-schema-draft.md` is superseded
> (it pre-dates the Redis move — it still listed `conversations`/`messages`, now dropped).
>
> **What this slice does NOT own (flagged, handed off):** the FastAPI auth dependency, ownership check,
> and `SET LOCAL` wiring (BACKEND owns the *code*; DATA owns the *RLS contract* it must satisfy);
> the secret-manager vendor + KMS choice (DEVOPS/AWS phase); gateway `accountId` derivation
> (WHATSAPP). Where they touch the schema, the contract is specified here.

---

## How to read this

Tasks are grouped **Phase 0 (Foundations)** → **Phase 1 (MVP)** → **Phase 2+ (post-MVP)**.
Each task: **what / why / depends-on / effort (S/M/L) / main risk.**
Effort is solo-dev-with-Claude: **S** ≈ a sitting, **M** ≈ a day or two, **L** ≈ several days.

**The one-line invariant this whole layer exists to guarantee:**
`business_id` everywhere + app-level filter + RLS (`USING` + `WITH CHECK`) + verify ownership via
`business_members` + connect as a **non-service role**. The old system died on exactly this (service
key bypassed RLS; email/`client_001` used as the tenant id). Every task below serves that invariant.

---

## Phase 0 — Foundations (the data layer everything else stands on)

### D0.1 — Migration tooling + DB roles + extensions
- **What:** Pick and wire a migration runner (plain versioned SQL files applied in order, or Alembic).
  Establish the **two non-service DB roles** up front: `app_role` (dashboard/API, tenant-scoped) and
  `gateway_role` (only role that may touch `whatsapp_credentials` + `whatsapp_connections`). Enable
  `pgcrypto` (for `gen_random_uuid()`). **No service-role key is ever used by app code.**
- **Why:** The C1/C2 root cause was the app connecting with the **service-role key that bypasses RLS**.
  Roles + least privilege are the *first* fence (RLS is the second); they must exist before any table so
  grants are written alongside each table, not bolted on. Reproducible migrations replace the old system's
  "no SQL file existed at all" (schema was buried in Python `CREATE TABLE` strings).
- **Depends-on:** Supabase project provisioned (DEVOPS).
- **Effort:** S–M.
- **Main risk:** Supabase defaults to the service key in examples — easy to accidentally ship it. Mitigate
  by storing only the non-service connection strings in the secret manager and adding a startup assertion
  that the connected role is **not** a superuser / service role.

### D0.2 — `current_business_id()` bridge function + RLS helper pattern
- **What:** Create the SQL function `current_business_id()` that reads the per-request session GUC
  (e.g. `current_setting('app.business_id', true)::uuid`), returning `NULL` when unset. Define the
  **standard RLS policy template** every tenant table will reuse:
  `USING (business_id = current_business_id())` **and** `WITH CHECK (business_id = current_business_id())`.
  When unset (`NULL`), the predicate fails → **zero rows, deny-by-default** (no anonymous fallback tenant).
- **Why:** This is the hand-wired RLS chosen in decision 0005 (Google login via FastAPI, not Supabase
  Auth). It is the single most security-critical piece of the data layer and was the old system's #1
  failure point, so it is defined once, centrally, and tested hard (D0.6). `WITH CHECK` (not just `USING`)
  is what stops a tenant from *inserting/updating* a row into someone else's `business_id`.
- **Depends-on:** D0.1.
- **Effort:** S (function) — but its **correctness** is L-weight; treat with care.
- **Main risk:** A `SET` instead of `SET LOCAL` on a pooled connection leaks the tenant id to the next
  request on that connection — a cross-tenant leak. The contract DATA must hand BACKEND: **`SET LOCAL` in
  the same transaction as the query**, and reset/`DISCARD` on connection return. With PgBouncer in
  *transaction* mode `SET LOCAL` is safe; in *session* mode it is not — this must be verified with DEVOPS.
  ⚠️ **needs verification:** pooler mode.

### D0.3 — Field-encryption helpers + key management (PII key + WhatsApp KEK)
- **What:** Build the encryption module with **two separate key domains**:
  (1) **PII data key** for `leads.phone`, `leads.contact_name`, `leads.answers`,
  `whatsapp_connections.phone_number`; (2) **crown-jewel KEK** (envelope encryption: per-business DEK
  wrapped by a KEK in the secret manager) for `whatsapp_credentials.auth_state`. Also the
  **HMAC key** for `customer_phone_hash`. Authenticated encryption (AEAD). Every encrypt stamps a
  `key_version`; every decrypt selects the key by `key_version` and **fails LOUD** (raise + log + metric)
  — **no plaintext fallback, ever.** App **fails to start** if any required secret is missing (no
  `change-me` defaults).
- **Why:** Directly kills **M2** (the old `decrypt()` silently returned ciphertext "safe during
  migration" — masking key/rotation breakage and undetected plaintext PII). This is a **clean redesign,
  not a migration**, so there are *no legacy plaintext rows* and the fallback has zero excuse to exist.
  Two key domains = limited blast radius (a leaked PII key never exposes WhatsApp sessions, per the
  security review). Fixes the C1 lesson (keys out of `.env`).
- **Depends-on:** secret-manager vendor + KEK-in-KMS-vs-app decision (DEVOPS/AWS phase). Until then,
  develop against a local secret provider with the **same interface** so swapping the backend is trivial.
- **Effort:** M.
- **Main risk:** Designing the helper around a single key (the old Fernet shape) and retrofitting the
  second domain + `key_version` later. Build the multi-key, versioned interface from day one. Secondary
  risk: KEK custody — if the KEK ever lands in `.env` or the DB, the crown jewel is unprotected (the
  whole point of envelope encryption is the KEK never touches Postgres).

### D0.4 — Core schema migration: the 9 tables (structure + FKs + indexes)
- **What:** One ordered migration set creating all 9 tables exactly per `data-model.md`:
  `users` (text PK = Google `sub`, global), `businesses` (uuid PK = THE `business_id`),
  `business_members` (unique `(business_id, user_id)`), `whatsapp_connections` (unique `business_id`,
  unique `gateway_account_id`), `whatsapp_credentials` (PK = `business_id`, `auth_state bytea`,
  `key_version`), `bot_settings` (two `jsonb`: `lead_steps` + `bot_profile`, `is_published`),
  `leads` (PII + `status` lifecycle `in_progress→new/abandoned→read/archived`, `key_version`,
  `cache_chat_ref`, the three timestamps), `bot_builder_messages`, `flow_events` (FK `lead_id`).
  All FKs with the correct `ON DELETE` (CASCADE for tenant children; `SET NULL` for `created_by`).
  All indexes from the model — critically on `leads`: `(business_id, status)`,
  `(business_id, submitted_at DESC)`, **`(business_id, last_activity_at)`** (the abandoned sweep).
  `updated_at` trigger where rows mutate.
- **Why:** This is the persisted backbone. Getting `ON DELETE CASCADE` and the indexes right now avoids
  painful data migrations later. The `(business_id, last_activity_at)` index is what makes the
  abandoned-lead sweep cheap (decision 0006).
- **Depends-on:** D0.1 (roles/extensions), D0.2 (so RLS lands with each table).
- **Effort:** M.
- **Main risk:** Getting `whatsapp_credentials` grants wrong (the dashboard role must have **no grant at
  all** here — not even SELECT). Also: forgetting `WITH CHECK` on a table = silent write-side leak. Apply
  RLS + grants table-by-table in the same migration, never in a separate "add RLS later" pass.

### D0.5 — RLS policies + per-role grants on every tenant table
- **What:** Enable RLS and attach the D0.2 template (`USING` + `WITH CHECK`) to **all 8 tenant tables**
  (everything except global `users`, which gets a self-row policy keyed on the session user id). Grants:
  `gateway_role` → read/write `whatsapp_credentials` + `whatsapp_connections` only; `app_role` →
  everything tenant-scoped **except** `whatsapp_credentials` (zero grant). Force-RLS on table owners so
  even the table owner is subject to policy.
- **Why:** Defence-in-depth behind the mandatory app-level filter. With RLS + `business_id` on every
  table, a forgotten `WHERE business_id = …` (the old C3 `UPDATE … no WHERE`, C4 booking IDOR) is caught
  by the database instead of nuking/leaking every tenant. The split grants enforce the crown-jewel
  isolation the security review marks **non-negotiable**.
- **Depends-on:** D0.4, D0.2.
- **Effort:** M.
- **Main risk:** `whatsapp_credentials` is accidentally readable by `app_role` (the single most dangerous
  miss — it's full WhatsApp account takeover). Verify with an explicit negative test (D0.6): connect as
  `app_role`, `SELECT` it, assert permission-denied.

### D0.6 — Tenant-isolation test suite (the non-negotiable gate)
- **What:** Automated tests that prove isolation at the DB layer: (a) tenant A's session cannot read
  tenant B's rows in *any* tenant table; (b) tenant A cannot **insert/update** a row carrying tenant B's
  `business_id` (the `WITH CHECK` path); (c) with **no** session var set, every tenant table returns
  zero rows (deny-by-default, no fallback tenant); (d) `app_role` gets permission-denied on
  `whatsapp_credentials`; (e) decrypt with a wrong/missing key **raises** (never returns ciphertext);
  (f) a CI grep asserts `auth_state` / decrypted creds / a QR string never appear in a serialized
  response or log fixture.
- **Why:** Decision 0005 says the hand-wired RLS bridge "**must be covered by isolation tests**" — it was
  the old system's #1 failure point. These tests are the gate that lets us trust the invariant instead of
  hoping. They encode every MUST from the security review as an executable check.
- **Depends-on:** D0.5, D0.3.
- **Effort:** M.
- **Main risk:** Tests that pass because they accidentally run as a superuser/owner (which bypasses RLS) —
  giving false confidence. The suite **must** connect as `app_role`/`gateway_role`, exactly as production
  does. This is the highest-value test suite in the project; under-investing here re-opens C2/C3/C4.

### D0.7 — Redis setup + live-chat cache contract
- **What:** Provision Redis (dev + prod) and implement the live-chat cache layer per decision 0006:
  key `chat:{business_id}:{customer_phone_hash}` → `{status (bot/human/closed), assigned_user_id,
  last_activity_at, last ~10 messages}`, with a **~60-min sliding TTL** (= auto-close on silence).
  **App-layer tenant isolation** (Redis has no RLS): `business_id` baked into every key **and re-checked
  on every access** against the caller's verified business. Private network + auth (password/ACL) + TLS.
  Optional: encrypt message bodies in cache (belt-and-suspenders; default = rely on private net + short
  TTL).
- **Why:** Redis replaces the old volatile process-local state (fixes **B11**) and is shared across AWS
  instances so the bot process and dashboard see the *same* live chat (needed for handoff). The
  re-check-on-access rule is the *only* thing standing in for RLS here — the security review is explicit
  that the code is the guard.
- **Depends-on:** Redis provisioned (DEVOPS); D0.2 (the same verified `business_id` feeds both DB and
  cache); the HMAC helper from D0.3 (for `customer_phone_hash`).
- **Effort:** M.
- **Main risk:** A cache accessor that takes a `business_id` from the request without re-verifying
  membership = a cross-tenant cache leak with no RLS safety net. The accessor API must *require* the
  already-verified business context, never a raw client value. ⚠️ **needs verification:** open Q4 from
  data-model.md — encrypt bodies in Redis or not (decide with security).

---

## Phase 1 — MVP (the data behind leads + handoff + bot builder + try-me)

### D1.1 — Lead lifecycle persistence (in_progress → new / abandoned)
- **What:** The data access for the lead funnel: **create a `leads` row the moment the questionnaire
  starts** (`status='in_progress'`, `started_at`, `last_step_index=0`), update encrypted `answers` +
  `last_activity_at` + `last_step_index` as answers arrive, flip to `new` + set `submitted_at` on
  completion. `is_test` set from try-me. `cache_chat_ref` points at the live Redis key while active.
  All PII encrypted via D0.3 with `key_version` stamped.
- **Why:** This is the heart of the product loop and the explicit upgrade in decision 0006: **create the
  lead at start so abandoners are recoverable** ("keep the lead data, throw away the chatter"). It is what
  lets the owner see who dropped off and call them back.
- **Depends-on:** D0.4, D0.3, D0.7.
- **Effort:** M.
- **Main risk:** Writing the lead only on completion (the old behavior) — then abandoners are invisible
  and the whole abandoned-follow-up feature is impossible. The create-at-start ordering is load-bearing.

### D1.2 — Abandoned-lead sweep query + funnel events
- **What:** The periodic sweep: find `leads` where `status='in_progress'` AND
  `last_activity_at < now() - 60 min`, flip them to `abandoned`, and append a `flow_events` row
  (`event='abandoned'`, the `step_index` reached, `lead_id` set). Backed by the
  `(business_id, last_activity_at)` index. Append `started` / `step_completed` / `completed` events at the
  matching lifecycle points. (The sweep runs as a periodic job — scheduling owned by BACKEND/DEVOPS; the
  **query + the data contract** are owned here.)
- **Why:** `abandoned` detection is defined as a 60-min sweep over idle `in_progress` leads (decisions
  0005/0006). `flow_events` powers the dashboard funnel (started vs completed vs abandoned) and each
  `abandoned` row points at a lead holding the phone + partial answers to follow up.
- **Depends-on:** D1.1, D0.4.
- **Effort:** S–M.
- **Main risk:** A sweep that scans cross-tenant or runs without the index → full-table scans at scale.
  Also: the old `close_stale_conversations` had a malformed `INTERVAL '%s minutes'` bug (B26) — use
  `now() - make_interval(mins => …)` and parameterize cleanly. Keep `is_test` rows out of real funnel
  stats.

### D1.3 — `bot_settings` config persistence (two jsonb) + try-me/publish flag
- **What:** Read/write the per-business `bot_settings` row: `lead_steps` (the questionnaire shape) and
  `bot_profile` (name, system_prompt, tone, language), `handoff_keywords`, and `is_published`
  (drives **try-me vs live**). This is the config that **moves off disk into the DB** (old
  `system_prompt.json` + `menus_chat.json`).
- **Why:** decision 0004 makes the AI bot builder + try-me non-optional MVP; this table is where the
  builder writes and the engine reads. Moving config into Supabase kills the per-user-JSON-on-disk model
  and the single-tenant `client_001` config-file path (B18).
- **Depends-on:** D0.4.
- **Effort:** S.
- **Main risk:** Schema-drift between what the builder writes into `lead_steps` and what the engine
  expects to read — keep a documented JSON shape (and validate on write). Low data-layer risk; mostly a
  contract with BACKEND.

### D1.4 — `whatsapp_connections` + `whatsapp_credentials` persistence (crown jewel)
- **What:** Connection state-machine writes (`disconnected/connecting/qr_pending/connected`,
  `phone_number` encrypted, `gateway_account_id` bridge, `last_error`) via `gateway_role`; and the
  crown-jewel `whatsapp_credentials` upsert — `auth_state` envelope-encrypted (D0.3), `key_version`
  stamped, bumped on every Baileys `creds.update`. **QR is NOT persisted** (streamed to the dashboard
  over the authed channel). Decrypt fails loud; row never serialized, never logged.
- **Why:** Fixes **M1** (Baileys creds are plaintext JSON on disk today = account takeover). The split
  table + dedicated role + envelope encryption is the security review's "SAFE BY DESIGN" path. Not
  persisting the QR closes the C6 "/status leaked the live QR" class at the data layer.
- **Depends-on:** D0.4, D0.5 (grants), D0.3 (KEK). Gateway `accountId` derivation (WHATSAPP).
- **Effort:** M.
- **Main risk:** Wrong `gateway_account_id ↔ business_id` mapping = **cross-tenant inbound** (a message
  routed to the wrong business). ⚠️ **needs verification:** confirm the rebuilt gateway derives
  `accountId` from `business_id` (open Q2, data-model.md). Secondary: `creds.update` fires often → ensure
  the encrypted upsert is cheap and never logs the payload.

### D1.5 — Seed + test fixtures (tenant-aware, `is_test`-tagged)
- **What:** Deterministic seed/fixtures for two demo tenants (insurance agency + service pro, the first
  customers): users, businesses, memberships, a published `bot_settings`, a spread of leads across all
  statuses (`in_progress`/`new`/`abandoned`/`read`), matching `flow_events`, and a couple of live Redis
  chats. All test data tagged `is_test=true`. A teardown that wipes only test rows.
- **Why:** Needed to develop/demo the dashboard and to run the isolation suite (D0.6) against realistic
  multi-tenant data. `is_test` keeps fixtures out of real stats (mirrors the model's intent).
- **Depends-on:** D0.4, D1.1, D1.3.
- **Effort:** S–M.
- **Main risk:** Fixtures inserted via a superuser/service connection (bypassing RLS) so they don't
  exercise the real write path — defeating their purpose for the isolation tests. Seed through the same
  roles the app uses.

### D1.6 — Data-protection compliance at the data layer (Israeli Privacy Law)
- **What:** The data-layer pieces of launch-required data protection (Israeli Protection of Privacy Law /
  נגישות+privacy track): (1) a documented **data inventory** — what PII we hold (customer phone, name,
  answers; business phone), where, encrypted with which key, and the legal basis; (2) **deletion / erasure
  support** — `ON DELETE CASCADE` already removes a business's children, but add a tested
  **"delete a customer / lead"** path (hard-delete the `leads` row + its `flow_events` + purge the Redis
  key) and a **"delete a business / account"** path (cascade + crown-jewel wipe) to satisfy data-subject
  erasure; (3) **export** — a per-business export of that business's own data (leads + funnel) for
  data-subject access / portability; (4) **retention** — define how long `abandoned` leads persist before
  auto-purge (the chatter already auto-expires in Redis; persisted leads need a stated retention window).
- **Why:** Launch compliance is REQUIRED (Israeli privacy law). The encryption + RLS already cover
  *confidentiality*; this task covers the *rights* side (access, erasure, retention) that the law also
  requires, and it lives at the data layer because that's where deletion/export/retention are actually
  enforced. Doing it in MVP avoids a scramble at launch.
- **Depends-on:** D0.4, D0.3, D0.7. Final retention numbers + the privacy-policy text are a product/legal
  call (COMPLIANCE/Omer) — DATA implements whatever window is chosen.
- **Effort:** M.
- **Main risk:** Erasure that misses a copy — e.g. deletes the `leads` row but leaves the live chat in
  Redis, or leaves `flow_events`/cache pointers dangling. The delete path must cover **every** place a
  given customer's data can live (Postgres rows + Redis key). ⚠️ **needs verification:** retention window
  + whether export is self-serve in MVP or manual.

---

## Phase 2+ — post-MVP (back-office, booking, RAG, scale)

### D2.1 — Back-office data layer: safe cross-tenant admin reads
- **What:** The data foundation for the **FULL back-office** (manage businesses & users, support +
  impersonate, platform metrics, billing VIEW). At the data layer this means: (1) a **platform-admin
  identity** — an `is_platform_admin` flag on `users` (or a separate `platform_admins` table), kept
  **out of** the tenant model; (2) a **read-only admin DB role** (`admin_ro_role`) used *only* by
  back-office endpoints, with a **bypass-RLS-for-read** capability that is **audited** — admin reads do
  not set `current_business_id()` and so can read across tenants, **but never decrypt customer PII by
  default** (admin lists show counts/metadata, not lead phone/answers, unless an explicit, logged
  "reveal" action for support); (3) an **`admin_audit_log`** table (who/admin, action, target
  business_id, when) — append-only; (4) **impersonation** modeled as the admin *assuming a specific
  `business_id`* through the normal `current_business_id()` path (so impersonated reads are RLS-scoped to
  that one tenant), with the assumption logged.
- **Why:** The back-office is the one place that legitimately reads across tenants — which is exactly the
  capability the old system leaked by accident (C2/C3). So it gets a *separate, narrow, audited* role,
  never the app role and never the service key. Modeling impersonation as "assume one business_id" reuses
  the proven RLS path instead of inventing a second, untested cross-tenant code path. Keeping PII
  encrypted-by-default in admin views satisfies privacy law (support staff see what they need, not every
  customer's phone).
- **Depends-on:** D0.5 (RLS + roles), D0.6 (isolation tests extended to cover admin paths), D0.3
  (so "reveal PII" is an explicit, logged decrypt).
- **Effort:** L.
- **Main risk:** The admin role becomes a de-facto service key (broad cross-tenant read with casual PII
  decrypt) — re-creating the exact C2/C3 blast radius the rebuild exists to eliminate. Keep it read-only,
  PII-masked by default, every cross-tenant read audited, and covered by isolation tests. **This is the
  highest-risk Phase 2 item.**

### D2.2 — Billing data placeholder (hooks only, engine deferred)
- **What:** Reserve the data seam for billing **without building payments**: a minimal `plan` /
  `subscription_status` field on `businesses` (e.g. `trial`/`active`/`past_due`) and a documented place
  where a future `subscriptions` / `invoices` table will attach. The back-office **billing VIEW** reads
  these read-only. No payment-provider tables, no VAT/invoice logic now.
- **Why:** Roadmap is explicit: **billing engine is DEFERRED — reserve a place/hooks only**;
  invoicing/VAT compliance rides with billing later. A tiny status field lets the back-office show plan
  state and lets us gate features later without a schema rewrite.
- **Depends-on:** D0.4.
- **Effort:** S.
- **Main risk:** Over-building now (modeling invoices/VAT before the engine exists) and getting the shape
  wrong. Keep it to a status field + a documented seam; resist the urge to design the full billing schema.

### D2.3 — Booking tables (Phase 2 feature)
- **What:** Add `booking_settings` + `bookings` when booking lands — with **all customer PII encrypted**
  (`client_name`/`client_email`/`client_phone`), `business_id` on every row, RLS `USING`+`WITH CHECK`,
  and the booking update path filtered by `business_id`.
- **Why:** Booking is Phase 2 (decision 0004). The old booking tables stored client PII in **plaintext**
  (M5) and `update_booking_status` filtered by `id` only (C4 IDOR) — both must not reappear. The security
  review flags this as a MUST when bookings land.
- **Depends-on:** D0.3, D0.5.
- **Effort:** M.
- **Main risk:** Re-introducing M5 (plaintext booking PII) / C4 (IDOR) by copying the old schema. Apply
  the same encrypt + RLS rules as `leads` from the start.

### D2.4 — RAG tables + pgvector (Phase 3 feature)
- **What:** `rag_sources` + `brain_chunks` with `VECTOR(n)` embeddings, `business_id` on every row, RLS,
  and a per-business vector index. Supabase Storage for source files, tenant-scoped.
- **Why:** RAG is Phase 3 (decision 0004); pgvector + Storage are already reserved in the architecture.
  Tenant scoping must hold for vector search too (the old `brain_chunks` did filter by `business_id` —
  keep that, add RLS).
- **Depends-on:** D0.5; pgvector extension.
- **Effort:** M–L.
- **Main risk:** Cross-tenant retrieval (a similarity search that forgets the `business_id` filter returns
  another business's documents). RLS + mandatory filter on the vector query both required.

### D2.5 — Scale: retention, partitioning, key rotation drills
- **What:** Operational data-layer hardening: enforce the lead-retention purge (from D1.6) on a schedule;
  consider partitioning/archival for the highest-volume tables as data grows; and **exercise key
  rotation** end-to-end (bump `key_version`, re-encrypt rows, retire the old key) for both the PII key and
  the WhatsApp KEK, proving the fail-closed decrypt + `key_version` selection actually work under
  rotation.
- **Why:** `key_version` exists precisely so rotation is safe; an unrehearsed rotation is the kind of
  thing that re-introduces the M2 "wrong key, silent garbage" failure. Retention + archival keep the
  encrypted PII footprint (and cost) bounded as the platform grows.
- **Depends-on:** D0.3, D1.6, real traffic.
- **Effort:** M (ongoing).
- **Main risk:** A rotation that half-completes (some rows on the new key, some on the old) with no clean
  way to tell which — mitigated by `key_version` per row, but only if rotation is scripted and tested, not
  done by hand under pressure.

---

## Cross-cutting MUST list (carried from the security review — these gate the build)

These are not separate tasks; they are invariants every task above must honour (from
`database-schema-security-review.md`, consolidated):

1. App connects as a **non-service role** for all tenant queries (else every RLS policy is dead).
2. **RLS `USING` + `WITH CHECK`** on `business_id = current_business_id()` on every tenant table.
3. App-level `business_id` filter stays **mandatory** (RLS is the *second* fence); verify `business_id`
   against `business_members`; never trust it from the client.
4. `whatsapp_credentials`: envelope-encrypted (KEK separate from PII key, in the secret manager),
   dedicated role, **dashboard role has zero grant**, never returned, never logged, decrypt fails loud.
5. **Decryption fails LOUD / fail-closed everywhere; no plaintext fallback** (kills M2).
6. **All secrets in a secret manager** (PII key, KEK, HMAC key, DB creds, session/OAuth); fail startup if
   a required secret is missing (kills M3).
7. **No mid-flow customer PII in cleartext** — partial answers live in encrypted `leads.answers`; Redis
   holds only the short-lived live chat.
8. **No anonymous fallback tenant; deny-by-default** when the session var is unset (kills C2).
9. **CI guard:** fail the build if `auth_state`, decrypted creds, or a QR appear in any response or log.

---

## Summary (the tight version)

**Phases**
- **Phase 0 — Foundations:** migration tooling + two non-service roles; the `current_business_id()` RLS
  bridge; the dual-key encryption helpers (PII key + WhatsApp KEK, `key_version`, fail-loud); the 9-table
  migration; RLS + grants on every tenant table; the **tenant-isolation test suite** (the gate); Redis
  live-chat cache with app-layer isolation.
- **Phase 1 — MVP:** lead lifecycle (create-at-start → abandoned); the abandoned-sweep query + funnel
  events; `bot_settings` config persistence; crown-jewel `whatsapp_credentials` + connection state;
  tenant-aware seed/fixtures; **data-protection compliance** (inventory, erasure, export, retention).
- **Phase 2+ — post-MVP:** back-office **safe cross-tenant admin reads** (read-only audited role +
  impersonation-as-assume-business_id + admin audit log); billing **placeholder hooks** (engine deferred);
  booking tables (encrypted, RLS); RAG + pgvector (tenant-scoped); scale (retention, partitioning, key
  rotation drills).

**The 5–8 biggest tasks**
1. `current_business_id()` RLS bridge — the hand-wired isolation core (D0.2).
2. Dual-key field-encryption + key management, fail-loud, `key_version` (D0.3).
3. The 9-table migration with FKs + indexes (D0.4).
4. RLS policies + per-role grants on every tenant table, incl. crown-jewel isolation (D0.5).
5. The tenant-isolation test suite — the non-negotiable gate (D0.6).
6. Redis live-chat cache + the abandoned-lead sweep query (D0.7 + D1.2).
7. Lead lifecycle persistence: create-at-start → abandoned follow-up (D1.1).
8. Back-office safe cross-tenant admin reads (D2.1, Phase 2).

**Top risk**
The hand-wired RLS / `current_business_id()` bridge is the whole product's tenant boundary, and it can
fail *silently*: a `SET` instead of `SET LOCAL` on a pooled connection, the app connecting with the
service role, or a missing `WITH CHECK` each re-opens the exact cross-tenant leak (C2/C3/C4) that killed
the old system. It is mitigated only by treating D0.6 (the isolation test suite, run as the real
non-service roles) as a hard build gate — plus confirming the connection-pooler mode is compatible with
`SET LOCAL` (⚠️ needs verification with DEVOPS).
