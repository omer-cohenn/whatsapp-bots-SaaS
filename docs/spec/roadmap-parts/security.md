# Roadmap — Security & Data-Protection slice

> My domain's part of the production roadmap for the **Bizz_up** rebuild.
> Owner: SECURITY agent. Drafted 2026-06-16.
> Grounded in: `security-issues.md` (C1–C6, M1–M5, L1–L4), `spec/data-model.md` (FINAL),
> `spec/architecture.md`, decisions `0001`/`0002`/`0004`/`0005`/`0006`.
>
> **Source-of-truth note:** the FINAL data-model is **9 Postgres tables + Redis** (decision 0006
> superseded the "12 tables / `conversations` table" wording in 0005). Live chat is in Redis, which
> has **no RLS** → its tenant isolation is an **app-layer** concern (called out below).
>
> **Framing:** this is a *clean rebuild*, not a patch of `last_bo`/`qr_wa_scanner`. So "fix C2" means
> "build the new system so C2 cannot exist," not "edit the old file." Every old issue maps to a
> design property of the rebuild. Each task lists the old issue IDs it closes.

---

## How the security work is sequenced

Three principles drive the ordering:

1. **Foundations must land before the MVP touches real PII.** Secrets-out, the auth gate, RLS + DB
   roles, and encryption are *prerequisites* for leads/handoff — not a hardening pass afterwards.
   The old system's leaks all came from skipping this. (decision 0004 already bakes auth + isolation
   + secrets into Phase 1.)
2. **The isolation test suite is the gate, not a nicety.** Hand-wired RLS was the old system's #1
   failure point (0005). Nothing tenant-scoped ships until the isolation suite is green in CI.
3. **Compliance + back-office security ride their features.** Privacy-law data-protection (consent,
   deletion, retention) ships with the data it governs; impersonation safety + audit ship with the
   back-office that introduces impersonation. Neither is bolted on at the end.

**Cross-domain dependencies I rely on** (other agents own these; I consume them):
- `devops_aws`: the **secret manager / KMS** (which vendor, KMS-vs-app-held KEK — open Q1 in data-model),
  the **private network + TLS + auth** for Postgres & Redis, and **CI runner** for my guards.
- `backend`: the FastAPI app structure, the Postgres connection layer (where `SET LOCAL app.business_id`
  lives), the LangGraph flow engine (where input validation hooks in), and the webhook handler.
- `gateway`: the Node/Baileys service (where token/CORS/QR hardening lands) and the
  `accountId ↔ business_id` bridge (open Q2 — wrong mapping = cross-tenant inbound).
- `data`: the schema DDL (I add RLS policies, `key_version` columns, GRANTs on top of their tables).

---

## Phase 0 — Foundations (security prerequisites; before MVP touches PII)

> These block Phase 1. They are the "make the old leaks structurally impossible" layer.

### 0.1 — Secrets out of `.env` + rotate everything (closes C1, L2, L4, part of M3)
- **What:** No secrets in any `.env` or repo file. All keys (Postgres creds, Redis auth, session secret,
  Google OAuth client secret, Gemini key, the **PII data key**, the **crown KEK** for WhatsApp creds, the
  **HMAC key** for phone lookups, the gateway API token) live in the secret manager and are injected as
  host/process env at runtime. **Every old `.env` value is treated as compromised and rotated** on day one
  (Supabase keys, DB password, Google OAuth secret, Gemini key, Fernet key, session secret, gateway token).
  Add a startup **secret-presence check**: the app (and gateway) **refuse to boot** if any required secret
  is missing or equals a known placeholder (`change-me*`, `my-secret-token`, `secret`).
- **Why:** C1 — the old `.env` was the master keychain (service key bypassing RLS, the Fernet key that
  decrypts every lead, the WhatsApp token). Even though it wasn't in git, local-disk exposure of all of
  them is a full compromise. Fail-loud-on-missing kills the `change-me-in-env` / `my-secret-token`
  defaults (M3, C6, L2).
- **Depends on:** `devops_aws` picking the secret-manager vendor (open Q1). Until then, dev uses a local
  `.env` that is git-ignored *and* whose values are throwaway, with the **same presence check** wired so
  prod parity holds.
- **Effort:** **M** (mechanism is small; the discipline + rotation + wiring the presence check into two
  services is the work).
- **Risk:** Rotating `ENCRYPTION_KEY`/Fernet means any data encrypted under it is unreadable — but this is
  a **clean rebuild with no data to migrate**, so we simply start fresh under new keys. Real risk is a
  *forgotten* secret read still pointing at a file → the presence check + the CI secret guard (0.7) catch it.

### 0.2 — Enforced auth gate on every route; no anonymous-tenant fallback (closes C2, C3, part of M3)
- **What:** A single FastAPI auth dependency/middleware applied to **every** `/api/*` and (later) back-office
  route. It (a) requires a valid signed session from Google login, (b) resolves the user, (c) resolves the
  business via `business_members`, (d) **rejects with 401/403 when there is no session** — never falling back
  to a shared/default business. There is **no** `_business_id_from_config()` equivalent and **no** global
  admin endpoint. The session cookie is signed with a real `SESSION_SECRET` from the manager (boot fails if
  unset). Genuinely public routes (the future public booking page in Phase 2, OAuth callback, health) are an
  explicit, reviewed allow-list — everything else is closed by default.
- **Why:** C2 — the old per-route check let most data endpoints skip auth and fall back to a shared tenant,
  leaking decrypted lead PII to anonymous callers and letting anonymous POSTs rewrite the bot config (which
  also *deleted* leads). C3 — `/admin/*` was unauthenticated and globally destructive. Closed-by-default
  middleware makes "forgot to guard this route" impossible.
- **Depends on:** 0.1 (real session secret); `backend` app skeleton; Google OAuth wiring (shared with
  `backend`).
- **Effort:** **M**.
- **Risk:** An allow-list entry that's too broad re-opens C2. Mitigate: the allow-list is tiny, reviewed,
  and the isolation suite (0.6) includes "unauthenticated request to a tenant route → 401."

### 0.3 — Hand-wired RLS on every tenant table (closes the core of C2/C3/C4)
- **What:** For all 8 tenant tables (`business_members`, `whatsapp_connections`, `whatsapp_credentials`,
  `bot_settings`, `leads`, `bot_builder_messages`, `flow_events`, and the businesses-scoping itself), enable
  RLS with both a read `USING (business_id = current_business_id())` and a write
  `WITH CHECK (business_id = current_business_id())` policy. `current_business_id()` reads the per-request
  `SET LOCAL app.business_id` the auth layer sets after verifying ownership via `business_members`. The app
  connects as a **non-service role** so RLS is actually enforced (the old service key bypassed it — *the*
  core bug). `business_id` is **never** taken from the browser.
- **Why:** Defense-in-depth so that even a forgotten `WHERE business_id = …` in app code (C4 was exactly
  that — `PATCH /api/bookings` had no predicate) still cannot cross tenants. RLS is the safety net under
  the app filter.
- **Depends on:** `data` schema DDL; 0.2 (something must set `app.business_id`); 0.4 (the non-service role).
- **Effort:** **M** (policies are formulaic; the `current_business_id()` + `SET LOCAL` plumbing and getting
  it right under a connection pool is the careful part).
- **Risk:** **Connection pooling** — a pooled connection that reuses a prior request's `app.business_id`
  would leak across tenants. Mitigate: `SET LOCAL` inside the per-request transaction (resets on commit),
  + an isolation test that hammers concurrent requests on a shared pool. **This is the single highest-risk
  item in the whole slice.**

### 0.4 — Least-privilege DB roles (closes part of C1; enforces crown-jewel isolation)
- **What:** Two app DB roles, neither the service/superuser role:
  - **dashboard/API role** — tenant-scoped, subject to RLS, **no grant at all on `whatsapp_credentials`**
    (not even SELECT).
  - **gateway role** — the *only* role that can read/write `whatsapp_credentials` (the Baileys session key).
  No service-role key anywhere in the app. Grants are explicit per-table; "missing grant first, RLS second."
- **Why:** C1 — the leaked Supabase **service key** granted full cross-tenant read/write bypassing RLS.
  Splitting roles means a compromised dashboard process **physically cannot** read the crown-jewel session
  keys, and a compromised gateway can't read leads. Blast-radius reduction.
- **Depends on:** `data` schema; `devops_aws` for how the two roles' credentials are provisioned/injected.
- **Effort:** **S–M**.
- **Risk:** Over-tight grants break a legitimate query at runtime → caught by integration tests; under-tight
  grants (e.g. dashboard role accidentally granted on credentials) defeat the point → an isolation test
  asserts the dashboard role gets a permission error on `whatsapp_credentials`.

### 0.5 — Encryption + fail-loud decrypt (PII data key + crown KEK) (closes M2; enables M1, M5)
- **What:** Field-level encryption before insert for all 🔒 columns: `leads.phone`, `leads.contact_name`,
  `leads.answers`, `whatsapp_connections.phone_number`, and (closing M5) booking client PII when Phase 2
  lands. Two **separate** keys: a **PII data key** for the above, and a distinct **crown KEK** that
  envelope-encrypts the Baileys `whatsapp_credentials.auth_state` (per-business DEK wrapped by the KEK).
  Both keys live in the manager/KMS, never the DB, never `.env`. Every encrypted row carries `key_version`
  for clean rotation. **Decryption fails loud** — on any decrypt error it logs (no plaintext/ciphertext in
  the log) + emits a metric + raises; it **never** returns the raw input. Plaintext lookups use a **keyed
  HMAC** (`customer_phone_hash`) whose key is also a real secret.
- **Why:** M2 — the old `decrypt()` swallowed all exceptions and returned the ciphertext/garbage "safe
  during migration," silently masking a wrong/rotated key and letting plaintext PII persist undetected.
  Fail-loud + no-fallback means a bad key fails *closed*. M1 — Baileys creds were plaintext JSON on disk
  (= account takeover); envelope encryption + crown KEK makes a stolen DB dump useless. Separate keys so one
  leak isn't total.
- **Depends on:** 0.1 (keys in the manager); `data` (the `key_version` columns); `devops_aws` (KMS choice,
  open Q1).
- **Effort:** **M**.
- **Risk:** Getting envelope encryption + rotation right is fiddly; a botched KEK wrap = unrecoverable
  session keys (forces a QR re-scan — acceptable, not catastrophic, but annoying). Mitigate with a tiny,
  well-tested crypto module + round-trip unit tests incl. a deliberately-wrong-key "must raise" test.

### 0.6 — Multi-tenant ISOLATION TEST SUITE (the gate) (proves C2/C3/C4 closed; guards RLS)
- **What:** A dedicated automated suite, **required green in CI before any tenant feature merges**, that
  proves one business can never see/touch another's data. Coverage:
  - **DB/RLS layer:** as business A, attempt SELECT/UPDATE/DELETE on B's rows in every tenant table →
    zero rows / permission denied. Attempt with a spoofed `app.business_id` → denied. Attempt to read
    `whatsapp_credentials` as the dashboard role → permission error.
  - **API layer:** A's session calling an endpoint with B's `business_id`/resource id (the C4 booking
    case, leads, conversations) → 404/403, never B's data. Unauthenticated request to a tenant route → 401
    (proves the C2 fallback is gone). No global/admin destructive endpoint exists.
  - **Pooling/concurrency:** interleaved concurrent requests from A and B on a shared connection pool →
    no `app.business_id` bleed (guards 0.3's top risk).
  - **Redis cache:** A cannot read/write B's `chat:{business_id}:…` key; a missing/forged prefix is
    rejected (app-layer isolation, since Redis has no RLS).
- **Why:** Hand-wired RLS was the old system's #1 failure (0005 explicitly: "must be covered by tests").
  This suite is the *contract* that the foundations actually hold, run on every change so a future edit
  can't silently regress isolation.
- **Depends on:** 0.2, 0.3, 0.4, 0.5; `backend` test harness; `devops_aws` CI.
- **Effort:** **L** (broad surface; the pooling/concurrency and Redis cases are the hard, high-value part).
- **Risk:** A green suite that doesn't actually exercise RLS (e.g. tests run as the service role and pass
  trivially) gives false confidence — *worse than no test*. Mitigate: tests run as the real non-service
  role(s), and the suite includes a self-check "negative control" (a deliberately-cross-tenant query that
  *must* fail) so a misconfigured harness is caught.

### 0.7 — CI guard: fail the build on any secret/PII in logs or responses (closes L1, L3; enforces M2)
- **What:** A CI check (+ a runtime log scrubber) that **fails the build** if a secret or raw PII can leak
  through logs or API responses. Two parts:
  - **Static/test-time:** scan the repo + run a set of API/log assertions — known secret patterns (Fernet
    key, JWT/session secret, Google `GOCSPX-`, Postgres URL with password, the gateway token, KEK/DEK
    material) and PII shapes (phone, email, the Baileys `auth_state`) must **never** appear in any captured
    log line or HTTP response body. Error responses to clients are generic (no `str(e)`, no stack — closes
    L3); details are logged server-side only, scrubbed.
  - **Runtime:** a logging filter that redacts the same patterns, so even an accidental `log.info(secret)`
    is masked in prod.
- **Why:** L1 — the old gateway printed API tokens to stdout on startup. L3 — handlers returned raw
  exception text (DB/stack) to clients and rendered exceptions into OAuth-callback HTML. The crown-jewel rule
  in data-model.md explicitly demands "a CI test fails the build if the session key ever appears in a
  response or log." This is that test, generalized to all secrets + PII. Israeli privacy law (see 1.x) also
  requires not exposing personal data in logs.
- **Depends on:** `devops_aws` CI runner; the logging setup from `backend`/`gateway`.
- **Effort:** **M**.
- **Risk:** Pattern-matching is imperfect — false negatives (a novel secret format slips through) and false
  positives (a legit value looks like a phone number, blocking the build). Mitigate: drive secret detection
  off the *known* secret names from the manager (not just regex), and keep an audited allow-list for false
  positives. Treat it as defense-in-depth, not the only control (encryption + no-fallback errors are the
  primary controls).

### 0.8 — Gateway transport hardening: token / CORS / QR / creds-at-rest (closes C6, M1, L1)
- **What:** Harden the Node/Baileys gateway: (a) **refuse to start without a strong, non-default
  `API_TOKENS`** — remove the `my-secret-token` fallback in both `index.js` and the frontend; (b) accept the
  token **only via header**, never `?token=` query string (keeps it out of logs/history); (c) **lock CORS**
  to the known backend/dashboard origins (no wildcard); (d) put `GET /status` **behind auth** and **never
  return the live QR unauthenticated** (the unauth QR was a session-hijack hole) — the QR is streamed to the
  dashboard over the authed channel and **never stored** (data-model.md); (e) the gateway writes the Baileys
  `auth_state` only as **envelope-encrypted ciphertext** into `whatsapp_credentials` (no plaintext
  `creds.json` on disk — closes M1), readable only by the gateway DB role (0.4); (f) **never log the token
  or any creds** (closes L1).
- **Why:** C6 — the shipped default token + wildcard CORS + query-string token + unauth `/status` together
  let anyone reachable on the port send WhatsApp as the business, redirect inbound messages to an attacker
  (full interception), wipe sessions, or hijack the session by loading the QR first. M1 — plaintext creds on
  disk = account takeover from any file leak.
- **Depends on:** 0.1 (token + KEK in manager); 0.4 (gateway DB role); 0.5 (envelope encryption module);
  `gateway` owns the service code; `devops_aws` for the gateway↔backend network/origins.
- **Effort:** **M**.
- **Risk:** Mis-scoped CORS or a wrong `accountId ↔ business_id` bridge (open Q2) could break linking or —
  worse — route a business's inbound messages to the wrong tenant (a cross-tenant leak via the transport
  layer). Mitigate: the isolation suite (0.6) includes an inbound-routing test once the bridge exists, and
  the bridge is confirmed during the build phase (0005).

---

## Phase 1 — MVP (security riding the leads + handoff + bot-builder + try-me build)

> Foundations (Phase 0) are in place; these are the security tasks that attach to the actual MVP features
> and the launch-required compliance.

### 1.1 — Webhook authenticity for the Baileys inbound path (closes C5, adapted)
- **What:** The inbound webhook (gateway → backend) must **authenticate the caller**. The old C5 was a Meta
  `X-Hub-Signature-256` HMAC check; since we're on the **Baileys gateway** (decision 0001), the equivalent is
  a **shared-secret / HMAC signature on the gateway→backend webhook** (secret from the manager), so the
  backend only accepts message payloads that genuinely came from our gateway — plus binding each payload to a
  known `gateway_account_id` → `business_id`. Reject unsigned/mismatched payloads before processing.
- **Why:** C5 — the old Meta webhook never verified its signature, so anyone who learned the public URL could
  POST forged "incoming message" payloads, drive the bot, inject `phone`/`text`, create leads, flip status,
  and burn Gemini quota. The Baileys path has the same exposure if the backend trusts any POST. Authenticating
  the webhook closes it.
- **Depends on:** 0.1; `gateway` (signs outbound); `backend` (verifies); the `accountId ↔ business_id` bridge
  (open Q2).
- **Effort:** **S–M**.
- **Risk:** A wrong/forged `accountId→business_id` mapping injects a customer's message into the wrong
  tenant's flow (cross-tenant). Covered by the inbound-routing isolation test (0.6 / 0.8).

### 1.2 — Input validation + bound-checking on all inbound/public fields; treat LLM I/O as untrusted (closes M4)
- **What:** Validate and bound every field arriving from WhatsApp or any public path before it touches the DB
  or the LLM: max lengths on message text, validated/normalized phone, validated email + field lengths on any
  public form (the booking form lands in Phase 2 but the validation pattern is set now), and **verify a
  business is real/provisioned** before accepting any public write (no auto-creating rows under an
  attacker-chosen identifier — the old `slug`-as-`business_id` hole). Sanitize/limit text before it reaches
  Gemini and **treat LLM output as untrusted** (no executing it, escape on render). SQL stays fully
  parameterized (the old code already was — keep it).
- **Why:** M4 — unbounded WhatsApp text + unvalidated public fields enabled stored-garbage, oversized
  payloads, **prompt-injection** via WhatsApp text into the Gemini flow, and creation of rows under arbitrary
  identifiers (a public unauthenticated write path). Validation + provisioning-check + untrusted-LLM posture
  closes it.
- **Depends on:** `backend` flow engine + the public-route allow-list (0.2); pairs with `gateway` payload
  shape.
- **Effort:** **M**.
- **Risk:** Prompt-injection can't be fully "validated away" (it's an open problem). Mitigate with
  least-privilege prompts (the LLM has no tools that can act destructively), output treated as text only,
  and bounded input — accept residual risk, document it.

### 1.3 — Data-protection: Israeli Privacy Law compliance for the data we collect (LAUNCH-REQUIRED)
- **What:** The security/data-protection half of launch compliance for the **leads** the bot collects (names,
  phones, form answers = personal data under Israel's Protection of Privacy Law). Concretely:
  - **Lawful collection + notice/consent:** the bot/booking flows tell the customer what's collected and why,
    and capture consent where required; a customer-facing **Privacy Policy** (content co-owned with the
    legal/compliance + frontend agents; I own the *data-handling* claims it must truthfully reflect:
    encryption at rest, who can access, retention, deletion).
  - **Data-subject rights:** a mechanism to **access, correct, and delete** a person's data on request
    (delete a lead + its `flow_events` + any Redis remnant; the model already cascades `flow_events` off
    `leads` and Redis auto-expires).
  - **Retention:** a defined retention period for leads + an **automated purge** of data past it (abandoned
    leads are kept for follow-up, but not forever).
  - **Minimization + security obligations:** collect only needed fields; the encryption (0.5), access
    controls (0.3/0.4), and no-PII-in-logs guard (0.7) are the "reasonable security measures" the law
    requires — this task ties them to the legal obligation and documents them.
  - **Breach-readiness:** a basic incident/notification note (who/what/when) so we can meet notification duties.
- **Why:** Launch compliance is **REQUIRED** (Omer). Beyond the legal duty, the whole product's trust story
  is "we handle small businesses' customer data safely." This is where the encryption + access controls become
  an auditable compliance posture, not just engineering.
- **Depends on:** 0.5 (encryption), 0.3/0.4 (access control), 0.7 (no PII in logs); the **legal/compliance +
  frontend** agents for the Privacy Policy + Terms + the consent UI surface (accessibility/WCAG of those pages
  is the frontend/compliance agent's, not mine).
- **Effort:** **M** (the deletion/retention plumbing is real work; the policy text is shared).
- **Risk:** Under-scoping the law (e.g. database-registration duties, cross-border transfer rules if data
  sits on non-Israeli AWS regions) → mark **needs verification** with a privacy-law professional; I'll
  enumerate the data-handling facts, not adjudicate the legal interpretation.

### 1.4 — Auth/session hardening for the owner app (rounds out M3, L3)
- **What:** Finish the owner-facing auth posture: secure session cookies (HttpOnly, Secure, SameSite),
  sensible session lifetime/refresh, CSRF protection on state-changing routes (since auth is cookie-based),
  generic client-facing errors everywhere (no `str(e)` / stack — also L3), and the OAuth callback hardened
  (state param, no exception text rendered into HTML).
- **Why:** M3/L3 — the old system signed sessions with a known constant fallback and leaked exception text to
  clients incl. the OAuth callback HTML. With cookie auth, CSRF is a real gap to close.
- **Depends on:** 0.2 (the auth layer); `backend`/`frontend` for CSRF token plumbing.
- **Effort:** **S–M**.
- **Risk:** Over-aggressive session expiry hurts UX; mis-placed CSRF check blocks legit calls. Low security
  risk, mostly tuning.

---

## Phase 2+ — Post-MVP (back-office, booking, RAG, scale)

> Security work that attaches to later features. The **back-office** is FULL (decision: manage businesses &
> users, billing VIEW, support + impersonate, platform metrics) — its security is substantial and is **my**
> domain. The billing **engine** is DEFERRED — I only reserve hooks, build no payment security now.

### 2.1 — BACK-OFFICE: platform-admin role + privileged access model (Phase 2)
- **What:** A real **platform-staff** identity tier, separate from tenant `business_members` — the back-office
  operator who can manage businesses & users, view billing, see platform metrics, and (carefully) impersonate.
  This needs its own authn/authz: a platform-admin role/claim, a **separate authenticated surface** (not the
  tenant app's auth path reused loosely), and explicit, least-privilege capabilities (e.g. "view billing" is
  read-only; "manage users" is scoped). Crucially, platform-admin access **does not** silently inherit RLS
  bypass — any cross-tenant read is **deliberate, logged, and scoped**, never the old service-key free-for-all.
- **Why:** The old system had **no admin-role concept at all** (that's exactly why C3's `/admin/*` was
  open-to-the-world). A FULL back-office that can touch every tenant is a huge privilege; it must be a
  first-class, tightly-scoped, audited role — the highest-blast-radius surface in the product after the crown
  KEK.
- **Depends on:** Phase 0 (auth gate, roles, RLS, isolation suite); `backend` back-office API; `data` for any
  platform-staff table.
- **Effort:** **L**.
- **Risk:** A back-office that re-introduces a god-mode/service-role path silently undoes all of Phase 0's
  isolation. Mitigate: back-office cross-tenant reads go through an explicit, logged, scoped path — and the
  isolation suite gets back-office cases ("a platform admin's normal session still can't read tenant data
  except via the audited admin path").

### 2.2 — BACK-OFFICE: impersonation safety + audit logging (Phase 2)
- **What:** Make "support can impersonate a business" safe:
  - **Explicit, bounded, consented-where-required:** impersonation starts an explicit session that is clearly
    flagged ("you are acting as <business> as staff <name>"), is **time-boxed**, and ideally is **read-first**
    (write actions while impersonating are extra-gated/limited).
  - **Full audit trail:** an **append-only audit log** records who impersonated whom, when, why, from where,
    and **every action taken** while impersonating — tamper-evident, retained, and queryable. The audit log
    itself is access-controlled (not editable by the operators it records).
  - **No credential theft:** impersonation never exposes the business's secrets (never the WhatsApp
    `auth_state`, never decrypted PII beyond what the support task needs), and never the crown KEK.
- **Why:** Impersonation is the single most abusable back-office power — an insider (or a compromised
  back-office account) could read every tenant's customer PII. Bounded + fully-audited impersonation is the
  control that makes a support feature compatible with the privacy obligations from 1.3. Under Israeli privacy
  law, staff access to personal data must be controlled and accountable — the audit log is that accountability.
- **Depends on:** 2.1 (platform-admin role); 0.4 (roles); 0.7 (no PII/secret in the audit log either —
  it logs *that* an action happened, scrubbed of raw secrets); `data` for the audit table.
- **Effort:** **M–L**.
- **Risk:** An audit log that's incomplete (misses some actions) or itself leaks PII is worse than none —
  it gives false assurance and a new leak surface. Mitigate: audit at a choke point (every impersonated
  request passes one middleware that logs), scrub per 0.7, and test that impersonated actions are recorded.

### 2.3 — BACK-OFFICE: billing-VIEW data access + reserved billing-engine hooks (Phase 2)
- **What:** Secure the **read-only** billing view (back-office sees plan/usage/invoices) and **reserve a
  place** for the future billing engine without building payment security now: define where billing data
  *would* live, mark it as future-sensitive (card data, if ever, is **out of scope** and would be tokenized
  via a PCI-compliant provider — never stored by us), and ensure today's billing-VIEW is least-privilege +
  audited like the rest of the back-office.
- **Why:** Billing engine is **DEFERRED** (Omer) — so no payment/PCI security work now, but the back-office
  *does* show billing, and that read path must respect the same auth/audit rules. Reserving the hooks avoids a
  later retrofit and signals "card data never touches our DB."
- **Depends on:** 2.1, 2.2.
- **Effort:** **S** (now — just the view's access control + a documented reservation; the real billing-security
  work is later with the engine).
- **Risk:** Scope-creep into building payment security prematurely. Explicitly *not* doing that now.

### 2.4 — Booking: extend security controls to the booking feature (Phase 2)
- **What:** When booking lands (Phase 2, fixing bug B7), extend the existing controls to it: **encrypt booking
  client PII** (name/email/phone) with the PII data key — closing **M5** (the old bookings were cleartext while
  leads were encrypted); add booking tables to **RLS** + the **isolation suite** (the old C4 cross-tenant
  booking-modification must be impossible by construction); validate the **public booking form** + verify the
  business slug is real before any write (the public-write hole from M4); and fold booking PII into the
  retention/deletion of 1.3.
- **Why:** M5/C4/M4 all centered on booking. Booking is the first **public unauthenticated write path** and a
  known cross-tenant-leak source in the old system, so it inherits the full stack: encryption + RLS + isolation
  tests + input validation + privacy retention.
- **Depends on:** 0.5, 0.6, 0.3, 1.2, 1.3; `backend`/`data` building the booking feature.
- **Effort:** **M**.
- **Risk:** Booking re-opens C4 if a new endpoint forgets the `business_id` predicate — RLS (0.3) is the net,
  and the isolation suite gets booking cases.

### 2.5 — RAG: tenant isolation + content safety for the knowledge base (Phase 3)
- **What:** When RAG lands (Phase 3), ensure uploaded documents + pgvector embeddings are **tenant-isolated**
  (a business's retrieval never returns another business's chunks — RLS/scoping on the vector store + storage),
  scan/limit uploads (size, type, malware-adjacent content), keep retrieval grounded (no cross-tenant context
  bleed into prompts), and gate the (old C3) rebuild/index operations behind auth + rate limits (the old
  `/admin/rebuild-rag` was an unauth DoS/cost vector).
- **Why:** RAG adds a new high-value cross-tenant leak surface (one business's private docs answering another's
  customer) and a new abuse/cost surface (unauth rebuilds). It must inherit isolation + the test suite.
- **Depends on:** 0.6 (isolation suite extended to vectors/storage); `data`/`backend` RAG build; `devops_aws`
  for pgvector/storage.
- **Effort:** **M–L**.
- **Risk:** Vector-store isolation is easy to get subtly wrong (embeddings in a shared index without a tenant
  filter). Mitigate: per-tenant scoping + a RAG cross-tenant retrieval test in the isolation suite.

### 2.6 — Scale-time hardening: rate limiting, abuse controls, key rotation drills (Phase 2+)
- **What:** As the platform scales: **rate limiting / abuse controls** on inbound webhooks, public endpoints,
  and Gemini-cost paths (the old C5/C3 burned quota with no limit); **sending rate limits** on the gateway to
  reduce WhatsApp **ban risk** (decision 0001's explicit mitigation); and a rehearsed **key-rotation drill**
  for the PII key + crown KEK (exercise `key_version` end-to-end so rotation is routine, not a crisis).
- **Why:** Baileys ban-risk (0001) and cost/DoS abuse become real at scale; key rotation must be practiced
  before it's needed (the old fail-closed design only helps if rotation actually works).
- **Depends on:** 0.5 (`key_version`), 0.8 (gateway), 1.1 (webhook); `devops_aws` for rate-limit infra.
- **Effort:** **M**.
- **Risk:** Rate limits too aggressive → drop legit customer messages; too loose → ban/cost risk remains.
  Tuning + monitoring.

---

## RETURN — tight summary

**Phases (my slice):**
- **Phase 0 — Foundations (8 tasks):** secrets-out + rotate, enforced auth gate (no anon fallback),
  hand-wired RLS, least-privilege DB roles, encryption + fail-loud decrypt, the **isolation test suite**
  (the gate), the **CI secret/PII guard**, and gateway transport hardening. These make the old leaks
  *structurally impossible* and must land before the MVP touches real PII.
- **Phase 1 — MVP security (4 tasks):** webhook authenticity (Baileys-adapted C5), input validation +
  untrusted-LLM posture, **Israeli privacy-law data-protection** (consent / access / delete / retention —
  launch-required), and owner-app session/CSRF hardening.
- **Phase 2+ — Post-MVP (6 tasks):** the **FULL back-office** security (platform-admin role, **impersonation
  safety + audit logging**, billing-VIEW + reserved billing hooks), booking security (closes M5/C4 by
  construction), RAG tenant isolation, and scale-time rate-limiting + key-rotation drills.

**The 5–8 biggest tasks:**
1. **Hand-wired RLS on every tenant table** (0.3) — the core fix for the cross-tenant leaks; the pooling case
   is the trickiest single piece.
2. **Multi-tenant isolation test suite** (0.6) — the gate that proves isolation holds; the old system's #1
   failure was the *absence* of this. **L.**
3. **Enforced auth gate, no anonymous-tenant fallback** (0.2) — closes C2/C3 by closing routes by default.
4. **Encryption + fail-loud decrypt, PII key + crown KEK** (0.5) — closes M2; protects leads + the Baileys
   crown-jewel session key.
5. **Least-privilege DB roles** (0.4) — kills the service-key god-mode (C1); the dashboard role physically
   can't read the WhatsApp session keys.
6. **Gateway transport hardening** (0.8) — token/CORS/QR/creds-at-rest; closes C6 + M1.
7. **CI secret/PII guard** (0.7) — fails the build on any secret/PII in logs or responses.
8. **Back-office impersonation safety + audit logging** (2.2) — makes the FULL back-office's most abusable
   power accountable; ties to privacy-law staff-access duties.

**Top risk:** **Hand-wired RLS leaking across tenants via connection pooling** (0.3). RLS depends on a
per-request `SET LOCAL app.business_id`; a pooled connection that carries a prior request's value silently
serves one tenant another's data — exactly the class of failure that sank the old system, and *invisible*
without a test that hammers concurrent requests on a shared pool. The mitigation is the isolation suite (0.6)
with explicit pooling/concurrency cases + a negative-control check so a misconfigured test harness can't give
false confidence. (Close second: a FULL back-office or RAG re-introducing a service-role/god-mode path that
silently bypasses all of Phase 0.)
