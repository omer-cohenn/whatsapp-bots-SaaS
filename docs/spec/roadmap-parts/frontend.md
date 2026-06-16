# Roadmap — FRONTEND (React + Tailwind)

> My domain's slice of the production roadmap for the **Bizz_up** rebuild.
> Author: FRONTEND agent · Date: 2026-06-16 · Status: draft for Omer.
> Contract: [`../../system-map/frontend-map.md`](../../system-map/frontend-map.md) (the 30-endpoint API inventory + page breakdowns).
> Grounded in: `00_overview.md`, `spec/architecture.md`, `spec/data-model.md`, decisions 0001–0006, `bugs.md` (B7/B8/B9), `security-issues.md` (C2/C6/M3).
> Stack reference (Vite/React structure only, NOT API contract): `qr_wa_scanner/frontend` (Vite 5 + React 18 + `@vitejs/plugin-react`) — verified present.

---

## Scope & guardrails (read first)

**What this domain owns:** every pixel the owner, the public visitor, and the platform admin see.
- **Owner app (MVP):** login gate, AI bot builder, try-me test chat, dashboard (leads incl. the **abandoned-lead follow-up list**, conversations + **bot↔human toggle**, the **funnel**), WhatsApp **QR-link onboarding** screen.
- **Back-office admin UI (Phase 2, FULL):** manage businesses/users, **billing VIEW placeholder** (engine deferred — hooks only), support + **impersonate**, platform **metrics**.
- **Public pages:** booking page (Phase 2), and the always-on **Terms / Privacy** pages.
- **Compliance (cross-cutting, REQUIRED from day one):** accessibility (נגישות / WCAG 2.1 AA, Israeli IS 5568), Terms + Privacy, cookie/consent + data-subject UX hooks (Israeli privacy law).

**Hard rules baked into every task below:**
- **Keep the API contract byte-for-byte** with `frontend-map.md`, with three *conscious* changes: send `date_from`/`date_to` not `from`/`to` (bug **B8**); **drop** the dead `GET /api/config` call (bug **B9** — confirmed nonexistent; derive active-flow classification from `/api/botbuilder/config`); **replace the `/botbuilder` iframe** with a real route.
- **No secrets, no tokens in the frontend.** The old gateway token `my-secret-token` was hardcoded in the reference `App.jsx` (security **C6**) — the new frontend talks **only** to FastAPI (same-origin, cookie session); it never holds or sees the Baileys gateway token or the WhatsApp `auth_state`.
- **Auth is a cookie session** (Google login via FastAPI, decision 0005). Frontend never trusts a client-supplied `business_id`; tenant scoping is entirely server-side (data-model "tenant rule"). Frontend just calls `/api/me` and renders.
- **RTL Hebrew everywhere** (`dir="rtl"`, Heebo font) — must be correct from the first commit, not retrofitted.
- **Write only inside `bizz_up/docs`.** Old trees are READ-ONLY references.

**Cross-team dependencies (named so they line up with sibling roadmap parts):**
- BACKEND owns every `/api/*`, `/auth/*` route, the cookie session, the SSE/WS channel that streams the **live QR** and **live chat** (Redis-backed), and the admin/impersonate endpoints. The frontend is blocked on these contracts.
- DEVOPS owns serving the built `dist/` (FastAPI catch-all SPA route or static host) + the dev `server.proxy` target.

---

## Phase 0 — Foundations

> Goal: a running React+Tailwind+RTL shell wired to the FastAPI session, with compliance and the design system in place *before* feature work, so accessibility and theming are never a retrofit.

### F0.1 — Scaffold: Vite + React 18 + Tailwind + RTL
- **What:** New Vite app (mirror `qr_wa_scanner/frontend` config), Tailwind installed with RTL-aware config (logical properties, `dir="rtl"` on root, Heebo as default font), single consolidated theme (one set of tokens replacing the 3 duplicated palettes noted in frontend-map: light "Heebo" owner palette + WhatsApp greens `#25D366`/`#128C7E`). Dev `server.proxy` for `/api`, `/auth` → FastAPI so the cookie session stays same-origin.
- **Why:** Everything else builds on it; getting RTL + theme right once avoids a painful retrofit. Vite proxy (not a hardcoded host) keeps cookies/session same-origin and avoids the reference app's hardcoded-URL mistake.
- **Depends on:** BACKEND dev origin reachable (for proxy). Otherwise self-contained.
- **Effort:** S
- **Risk:** Tailwind RTL gotchas (physical `left/right` utilities leaking into an RTL layout). Mitigate by standardizing on logical utilities and a lint rule.

### F0.2 — App shell, routing, AuthGate + cookie-session API client
- **What:** Router (`/` authed dashboard, `/book/:slug` public lightweight entry, `/admin/*` later, `/terms`, `/privacy`). One `AuthProvider` + route guard calling `GET /api/me` (401 → LoginScreen). One `apiClient` wrapper: `credentials: 'include'`, central 401/403/409 handling, JSON + multipart helpers, and the shared **AI-response parser** (`{content:[{text}]}` + the ```json fenced-block extractor) that three endpoints reuse.
- **Why:** Centralizes the auth pattern both authed pages duplicated today; one place to enforce session handling and error UX. The shared AI parser is load-bearing for the builder + try-me.
- **Depends on:** F0.1; BACKEND `/api/me`, `/auth/google`, `/auth/logout` contract.
- **Effort:** M
- **Risk:** Cookie/session behaviour through the dev proxy (SameSite, CSRF posture). Confirm `POST /auth/logout` + state-changing POSTs work cross-proxy; coordinate CSRF stance with BACKEND.

### F0.3 — Accessibility foundation (נגישות / WCAG 2.1 AA) — COMPLIANCE
- **What:** Bake in from the start: semantic landmarks, focus management + visible focus rings, skip-to-content, `lang="he"`/`dir="rtl"`, color-contrast-checked tokens (the green palette must pass AA on text), keyboard operability for all interactive primitives, accessible toast/live-region (`aria-live`) for the existing toast pattern, reduced-motion support. Add an a11y lint/test gate (`eslint-plugin-jsx-a11y` + axe in CI) so regressions fail the build.
- **Why:** Israeli law (IS 5568 / WCAG 2.1 AA) makes this a **launch blocker**, not a nice-to-have. Retrofitting a11y is multiples more expensive than building it in. Doing it in Phase 0 means every later component inherits it.
- **Depends on:** F0.1 (tokens), F0.2 (shell primitives).
- **Effort:** M
- **Risk:** A11y debt compounds silently; without the CI gate it rots. RTL + screen-reader testing in Hebrew is easy to skip — schedule a real assistive-tech pass before launch.

### F0.4 — Terms & Privacy pages + consent/data-rights UX hooks — COMPLIANCE
- **What:** Static, accessible, RTL `/terms` and `/privacy` routes (content authored with the docs/compliance owner — frontend ships the shell + renders Markdown/HTML), footer links from every page incl. login, a minimal cookie/consent banner, and **placeholder UX hooks** for data-subject requests (export/delete account) wired to backend stubs when ready.
- **Why:** Required for launch (Israeli privacy law). Cheap as a Phase-0 shell; expensive if it blocks go-live later. Pairs naturally with the privacy/data-protection work other agents own.
- **Depends on:** F0.1; legal copy from the docs/compliance track.
- **Effort:** S
- **Risk:** Legal copy not ready in time — ship the shell + "needs verification" placeholder so the route exists and is styled, fill copy before launch.

### F0.5 — Shared UI kit + lib (dates, slots, calendar, primitives)
- **What:** Extract the repeated logic the four old pages duplicated into shared modules: `lib/dates.ts` (`HEB_DAYS`/`HEB_MONTHS`/`DAYS_SHORT`, `fmtDate`), `lib/slots.ts` (mirrors backend slot math), `components/Calendar` (week/month grid — three near-duplicate impls today), accessible `Toast` provider, `Modal`, `Button`, `Field`, `Tabs`, `StatCard`, status→label/color maps. All a11y-compliant (from F0.3).
- **Why:** Used by dashboard, booking, and admin alike; building shared primitives once keeps later phases fast and consistent, and guarantees a11y is uniform.
- **Depends on:** F0.1, F0.3.
- **Effort:** M
- **Risk:** Over-engineering the kit before real usage. Keep it lean — extract on second use, not speculatively.

---

## Phase 1 — MVP (the build→test→go-live→collect loop)

> Ship-first order per decision 0004: **leads + handoff + AI bot builder + try-me**. This is the owner-facing SaaS that lets one real business go live. (Booking is Phase 2, RAG Phase 3.)

### F1.1 — Login screen + owner app header
- **What:** Google sign-in card (RTL, accessible), and the authed header: dynamic title, **status pill** (bot connected / not connected, from `/api/status`), user chip (avatar/name from `/api/me`), logout (`POST /auth/logout`).
- **Why:** The front door of the entire owner app; gates everything.
- **Depends on:** F0.2 (AuthGate), BACKEND `/api/me`, `/api/status`, `/auth/*`.
- **Effort:** S
- **Risk:** Low. Status-pill semantics must match the new `whatsapp_connections.status` state machine (`disconnected`/`connecting`/`qr_pending`/`connected`), not the old shape — confirm with BACKEND.

### F1.2 — WhatsApp QR-link onboarding screen
- **What:** The one-time "scan to connect your WhatsApp" flow. Renders the **live QR streamed over the authed channel** (SSE/WS from backend — the QR is **never stored**, per data-model + decision 0005), shows the connection state machine (`disconnected → connecting → qr_pending → connected`), handles expiry/refresh + errors (`last_error`), and a connected/health state.
- **Why:** No bot can go live without the business linking its WhatsApp number (decision 0001/0002). This is the gateway to the whole product; it's *new* (the old owner app had no QR onboarding — that lived only in the standalone scanner).
- **Depends on:** BACKEND streaming channel + `whatsapp_connections` status endpoint; the gateway↔backend bridge (the open `accountId ↔ business_id` question). **This is the riskiest MVP dependency.**
- **Effort:** M
- **Risk:** **High.** The QR/stream contract doesn't exist yet and the inbound path is unverified (decision 0001). The QR is session-hijack material — must render only over the authed channel, never logged, never persisted. Frontend is blocked until BACKEND defines the stream shape.

### F1.3 — Leads dashboard: stats + funnel
- **What:** Stat cards + flow breakdown from `GET /api/dashboard?period=` (`total_leads`, `abandoned`, `avg_open_chats`, `leads_by_flow`), period filter (all/month/day), and the **lead funnel** visual (started → completed → abandoned) sourced from `flow_events`. `is_test` leads excluded from real stats.
- **Why:** The "collect" half of the loop; the funnel is an explicit MVP inclusion (decision 0005) and the owner's at-a-glance health.
- **Depends on:** F0.5 (StatCard/charts), BACKEND `/api/dashboard`; funnel endpoint shape (new — confirm BACKEND surfaces `flow_events` aggregates).
- **Effort:** M
- **Risk:** Funnel data contract is new (old `/api/dashboard` lacked a true funnel). May need a small dedicated endpoint. Mark "needs verification".

### F1.4 — Leads table + abandoned-lead follow-up list
- **What:** Leads table from `GET /api/leads?period=` with sub-tabs/filters by status. A first-class **"abandoned / follow up" view** (leads with `status in (in_progress, abandoned)`, showing phone + partial `answers` + `last_step_index` so the owner can call them back). Replace the old active/old classification (which depended on the dead `/api/config`, **B9**) with status-driven filtering. "Generate test lead" button (`POST /api/leads/test`). PII shown only as the backend returns it (decrypted server-side, tenant-scoped).
- **Why:** Recovering drop-offs is a headline feature (decision 0006 "keep the lead data, throw away the chatter"). The abandoned list is *why* leads are persisted at all.
- **Depends on:** F1.3, BACKEND `/api/leads` returning the new `status`/`last_step_index`/`is_test` fields.
- **Effort:** M
- **Risk:** Showing PII (phone/answers) → must be access-controlled server-side and never cached in the browser beyond the view; coordinate with security. Old "active/old via `/api/config`" logic must be fully removed (B9), not ported.

### F1.5 — Conversations list + bot↔human handoff toggle (live chat)
- **What:** A conversations view backed by the **Redis live-chat cache** (via backend): list by status (`bot`/`human`/`closed`), open a conversation to see the **last ~10 messages**, **flip bot↔human** (and back), and let the owner **send a reply** while in `human` mode (dashboard → backend → gateway `/send`). Live updates via the streaming channel; graceful "conversation expired/auto-closed" (60-min TTL) state.
- **Why:** Human handoff is half the MVP customer experience (decision 0004). This is the owner's live-intervention surface.
- **Depends on:** BACKEND conversations endpoints over Redis + the live channel + the send path through the gateway. The old `test_chat_status.html` `/api/conversations*` shapes are the *starting point* but the data source changed (process-memory → Redis) — **contract needs re-confirmation**.
- **Effort:** L
- **Risk:** **High.** New realtime contract (Redis-backed, not the old in-memory model from `test_chat_status.html`); ephemerality (messages roll off / TTL expiry) makes UX edge-cases (stale view, expired chat, race on toggle) tricky. Blocked on BACKEND's live-channel design.

### F1.6 — AI bot builder (port botbuilder.html CDN-React → Vite/Tailwind)
- **What:** Port the existing in-browser-Babel `botbuilder.html` to a real Vite route + Tailwind (it's already componentized — highest-value, lowest-architecture-risk conversion). Components per frontend-map: `BuilderTopBar` (save status, AI button, Try button), flows tab (flow chips + per-type editors: steps / **knowledge** / **human_handoff** / booking_link), settings tab (business name, system prompt, tone chips, `MainMenuEditor` with WhatsApp-style preview, handoff keywords, escalation), `Editable`, `FloatingWindow`. **AI assist panel** (`POST /api/ai/chat`) that builds a system prompt from current config, extracts ```json blocks, and applies them. Load/autosave via `GET`/`POST /api/botbuilder/config`. Map config to the new `bot_settings` shape (`lead_steps`, `bot_profile`, `handoff_keywords`, `is_published`). For MVP, **knowledge/RAG editor + booking_link editor are reserved/stubbed** (RAG = Phase 3, booking = Phase 2).
- **Why:** Without the builder there is no bot — it's how a bot is created (decision 0004, "as foundational as login").
- **Depends on:** F0.2 (shared AI parser), BACKEND `/api/botbuilder/config` + `/api/ai/chat` (Gemini proxy, returns Anthropic-shaped `{content:[{text}]}` — keep verbatim). Config mapping to `bot_settings`.
- **Effort:** L
- **Risk:** Config schema drift: old config object vs new `bot_settings` jsonb (`lead_steps`/`bot_profile`). Debounced-autosave + concurrent-edit safety. AI applies arbitrary JSON to config — validate before apply to avoid corrupting `bot_settings`. Iframe→route swap must not regress save behaviour.

### F1.7 — Try-me test chat
- **What:** First-class in-app test conversation that runs the **same engine** with no WhatsApp (decision 0004): simulates the menu + each flow type (steps with validation, human_handoff), shows bot replies, marks the session `is_test` so it's excluded from real stats/funnel. Port from the old `TryMeOverlay` but wire to the backend test-conversation path (Redis test session), not just `/api/ai/validate` client-side. Accessible chat UI (live region for new messages).
- **Why:** The "trust" step of build→test→go-live; owners won't publish a bot they can't try. Explicit MVP item.
- **Depends on:** F1.6 (builder context), BACKEND try-me/test-conversation endpoint(s) + `is_test` tagging; reuses `/api/ai/validate` shape.
- **Effort:** M
- **Risk:** Keeping try-me behaviour identical to the live engine (else owners test a lie). The old overlay validated partly client-side; the rebuild should drive it through the real engine — confirm the backend exposes a test path.

### F1.8 — Publish / go-live control + global error/empty/loading states
- **What:** A "publish" toggle (drives `bot_settings.is_published` = try-me vs live) with clear pre-publish checklist (WhatsApp connected? config valid?). Plus the unglamorous-but-required: consistent loading skeletons, empty states, error boundaries, accessible 409/403/401 handling across the app.
- **Why:** Closes the loop (build→test→**go-live**). Robust states are what makes the MVP feel finished and keeps a11y intact under error conditions.
- **Depends on:** F1.1–F1.7.
- **Effort:** S
- **Risk:** Low. Mainly coordination: define what "ready to publish" requires with BACKEND.

---

## Phase 2+ — Post-MVP (back-office, booking, RAG, scale)

### Back-office admin UI — FULL (Phase 2) — owner of the BACK-OFFICE frontend slice

> A separate, role-gated admin surface (`/admin/*`), only for platform admins. Distinct from the per-tenant owner app. All a11y rules (F0.3) apply equally.

#### F2.1 — Admin shell + role gating
- **What:** `/admin` layout, admin nav, an **admin-role gate** (server-verified — frontend renders only what `/api/me` flags as admin; never a client-side-only gate, per security C2/C3 lessons). Distinct visual treatment so admin vs tenant context is unmistakable.
- **Why:** Foundation for all back-office screens; the old system had **zero** admin-role concept (the `/admin/*` endpoints were unauthenticated — C3). Getting the gate right is a security requirement.
- **Depends on:** BACKEND admin-role flag on `/api/me` + admin route authz.
- **Effort:** M
- **Risk:** Privilege boundary — a UI-only gate is worthless; the real check is server-side. Frontend must fail safe (hide + the API rejects).

#### F2.2 — Manage businesses & users
- **What:** List/search/inspect businesses (`businesses` + `business_members`), drill into a business (status, WhatsApp connection state, plan placeholder), manage users/roles, suspend/activate. Read-heavy with guarded mutations.
- **Why:** Core back-office (Omer: FULL). Day-to-day platform operation.
- **Depends on:** F2.1, BACKEND admin business/user endpoints (new).
- **Effort:** L
- **Risk:** Cross-tenant data on one screen is exactly where the old leaks happened — every call must be an explicit admin-scoped endpoint, never the tenant-scoped ones with scoping disabled.

#### F2.3 — Support tools + impersonate
- **What:** Per-business support view; **impersonate** a business owner to reproduce issues, with a **persistent "you are impersonating X" banner**, an obvious exit, and (frontend-surfaced) audit indication. Read-mostly while impersonating by default.
- **Why:** Explicitly requested (support + impersonate). Essential for solo-founder support.
- **Depends on:** F2.1, BACKEND impersonation session mechanism + audit (security-sensitive — design with the security track).
- **Effort:** M
- **Risk:** **High (security).** Impersonation is a privilege-escalation surface; the UI must make the impersonated state unmissable and exit trivial, and must rely on a real backend impersonation token, not client-side `business_id` spoofing (the exact anti-pattern the data-model forbids).

#### F2.4 — Platform metrics dashboard
- **What:** Cross-tenant KPIs: businesses, active bots, leads captured, conversations, abandoned rate, WhatsApp connection health. Charts reuse the F0.5/F1.3 viz primitives.
- **Why:** "Platform metrics" is a named back-office requirement; the founder's health view.
- **Depends on:** F2.1, BACKEND metrics/aggregate endpoints (new).
- **Effort:** M
- **Risk:** Aggregate queries can be heavy; coordinate paging/caching with BACKEND. Don't leak per-tenant PII into platform aggregates.

#### F2.5 — Billing VIEW placeholder (engine DEFERRED) — reserve hooks only
- **What:** A read-only "Billing" section per business showing **plan / status placeholder** and an empty invoices area, plus **reserved UI hooks/slots** (a `BillingPanel` boundary, route, nav item) so the future billing/invoicing/VAT engine drops in without rework. **Build NO payment flows, NO checkout, NO invoicing now** (Omer: engine deferred; invoicing/VAT compliance rides with billing later).
- **Why:** Omer wants the *place* reserved, not the engine. Cheap structural placeholder now saves a re-architecture later; explicitly scoped to avoid wasting effort on deferred work.
- **Depends on:** F2.1. No backend billing dependency (placeholder only).
- **Effort:** S
- **Risk:** Scope creep into real billing. Hold the line: placeholder + hooks only. Clearly label as "coming soon / not active".

### Booking (Phase 2) — public + owner

#### F2.6 — Public booking page (port + enrich)
- **What:** Port `book_client.html` to the public `/book/:slug` route (kept as a **lightweight separate entry** so the public bundle doesn't pull the authed app): month calendar of working days, slot grid, validated booking form (name/phone required), success card. **Preserve the load-bearing `409` branch** (slot taken → alert + reload slots, frontend-map). Mine the richer `bookslot.html` mockup for week/month/**year** views + load-heatmap look-and-feel, wired to real endpoints.
- **Why:** Booking is the Phase-2 customer feature; the service-pro customer needs it.
- **Depends on:** BACKEND `/api/book/{slug}/*` (public), and bug **B7** fix (chat flow must actually book) on the backend side.
- **Effort:** M
- **Risk:** Public page = unauthenticated input → strict client validation + a11y, but trust nothing client-side. Keep the public bundle small (no admin/owner code).

#### F2.7 — Owner schedule/calendar tab
- **What:** Owner-side availability settings (duration + per-day toggles/hours), booking-link banner with copy, week/month calendar of appointments, appointment modal (confirm/cancel). Wire to `/api/booking-settings`, `/api/bookings` (**send `date_from`/`date_to`** — fixes **B8**), `PATCH /api/bookings/{id}`.
- **Why:** Owners manage the appointments the public page creates.
- **Depends on:** F2.6 contracts, BACKEND booking endpoints; **B8** param-name alignment.
- **Effort:** M
- **Risk:** The B8 mismatch must be consciously resolved (send correct param names) or the calendar silently returns everything unfiltered, as today.

### RAG / knowledge (Phase 3)

#### F3.1 — Knowledge (RAG) builder tab — un-stub
- **What:** Activate the reserved RAG tab in the bot builder: status counts, "when to use RAG" use-cases editor, file dropzone (`/api/rag/upload` multipart), URL scrape (`/api/rag/add-url`), indexed-source list with delete (`/api/rag/source/{id}`), and the knowledge flow in try-me (`/api/rag/chat`). Components already mapped in frontend-map.
- **Why:** RAG is the Phase-3 customer capability; the builder UI is largely specced already.
- **Depends on:** BACKEND RAG pipeline + pgvector (Phase 3), the `/api/rag/*` endpoints.
- **Effort:** M
- **Risk:** Upload UX (large files, progress, errors) and grounding expectations; depends on backend RAG readiness.

### Scale / polish (Phase 3+)

#### F3.2 — Performance, bundle split, and scale-readiness
- **What:** Route-level code-splitting (public vs owner vs admin bundles), data-fetching/caching layer (e.g. TanStack Query) if not adopted earlier, optimistic UI for toggles, virtualization for large leads/conversation lists, and a hardened realtime reconnection strategy for the live channel across multiple backend instances.
- **Why:** As tenants grow, the live-chat/conversations and leads surfaces are the first to feel slow; multi-instance backends stress the realtime channel.
- **Depends on:** Phase 1 live-channel + lists; DEVOPS multi-instance topology.
- **Effort:** M
- **Risk:** Realtime correctness under reconnect/multi-instance is subtle; premature optimization elsewhere wastes time — drive by real metrics.

#### F3.3 — Compliance hardening + assistive-tech audit (pre-launch gate)
- **What:** Full manual screen-reader pass in Hebrew/RTL, keyboard-only walkthrough of every flow, contrast re-audit of final theme, finalize Terms/Privacy + consent flows with real legal copy, wire the data-subject (export/delete) UX to live backend endpoints.
- **Why:** WCAG/Israeli-privacy conformance is a **launch blocker**; the CI gate (F0.3) catches regressions but a human audit is required before go-live.
- **Depends on:** F0.3, F0.4, all feature screens; legal copy; backend data-rights endpoints.
- **Effort:** M
- **Risk:** Found-late a11y defects can delay launch. The Phase-0 foundation (F0.3/F0.4) is what keeps this a *verification* pass rather than a rebuild.

---

## RETURN — tight summary

**Phases (frontend):**
- **Phase 0 — Foundations:** Vite+React+Tailwind+RTL scaffold, app shell + AuthGate + cookie-session API client, **accessibility foundation (WCAG, with a CI a11y gate)**, **Terms/Privacy + consent hooks**, shared UI kit/lib. Compliance and design system go in *first*.
- **Phase 1 — MVP:** the owner build→test→go-live→collect loop — login/header, **WhatsApp QR onboarding**, leads dashboard + **funnel**, leads table + **abandoned-lead follow-up list**, **conversations + bot↔human toggle (live, Redis-backed)**, **AI bot builder** (port botbuilder.html → Vite/Tailwind), **try-me test chat**, publish/go-live + robust states.
- **Phase 2+ — Post-MVP:** **FULL back-office** (admin shell + role gate, manage businesses/users, support + **impersonate**, **platform metrics**, **billing VIEW placeholder — engine deferred, hooks only**); **booking** (public page + owner calendar, fixes B7/B8); **RAG** knowledge builder (Phase 3); performance/scale + **pre-launch a11y/compliance audit**.

**5–8 biggest tasks (by effort/risk):**
1. **F1.5 Conversations + bot↔human toggle (live chat)** — L, new Redis-backed realtime contract; the trickiest MVP surface.
2. **F1.6 AI bot builder port** — L; config schema drift to `bot_settings` + AI-applies-JSON safety; the heart of the product.
3. **F2.2 Manage businesses & users** — L; cross-tenant admin data exactly where old leaks lived.
4. **F1.2 WhatsApp QR onboarding** — M but **highest dependency risk**; QR streamed/never stored, blocked on an unverified inbound path.
5. **F1.7 Try-me test chat** — M; must mirror the live engine exactly.
6. **F1.4 Leads + abandoned-lead follow-up list** — M; PII handling + remove the dead `/api/config` (B9) classification.
7. **F2.3 Support + impersonate** — M; privilege-escalation surface, must rely on a real backend impersonation token.
8. **F0.3 Accessibility foundation** — M; a launch-blocking compliance pillar that must be built in, not retrofitted.

**Top risk:** **The frontend's two highest-value MVP surfaces — the WhatsApp QR onboarding (F1.2) and the live conversations/handoff (F1.5) — both depend on realtime/streaming contracts that do not exist yet and on an inbound WhatsApp path that has never been verified end-to-end (decision 0001).** If the backend live-channel + gateway↔backend (`accountId ↔ business_id`) bridge slip, the frontend can build the builder/leads/try-me but cannot complete the go-live loop. Secondary risk: the QR and live-chat data are session-hijack / PII material, so these UIs must stream over the authed channel only, never store/log secrets, and never trust a client `business_id` (the exact anti-patterns behind security C2/C6/M1).
