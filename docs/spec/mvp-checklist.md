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
- [x] Conversation engine (pure engine on Redis): the **lead-collection flow** (validate → store → advance) — verified end-to-end via `/api/bot/sim` + `bot_runtime.run_turn`
- [x] **Human handoff** logic (flip status to 'human'; bot then silent) — verified (flip-back via owner reply lands with M6/M7 inbound)
- [x] **Lead lifecycle**: create at start → `new`/`abandoned` + funnel events (PII **encrypted at rest, asserted on the raw columns**, `is_test` honored)
- [x] **Abandoned sweep** (60-min, single-runner) — verified by back-dating a lead + calling the sweep directly
- [x] Try-me endpoint (same engine, no WhatsApp) — done (M5 try-me 18/18); **try-me chat UI** is frontend (not covered by this backend run)

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
- [x] Leads dashboard + **funnel** (started → completed → abandoned) — verified; counts match DB truth, is_test excluded by default
- [x] Leads table + the **abandoned-lead follow-up list** (phone + partial answers) — verified; decrypted phone/name/ALL answers, status (incl. synthetic 'open') + flow filters work
- [x] Conversations list + **bot↔human toggle** (live, Redis-backed) + owner reply — verified; tenant-scoped list, status flip (bot/human/closed), reply queued to outbox
- [x] **Publish / go-live** control (`is_published`) + loading / empty / error states — verified; PUT /api/bot/publish reflected by GET /api/bot/settings; frontend `tsc --noEmit` clean

> ⚠️ **KNOWN BUG (open):** `?period=week|month` returns **HTTP 500** on `GET /api/leads`
> AND `GET /api/dashboard`. Cause: `app/services/leads.py` `_period_clause` binds the
> string `'7 days'` to a `$N::interval` asyncpg param — asyncpg needs a `datetime.timedelta`.
> `period=all` (the default) works. Tracked by the 2 xfail tests in `test_dashboard.py`.

✅ **Done when:** the owner sees leads, follows up with abandoners, takes over a chat, and flips the bot live.
   — All four met; M7 narrated **13/15** (the 2 red = the period bug above), strict gate **9 passed / 2 xfailed**.

## M8 (handoff-chat) — The in-app human-handoff chat 💬 — ✅ DONE 2026-06-19
> Per [decision 0008](../decisions/0008-m8-handoff-chat.md). (This is distinct from the AWS milestone below, which keeps its original number for the roadmap.)
- [x] Full transcript in Redis: `conv:{business}:{conv}:log` — a LIST of `{role, body, at}`, role ∈ customer|bot|owner, **LTRIM to 200**, fully tenant-isolated (`_assert_owns` on the `:log` key) — `app/services/conversation_state.py` (`append_message`/`get_messages`).
- [x] New status `waiting` (customer asked for a human, nobody picked up yet) in the valid set + the status journey **bot→waiting→human→closed**.
- [x] **Bot is SILENT in `waiting` AND `human`** — and the inbound customer message is STILL appended to the transcript (role=customer) on the silent path — `app/services/bot_runtime.py`.
- [x] Handoff sets status `waiting` (not `human`) + logs the `handed_off` funnel event (the dashboard's "ביקש נציג" light).
- [x] Read/extend the API: `GET /api/conversations/{id}` (status + linked decrypted lead + messages) · `GET .../messages` · `POST .../reply` (also appends role=owner) · `POST .../status` (Literal widened to `waiting`) — `app/api/dashboard.py`.
- [x] 🚦 **Isolation extended:** business A can never read B's conversation detail/messages (empty/default, no leak) — covered in `tests/test_m8.py` + `tests/m8_full_test.py`.

✅ **Done:** `tests/test_m8.bat` → M8 narrated **27/27** + strict `tests/test_m8.py` **17/17**; the strict M2–M8 bundle **108 passed**; M2 **12/12** + M3 **5/5** + M4 **9/9** + M5 **18/18** + M5b **10/10** + M7 **15/15** all still green (the M5 handoff tests were updated to this locked contract — handoff → `waiting`; product source already implemented it).

## M9 (lead-outcomes) — Outcomes unified around the LEAD 🎯 — ✅ DONE 2026-06-19
> Per [decision 0009](../decisions/0009-m9-lead-outcomes.md). (Distinct from the launch-readiness milestone below, which keeps its number.) The lead status is the **single source of truth** for an outcome — both outcomes reuse EXISTING endpoints; no new endpoint.
- [x] "בוצעה עסקה" → lead status `deal` + conversation status `closed`; "סגירת פנייה" → lead status `closed` + conversation status `closed` — via `PATCH /api/leads/{id}/status` (deal|closed) + `POST /api/conversations/{id}/status` (closed).
- [x] `GET /api/leads?status=` additionally accepts `deal` and `closed`; `list_leads` filters by them (stored lead.status values) — `app/services/leads.py` (`_REAL_STATUSES`).
- [x] **Every handoff ALWAYS yields a lead:** when `event=='handed_off'` with no active lead, the runtime creates a minimal lead (`lead_name="פנייה לנציג"`, status `in_progress`), links it to the conversation, and attaches the `handed_off` funnel event — `app/services/bot_runtime.py`. Status still flips to `waiting`.
- [x] The lead read (LeadItem + list_leads + `_decrypt_lead_row`) includes `conversation_id: string | null`, derived from `cache_chat_ref` by stripping the `conv:{business_id}:` prefix (null when absent).
- [x] 🚦 **Isolation re-proved:** business A cannot read/filter/PATCH B's deal/closed leads — `tests/test_m9.py` + a negative control in `tests/m9_full_test.py`.

✅ **Done:** `tests/test_m9.bat` → M9 narrated **11/11** + strict `tests/test_m9.py` **10/10**; the strict M3–M9 bundle **118 passed**; M2 **12/12** + M3 **5/5** + M4 **9/9** + M5 **18/18** + M5b **10/10** + M7 **15/15** + M8 **27/27** all still green. (No M8 handoff assertions required changing — none had assumed "handoff → no lead".)

## M10 (transcript TTL by status + private outcome note) — ✅ DONE 2026-06-19
> Per [decision 0010](../decisions/0010-m10.md). Two promises: the live transcript must **not vanish while a human is needed**, and the owner's outcome note is **encrypted + private**.
- [x] **TTL by status** centralized in `conversation_state._apply_ttl`, applied by BOTH `set_status` AND `append_message` using the CURRENT status: `bot` → sliding ~60-min; `waiting`/`human` → **PERSIST** (no expiry); `closed` → 30-day. Covers the conv hash key, its `:log` list, and the index. `append_message` no longer unconditionally re-sets the 60-min TTL (the bug that silently deleted a waiting transcript on the next message).
- [x] **Encrypted outcome note** (migration `0007_outcome_note.sql`, additive + idempotent): `PATCH /api/leads/{id}/status` body accepts `{status, note?}`; when present `note` is encrypted into `leads.outcome_note` (like phone/answers, key_version stamped) — **raw column is ciphertext**. `LeadItem` carries `outcome_note: string | null`, decrypted for the owner; the API takes it optionally (the UI requires it for deal/closed).
- [x] 🚦 **Isolation re-proved:** business A cannot set or read B's `outcome_note` (PATCH → 404; not visible in A's leads list).

✅ **Done:** `tests/test_m10.bat` → M10 narrated **10/10** (incl. a negative control that forces the old 60-min timer back, catches it, then restores PERSIST) + strict `tests/test_m10.py` **13/13**; the strict M3–M10 bundle **131 passed**; M2 **12/12** + M3 **5/5** + M4 **9/9** + M5 **18/18** + M5b **10/10** + M7 **15/15** + M8 **27/27** + M9 **11/11** all still green. (No old assertions required changing — product source already implemented the locked M10 contract.)

## M11 (public booking + Google Calendar) — Appointment booking 📅 — ✅ DONE 2026-06-21
> Per [decision 0011](../decisions/0011-m11-appointments-booking.md). Phase-2 booking, built now: a public booking page + per-business (optional) Google Calendar. (Distinct from the launch-readiness milestone below, which keeps its number.)
- [x] **Four tables** (`booking_settings`/`services`/`bookings`/`google_credentials`) — migrations `0008_booking` + `0009_rls_booking` (RLS ENABLE+FORCE + `p_tenant_isolation` on all four; `app_role` full CRUD, `gateway_role` nothing) + `0010_booking_slug_resolve` (the public slug→tenant + the PII-free reminder read, both SECURITY DEFINER). Additive + idempotent; auto-apply via the compose `migrate`.
- [x] **Slot algorithm:** SPLIT working-hours ranges per weekday (Sun=0), per-service durations, the rules `min_notice_minutes` / `buffer_minutes` / `max_days_ahead` — computed in **Asia/Jerusalem**, stored **UTC** (zoneinfo).
- [x] **Public page** (no session): `GET /api/book/{slug}/services|slots`, `POST /api/book/{slug}` (creates a unified **LEAD + booking** in one tx, client PII **encrypted at rest — asserted on raw columns**, double-booking → **409**, unknown slug → **404**, junk → **422**), `POST .../cancel|reschedule/{cancel_token}`.
- [x] **Admin** (gated `/api`): `GET/PUT /api/booking/settings`, `GET/POST/PATCH/DELETE /api/services[/{id}]`, `GET /api/bookings`, `PATCH /api/bookings/{id}` (status / reschedule), `GET /api/google/connect|callback|status` + `POST /api/google/disconnect`.
- [x] **Google Calendar OPTIONAL** per business via a decoupled hook (mock-tested): create-event with the right params, **Meet only when `meet_enabled`**, a Google failure **degrades gracefully** (booking stands), the KEK-encrypted **refresh_token never leaks** in a response/log.
- [x] 🚦 **C4 re-proved:** A cannot read/list/PATCH B's bookings/services/settings (foreign PATCH → 404); admin routes 401 without a session; the public slug only exposes its own tenant.

✅ **Done:** `tests/test_m11.bat` → M11 narrated **21/21** (incl. an active negative control: drop RLS on `bookings` → catch the leak → restore) + strict `tests/test_m11.py` **28/28**; the strict M3–M10 bundle **131 passed**; M2 **12/12** + M3 **5/5** + M4 **9/9** + M5 **18/18** + M5b **10/10** + M7 **15/15** + M8 **27/27** + M9 **11/11** + M10 **10/10** all still green. (No old assertions required changing — product source already implemented the locked M11 contract; the one nuance worth noting: an off-grid-but-still-future time maps to **409**, a past/closed one to **422** — the test asserts the real contract.)

## M11.1 (public booking page polish) — ✅ DONE 2026-06-21
> Per [decision 0012](../decisions/0012-m11-public-booking-polish.md). Richer service cards + a per-business welcome message + a day-availability call for the public calendar. NO images / no file storage.
- [x] **Migration `0011_booking_service_extras`** (additive + idempotent): `services.description text`, `services.price int` (nullable, ≥0 ₪, app-enforced), `booking_settings.welcome_message text`. No new RLS/grant (the existing `services` / `booking_settings` policies cover new columns).
- [x] **Service cards:** `ServiceItem`/`ServiceCreateRequest`/`ServiceUpdateRequest` + `PublicServiceItem` carry `description` (≤500) + `price` (≥0, OPTIONAL). PATCH distinguishes *omit* (untouched) from *explicit null* (clear) via `model_fields_set`; price `0` is a valid free price; an empty price stays null (UI shows "ללא עלות").
- [x] **Welcome message:** `BookingSettings.welcome_message` (≤600) persists on `PUT /api/booking/settings` + returns on GET; the public `GET /api/book/{slug}/services` response includes it (None when unset).
- [x] **Availability:** new public `GET /api/book/{slug}/availability?service_id=&from=&to=` → `{dates:[...]}` (days with ≥1 free slot; loops `compute_slots`); range bounded ≤ 62 days (else **422**), inverted/bad range → **422**, unknown slug → **404**.
- [x] **AI welcome:** new gated `POST /api/booking/welcome/generate` (`current_business`); dedicated Hebrew prompt via `booking_welcome` mirroring `bot_builder_ai` (gemini-3.1-flash-lite, validate-at-use → **503** no key, **502** call fail). Never logs/leaks the key.
- [x] 🚦 **Isolation re-proved on the NEW fields:** A cannot PATCH B's service description/price (404, B untouched); A's settings never show B's welcome_message; the public slug exposes only its own welcome + services.

✅ **Done:** `tests/test_m11_1.bat` → M11.1 narrated **20/20** (incl. an active negative control: drop RLS on `booking_settings` → catch the welcome-message leak → restore) + strict `tests/test_m11_1.py` **20/20**; the strict M3–M11 bundle **179 passed** (was 159 + the 20 new M11.1 tests); M2 **12/12** + M11 **28/28** all still green. No product source was edited to pass — the locked M11.1 contract was already implemented.

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
