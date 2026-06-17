# MVP Checklist — the focused build path (Phases 0 + 1 only)

> 📍 **Status (2026-06-16): M0 ✅ · M1 ✅** — the stack runs and WhatsApp receive works end-to-end. **Resume at M2.** Details in [`../STATUS.md`](../STATUS.md).

> **This is your day-to-day working list.** It contains *only* what's needed to get your first business
> **live on WhatsApp** — nothing from the later phases (back-office, booking, RAG, scale all live in
> [`roadmap.md`](roadmap.md), built later). Tick items off as you go. Full detail for any item is in the
> per-domain files under [`roadmap-parts/`](roadmap-parts/) and the [`build-guide.md`](build-guide.md).

**🎯 Definition of "MVP done" (the finish line):**
> An owner logs in → builds a bot with the AI assistant → tests it in try-me → scans the QR to connect
> WhatsApp → a real customer message arrives → an encrypted lead is captured (and drop-offs are
> recoverable) → the owner sees their leads + live chat and can take over → all live on a stable HTTPS
> domain, meeting launch compliance.

**Two things to start early, in parallel with everything:**
- ⚡ **M1 (the WhatsApp receive spike)** — retire the biggest unknown in week one.
- 🧱 **M2 (the tenant wall)** — the security foundation everything else stands on.

You can build **M0–M7 entirely on your laptop first**, then do **M8 (AWS)** when you're ready to go public.

---

## M0 — Project setup ⚙️ *(Foundations)*
- [x] Monorepo: `backend/` `gateway/` `frontend/` `infra/` `supabase/` `tests/`
- [x] `docker-compose` stack with **health-gated** startup (no blind sleeps)
- [ ] Pinned, baked-in dependencies; drop RAG-only deps; migrate to the `google-genai` SDK
- [ ] Secrets loaded from a manager; **app refuses to boot if any is missing** (no `change-me` defaults)
- [ ] `Makefile` (`make dev / test / lint / isolation / migrate / seed / down`)
- [ ] Backend app package skeleton (routers / services / core) — no more one-giant-`main.py`
- [ ] Frontend scaffold: **Vite + React + Tailwind + RTL Hebrew** (one theme)

✅ **Done when:** `make dev` brings the whole stack up healthy on a fresh clone.

## M1 — De-risk the biggest unknown ⚡ *(do this EARLY)*
- [x] Minimal gateway skeleton + **freeze the gateway↔backend message contract**
- [ ] Multi-session spike — prove several WhatsApp sessions run in one process
- [x] ⚠️ **End-to-end RECEIVE smoke test:** ✅ DONE 2026-06-16 — real WhatsApp messages (`type:conversation`) reach the backend webhook (200). (Multi-session spike deferred to M6.)

✅ **Done when:** a real WhatsApp message provably reaches the backend. *(If it doesn't — we replan before building more.)*

## M2 — The tenant wall + isolation gate 🧱🛡️ *(the heart of the rebuild)* — ✅ DONE 2026-06-16
- [x] DB migrations: the **9 tables** (FKs, indexes incl. `(business_id, last_activity_at)`) — `supabase/migrations/0003`
- [x] **Two non-service DB roles** (`app_role` + gateway-only `gateway_role`) — `0001`
- [x] `current_business_id()` + **RLS (`USING` + `WITH CHECK`) on every tenant table** — `0002` + `0004`
- [x] Backend DB session as the **non-service role** + per-request `SET LOCAL business_id` *(same transaction!)* — `app/db/session.py`
- [x] Encryption helpers: PII key + crown **KEK** (envelope) + HMAC, `key_version`, **fail-loud decrypt** — `app/core/crypto.py`
- [x] Redis live-chat layer (key per business, re-checked on every access) — `app/services/live_chat.py`
- [x] CI **secret/PII guard** (fail the build on any leak in logs/responses) — `tests/test_secret_guard.py`
- [x] 🚦 **The multi-tenant ISOLATION TEST SUITE** (incl. pooling/concurrency + deny-by-default canary) — `tests/isolation/` (10 passing) + `tests/demo_isolation.py` (9/9)

✅ **Done:** authed request → tenant-scoped DB session with RLS live; a stranger gets nothing; `make demo-isolation` shows 9/9, `make isolation` green, and `make demo-break` proves the gate catches a regression (8/9). Migrations auto-apply via the compose `migrate` step.

## M3 — Login & accounts 🔑
- [x] Google OAuth login + **opaque Redis-backed session** (`bizzup_session`) + auto-provisioned business (`provision_owner`, idempotent); CSRF **state in Redis** — `app/services/auth.py`, `app/api/auth.py`, `supabase/migrations/0005_auth_bootstrap.sql`
- [x] **One enforced deny-by-default auth gate** on the whole `/api/*` group (no anonymous fallback tenant); `current_business` comes from the server-side session, never the client — `app/core/deps.py`, `app/api/me.py`
- [x] Frontend app shell + **AuthGate** + cookie-session API client — `frontend/` (TS + react-router; container healthy)
- [x] Login screen + owner header (connection-status pill from `/api/me`) — `frontend/` (LoginPage, OwnerHeader)
- [x] **Accessibility foundation** (WCAG / נגישות) + a11y CI gate — `frontend/`
- [x] **Terms / Privacy** pages + consent + data-rights UX hooks — `frontend/` (Terms/Privacy routes)
- [x] Shared UI kit (dates, slots, calendar, toast, primitives) — `frontend/` (UI kit)

✅ **Done:** the backend auth surface is proven end-to-end — no-cookie/forged-cookie `/api/me` → 401, a valid Avi session → 200 scoped to Avi only, logout truly destroys the session, `/auth/google` → 302 to Google + a Redis CSRF state, `provision_owner` idempotent. `tests/test_m3.bat` shows the M3 story **5/5**, the `test_auth_gate.py` gate green (7/7), and the M2 wall still **12/12** (no regression) — `tests/m3_full_test.py` + `tests/test_auth_gate.py`. The frontend shell/AuthGate/Terms/Privacy/UI-kit were delivered and the container boots healthy; the **Google click-through itself is a one-time manual browser check** at `:5173` (OAuth can't be scripted).

## M4 — Build a bot (the AI builder) 🤖
- [ ] `bot_settings` config service (the two jsonb: `lead_steps` + `bot_profile`)
- [ ] AI-assist endpoints (Gemini proxy, auth-gated, input-bounded)
- [ ] AI bot builder UI (port `botbuilder.html` → real Vite/Tailwind route; RAG/booking editors stubbed)

✅ **Done when:** an owner describes a bot to the AI and gets a saved, valid `bot_settings`.

## M5 — The bot brain + leads 🧠
- [ ] Conversation engine (LangGraph on Redis): the **lead-collection flow** (validate → store → advance)
- [ ] **Human handoff** logic (flip status; owner replies; flip back)
- [ ] **Lead lifecycle**: create at start → `new`/`abandoned` + funnel events (PII encrypted, `is_test` honored)
- [ ] **Abandoned sweep** (60-min, single-runner)
- [ ] Try-me endpoint (same engine, no WhatsApp) + **try-me chat UI**

✅ **Done when:** in try-me, a full questionnaire runs, a lead is saved, and an abandoned one is swept — no WhatsApp needed.

## M6 — Connect WhatsApp for real 💬
- [ ] **QR linking flow** (multi-session onboarding) — live QR over the authed channel, **never stored**
- [ ] **Encrypted session-cred persistence** (crown jewel, gateway role only)
- [ ] **`accountId ↔ business_id` bridge** (verify the mapping; two-tenant inbound test)
- [ ] **Hardened inbound receive** (idempotent on `message_id`, graceful non-text)
- [ ] **Outbound send + rate-limiting** (E.164; ban mitigation) + Gemini replies
- [ ] Reconnection / reliability (backoff, logout handling, persistent webhook)
- [ ] **Stable authed gateway↔backend channel** (kill ngrok)

✅ **Done when:** an owner scans the QR, a real customer message comes in and gets a reply, reliably.

## M7 — The dashboard 🖥️
- [ ] Leads dashboard + **funnel** (started → completed → abandoned)
- [ ] Leads table + the **abandoned-lead follow-up list** (phone + partial answers)
- [ ] Conversations list + **bot↔human toggle** (live, Redis-backed) + owner reply
- [ ] **Publish / go-live** control (`is_published`) + loading / empty / error states

✅ **Done when:** the owner sees leads, follows up with abandoners, takes over a chat, and flips the bot live.

## M8 — Ship to AWS ☁️ *(when ready to go public)*
- [ ] AWS account + **region** (EU) + root **MFA** + CloudTrail
- [ ] 💸 **Budget alarm (day one)**
- [ ] VPC (private subnets) + **Secrets Manager + KMS** (the KEK) + ECR
- [ ] CI/CD: build → push → deploy (GitHub OIDC)
- [ ] Containerize backend + gateway (**gateway = single-writer**, DB-backed KMS-encrypted creds)
- [ ] **ALB + ACM HTTPS + Route53** (kills ngrok for good)
- [ ] ECS/Fargate (backend autoscale; **gateway desired=1**) + **ElastiCache Redis**
- [ ] CloudWatch logs + alarms (gateway-down alarm)

✅ **Done when:** the whole thing runs on a stable HTTPS domain in AWS — secrets vaulted, gateway single-writer.

## M9 — Launch readiness ✅
- [ ] **Webhook authenticity** (HMAC the gateway→backend call)
- [ ] Input validation + treat LLM output as **untrusted**
- [ ] **Data-subject export + delete** (covers Postgres *and* Redis) + consent + retention
- [ ] Session / CSRF hardening; generic error responses
- [ ] 🧪 **ONE real end-to-end inbound test** on the live gateway
- [ ] Pre-launch **accessibility pass** (Hebrew/RTL screen-reader + keyboard)

✅ **Done when:** the finish line at the top is met → onboard your first real business. 🎉

---

## A few decisions you'll hit along the way (not now)
🌍 AWS region · 🌐 a domain name · 🔧 GitHub for CI · 📱 a throwaway WhatsApp number for the M1 spike.

## The one rule that never changes
Every checkbox in **M2** serves the **multi-tenant wall** — `business_id` everywhere + RLS + the
isolation suite as a hard CI gate. It was the old system's #1 failure. Don't let any later milestone
merge without extending that suite.
