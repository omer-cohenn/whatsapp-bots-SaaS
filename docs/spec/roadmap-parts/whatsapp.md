# Roadmap — WhatsApp Gateway (Baileys) domain

> My slice of the production roadmap for the Bizz_up rebuild. Owner: the WhatsApp agent (Node / Baileys).
> Written 2026-06-16. Grounded in: decisions 0001 (Baileys canonical), 0002 (multi-tenant), 0006 (Redis live chat);
> `spec/architecture.md`, `spec/data-model.md` (tables 4 `whatsapp_connections`, 5 `whatsapp_credentials`);
> `system-map/whatsapp-gateway.md`, `system-map/infrastructure.md`; `bugs.md` (B1, B3, B15, B18–B23); `security-issues.md` (C6, M1, L1, L2).
>
> **Scope of this domain:** the Node/Baileys gateway service and everything from "a customer's WhatsApp message arrives"
> to "it reaches the backend webhook", plus "backend asks to send" to "WhatsApp delivers it" — multi-session, QR linking,
> encrypted session creds, the **inbound receive path** (still unverified end-to-end), the **gateway↔backend wiring**
> (stable URL + auth token, replacing ngrok), reconnection/reliability, send rate-limiting, and the
> **`accountId` ↔ `business_id` bridge**.
>
> **Boundary with other agents.** I own the gateway and the transport contract. The *backend agent* owns the webhook
> handler, the conversation engine, RLS, and the secret-manager wiring (I consume it). The *devops_aws agent* owns where
> the gateway runs, durable storage, the public endpoint (ALB/DNS/TLS), and KMS provisioning — I state the requirements;
> they implement the infra. The *data agent* owns the table DDL for `whatsapp_connections` / `whatsapp_credentials`; I
> own what goes in them and who may read them. Cross-refs are noted per task.

---

## How to read this

Effort: **S** ≈ ≤1 day · **M** ≈ 2–4 days · **L** ≈ ≥1 week (solo + Claude, steady pace).
Each task: **what** · **why** · **depends-on** · **effort** · **main risk**.

The single most important early item is **WA-1.4: one real end-to-end RECEIVE test** — decision 0001 flags the inbound
path as *never verified all the way through*. Everything downstream (lead collection, handoff, try-me going live) is
worthless if receive silently drops messages. It gets a throwaway spike in Phase 0 and a hardened version in Phase 1.

---

## Phase 0 — Foundations

> Goal: de-risk the two unknowns that could sink the whole approach (does receive even work end-to-end? can we hold
> multiple sessions?), and lock the transport contract so the backend agent and I can build in parallel. Throwaway-OK
> spikes here; the productionized versions live in Phase 1.

### WA-0.1 — Stand up the gateway as a clean service skeleton
- **What:** A fresh Node service (keep `@whiskeysockets/baileys`, drop the old React UI — the dashboard owns the QR UX
  now). Config from env/secret-manager, **pinned** deps, structured logging (pino) with a **secret-redaction** rule,
  `/healthz` + `/readyz`. No business logic yet — just a service that boots, reads config, and refuses to start if a
  required secret is missing.
- **Why:** The old gateway is a single `index.js` with in-RAM state, a hardcoded default token, wildcard CORS, and tokens
  printed to stdout (C6, L1). A clean skeleton is the base every other task lands on, and "fail to start without secrets"
  kills the `my-secret-token` / `change-me` class of bug at the root.
- **Depends-on:** — (can start immediately).
- **Effort:** M
- **Main risk:** Baileys version churn — `fetchLatestBaileysVersion()` can fail at boot and the old code had no
  try/catch around startup (B22). Pin the Baileys version and wrap startup; treat the upstream lib as unstable.

### WA-0.2 — Define and freeze the gateway↔backend transport contract
- **What:** Write down (in `spec/`, owned jointly with backend) the exact wire contract, both directions:
  - **Inbound** (gateway → backend webhook): normalized JSON `{ gateway_account_id, from (E.164), push_name,
    message_id, timestamp, type, text, raw }`. **`gateway_account_id` is the routing key**, not a phone number.
  - **Outbound** (backend → gateway): `POST /send { gateway_account_id, to (E.164), text, client_msg_id }`.
  - **Auth:** shared service token in a header (`Authorization: Bearer …` / `X-Gateway-Token`), **never** a query string.
  - **Idempotency:** inbound carries `message_id`; outbound carries a `client_msg_id` so retries don't double-send.
- **Why:** The #1 architectural bug (B1) is that the two old halves spoke *incompatible* shapes — the Baileys flat payload
  vs. the Meta envelope — so a forwarded message parsed as `{"status":"ignored"}`. A frozen contract lets the backend
  agent build the receive handler against a spec instead of guessing, and lets us both write fixtures.
- **Depends-on:** WA-0.1 (loosely); coordinate with backend agent.
- **Effort:** S
- **Main risk:** Contract drift between the two services. Mitigate with a shared fixture file (a real `messages.upsert`
  sample → expected normalized JSON) that both sides test against.

### WA-0.3 — Multi-session manager spike (one session per business)
- **What:** Prove we can run **N concurrent Baileys sockets** in one process, each keyed by `gateway_account_id`, each
  with its own auth state, lifecycle (`connecting`/`qr_pending`/`connected`/`disconnected`), and reconnect. Keep a
  registry keyed by `gateway_account_id` (the old `accounts` Map, but the key is the bridge id, not "default").
- **Why:** Decision 0002 requires true multi-tenant: one WhatsApp number per business. The old gateway *could* do
  multiple accounts but shipped effectively single-tenant (`credentials/default`, `firstConnected()` fallbacks). We must
  confirm the concurrency model and per-socket isolation before building onboarding on top of it.
- **Depends-on:** WA-0.1.
- **Effort:** M
- **Main risk:** Per-socket memory/CPU footprint and event-loop contention as session count grows — caps how many
  businesses fit per instance and feeds the scale story (WA-2.x). Measure footprint per session early.

### WA-0.4 — End-to-end RECEIVE smoke test (throwaway spike) ⚠️ TOP PRIORITY
- **What:** Link one real test number by QR, send it a WhatsApp message from a phone, and watch it travel
  `messages.upsert` → normalized payload → an actual backend stub that ACKs. Confirm `fromMe` is filtered, the
  `gateway_account_id` is attached, and non-text types don't crash the handler. This is a spike to *prove the path*, not
  the hardened version (that's WA-1.4).
- **Why:** Decision 0001 + B1 + bug B23: **sending was verified, receiving never was**, and `credentials/default/` was
  empty at scan time (no session ever persisted that we can confirm). This is the single biggest unknown in the whole
  rebuild. If receive is broken, the product doesn't exist — find out in week one, not after building the UI.
- **Depends-on:** WA-0.1, WA-0.2, WA-0.3 (minimal versions).
- **Effort:** S (assuming a phone + test number on hand).
- **Main risk:** It *doesn't* work, or works only intermittently (Baileys quirks: history-sync noise, `type !== 'notify'`
  events, decryption of certain message kinds). Budget buffer for debugging; this is exactly the risk decision 0001
  called out. **If it fails, it reshapes the rest of the roadmap — that's why it's first.**

### WA-0.5 — Crypto contract for session creds (envelope encryption) — design + helper
- **What:** Settle *how* the Baileys auth state is encrypted before it ever touches `whatsapp_credentials.auth_state`
  (`bytea`): per-business **DEK** wrapped by a **master KEK in the secret manager / KMS** (never in DB, never in `.env`),
  `key_version` for rotation, **decrypt fails loud** (no plaintext fallback — the old `decrypt()` returned ciphertext on
  failure, banned per M2). Build the encrypt/decrypt helper + a serialize/deserialize for the full Baileys auth state.
- **Why:** `whatsapp_credentials.auth_state` is the **crown jewel** (data-model.md): reading it = full WhatsApp account
  takeover. M1: today it's plaintext JSON on disk. The encryption envelope must be designed before we persist a single
  real session (WA-1.2), or we'll have plaintext creds in the DB "temporarily" — which always becomes permanently.
- **Depends-on:** WA-0.1; KEK location decided with **devops_aws** (KMS strongly preferred — data-model open Q1).
- **Effort:** M
- **Main risk:** Getting envelope encryption subtly wrong (IV reuse, wrapping the DEK incorrectly, a silent fallback
  sneaking back in). Keep the crypto tiny, well-tested, and reviewed by the security agent.

---

## Phase 1 — MVP

> Goal: a business owner links their own number by QR, the gateway holds that session encrypted, customer messages flow
> in and replies flow out reliably, over a stable authenticated channel — multi-tenant, no ngrok. This is the gateway's
> contribution to the MVP loop (build → test → go-live → collect) from decision 0004.

### WA-1.1 — QR linking flow (multi-session onboarding) end-to-end
- **What:** The full link flow per business: backend asks gateway to start a session for a `gateway_account_id` → gateway
  emits QR → **QR streamed live to the dashboard over the authed backend channel, never stored** (data-model.md:
  it's session-hijack material) → owner scans → on `connection: 'open'` the gateway reports `connected` and the linked
  phone number → backend updates `whatsapp_connections.status`. Surface the state machine
  (`disconnected`/`connecting`/`qr_pending`/`connected`) the dashboard renders.
- **Why:** This is how a business goes live (decision 0001: "businesses onboard by scanning a QR"). Without it there is no
  way to connect a number, so nothing else in the product can run.
- **Depends-on:** WA-0.3 (multi-session), WA-1.6 (the bridge), WA-1.5 (auth channel); UI is the frontend agent;
  `whatsapp_connections` table is the data agent.
- **Effort:** L
- **Main risk:** QR lifecycle edge cases — QR expiry/refresh (Baileys rotates the QR), the owner closing the tab
  mid-scan, double-link attempts, or a stale `qr_pending` that never resolves. The flow must be restartable and the QR
  must reach the dashboard fast (it expires in seconds). Never leak the QR on an unauthenticated route (old C6 leaked it
  via unauthenticated `GET /status`).

### WA-1.2 — Encrypted session-cred persistence (the crown jewel, wired)
- **What:** Replace the on-disk `credentials/<id>/creds.json` store with a custom Baileys auth-state adapter that
  reads/writes `whatsapp_credentials.auth_state` as **ciphertext** via the WA-0.5 helper. Persist on Baileys'
  `creds.update`; load + decrypt on session start. Enforce that **only the gateway DB role** can touch this table (the
  dashboard/API role has *no grant, not even SELECT* — data-model.md); the value is **never returned by any API, never
  logged, never serialized**.
- **Why:** M1 (plaintext creds on disk → account takeover) is the highest-severity item in this domain. This is the table
  the whole "crown jewel" design in data-model.md exists to protect. It must land before any real customer links a
  number.
- **Depends-on:** WA-0.5 (crypto helper), `whatsapp_credentials` table (data agent), secret manager / KMS (devops_aws).
- **Effort:** M
- **Main risk:** **Single-writer correctness.** Baileys fires frequent `creds.update`s; concurrent or out-of-order writes
  (esp. if two instances ever touch one session) can corrupt the auth state and silently break the session (forcing a
  re-scan and looking like a "ban"). One session = one writer must be guaranteed (ties to WA-2.2). Also: a CI test that
  fails the build if `auth_state` ever appears in a response or log (data-model.md mandates this).

### WA-1.3 — The `accountId` ↔ `business_id` bridge
- **What:** Make `gateway_account_id` the stable join between a Baileys session and a tenant. On link, generate/assign a
  `gateway_account_id`, store it on `whatsapp_connections.gateway_account_id` (UNIQUE). Every inbound payload carries it;
  the backend resolves `business_id` from it (one indexed lookup) and sets the RLS session var. The gateway itself stays
  tenant-agnostic — it only knows `gateway_account_id`, never `business_id` (smaller blast radius, and it keeps tenant
  logic in the backend where RLS lives).
- **Why:** This is *the* fix for B18 (old inbound collapsed every message to one global `client_001`). data-model.md flags
  the wrong mapping as "cross-tenant inbound" — a customer's message landing in another business's dashboard. Decision
  0002's inbound-routing requirement lives or dies here.
- **Depends-on:** WA-0.2 (contract), `whatsapp_connections` table (data agent), backend resolver (backend agent).
- **Effort:** S (gateway side) / M (with the backend resolver + tests).
- **Main risk:** A mismatched or reused `gateway_account_id` = silent cross-tenant leak (the exact failure data-model.md
  warns about, open Q2). Needs explicit isolation tests: two sessions, two businesses, prove messages never cross.
  UNIQUE constraint + "reject unknown `gateway_account_id`" on the backend, never a "first connected" fallback.

### WA-1.4 — Hardened inbound RECEIVE path (the real one)
- **What:** Productionize WA-0.4: filter `fromMe` and non-`notify` events; normalize to the WA-0.2 contract; attach
  `gateway_account_id`; handle text first, and **gracefully degrade** non-text (image/audio/location) to a safe
  placeholder instead of crashing; bound text length before forwarding (feeds the backend's prompt-injection defense,
  M4). Deliver to the backend webhook with **retry + a dead-letter** (see WA-1.7).
- **Why:** Receive is the unverified path (decision 0001) and the foundation of lead collection + handoff (the MVP).
  Decision 0004 explicitly bakes "one real end-to-end inbound test" into Phase 1. The old gateway dropped a message
  permanently on any webhook hiccup (B21) — unacceptable for a lead-capture product.
- **Depends-on:** WA-0.4, WA-1.3, WA-1.5, WA-1.7.
- **Effort:** M
- **Main risk:** Message-type zoo + duplicate delivery. Baileys re-emits on reconnect and during history sync;
  without `message_id`-based idempotency the backend creates duplicate leads. De-dupe on `message_id`.

### WA-1.5 — Stable, authenticated gateway↔backend channel (kill ngrok)
- **What:** A **stable** internal URL between backend and gateway (private networking in prod, env-configured in dev),
  with a **strong service token** (high-entropy, from the secret manager; service refuses to start without it),
  header-only auth, and a **restricted CORS allow-list** (the gateway's API is service-to-service — browsers shouldn't
  call it at all). Remove the old `?token=` query auth and the `my-secret-token` fallback.
- **Why:** B15: ngrok's free URL rotated every session, forcing re-registration each run — "not viable for production".
  C6: default token + wildcard CORS + query-string token = the gateway's send/account-control API was effectively open.
  A stable authed channel is what makes "gateway↔backend actually wired" (architecture.md) real and is a prerequisite for
  both send and receive being dependable.
- **Depends-on:** WA-0.1, WA-0.2; the public/private endpoint itself is **devops_aws** (ALB/DNS/TLS) — I define the
  requirement and the token handling.
- **Effort:** M
- **Main risk:** Token handling regressions (logging the token — old L1 printed it to stdout; leaking via query string).
  Redact in logs; header-only; rotate-able. Also: in prod the gateway must **not** be internet-exposed at all.

### WA-1.6 — Reconnection & reliability (backoff, logout handling, webhook persistence)
- **What:** Replace the old unconditional 3s reconnect (B20, hot-loops a banned session forever) with **exponential
  backoff + jitter + a cap**, and **stop retrying on permanent failures** (e.g. `loggedOut`). On `loggedOut`, set
  `whatsapp_connections.status='disconnected'`, record `last_error`, and surface "re-link needed" to the dashboard — but
  **do not** silently wipe creds and auto-spin a new QR the way the old `deleteCredentials()` did (make re-link a
  deliberate, owner-visible action). **Webhook target is no longer in-RAM** (B3): it's the stable URL from config, so a
  restart never silently stops inbound forwarding.
- **Why:** B20 (hot-loop) actively *increases* ban risk against an already-flagged account. B3 (in-RAM webhook URL lost
  on restart → bot goes silent) is a classic "why did it stop working" outage. Reliability is what makes the gateway
  trustworthy enough to put a real business on.
- **Depends-on:** WA-0.1, WA-0.3, WA-1.5.
- **Effort:** M
- **Main risk:** Distinguishing *transient* disconnects (network blip → reconnect) from *permanent* ones (logged out,
  banned → stop + alert). Misclassify and you either hot-loop (ban risk) or give up on a recoverable session (false
  outage). Lean on Baileys' `DisconnectReason` + Boom status codes; backoff conservatively.

### WA-1.7 — Outbound send + rate-limiting (ban-risk mitigation)
- **What:** A `POST /send` that resolves the session by `gateway_account_id` (no `firstConnected()` fallback),
  normalizes the number to **full international E.164** (kill the hardcoded `972` prefix, B19), and pushes through a
  **per-session send queue with rate-limiting** (token-bucket / min-interval + small jitter, modest concurrency caps).
  Idempotent on `client_msg_id`. Returns a clear success/failure the backend can act on (no fire-and-forget).
- **Why:** Decision 0001's explicit mitigation for the **Baileys account-ban risk** is "sane sending rate limits + one
  number per business". Sending too fast / too bursty is the fastest way to get a number banned, which loses the business
  its WhatsApp line. B19 (hardcoded Israel prefix) corrupts any non-IL number despite the README claiming international
  support.
- **Depends-on:** WA-0.3, WA-1.5; the inbound durability mechanism (queue/DLQ) is shared with WA-1.4.
- **Effort:** M
- **Main risk:** Tuning the rate. Too aggressive → ban (catastrophic for the tenant); too slow → laggy replies that feel
  broken. No public "safe" number from WhatsApp — start conservative, make limits configurable, and monitor. This is an
  inherent, unfixable risk of the unofficial-library decision (0001), only *mitigated*, never eliminated.

### WA-1.8 — Try-me test mode support (no real WhatsApp)
- **What:** Ensure the engine can run a conversation **without** a linked session — the gateway is simply **not in the
  loop** for try-me. Confirm the contract lets the backend originate a "test" conversation (tagged `is_test`) that never
  calls `/send` and never needs a session. Mostly a "don't accidentally require the gateway" guarantee plus a tiny
  contract note.
- **Why:** Decision 0004 makes try-me a first-class part of the MVP build loop ("trust before go-live"). An owner must be
  able to test the bot before scanning the QR — so try-me must work with **zero** gateway involvement. This is cheap but
  easy to break if send is wired in assuming a session always exists.
- **Depends-on:** WA-0.2 (contract clarity). Mostly a backend concern; my job is to not make the gateway a hard dependency
  for test conversations.
- **Effort:** S
- **Main risk:** A latent coupling where some send path assumes a live session and throws in test mode. Guard it.

### WA-1.9 — Compliance touchpoints in my domain (launch-required)
- **What:** The gateway/transport pieces of the launch-compliance requirements:
  1. **Data minimization & retention:** the gateway forwards messages and does **not** persist raw chat — live chat lives
     in Redis with a ~60-min TTL (decision 0006), and only the lead data is kept (data-model.md). The gateway holds *no*
     message store. Confirm and document this (Israeli privacy law / "keep the lead data, throw away the chatter").
  2. **Logs carry no PII/secrets:** structured logging redacts phone numbers, message bodies, tokens, and `auth_state`
     (extends L1; data-model.md "logs never carry secrets or raw PII").
  3. **Consent/opt-out hook (reserve):** leave a clean seam so a future "STOP"/opt-out keyword can suppress outbound to a
     number (privacy-law friendliness) — *reserve the hook, don't build the policy now.*
- **Why:** Launch compliance is **required** (Israeli privacy law, data protection). The gateway is the point where raw
  customer phone numbers and message text enter the system, so minimization + redaction must be enforced *here*, at the
  edge. Accessibility (WCAG) and Terms/Privacy text are the frontend/back-office agents' domains — but they depend on the
  gateway honestly *not* hoarding data.
- **Depends-on:** WA-0.1 (logging), decision 0006 (Redis), data-model.md retention rules.
- **Effort:** S
- **Main risk:** Accidental PII capture in logs/error traces (old L3 dumped raw exceptions; `server_err.txt` pattern).
  A single unredacted `console.log(msg)` during debugging defeats it — enforce redaction at the logger, not by discipline.

---

## Phase 2+ — Post-MVP (back-office, scale, booking/RAG support)

> Goal: operability at scale, the gateway's contribution to the FULL back-office (support + impersonate + platform
> metrics), and the multi-instance hardening that the single-socket Baileys model needs. The billing **engine** is
> deferred — I only **reserve hooks**, per Omer's roadmap.

### WA-2.1 — Back-office: connection health for platform ops & support
- **What:** Expose per-session operational signals to the back-office: per-business connection status, `last_connected_at`,
  `last_error`, reconnect counts, send-queue depth, recent send failures, and ban/disconnect events — **as metrics and
  status only, never message content, never `auth_state`**. Feed a platform-metrics view (how many businesses connected
  right now, how many in `qr_pending`, disconnect rates) and let support see "is this business's WhatsApp actually up?"
- **Why:** Back-office is FULL in the roadmap (manage businesses & users, support + impersonate, platform metrics).
  "Why isn't my bot replying?" is the #1 support ticket for a WhatsApp product, and 90% of the time the answer is a
  dropped session. Support needs this visibility without ever touching the crown jewel.
- **Depends-on:** WA-1.6 (the gateway must *emit* these signals), `whatsapp_connections` (data agent), back-office UI
  (back-office agent).
- **Effort:** M
- **Main risk:** Over-exposure. The temptation to surface "just enough to debug" creeps toward exposing phone numbers or
  session internals. Hard rule: status/metrics only; `auth_state` and message bodies are never in any back-office view.

### WA-2.2 — Horizontal-scale model for sessions (single-writer, multi-instance)
- **What:** Solve the hardest infra constraint (infrastructure.md "biggest blocker"): Baileys sessions are **stateful
  single sockets** that resist horizontal scaling. Design ownership so each `gateway_account_id` is served by **exactly
  one** instance at a time (a session-assignment / lease / sharding scheme), with safe hand-off on instance restart or
  deploy, and a way to drain sessions for zero-downtime deploys.
- **Why:** A single gateway instance is a single point of failure for *every* business (old gateway: "one process, one
  port; if it crashes, all accounts go down"). Growth past one box requires solving single-writer, or two instances will
  both write `whatsapp_credentials` for one session and corrupt it (the WA-1.2 risk, at scale).
- **Depends-on:** WA-1.2 (cred persistence), WA-1.6 (reconnection); infra (instance model, lease store) is **devops_aws**.
- **Effort:** L
- **Main risk:** Split-brain — two instances believing they own the same session → corrupted auth state, duplicate
  sends, ban risk. This is genuinely hard with single-socket sessions; needs a real lease/ownership mechanism and a
  fencing guarantee, co-designed with devops_aws.

### WA-2.3 — Cred key rotation & disaster recovery
- **What:** Operational rotation for the crown jewel: rotate the KEK and re-wrap DEKs using `key_version` (the schema
  already carries it), with **fail-closed** decrypt throughout. A documented recovery runbook for "instance died /
  storage lost" — and the honest answer that a destroyed session means each affected business must **re-scan the QR**
  (so the path must be smooth and self-serve).
- **Why:** data-model.md mandates key versioning + rotation for `whatsapp_credentials`; a key compromise with no rotation
  path means re-linking every business by hand. Rotation is a security-hygiene + incident-readiness requirement.
- **Depends-on:** WA-0.5, WA-1.2; KMS rotation policy with **devops_aws**.
- **Effort:** M
- **Main risk:** A rotation bug that makes existing sessions undecryptable = a mass re-link event (every business offline
  until they re-scan). Test rotation against real persisted sessions in staging before ever running it in prod.

### WA-2.4 — Richer messaging for booking & RAG flows
- **What:** Extend outbound beyond plain text as Phase 2/3 features land: reliably send **booking links** (Phase 2) and,
  if needed, media/structured replies for RAG answers (Phase 3). Possibly inbound media handling (e.g. a customer sends a
  document) feeding RAG. Built on the same rate-limited send queue.
- **Why:** Phase 2 is booking (decision 0004, including fixing the "chat flow doesn't actually book" bug B7 — backend's
  fix, but the link goes out *through me*) and Phase 3 is RAG. The transport must support whatever those flows need to
  send/receive.
- **Depends-on:** WA-1.7 (send queue); driven by the Phase 2/3 feature specs.
- **Effort:** M
- **Main risk:** Media handling expands the message-type surface (bigger payloads, more Baileys edge cases, more ban-risk
  if abused). Keep it minimal and rate-limited; resist scope creep here.

### WA-2.5 — Reserve billing hooks (no engine)
- **What:** Make sure per-business usage signals the billing engine will eventually want — message volume sent/received,
  active-session time — are *observable and attributable to `business_id`* (via the bridge), even though nothing meters
  or charges yet. A clean seam, not an implementation.
- **Why:** Omer's roadmap: billing engine is **DEFERRED** — "only reserve a place/hooks for it". WhatsApp message volume
  is the most likely billable/limitable axis, so the data should be *attributable* from day one rather than retrofitted.
- **Depends-on:** WA-1.3 (the bridge), WA-2.1 (metrics plumbing).
- **Effort:** S
- **Main risk:** Over-building a billing system disguised as "hooks". Keep it to: the numbers exist and are tagged by
  business. Do **not** build metering, quotas, or enforcement now.

---

## Cross-cutting dependencies & open questions

**Hard dependencies on other agents (blocking my Phase 1):**
- **Data agent:** DDL for `whatsapp_connections` (table 4) and `whatsapp_credentials` (table 5), incl. the
  **gateway-only DB role** with no dashboard grant on the crown jewel.
- **devops_aws:** secret manager / **KMS** for the KEK (data-model open Q1 — KMS strongly preferred); the **stable
  private endpoint** replacing ngrok (B15); the instance/scaling model + a lease store for WA-2.2; Redis (for the
  backend's live-chat side, decision 0006).
- **Backend agent:** the webhook receive handler + the `gateway_account_id → business_id` resolver + RLS session var;
  the conversation engine; secret-manager client wiring.

**Open questions I need answered (carried from data-model.md):**
1. **KEK: KMS vs app-held?** (Open Q1) — KMS strongly preferred; decide with devops_aws in the AWS phase. Blocks the
   *production* hardening of WA-0.5/WA-1.2, not the dev version.
2. **`gateway_account_id` generation & bridge confirmation** (Open Q2) — confirm the exact id scheme during the build
   phase (WA-1.3). Wrong mapping = cross-tenant inbound; this is the highest-stakes correctness question in my domain.
3. **Send rate limits — actual numbers?** No authoritative WhatsApp figure exists for Baileys; start conservative, make
   configurable, tune from real ban/no-ban observation (WA-1.7).
4. **Does receive actually work end-to-end?** (decision 0001) — answered empirically by WA-0.4. *Everything assumes yes;
   if no, the roadmap shifts.* Marked **needs verification** until that spike passes.

---

## Summary (return)

**Phases**
- **Phase 0 — Foundations:** clean gateway skeleton; freeze the gateway↔backend contract; multi-session spike; **the
  end-to-end RECEIVE smoke test (top priority unknown)**; design the crown-jewel encryption envelope.
- **Phase 1 — MVP:** QR linking (multi-session); encrypted session-cred persistence; the `accountId↔business_id` bridge;
  hardened inbound receive; stable authed channel (kill ngrok); reconnection/reliability; outbound send + rate-limiting;
  try-me support; compliance edge (data minimization + log redaction).
- **Phase 2+ — Post-MVP:** back-office connection health + platform metrics; horizontal-scale single-writer model; cred
  key rotation + DR; richer messaging for booking/RAG; reserve (not build) billing hooks.

**Biggest tasks (5–8)**
1. **WA-1.1 — QR linking flow, multi-session (L).** How any business goes live.
2. **WA-2.2 — Horizontal-scale single-writer session model (L).** The "biggest blocker" — single-socket Baileys vs.
   multi-instance, with split-brain risk.
3. **WA-1.2 — Encrypted session-cred persistence, the crown jewel (M).** Fixes the top security issue (M1); single-writer
   correctness is the hard part.
4. **WA-1.4 — Hardened inbound receive path (M).** Productionizes the unverified path the whole product depends on.
5. **WA-1.7 — Outbound send + rate-limiting (M).** The primary mitigation for the Baileys ban risk (decision 0001).
6. **WA-1.6 — Reconnection/reliability: backoff + logout handling + persistent webhook (M).** Fixes the hot-loop (B20)
   and the silent-stop (B3); makes the gateway trustworthy.
7. **WA-1.5 — Stable authed gateway↔backend channel, kill ngrok (M).** Fixes B15 + C6; makes "actually wired" real.
8. **WA-0.4 — End-to-end RECEIVE smoke test (S, but first).** De-risks the single biggest unknown in week one.

**Top risk**
**The Baileys account-ban risk is structural and only mitigable, never eliminable** (decision 0001: unofficial library,
against WhatsApp ToS). A banned number takes a business's WhatsApp line down. It is attacked from several angles —
conservative **send rate-limiting** (WA-1.7), **backoff instead of reconnect hot-loops** (WA-1.6), and **one number per
business** (the multi-session model) — but it cannot be designed away. Close behind, and the thing most likely to cause a
*silent* failure: a **wrong `gateway_account_id↔business_id` mapping** leaking one business's inbound messages into
another's dashboard (WA-1.3) — which is why receive isolation needs explicit two-tenant tests. And the one true unknown:
**receive has never been verified end-to-end** (WA-0.4) — the entire Phase 1 assumes it works.
