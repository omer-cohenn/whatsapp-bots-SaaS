# Security Review — Database Schema DRAFT (Bizz_up MVP / Phase 1)

> **Reviewer:** SECURITY agent. **Date:** 2026-06-16.
> **Reviews:** `spec/database-schema-draft.md` (the DATA agent's draft).
> **Grounds:** CLAUDE.md (Rules 1–4), `security-issues.md` (C1–C6, M1–M5, L1–L4),
> decisions 0001–0004, the old `system-map/database-schema.md` + `backend-map.md`.
> **Method:** read-only on original folders; this file is the only thing written.
> "needs verification" = a build-time check I will not invent the answer to.

## TL;DR verdict

| # | Item | Verdict |
|---|------|---------|
| 1 | WhatsApp KEY / `whatsapp_credentials` | **SAFE BY DESIGN, with mandatory build-time controls.** The table shape is right (isolated, encrypted, own PK). It is only as safe as the runtime controls behind it — listed below as MUST. |
| 2 | PII encryption (phone, names, bodies, lead answers) | **MOSTLY SAFE.** Right fields marked 🔒. Two real gaps: the M2 silent-decrypt trap must be killed *in the rebuild* (schema can't enforce it), and `current_flow_state` (mid-flow PII) is left unencrypted-by-default. |
| 3 | Multi-tenant isolation | **STRONG — best part of the draft.** Every tenant table carries `business_id`; the phone-only collision (C-class) is structurally fixed. RLS wiring + non-service role are the only open risks, both flagged. |
| 4 | Secrets | **DIRECTION CORRECT.** Two key domains + KEK in a secret manager + `key_version` for rotation. Nothing plaintext-in-DB. Caveats below (HMAC key, where the KEK lives). |
| 5 | Access paths / least privilege | **DIRECTION CORRECT, under-specified.** `whatsapp_credentials` correctly "never via API". Needs an explicit never-expose list + per-role grants the draft only gestures at. |

**Overall: the draft is safe to build from**, provided the **MUST** rules below are honoured in the build phase. None of the old C-class data-leak bugs survive this schema *on paper*; the residual risk is entirely in runtime wiring (RLS role, decrypt-fail behaviour, KEK custody), which a schema cannot guarantee on its own.

---

## Item 1 — The WhatsApp KEY / `whatsapp_credentials` (CROWN JEWEL)

**Verdict: SAFE BY DESIGN.** This is the single most important table and the draft gets the
structure right. It fixes **M1** (today the Baileys auth state sits as plaintext
`qr_wa_scanner/credentials/<accountId>/creds.json`). What the draft does well:

- Split into its **own table**, physically separate from `whatsapp_connections`, so frequent
  low-trust status reads never load the key. ✅ (This is exactly the right instinct.)
- `auth_state` is `bytea`, ciphertext only, marked 🔒🔒. ✅
- `key_version` column → enables rotation and **fail-closed** decrypt (the M2 fix). ✅
- PK = `business_id` (one cred-set per business), `ON DELETE CASCADE`. ✅
- Stated intent: envelope encryption (per-business DEK wrapped by a KEK in the secret manager),
  dedicated DB role, strict RLS, never returned by an API, never logged, decrypt fails loud. ✅

**But "safe by design" ≠ "safe": the schema cannot enforce any of the runtime controls.**
The crown jewel is only protected if these are true in the rebuild. Mandatory:

**MUST (non-negotiable for this table):**
1. **Envelope encryption, KEK outside the DB and outside `.env`.** DEK per business, wrapped by a
   KEK held in a secret manager / KMS. The DB stores only ciphertext + wrapped DEK; the KEK never
   touches Postgres. This is what makes a full DB dump (the C1 leaked-service-key scenario) useless.
   The KEK MUST be a *different* key from the lead-PII data key (item 4) — different blast radius.
2. **Dedicated, least-privilege DB role.** Only the gateway/connection service may `SELECT`/`UPSERT`
   this table. The dashboard/API role gets **no grant at all** on `whatsapp_credentials` — not even
   `SELECT`. (RLS is the second fence; the missing GRANT is the first.)
3. **Never serialised to any response, ever.** No endpoint returns `auth_state`. Add a test that
   greps API responses for the column / known creds shape and fails CI if present.
4. **Never logged.** Not in debug logs, not in error messages, not in exception traces. (Recall L1:
   the old gateway literally `console.log`-ed its API token at startup. Same mistake here = takeover.)
5. **Decrypt fails LOUD (fail-closed).** If unwrap/decrypt fails (wrong/rotated key, corruption),
   raise + alert and treat the session as down. **Never** fall back to returning the raw bytes
   (that is the M2 trap applied to the crown jewel — catastrophic here).
6. **RLS on `business_id`** as defence-in-depth behind the grant + the app filter.

**needs verification (build phase):**
- KMS vs app-held KEK — security reviewer/Omer to choose (KMS strongly preferred).
- The `qr_code` question (item below) — a live QR is *also* session-hijack material during the
  link window, so it inherits crown-jewel-adjacent handling.

**Related risk the draft already flags — `whatsapp_connections.qr_code`:**
A QR data-URL, while `qr_pending`, lets anyone who reads it hijack the session before the owner
scans (this is gateway audit C6: unauthenticated `/status` leaking the QR). The draft marks it 🔒
and says "clear once connected / consider streaming transiently."
**Verdict: prefer NOT persisting the QR at all** — stream it to the dashboard over the authed
channel and never write it to a row. If it *must* be persisted: encrypt it, set it to `NULL` the
instant status flips to `connected`, and never expose it on any unauthenticated route.
**needs verification:** does the dashboard need to re-fetch the QR after a reload? If no, don't store it.

---

## Item 2 — PII encryption (phone, names, message bodies, lead answers)

**Verdict: MOSTLY SAFE — right fields encrypted, two gaps to close in the build.**

What's correctly marked 🔒 (encrypt at rest):
- `leads.phone`, `leads.contact_name`, `leads.answers` ✅
- `conversations.customer_phone`, `conversations.customer_name` ✅
- `messages.body` ✅ (old system logged this in plaintext — audit #9 — so this is a real fix)
- `whatsapp_connections.phone_number` ✅

This also closes **M5** (old `bookings`/`flow_events` stored name/email/phone in *plaintext*).
Booking tables are out of MVP scope (Phase 2), but the principle — *all* customer PII encrypted,
no cleartext-PII table — is correctly applied to everything in scope. **MUST: keep this rule when
booking tables land in Phase 2** so M5 doesn't reappear.

**Gap A — the M2 "decrypt silently returns plaintext" trap (HIGHEST-PRIORITY carry-over).**
The audit's M2 is the most insidious finding: the old `crypto.decrypt()` caught all exceptions and
returned the input unchanged ("migration-safe"), so a wrong/rotated key or a legacy plaintext row
passed through **silently** — masking both key-rotation breakage and undetected plaintext PII.
A schema *cannot* prevent this; it's a code behaviour. But the schema review must hard-flag it:
- **MUST: in the rebuild, decryption failure is loud (log + metric + alert) and fails closed.**
  No `except Exception: return value`. A bad key must error, never leak ciphertext-as-plaintext.
- **MUST: no plaintext fallback.** Because this is a *clean redesign, not a migration* (the draft
  says so explicitly), there are **no legacy plaintext rows to tolerate** — so there is zero reason
  to keep the M2 fallback. Every 🔒 column is ciphertext from row one. Enforce that invariant.
- **SHOULD: add `key_version` to `leads` too** (the draft only puts it on `whatsapp_credentials`,
  and even notes "consider adding to leads"). Without it, rotating the PII data key later forces a
  guess-and-check decrypt — which is precisely the ambiguity that birthed the M2 fallback. A version
  column lets PII decrypt fail-closed and rotate cleanly, same as the crown jewel. **Recommend adding.**

**Gap B — `conversations.current_flow_state` (mid-flow PII), unencrypted by default.**
This `jsonb` replaces the old volatile in-memory `flow_state._flows` (good — fixes restart/multi-worker
data loss). But mid-flow it holds **partial answers**, which are customer PII (a half-finished lead:
name, phone, whatever the questionnaire asks). The draft leaves it unencrypted and only flags it.
**Verdict: this is a real at-rest PII gap.** Pick one, don't ship it plaintext:
- (preferred) **Encrypt the blob** with the PII data key, same as `leads.answers`; or
- **Persist only a non-PII cursor** (step index + which keys are answered) and keep the actual
  partial values in the encrypted `leads.answers`-in-progress / transient store.
**MUST: do not persist mid-flow customer answers in cleartext.**

**Note — `customer_phone_hash` is a lookup key, NOT a substitute for encryption.** It's correct that
the *encrypted* phone stays in `customer_phone` and the HMAC is only for lookup/uniqueness. Just
flag: an HMAC is deterministic, so it is **linkable across rows** and (for phone numbers, a small
keyspace) **brute-forceable if the HMAC key leaks**. That's an acceptable tradeoff for per-business
dedup, *provided the HMAC key is in the secret manager* (see item 4), not in code or DB.

---

## Item 3 — Multi-tenant isolation (`business_id` + RLS)

**Verdict: STRONG. This is the strongest part of the draft and directly kills the old C2/C3/C4
root cause.** The old system's core defect was **using `email` as `business_id` on the API path and
a flat `"client_001"` on the webhook path** (old schema doc + audit C2/§4). The draft replaces this
with a real `businesses` table keyed by a UUID — the correct structural fix.

**Every tenant table carries `business_id uuid → businesses(id)` — I checked each one:**

| Table | `business_id`? | RLS intended? | Notes |
|-------|:---:|:---:|------|
| `users` | N/A (global) | n/a | Correct — auth identity, no tenant key. |
| `businesses` | defines it | n/a (is the tenant) | The anchor. |
| `business_members` | ✅ | ✅ | The user↔business map — *this is the table the old system lacked*, and its absence is why isolation broke. ✅ |
| `whatsapp_connections` | ✅ NOT NULL UNIQUE | ✅ | One session/business. |
| `whatsapp_credentials` | ✅ PK | ✅ (+ dedicated role) | Crown jewel. |
| `bot_settings` | ✅ NOT NULL UNIQUE | ✅ | |
| `leads` | ✅ NOT NULL | ✅ | |
| `conversations` | ✅ NOT NULL | ✅ | PK now UUID; uniqueness `(business_id, customer_phone_hash)` — **the collision fix**. |
| `messages` | ✅ NOT NULL (denormalized) | ✅ | `business_id` denormalized on purpose so every query filters directly — good defence-in-depth. |
| `bot_builder_messages` | ✅ NOT NULL | ✅ | |

**No tenant table is missing `business_id`.** ✅

**The old C-class collision is fixed structurally, not by convention:**
- Old `conversations` PK was `phone` alone → two businesses sharing a customer phone collided, and
  hot-path queries (`get/set_chat_status`, `update_last_msg_at`, `close_stale_conversations`) keyed
  on phone only (audit security flag #2). The draft makes the PK a UUID, the uniqueness key
  `(business_id, customer_phone_hash)`, and **denormalizes `business_id` onto `messages` and
  `leads`** — so there is **no code path that can key on phone alone**. ✅ This is the right way to
  fix it (structure, not discipline).
- Old C3 (`UPDATE flow_events SET business_id=%s` with no WHERE) and C4 (booking IDOR) were
  missing-`business_id`-predicate bugs. With RLS keyed on `business_id` **and** `business_id` on
  every table, an UPDATE/SELECT that forgets the predicate is caught by RLS instead of nuking/leaking
  every tenant. ✅ (Provided RLS is actually active — see MUST below.)

**MUST (the isolation guarantees that make the above real):**
1. **Connect with a NON-service role for all tenant queries.** This is the C1/C2 root cause: the old
   `.env` held `SUPABASE_SERVICE_KEY`, the service-role key that **bypasses RLS entirely**. If the
   rebuild uses the service key for app queries, *every RLS policy in this schema is dead* and we are
   back to a single missing `WHERE` = full cross-tenant leak. The draft says this; it must be enforced.
2. **App-level `business_id` filter stays MANDATORY on every query** (Rule 2). RLS is the *second*
   fence, not the only one. Defence-in-depth.
3. **`business_id` must be verified against `business_members` for the authed user — never trusted
   from the client** (Rule 2: "Never trust a `business_id` coming from the client"). This is what
   `business_members` is *for*; the old system had no such check (it equated email=tenant). The
   ownership check on every request is what stops a logged-in tenant A from passing tenant B's id.
4. **RLS policy intent (state it explicitly per table):**
   `USING (business_id = current_business_id())` and
   `WITH CHECK (business_id = current_business_id())` on **both** read and write, so a row can be
   neither read nor inserted/updated outside the caller's business. `current_business_id()` resolves
   from a per-request session variable (FastAPI sets it after verifying membership) **or**
   `auth.uid()`-derived if Supabase Auth is chosen.

**needs verification (build phase, the draft's open Q8):**
- Exact RLS mechanism: the `current_business_id()` session-variable wiring (e.g. `SET LOCAL`
  per transaction from the verified `business_id`) vs Supabase-Auth `auth.uid()` + a membership
  lookup in the policy. **Do not invent this** — confirm with Omer which auth model (draft open Q1)
  before writing policies, because it changes how RLS reads identity.
- `business_members` join table vs a simpler `businesses.owner_user_id` (draft open Q6). **Security
  preference: keep the join table** — it makes the ownership check explicit and survives staff/
  multi-owner without a schema change. The single-column shortcut works for a 1:1 MVP but invites a
  rewrite the moment a second user is added. Either is *safe* if the ownership check is enforced.

---

## Item 4 — Secrets (nothing plaintext; keys + DB creds in a secret manager)

**Verdict: DIRECTION CORRECT — the draft internalises the C1 lesson.** C1 was the master failure:
*every* live secret (Supabase service key, Meta token, Fernet `ENCRYPTION_KEY`, DB password, Google
OAuth secret, session secret) sat in plaintext `.env`. The draft's encryption plan responds to this:

- **Two key domains, by sensitivity** ✅ — (1) crown-jewel KEK for `whatsapp_credentials`, (2) PII
  data key for leads/conversations/messages/connections. Separating them limits blast radius: a leak
  of the PII key doesn't expose WhatsApp sessions, and vice versa.
- **KEK in a secret manager / KMS, never in `.env`, never in the DB** ✅ — directly the C1 fix.
- **`key_version` for rotation** ✅ — rotation is impossible to do safely without it; C1's fix note
  explicitly calls out "rotating `ENCRYPTION_KEY` requires re-encrypting existing rows."
- **Nothing sensitive stored plaintext in the DB** ✅ — all PII + the session key are 🔒.

**MUST:**
1. **All of these live in the secret manager, none in `.env` or code:** the PII data key, the crown
   KEK (or its KMS handle), the **HMAC key** for `customer_phone_hash`, the DB connection creds (incl.
   the non-service role password), and any session/OAuth secrets. (M3: the old `SESSION_SECRET`
   fell back to the constant `"change-me-in-env"` → fail-startup-if-unset, never default.)
2. **The HMAC key is a real secret.** `customer_phone_hash` is only privacy-preserving while its key
   is secret (phone numbers are a brute-forceable keyspace). It is *not* a "hash, so harmless" value —
   treat it like the data key. The draft flags HMAC key mgmt as needs-verification; this is the answer:
   secret manager, rotstandardised with `key_version` thinking if it ever rotates (rotating it
   re-derives all hashes — note that cost).
3. **Treat all old `.env` values as compromised** (C1 fix direction) — the rebuild uses freshly
   issued secrets, not the leaked ones.

**needs verification:**
- Which secret manager (KMS, Vault, cloud provider) — not specified; Omer/build phase to choose.
  Don't invent the vendor.
- Whether `users.email` is "PII to encrypt" or "the queryable auth handle" (draft open Q7).
  **Security view: leave `email` queryable (unencrypted) but access-controlled.** It is the login
  key and unique constraint; encrypting it breaks login lookups and uniqueness for marginal benefit
  (it's owner-business email, lower sensitivity than customer PII). Protect it with the non-service
  role + RLS-on-`users`-by-self, not with at-rest encryption. (Acceptable either way; flagging the
  tradeoff, not inventing a mandate.)

---

## Item 5 — Access paths / least privilege (what must NEVER hit the API)

**Verdict: DIRECTION CORRECT but UNDER-SPECIFIED — the draft says "never expose the crown jewel"
but doesn't enumerate the rest.** Here is the explicit list the build must honour.

**NEVER returned by any API / NEVER readable by the dashboard role:**
- **`whatsapp_credentials.auth_state`** (and the whole row). No endpoint, no serialiser, no log.
  Dashboard/API role gets **zero grant** on this table. Only the gateway/connection service role.
- **`whatsapp_connections.qr_code`** while pending — only over the authed dashboard channel to the
  owner of *that* business, never on an unauthenticated route (this is gateway C6). Prefer not
  persisting it at all (item 1).
- **Raw ciphertext / `key_version` internals** — never surfaced; decryption happens server-side and
  only the authed owner of the business sees the *decrypted* value for *their* rows.

**Exposed ONLY to the authed owner of that business (decrypted server-side, RLS-scoped):**
- `leads.*`, `conversations.*`, `messages.*` PII — these are what the old C2 leaked to anonymous
  callers. They must sit behind enforced auth (decision 0004 bakes in real login) **and** RLS **and**
  the membership ownership check. No anonymous fallback tenant — ever (C2's exact failure mode).

**Least-privilege roles (state explicitly at build time):**
1. **gateway/connection role** — `whatsapp_credentials` (read/write), `whatsapp_connections`
   (read/write). No access to `leads`/`messages` beyond what the engine strictly needs.
2. **app/dashboard role** — everything tenant-scoped **except** `whatsapp_credentials` (no grant).
   Non-service (RLS applies).
3. **no service-role key in the app at all** (C1). If a migration/admin task needs elevated access,
   it runs out-of-band, never from a request handler (recall C3: unauthenticated `/admin/*` that
   rewrote every tenant's rows — such endpoints must not exist in the rebuild, or must be authed
   admin-only and `business_id`-scoped).

**MUST:**
1. **Enforced auth on every `/api/*` route** — no per-route opt-in that some routes skip (C2's
   structural flaw was exactly this). A single auth dependency/middleware, deny-by-default.
2. **No shared/anonymous fallback tenant.** Reject unauthenticated requests; never resolve to a
   default `business_id` (C2).
3. **CI guard:** a test that fails if `auth_state`, decrypted creds, or a QR appear in any response
   body or log line.

---

## Cross-checks against the audit (carry-over status)

| Audit finding | Addressed by this schema? | Residual action |
|---|---|---|
| **C1** secrets in `.env` | Yes — KEK/data-key/HMAC/DB creds → secret manager; `key_version`; no plaintext-in-DB. | Pick vendor; rotate all old secrets (build). |
| **C2** no-auth → shared tenant leak | Yes — real `businesses` UUID + `business_members` + RLS + mandatory auth. | Enforce single auth dependency; no fallback tenant (code). |
| **C3** admin UPDATE no WHERE | Mitigated — RLS + `business_id` on every table catches a forgotten predicate. | Don't ship unauthenticated/global admin endpoints (code). |
| **C4** booking IDOR | Out of MVP scope (bookings = Phase 2), but the pattern (`business_id` predicate + RLS) is set for when it lands. | Apply same rules in Phase 2. |
| **C5 / C6** webhook & gateway auth | Out of schema scope (transport/gateway, not tables). | Handle in gateway/webhook rebuild — *not* solvable in the DB. |
| **M1** Baileys creds plaintext on disk | Yes — `whatsapp_credentials`, encrypted, isolated. | Honour item-1 MUSTs (envelope enc, role, fail-loud). |
| **M2** silent decrypt → plaintext | Schema enables the fix (`key_version`, clean redesign = no legacy rows); cannot enforce it. | **MUST: loud fail-closed decrypt, no plaintext fallback** (code). HIGHEST carry-over. |
| **M3** session secret default | Out of schema scope. | Fail-startup-if-unset (code). |
| **M5** plaintext booking/flow PII | Yes — all in-scope PII is 🔒; principle set for Phase 2. | Keep the rule when bookings land. |
| **L1 / #9** secrets & PII in logs | Schema can't enforce; flagged. | Never log creds/QR/raw PII (code + CI grep). |

---

## Consolidated MUST-FIX before/at build (the rules that keep data from leaking)

1. **App connects as a NON-service DB role** for all tenant queries — or every RLS policy here is
   dead (C1/C2 root cause).
2. **RLS on every tenant table:** `USING` + `WITH CHECK` on `business_id = current_business_id()`,
   read and write.
3. **App-level `business_id` filter stays mandatory** on every query (Rule 2); verify `business_id`
   against `business_members` for the authed user; never trust it from the client.
4. **`whatsapp_credentials`:** envelope-encrypted (KEK in secret manager, separate from PII key),
   dedicated DB role with the dashboard role having *no* grant, never returned, never logged,
   decrypt fails loud.
5. **Decryption fails LOUD / fail-closed everywhere; no plaintext fallback** (kills M2). Clean
   redesign = no legacy plaintext rows, so the fallback has no excuse to exist.
6. **All secrets in a secret manager** (PII data key, crown KEK, HMAC key, DB creds, session/OAuth) —
   none in `.env` or code; fail startup if a required secret is missing (kills M3).
7. **Encrypt `conversations.current_flow_state`** (or persist only a non-PII cursor) — don't store
   mid-flow customer answers in cleartext.
8. **Enforced auth on all `/api/*`, deny-by-default, no anonymous fallback tenant** (kills C2);
   no unauthenticated/global admin endpoints (kills C3).
9. **CI guard** that fails if `auth_state`, decrypted creds, or a QR appear in any response or log.

## SHOULD / recommended

- Add `key_version` to `leads` (and any PII-bearing table), for clean PII-key rotation + fail-closed.
- Do **not** persist `qr_code`; stream it over the authed channel. If persisted, encrypt + null on connect.
- Keep `business_members` (explicit ownership check) over `businesses.owner_user_id`.

## Open questions I am NOT answering (need Omer / build-phase decision — won't invent)

1. Auth model: Google-via-FastAPI vs Supabase Auth — changes how RLS reads identity (`current_business_id()`
   session var vs `auth.uid()`). Draft open Q1/Q8.
2. KMS vs app-held KEK for the crown jewel. Draft open Q (item 1).
3. Which secret-manager vendor.
4. Whether to persist the QR at all (depends on whether the dashboard re-fetches it after reload).
5. `users.email` encryption — security leaning: leave queryable + access-controlled (acceptable either way).
6. Gateway `accountId` ↔ `business_id` bridge — confirm the rebuilt gateway derives `accountId` from
   `business_id` so inbound routing via `whatsapp_connections.gateway_account_id` is correct
   (this is also a tenant-isolation dependency: wrong mapping = cross-tenant inbound). Draft open Q2.
