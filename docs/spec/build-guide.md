# Build Guide — per part (steps + things to know)

> A quick-reference "how to build each part" cheat-sheet, distilled from the 7 domain roadmaps in
> [`roadmap-parts/`](roadmap-parts/) and sequenced by the master [`roadmap.md`](roadmap.md).
> Each part has **Build steps** (ordered, phase-tagged) and **Things to know** (the facts/gotchas that
> matter while building it). Phase tags: **[P0]** Foundations · **[P1]** MVP · **[P2]** Back-office ·
> **[P3]** Booking · **[P4]** RAG · **[P5]** Scale. Full detail (why/depends-on/risk per task) is in the
> linked part file.

---

## 🧠 Backend — FastAPI / LangGraph (the brain) · [backend.md](roadmap-parts/backend.md)
*The API, the conversation engine, the WhatsApp in/out, and the back-office APIs.*

**Build steps**
1. **[P0]** App package (routers / services / core) + **fail-closed secrets loader** (kill the one-giant-`main.py`).
2. **[P0]** DB session as a **non-service role** + per-request `SET LOCAL business_id` (so RLS works).
3. **[P0]** Google OAuth login + **ownership check** (`business_members`); OAuth CSRF state in Redis.
4. **[P0]** Crypto module — PII key + crown-jewel envelope encryption, **fail-loud decrypt**.
5. **[P0]** Redis live-chat layer (key per `business_id`, re-checked on every access).
6. **[P0]** Structured logging + **CI guard** (no secret/PII/QR in logs or responses).
7. **[P0]** **Tenant-isolation test suite** — the exit gate.
8. **[P1]** `bot_settings` config service (the two jsonb: `lead_steps` + `bot_profile`).
9. **[P1]** Conversation engine (LangGraph on Redis) — **lead-collection flow**.
10. **[P1]** **Human handoff** (flip status in Redis; owner replies from dashboard).
11. **[P1]** **Lead lifecycle** — create at start → `new`/`abandoned` + funnel events.
12. **[P1]** **Abandoned sweep** (60-min, single-runner).
13. **[P1]** **Inbound webhook** (Baileys payload, tenant-routed by `accountId`, gateway-authed).
14. **[P1]** **Outbound sender** + Gemini replies (`google-genai` SDK).
15. **[P1]** WhatsApp connect lifecycle API (QR state machine).
16. **[P1]** AI-assist endpoints (Gemini proxy for the builder).
17. **[P1]** Try-me endpoint (same engine, no WhatsApp).
18. **[P1]** Dashboard read APIs (leads, abandoned list, live conversations, funnel).
19. **[P1]** Enforced deny-by-default auth gate + rate limits (every route).
20. **[P2]** Back-office APIs (manage businesses/users, **support/impersonate + audit**, metrics, billing-view).
21. **[P2]** Data-subject **export/delete** + consent (privacy law). **[P3]** Booking engine. **[P4]** RAG.

**Things to know**
- Stack is **locked**: FastAPI + Google OAuth (hand-wired RLS, *not* Supabase Auth); Baileys gateway; model `gemini-3.1-flash-lite` via `google-genai`.
- ⚠️ **Top gotcha:** `SET LOCAL business_id` must run in the **same transaction** as the query, or a pooled connection leaks one tenant's data to another. This is *the* #1 risk.
- **Persist the lead, throw away the chatter** — live chat lives in Redis; the `lead` row is created at questionnaire *start* so abandoners are recoverable.
- **Decrypt fails loud** — never return ciphertext-as-plaintext (the banned old behavior).
- The `accountId ↔ business_id` mapping **is** the tenant boundary for inbound — confirm it with the gateway.
- The WhatsApp **receive path was never verified** — needs one real end-to-end test (it's the riskiest unknown).

---

## 🎨 Frontend — React + Tailwind · [frontend.md](roadmap-parts/frontend.md)
*Everything the owner, the public visitor, and the platform admin see.*

**Build steps**
1. **[P0]** Scaffold Vite + React 18 + Tailwind + **RTL Hebrew** (one theme, not 3).
2. **[P0]** App shell + **AuthGate** + cookie-session API client (+ the shared AI-response parser).
3. **[P0]** **Accessibility foundation** (WCAG / נגישות) + a CI a11y gate.
4. **[P0]** **Terms / Privacy** pages + consent + data-rights UX hooks.
5. **[P0]** Shared UI kit (dates, slots, calendar, toast, buttons, fields).
6. **[P1]** Login screen + owner header (connection status pill).
7. **[P1]** **WhatsApp QR onboarding** (live QR over the authed channel; never stored).
8. **[P1]** Leads dashboard + **funnel** (started → completed → abandoned).
9. **[P1]** Leads table + the **abandoned-lead follow-up list**.
10. **[P1]** Conversations + **bot↔human toggle** (live, Redis-backed).
11. **[P1]** **AI bot builder** (port `botbuilder.html` → real Vite/Tailwind route).
12. **[P1]** **Try-me** test chat (drive the real engine; `is_test`).
13. **[P1]** Publish / go-live control + loading/empty/error states.
14. **[P2]** Back-office admin UI: shell + **role gate**, manage businesses/users, support + **impersonate**, metrics, **billing-view placeholder**.
15. **[P3]** Booking: public page + owner calendar. **[P4]** RAG knowledge-builder tab. **[P5]** Perf + **pre-launch a11y audit**.

**Things to know**
- **Keep the API contract byte-for-byte** with `frontend-map.md`, with 3 conscious fixes: send `date_from`/`date_to` (B8); **drop the dead `GET /api/config`** call (B9); replace the `/botbuilder` iframe with a real route.
- **No secrets in the frontend** — it talks only to FastAPI (same-origin cookie session); it never holds the gateway token or the WhatsApp `auth_state`. Never trust a client-supplied `business_id`.
- **RTL Hebrew from commit #1** — retrofitting it is painful.
- **Accessibility is a launch blocker** (Israeli law) — built in, gated in CI, not bolted on.
- The two riskiest screens — **QR onboarding** and **live conversations** — depend on backend realtime contracts that don't exist yet. Build the builder/leads/try-me while those firm up.

---

## 🗄️ Data — Supabase (Postgres) + Redis · [data.md](roadmap-parts/data.md)
*The 9 tables, the tenant wall (RLS), encryption, and the live-chat cache.*

**Build steps**
1. **[P0]** Migration tooling + **two non-service DB roles** (`app_role`, `gateway_role`) + `pgcrypto`.
2. **[P0]** `current_business_id()` bridge + the standard **RLS policy template** (`USING` + `WITH CHECK`).
3. **[P0]** Encryption helpers — **PII key + crown KEK** (envelope) + HMAC, `key_version`, **fail-loud**.
4. **[P0]** The **9-table migration** (FKs, `ON DELETE`, indexes — incl. `(business_id, last_activity_at)`).
5. **[P0]** RLS + per-role **grants** on every tenant table (dashboard role gets **zero** grant on the crown jewel).
6. **[P0]** **Tenant-isolation test suite** (the gate).
7. **[P0]** Redis live-chat contract (key per business, ~60-min TTL).
8. **[P1]** Lead lifecycle persistence (create-at-start → abandoned).
9. **[P1]** Abandoned-sweep query + funnel events.
10. **[P1]** `bot_settings` persistence (the two jsonb). 
11. **[P1]** `whatsapp_connections` + crown-jewel `whatsapp_credentials` persistence.
12. **[P1]** Seed/test fixtures (two demo tenants, `is_test`).
13. **[P1]** Data-protection at the data layer (inventory, **erasure**, export, retention).
14. **[P2]** Back-office safe cross-tenant reads (audited read-only role + `admin_audit_log` + impersonation-as-assume-`business_id`); billing placeholder field. **[P3]** Booking tables. **[P4]** RAG + pgvector. **[P5]** retention/partitioning + rotation drills.

**Things to know**
- **`data-model.md` is the source of truth** (9 tables + Redis).
- The invariant: **`business_id` everywhere + filter + RLS (USING + WITH CHECK) + verify ownership + non-service role.**
- `SET LOCAL` (not `SET`); the connection pooler must run in **transaction mode** (verify with devops).
- `whatsapp_credentials`: own table, envelope-encrypted, **gateway role only** — dashboard role can't even `SELECT`.
- **Seed through the real app roles**, not a superuser — or the isolation tests prove nothing.

---

## 💬 WhatsApp gateway — Node / Baileys · [whatsapp.md](roadmap-parts/whatsapp.md)
*From "a customer message arrives" to "it reaches the backend", and replies back out.*

**Build steps**
1. **[P0]** Clean gateway skeleton (pinned deps, fail-closed, redacted logs, `/healthz`).
2. **[P0]** **Freeze the gateway↔backend contract** (inbound/outbound shapes, header auth, idempotency).
3. **[P0]** Multi-session manager spike (one session per business).
4. **[P0]** ⚠️ **End-to-end RECEIVE smoke test — DO THIS FIRST.**
5. **[P0]** Envelope-crypto design for the session creds.
6. **[P1]** **QR linking flow** (multi-session onboarding).
7. **[P1]** Encrypted cred persistence (the crown jewel, wired to the DB).
8. **[P1]** The **`accountId ↔ business_id` bridge**.
9. **[P1]** Hardened inbound receive (idempotent on `message_id`, graceful non-text).
10. **[P1]** **Stable authed channel — kill ngrok** (header-only token).
11. **[P1]** Reconnection/reliability (backoff + jitter, logout handling, persistent webhook URL).
12. **[P1]** Outbound send + **rate-limiting** (E.164 numbers; the ban-risk mitigation).
13. **[P1]** Try-me support (gateway stays *out* of the loop for test chats).
14. **[P1]** Compliance edge (data minimization + log redaction).
15. **[P2]** Back-office connection health/metrics. **[P5]** Horizontal-scale single-writer sharding; cred key-rotation + DR.

**Things to know**
- **Baileys is unofficial → ban risk is structural** (only mitigated): conservative send rate-limits + one number per business + backoff (never a reconnect hot-loop).
- The **receive path has never been verified** — spike it in week one; if it fails, the roadmap shifts.
- The gateway stays **tenant-agnostic** — it knows `accountId`, never `business_id` (the backend maps it).
- **One session = one writer.** Two instances writing one session corrupts the creds (looks like a ban) — this caps the gateway at a single instance until [P5] sharding.
- The **QR is never stored**; `auth_state` is never logged or returned by any API.

---

## 🧱 Infra — local dev, CI, isolation harness · [infra.md](roadmap-parts/infra.md)
*"Make it runnable, repeatable, and safe to develop on."*

**Build steps**
1. **[P0]** Monorepo structure (`backend/` `gateway/` `frontend/` `infra/` `supabase/` `tests/`).
2. **[P0]** `docker-compose` local stack with **health-gated** startup (no blind sleeps).
3. **[P0]** **Pinned, baked-in deps** — install at build time; drop RAG-only deps; move to `google-genai`.
4. **[P0]** **Secrets out of `.env`** → manager, fail-on-missing, **no `change-me` defaults**.
5. **[P0]** Portable entrypoints + a `Makefile` (`make dev|test|lint|isolation|migrate|seed|down`).
6. **[P0]** DB migrations + **RLS bootstrap + roles** in the local DB (mirrors prod).
7. **[P0]** **The multi-tenant isolation test harness** (the flagship deliverable).
8. **[P0]** **CI pipeline** — lint + tests + **isolation gate** + secret-leak grep (all blocking).
9. **[P1]** Gateway↔backend wired in compose + the **e2e receive test** (throwaway number).
10. **[P1]** Redis live-chat + abandoned sweep wiring (+ isolation coverage).
11. **[P1]** Externalize OAuth CSRF state to Redis (B12); finish the `google-genai` swap (B16).
12. **[P1]** Compliance infra (servable Terms/Privacy, secure session cookies, a **delete-flushes-Redis** hook).
13. **[P2]** Back-office admin/impersonate role + isolation-harness extension. **[P3/P4]** booking/RAG infra. **[P5]** parity hand-off to devops.

**Things to know**
- Target: **one `make dev`** brings up backend + gateway + frontend + Redis + Supabase, health-gated.
- **Local mirrors prod** so "works on my machine" = "works in the container."
- In **CI use a lightweight `postgres` + `redis`** (not the heavy Supabase stack) to stay fast.
- ⚠️ **Top risk = false confidence:** the isolation harness must connect as the **real non-service role** (not a superuser) and include a forgotten-`WHERE` canary, or a green test hides a real leak.
- You're on Windows → use WSL2 + `.gitattributes` (LF) + named volumes to avoid Docker friction.

---

## ☁️ DevOps / AWS — production platform · [devops-aws.md](roadmap-parts/devops-aws.md)
*Provision and wire the cloud: compute, network, secrets, data services, CI/CD, monitoring.*

**Build steps**
1. **[P0]** AWS account baseline — region (EU suggested), **root MFA**, CloudTrail, IAM.
2. **[P0]** **Budget alarm on day one** (→ your email).
3. **[P0]** VPC (public + private subnets, security groups; watch NAT-gateway cost).
4. **[P0]** **Secrets Manager + KMS** key (the crown-jewel KEK); **rotate every old `.env` secret**.
5. **[P0]** ECR repos (backend, gateway). 
6. **[P0]** CI/CD (build → push → deploy via GitHub OIDC; secret-leak gate).
7. **[P1]** Containerize backend (pinned, no `--reload`, healthcheck, non-root).
8. **[P1]** ⭐ Containerize the **gateway** — single-writer service + **DB-backed, KMS-encrypted creds** (hardest task).
9. **[P1]** **ALB + ACM HTTPS + Route53** (kills ngrok; needed for OAuth + TLS).
10. **[P1]** ECS/Fargate services — **split scaling** (backend autoscales; **gateway locked to desired=1**).
11. **[P1]** **ElastiCache Redis** (private subnet, TLS, AUTH).
12. **[P1]** CloudWatch logs + alarms (gateway-down alarm = revenue-impacting); no-secrets-in-logs.
13. **[P1]** Verify secrets fail-closed + least-privilege IAM/KMS grants (dashboard task can't decrypt the KEK).
14. **[P2]** Back-office metrics dashboard + impersonation-audit infra; compliance hosting (HTTPS/HSTS, retention/deletion, residency). **[P3]** booking WAF. **[P4]** RAG compute. **[P5]** S3+CloudFront frontend, horizontal scale + gateway sharding, **IaC (Terraform/CDK)**.

**Things to know**
- **Budget alarm first** — a runaway task, NAT gateway, or Gemini loop can quietly burn money (solo project).
- **Never autoscale the gateway** — more than one instance = duplicate WhatsApp sockets = bans. Single-writer until [P5] sharding.
- **KEK lives in KMS**, separate from the PII key; treat all old `.env` values as compromised and re-issue.
- **DB stays on Supabase for the MVP** (don't migrate to RDS now).
- Decisions already made: KMS for the KEK · ElastiCache Redis · ALB+ACM+Route53 · ECS Fargate · Supabase for MVP.
- 🙋 Needs you: AWS region/residency · do you own a domain? · GitHub for CI? · Terraform vs CDK (later).

---

## 🛡️ Security — the spine across everything · [security.md](roadmap-parts/security.md)
*"Build it so the old leaks cannot exist," then guard it with tests.*

**Build steps**
1. **[P0]** **Secrets out of `.env` + rotate all** + a startup presence check (ban `change-me`/`my-secret-token`/`secret`).
2. **[P0]** **Enforced auth gate** on every route — **no anonymous-tenant fallback**.
3. **[P0]** **Hand-wired RLS** on every tenant table (`USING` + `WITH CHECK`).
4. **[P0]** **Least-privilege DB roles** (dashboard vs gateway; crown-jewel isolation).
5. **[P0]** Encryption + **fail-loud decrypt** (PII key + crown KEK).
6. **[P0]** **The isolation test suite** — incl. **pooling/concurrency** + Redis + a negative-control test.
7. **[P0]** **CI secret/PII guard** (fail the build on any leak in logs/responses).
8. **[P0]** **Gateway transport hardening** (strong token, header-only, locked CORS, authed `/status`, no stored QR, encrypted creds).
9. **[P1]** **Webhook authenticity** (HMAC the gateway→backend call).
10. **[P1]** Input validation + **treat LLM I/O as untrusted** (prompt-injection, public-write validation).
11. **[P1]** **Israeli privacy-law data-protection** (consent / access / delete / retention).
12. **[P1]** Owner session/CSRF hardening (secure cookies, generic errors).
13. **[P2]** Platform-admin role + **impersonation safety + append-only audit log**; billing-view access. **[P3]** booking security (closes C4/M5). **[P4]** RAG isolation + upload safety. **[P5]** rate-limit/abuse + key-rotation drills.

**Things to know**
- It's a **clean rebuild** → "fix C2" means "build so C2 can't exist," and there are **no legacy plaintext rows** (so no decrypt fallback is needed).
- ⚠️ **#1 risk:** hand-wired RLS leaking via **connection pooling**. The isolation suite (with pooling cases) is the gate that proves it doesn't.
- **Foundations land before the MVP touches real PII** — secrets, auth, RLS, encryption are prerequisites, not a later hardening pass.
- The **back-office / impersonation** is the highest blast radius after the KEK — must be read-only-by-default, PII-masked, **audited**, and isolation-tested.
- Compliance + back-office security **ride their features** (built with them, not bolted on at the end).

---

## The one cross-cutting truth
Every part keeps pointing at the **same single thing**: the **multi-tenant wall** — `business_id` everywhere,
RLS with a non-service role, the `accountId↔business_id` routing, and the audited back-office path — all proven
by **one isolation test suite that's a hard CI gate**. Get that right and the rest is ordinary engineering;
get it wrong and you rebuild the old system's #1 failure. Everything in [P0] exists to make that wall real.
