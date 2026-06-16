# Master Build Roadmap — Bizz_up (production)

> The single, ordered plan to build Bizz_up and take it **online**. Synthesized by the main agent from the
> 7 domain roadmaps in [`roadmap-parts/`](roadmap-parts/) (backend, frontend, data, whatsapp, infra,
> devops_aws, security). Date: 2026-06-16. Reflects decisions 0001–0006 + Omer's roadmap answers
> (MVP-first; full back-office; **billing engine deferred**; launch compliance = accessibility + Terms/Privacy
> + data-protection; pace = solo + Claude, steady).
>
> **How to read:** phases are sequential; inside a phase, work runs in parallel across domains. Effort:
> **S** ≈ a sitting · **M** ≈ a day or two · **L** ≈ several days (solo + Claude). Full task detail (the
> "why / depends-on / risk" for every item) lives in the per-domain files under `roadmap-parts/`.

---

## The golden thread (the 5 things that drive the whole plan)

1. **Foundations before features.** Secrets-out, the auth gate, the tenant wall (RLS + roles), and encryption
   are *prerequisites* for touching real customer data — not a hardening pass at the end. The old system died
   from skipping this.
2. **The isolation test suite is a hard gate.** Multi-tenant isolation is hand-wired (decision 0005) and was
   the old system's **#1 failure**. Nothing tenant-scoped ships until that suite is green in CI.
3. **Retire the biggest unknown first.** The WhatsApp **receive path was never verified end-to-end**
   (decision 0001). A throwaway "does a message even arrive?" spike happens in **week one** — if it fails, it
   reshapes everything.
4. **The gateway is special.** Baileys = one *stateful* socket per business. It runs **single-writer**
   (one instance) until we build session-sharding; its ban-risk is *mitigated, never eliminated*.
5. **Compliance is woven in, not bolted on.** Accessibility, Terms/Privacy, and data-protection land *by
   launch* (through Phases 0–1), because they're legally required to go online.

---

## Phases at a glance

| Phase | Goal | Done when |
|---|---|---|
| **0 — Foundations** | A safe, repeatable platform + the security spine | One command runs the whole stack; isolation suite green in CI; secrets in a vault (fail-closed); the receive spike passes |
| **1 — MVP + Launch** | First real business live on WhatsApp | Owner builds a bot → tests it → scans QR → receives msgs → collects leads (incl. abandoned follow-up) → handoff works; live on a stable HTTPS domain; launch-compliance met |
| **2 — Back-office** | Operate the platform (full admin) | You can manage tenants, support + impersonate (audited), and see platform metrics |
| **3 — Booking** | Real appointment booking | Chat + link flows create real, isolated, encrypted bookings (old IDOR/fake-booking gone) |
| **4 — RAG** | Answer from the business's own content | Grounded answers, strictly tenant-isolated retrieval |
| **5 — Scale & Harden** | Many businesses, HA, IaC | Gateway sharding, Multi-AZ, Terraform/CDK, rotation drills |
| **Deferred — Billing** | Monetize | Subscriptions + invoicing/VAT, cards via a PCI provider (never stored) |

---

## Phase 0 — Foundations

**Goal:** a fresh clone runs with one command, CI is green, secrets are safe, and the tenant wall is proven —
the base every feature stands on.

| Domain | Key tasks | Effort |
|---|---|---|
| 🧱 Infra | Monorepo (backend/frontend/gateway) + **docker-compose** with **health-gated** startup (kills B13); **pinned, baked-in deps** + drop RAG-only deps + migrate to `google-genai` (kills B2/B16); portable Makefile (kills B14) | S–M, M, S |
| 🗄️ Data | `current_business_id()` **RLS bridge**; 9-table migration (FKs + indexes); RLS `USING`+`WITH CHECK` + per-role grants; **dual-key encryption** (PII key + WhatsApp KEK, `key_version`, **fail-loud**) | S✦, M, M, M |
| 🛡️ Security | **Secrets out of `.env` + rotate all** + presence check; **enforced auth gate** (no anonymous-tenant fallback); **least-privilege DB roles**; **gateway hardening** (token/CORS/QR); **CI secret/PII guard** | M ×5 |
| 🧪 Infra+Data+Sec | **The multi-tenant ISOLATION TEST SUITE** — DB/RLS + API + Redis + crown-jewel no-read + secret-in-logs; **blocking in CI** | **L (the flagship)** |
| ☁️ DevOps | AWS account + region + root MFA; **Budget alarm day one**; VPC (private subnets); **Secrets Manager + KMS** (KEK); ECR; CI/CD (build→push→deploy, OIDC) | S, S, M, M, S, M |
| 💬 WhatsApp | Clean gateway skeleton (pinned, fail-closed, redacted logs); **freeze the gateway↔backend contract**; multi-session spike; **⚠️ end-to-end RECEIVE smoke test (FIRST)**; envelope-crypto design | M, S, M, **S✦**, M |
| 🧠 Backend | App skeleton (kill the one-giant-`main.py`) + fail-closed secrets loader; Google OAuth + `business_members` ownership check; crypto wiring; Redis cache layer | M ×4 |

✦ = small to build, but **correctness-critical** — treat with care.
**Exit gate:** `make dev` brings the stack up healthy on any host • isolation suite + secret-leak check green in CI • the receive spike proves a real WhatsApp message reaches a backend stub.

---

## Phase 1 — MVP + Launch

**Goal:** the full loop — **build (with AI) → test (try-me) → go live (QR) → collect leads → hand off** — working
for a real business, on a stable HTTPS domain, meeting launch compliance.

| Domain | Key tasks | Effort |
|---|---|---|
| 🧠 Backend | **Conversation engine (LangGraph on Redis)** for leads + handoff; **lead lifecycle** (create-at-start → new/abandoned) + the **60-min sweep**; AI-assist (Gemini proxy); webhook receiver + sender | L, M, M, M |
| 💬 WhatsApp | **QR linking (multi-session)**; encrypted cred persistence (crown jewel, wired); **`accountId↔business_id` bridge**; hardened **receive**; **stable authed channel (kill ngrok)**; reconnect/backoff; **send + rate-limit** (ban mitigation); try-me support; log-redaction | L, M, M/S, M, M, M, M, S, S |
| 🎨 Frontend | Scaffold + **accessibility foundation** + Terms/Privacy pages; **QR onboarding**; leads dashboard + **abandoned-follow-up list** + funnel; **live conversations + bot↔human**; **AI bot builder** (port `botbuilder`); **try-me**; publish/go-live | M, M, M, L, L, M, S |
| 🗄️ Data | Lead lifecycle persistence; abandoned-sweep query + funnel events; `bot_settings` persistence; crown-jewel + connection state; seed fixtures; **data-protection** (export / delete / retention) | M, S–M, S, M, S–M, M |
| ☁️ DevOps | Containerize backend; **containerize gateway (single-writer + DB-backed KMS-encrypted creds)**; **ALB + ACM + Route53**; ECS services (split scaling); **ElastiCache Redis**; CloudWatch logs/alarms; secrets fail-closed verify | M, **L**, M, M, S, M, S |
| 🛡️ Security | Webhook authenticity (Baileys-adapted); input validation + untrusted-LLM posture; **Israeli privacy-law data-protection**; owner session/CSRF hardening | S–M, M, M, S–M |

**Exit gate (= public launch readiness):** a real owner builds a bot, tests it in try-me, scans the QR, a real
customer message arrives and a lead is captured (abandoners recoverable), handoff works, replies go out reliably
— all on a stable HTTPS domain, with Terms/Privacy live, accessibility in place, and data-subject delete/export working.

---

## Phase 2 — Back-office (FULL)

**Goal:** operate the platform yourself — manage tenants, support them, see health — **without** re-opening the
cross-tenant leaks. The back-office is the one place that *legitimately* crosses tenants, so it gets a separate,
narrow, **audited** path (never the old service-key god-mode).

| Domain | Key tasks | Effort |
|---|---|---|
| 🛡️ Security | **Platform-admin role** + privileged access model; **impersonation safety + append-only audit log**; billing-VIEW access control + reserved hooks | L, M–L, S |
| 🗄️ Data | Safe **cross-tenant admin reads** (read-only audited role, PII-masked by default); **impersonation = "assume one `business_id`"** via the proven RLS path; `admin_audit_log`; billing status field (placeholder) | L, S |
| 🧠 Backend | Back-office APIs: manage businesses/users, support/impersonate (audited), platform metrics | M–L |
| 🎨 Frontend | Back-office admin UI: manage tenants/users, support + impersonate, metrics, **billing-view placeholder** | L |
| ☁️ DevOps | Platform-metrics data path + **CloudWatch ops dashboard**; impersonation **audit infrastructure** | M, S |
| 🧪 Infra | Admin/impersonate role in migrations; **extend the isolation suite** to admin + impersonation (proves old C3 stays closed) | M |

**Exit gate:** you can onboard, manage, and support businesses; every cross-tenant/impersonation action is
scoped, PII-masked-by-default, and audited; the isolation suite covers the admin paths.

---

## Phase 3 — Booking (the first post-launch feature)

Real appointment booking — fixing the old "chat flow doesn't actually book" (B7), the cross-tenant booking
modification (C4 IDOR), and plaintext booking PII (M5).

- 🗄️ **Data:** `booking_settings` + `bookings`, **all client PII encrypted**, `business_id` + RLS (`USING`+`WITH CHECK`). (M)
- 🧠 **Backend:** booking engine — chat flow creates a real, slot-checked booking; the link flow keeps working. (M)
- 🎨 **Frontend:** public booking page + the owner's calendar/schedule views. (M–L)
- 🛡️ **Security:** encrypt booking PII; add booking to the isolation suite (the C4 case); validate the **public** form + verify the slug is a provisioned business (M4); fold into retention/deletion. (M)
- ☁️ **DevOps:** **WAF / rate-limit** on the public booking write path (it's unauthenticated). (S)
- 💬 **WhatsApp:** reliably send booking links. (part of WA-2.4)

---

## Phase 4 — RAG (answer from the business's own content)

- 🗄️ **Data:** `rag_sources` + `brain_chunks` (pgvector), per-tenant, RLS, tenant-scoped vector index. (M–L)
- 🧠 **Backend:** grounded retrieval (zero invention); auth + rate-limit on the rebuild/index op (old `/admin/rebuild-rag` was an unauth DoS). 
- 🎨 **Frontend:** knowledge-base builder (upload files / add URLs).
- 🛡️ **Security:** **tenant-isolated retrieval** (no cross-tenant context bleed) + upload safety; RAG case in the isolation suite. (M–L)
- ☁️ **DevOps / Infra:** **heavy ML deps quarantined** (separate worker/image or a managed embedding API) so the chat path stays lean; Storage for source files; async ingestion. (L)

---

## Phase 5 — Scale & Harden (when one business becomes many)

- 💬 **WhatsApp:** **horizontal-scale session model** — each session served by exactly one instance (sharding/lease), safe hand-off on deploy. *The hardest scaling problem.* (L)
- ☁️ **DevOps:** Multi-AZ Redis; backend autoscaling; RDS-vs-Supabase revisit; **Infrastructure-as-Code (Terraform or CDK)** to codify the proven platform. (L)
- 🛡️ **Security / Data:** rate-limit/abuse controls; **key-rotation drills** (PII key + crown KEK, end-to-end); retention/partitioning at volume. (M)

---

## Deferred — Billing engine

Per Omer: **not built now**, only a **place reserved** (a `subscription_status` field on `businesses`; the
back-office shows a billing *view*). When it's time to monetize:
- Pick a provider (Stripe / Paddle / an Israeli gateway) — **cards are tokenized by the provider, never stored by us** (PCI stays out of our DB).
- Subscriptions + invoices; **invoicing / VAT compliance** (חשבונית/מע״מ) rides here.
- The back-office billing view goes live; usage signals (e.g. WhatsApp volume) are already attributable per business.

---

## Compliance track (required by launch — woven through Phases 0–1)

| Item | Where it lives | Phase |
|---|---|---|
| **Accessibility (נגישות / WCAG)** | Frontend foundation + CI a11y gate | 0 → 1 |
| **Terms of Service + Privacy Policy** | Frontend pages (content = legal); served over HTTPS | 1 |
| **Data protection (Israeli Privacy Law)** | Data + Security: encryption, access control, **consent / access / delete / retention** | 1 |
| **HTTPS + data residency** | DevOps: ACM/HSTS + EU region choice | 0 → 1 |
| **Invoicing / VAT** | rides with **billing** | Deferred |

> Backups are the sneaky gap: a "deleted" lead must not survive in a DB snapshot — deletion handling must cover
> backups + the Redis cache, not just the live row.

---

## Top cross-cutting risks (the things most likely to bite)

1. **Hand-wired tenant isolation leaking** — RLS depends on a per-request `SET LOCAL app.business_id`; a pooled
   connection reusing a prior value, the app using a service role, or a missing `WITH CHECK` silently re-opens
   the old cross-tenant leak. **Mitigation:** the isolation suite (with pooling/concurrency + a negative-control
   test) as a hard CI gate; verify the connection-pooler runs in *transaction* mode.
2. **The Baileys gateway** — three-in-one: the **receive path is unverified** (retire in the Phase-0 spike); it's
   **single-writer stateful** (caps us at one instance until Phase-5 sharding; a wrong move = duplicate sockets →
   bans); and **ban-risk is structural** (unofficial lib) — only mitigated by rate limits + one number per business.
3. **`accountId ↔ business_id` bridge** — a wrong mapping routes a customer's message into the wrong business's
   dashboard (cross-tenant via transport). Needs explicit two-tenant inbound tests.
4. **Back-office / impersonation** — deliberate cross-tenant power; if it reaches for a service-key shortcut it
   re-creates the exact blast radius the rebuild exists to kill. Must be read-only-by-default, PII-masked, audited,
   and isolation-tested.
5. **Crown-jewel key custody** — the WhatsApp KEK must live in **KMS**, separate from the PII key, fail-closed.

---

## Open decisions for Omer (needed during the build — not now)

- 🌍 **AWS region / data residency** — an EU region (Frankfurt/Ireland) is suggested for Israeli-privacy comfort. Confirm.
- 🌐 **Domain name** — do you own one for the product? (needed for the stable HTTPS endpoint.)
- 🔧 **CI host** — GitHub Actions assumed. OK?
- 🧰 **IaC tool** — Terraform vs AWS CDK (Phase 5; decide later).
- 📱 **Test WhatsApp number** — a safe throwaway number for the receive spike (so we never risk a real business's session).
- 🗃️ Minor data choices carried over: keep `bot_builder_messages`? encrypt Redis message bodies? lead-retention window? (defaults are fine to start.)

---

## Where the detail lives
Per-domain task lists (every task's why / depends-on / effort / risk):
[`backend.md`](roadmap-parts/backend.md) · [`frontend.md`](roadmap-parts/frontend.md) ·
[`data.md`](roadmap-parts/data.md) · [`whatsapp.md`](roadmap-parts/whatsapp.md) ·
[`infra.md`](roadmap-parts/infra.md) · [`devops-aws.md`](roadmap-parts/devops-aws.md) ·
[`security.md`](roadmap-parts/security.md)
