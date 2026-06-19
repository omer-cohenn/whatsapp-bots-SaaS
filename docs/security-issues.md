# Security Issues — `last_bo` + `qr_wa_scanner` audit

> **Status: FILLED** by security scanner on 2026-06-15.
> Scope: `C:\Users\עמר כהן\Desktop\last_bo` (FastAPI WhatsApp bot + dashboard) and
> `C:\Users\עמר כהן\Desktop\qr_wa_scanner` (Node/Baileys WhatsApp gateway).
> `node_modules`, `.venv`, `__pycache__`, `.git` internals excluded from scanning.
> Original folders treated as strictly read-only; nothing in them was modified.

Legend for file refs: `path:line`. Secret values are shown only by variable name or last 4 chars.

---

## CRITICAL

### C1 — Live production secrets sit in plaintext `.env` on disk (all of them)
- **Where:** `last_bo\.env:1-33`
- Contains real, non-placeholder values for: `GEMINI_API_KEY` (…fJw), `WHATSAPP_TOKEN` (a full long-lived Graph token, …ZDZD), `WHATSAPP_APP_SECRET` (…c7d), `DATABASE_URL` with embedded Postgres password (…Rdy), `SUPABASE_SERVICE_KEY` (…Rlg — the service-role key that bypasses Row Level Security), `ENCRYPTION_KEY` (the Fernet key that decrypts all lead data, …faU=), `SESSION_SECRET` (…d0e), `GOOGLE_CLIENT_SECRET` (GOCSPX-…WdT0).
- `qr_wa_scanner\.env:7` also defines `API_TOKENS=my-secret-token` (a trivially guessable gateway token).
- **Why dangerous:** This is the master keychain for the whole system. The Supabase **service key** alone grants full read/write to every tenant's database bypassing RLS. The `ENCRYPTION_KEY` lets anyone decrypt the "encrypted" leads (see C2). The `WHATSAPP_TOKEN` lets an attacker send messages as the business. Any one leak is a full compromise; they are all in one file.
- **Mitigating fact (verified):** `.env` is listed in `last_bo\.gitignore:1` and is **not** tracked by git (`git ls-files --error-unmatch .env` → "did not match"). Commit `d6bd77d` only *mentions* `.env` in its message; the file blob is not in history. So the leak is local-disk exposure, not a git-history leak. `qr_wa_scanner\.gitignore:2` also ignores `.env`.
- **Fix direction:** Treat every value in both `.env` files as compromised and rotate them all now (Supabase keys, DB password, Meta token + app secret, Google OAuth secret, Gemini key, Fernet key, session secret). Move secrets to a secret manager / host env vars rather than a file. Replace `my-secret-token` with a high-entropy random token. Note that rotating `ENCRYPTION_KEY` requires re-encrypting existing rows.

### C2 — Most dashboard/data API endpoints have NO authentication and silently fall back to a shared tenant
- **Where:** `last_bo\main.py` — `_business_id()` at `main.py:95-99` returns `user["email"]` *only if logged in*, otherwise `_business_id_from_config()` (`main.py:87-92`) which reads a single shared `client_config/system_prompt.json`. Endpoints that call `_business_id(request)` with **no `get_session_user` guard**: `/api/status` (153), `/api/dashboard` (179), `/api/leads` (196), `/api/leads/test` (205), `/api/conversations` (261), `/api/conversations/{phone_enc}/status` (270), `/api/rag/sources` (472), `/api/rag/status` (478), `/api/rag/upload` (484), `/api/rag/add-url` (499), `/api/rag/source/{id}` DELETE (514), `/api/rag/rebuild` (523), `/api/rag/use-cases` (530), `/api/botbuilder/config` GET (873) and POST (878).
- **Why dangerous:** An unauthenticated attacker hitting `GET /api/leads` (or `/api/dashboard`, `/api/conversations`) receives decrypted lead PII (names, phones, form answers) for whatever business_id the shared config resolves to. `POST /api/botbuilder/config` lets an anonymous caller rewrite the bot's flows/persona **and triggers `delete_orphaned_leads` (main.py:885-889), destroying stored leads**. `DELETE /api/rag/source/{id}` lets anonymous callers delete knowledge sources. There is no global auth middleware — only a per-route check that these routes skip.
- **Fix direction:** Add a single enforced authentication dependency (FastAPI dependency / middleware) applied to every `/api/*` and `/admin/*` route except the genuinely public booking endpoints. Reject requests with no session instead of falling back to a shared business_id.

### C3 — Admin endpoints are completely unauthenticated and globally destructive
- **Where:** `last_bo\main.py` — `POST /admin/migrate-leads` (398-452), `POST /admin/rebuild-rag` (455-462).
- **Why dangerous:** `/admin/migrate-leads` runs `SELECT ... FROM leads` with **no business_id filter** (main.py:413) across the *entire* table and then `UPDATE flow_events SET business_id=%s` for **every row** (main.py:449) to the caller's business_id. An anonymous attacker can call it and reassign all tenants' flow_events to themselves / corrupt data. `/admin/rebuild-rag` rebuilds the vector index on demand (DoS / cost). Neither checks `get_session_user`, and there is no admin role concept.
- **Fix direction:** Require authenticated admin-only access for all `/admin/*` routes. Scope the migration queries by business_id, or remove the one-time migration endpoint from the running app entirely.

### C4 — Cross-tenant booking modification: `PATCH /api/bookings/{booking_id}` ignores business_id
- **Where:** `last_bo\main.py:593-601` calls `update_booking_status(booking_id, ...)`; `bot\leads_db.py:461-465` runs `UPDATE bookings SET status=%s WHERE id=%s` with **no business_id predicate**.
- **Why dangerous:** Booking IDs are UUIDs, but any logged-in user (tenant A) who learns or guesses a booking_id belonging to tenant B can change that booking's status (e.g. cancel a competitor's appointments). The endpoint checks that *a* user is logged in but never that the booking belongs to *that* user's business.
- **Fix direction:** Add `AND business_id = %s` to the update and pass the caller's business_id, returning 404 when no row matches.

### C5 — Inbound Meta WhatsApp webhook does not verify the request signature
- **Where:** `last_bo\main.py:325-395` (`POST /webhook`). It parses `body["entry"]...` directly. No `X-Hub-Signature-256` HMAC check against `WHATSAPP_APP_SECRET` exists anywhere (grep for `X-Hub-Signature`/`hmac` finds none in the request path; `WHATSAPP_APP_SECRET` is only used by `wapy_client\client.py:11` and `run_ngrok.ps1`).
- **Why dangerous:** The webhook is exposed publicly (via ngrok per `run_ngrok.ps1`). Anyone who learns the URL can POST forged "incoming WhatsApp message" payloads, driving the bot, injecting arbitrary `phone`/`text` into flows, creating leads, flipping chat status, and burning Gemini quota. The GET verification (main.py:289-294) only protects subscription setup, not message delivery.
- **Fix direction:** Verify the `X-Hub-Signature-256` HMAC-SHA256 of the raw body using `WHATSAPP_APP_SECRET` and reject mismatches before processing.

### C6 — `qr_wa_scanner` gateway exposes full WhatsApp send/account control behind a default hardcoded token, with CORS wildcard
- **Where:** `qr_wa_scanner\index.js:12` default token `'my-secret-token'`; `index.js:184` `app.use(cors())` (wildcard, all origins); `index.js:188` reads token from `x-api-token` **or `req.query.token`** (token ends up in URLs/logs). Frontend hardcodes the same default: `App.jsx:312` `localStorage... || "my-secret-token"`. `index.js:195-205` `GET /status` has **no `authMiddleware`** and returns the live login QR code.
- **Why dangerous:** With the shipped default token, anyone who can reach the port can `POST /send` (send WhatsApp messages as the connected number), `POST /webhook` (redirect all incoming messages to an attacker URL — full message interception), `DELETE /accounts/:id` (wipe sessions), or list/add accounts. The unauthenticated `GET /status` leaks the QR code, so an attacker who loads it before the owner can hijack the WhatsApp session entirely. `cors()` wildcard lets any website call the API from a victim's browser; accepting the token via query string puts the credential in server logs and browser history.
- **Fix direction:** Refuse to start without a strong non-default `API_TOKENS`; remove the `'my-secret-token'` fallback in both `index.js` and `App.jsx`. Put `/status` behind auth (or at least never return the QR unauthenticated). Restrict CORS to known origins. Accept the token only via header, never query string.

---

## MEDIUM

### M1 — WhatsApp/Baileys session credentials stored as unencrypted JSON on disk
- **Where:** `qr_wa_scanner\index.js:34-36` `saveState()` writes `creds.json` via `JSON.stringify(...)`; path `credentials/<accountId>/creds.json` (index.js:18-19). `credentials/` is gitignored (`qr_wa_scanner\.gitignore:3`) and currently only contains an empty `credentials/default/` dir (no live session captured at scan time — *needs verification* on a running instance).
- **Why dangerous:** Baileys `creds.json` holds the noise keys / signed identity that ARE the WhatsApp session. Anyone with read access to that file can clone the session and impersonate the account on another machine — no QR re-scan, no password. Plaintext at rest means any local malware, backup, or file-share leak is a full account takeover.
- **Fix direction:** Encrypt the auth state at rest (e.g. envelope-encrypt with a key from a secret manager), restrict file permissions, and keep it off any synced/backed-up location.

### M2 — Lead data IS encrypted, but the "decrypt-fails-returns-plaintext" fallback can silently bypass encryption
- **Where:** `last_bo\bot\crypto.py:20-26` — `decrypt()` catches all exceptions and `return value` (the still-encrypted-or-garbage input) "safe during migration". `leads_db.py` confirms leads ARE encrypted on write: `save_lead` (leads_db.py:144-156) encrypts phone, flow_id, and the whole data blob via Fernet; `get_leads` (188-217) and `get_conversations_by_status` (319-344) decrypt on read. So **lead data at rest is genuinely encrypted** (good).
- **Why dangerous:** The broad `except Exception: return value` means a wrong/rotated `ENCRYPTION_KEY`, or any legacy plaintext row, is returned as-is with no error and no logging — masking both migration gaps and key-rotation mistakes. `get_leads` (205-207) and the migration `is_plaintext` heuristic (main.py:422-423, keyed on the `gAAAAA` Fernet prefix) explicitly tolerate plaintext rows, so plaintext PII can persist undetected.
- **Fix direction:** Make decryption failure loud (log + metric) instead of silently returning ciphertext; once migration is complete, remove the plaintext fallback so a bad key fails closed rather than leaking/erroring silently.

### M3 — CORS / deployment exposure on the FastAPI side relies on no global protection
- **Where:** `last_bo\main.py` has no CORS middleware (only `SessionMiddleware` at main.py:79) — so browser CORS is default-deny, which is fine — but combined with C2 the lack of auth, not CORS, is the exposure. `SESSION_SECRET` falls back to `"change-me-in-env"` (main.py:79) if the env var is missing.
- **Why dangerous:** If `SESSION_SECRET` is ever unset, sessions are signed with a publicly-known constant, letting anyone forge a logged-in session cookie (defeating C2's intended auth). The real secret is also exposed per C1.
- **Fix direction:** Fail startup if `SESSION_SECRET` is unset rather than using a known default; rotate the current value (it is exposed in `.env`).

### M4 — Unvalidated user input from WhatsApp and the public booking page
- **Where:** Webhook ingest `main.py:333` takes `message["text"]["body"]` and feeds it into flow steps / Gemini with no length or content limits. Public booking `POST /api/book/{slug}` (main.py:642-663) writes `name/email/phone/notes` straight to the DB (`create_booking`, leads_db.py:448-458) with no validation of email format, phone, or field length; `slug` is attacker-controlled and used directly as `business_id`. Booking-link injection: the `slug` is also rendered in prompts (gemini.py:59-61).
- **Why dangerous:** No SQL injection (queries are parameterized throughout leads_db.py — verified), but unbounded/unvalidated input enables stored-garbage, oversized payloads, prompt-injection via WhatsApp text into the Gemini system flow, and creation of bookings/settings under arbitrary `slug`s (a public, unauthenticated write path that can seed rows for any business_id — `get_booking_settings`/`save_booking_settings` auto-create defaults). Email/phone are stored unvalidated and later shown in the owner dashboard.
- **Fix direction:** Validate and bound-check all public/inbound fields (email, phone, max lengths); verify the `slug` corresponds to a real provisioned business before accepting public booking writes; sanitize/limit text before it reaches the LLM and treat LLM output as untrusted.

### M5 — Phone numbers stored in plaintext in `bookings` and `flow_events`
- **Where:** `leads_db.py` — `create_booking` stores `client_phone`/`client_email`/`client_name` in plaintext (78-89 schema, 448-458 insert); `flow_events.phone` is plaintext (52-60, `log_flow_event` 178-185); `conversations.phone` is the encrypted token but used as a primary key. Leads use encryption but bookings do not.
- **Why dangerous:** Inconsistent protection — the project went to the trouble of encrypting leads, but appointment client PII (name/email/phone) sits in cleartext, so a DB read (e.g. via the leaked Supabase service key, C1) exposes it directly.
- **Fix direction:** Apply the same field encryption to booking client PII, or document why bookings are intentionally cleartext and compensate with DB-level controls.

---

## LOW

### L1 — Gateway prints API tokens to the console on startup
- **Where:** `qr_wa_scanner\index.js:304` `console.log('🔑 API Tokens: ${API_TOKENS.join(', ')}')`.
- **Why dangerous:** The auth token is written verbatim to stdout/terminal logs (and `start.bat:60` runs with `LOG_LEVEL=info` in a persistent window), so anyone with log/terminal access reads the live credential. Also `index.js:160` logs webhook failures with `e.message` which may include URLs.
- **Fix direction:** Never log secrets; print only a masked hint or a count.

### L2 — `WEBHOOK_VERIFY_TOKEN=secret` is a trivial value
- **Where:** `last_bo\.env:10`.
- **Why dangerous:** The Meta webhook verification token is the literal word `secret`, trivially guessable; low impact (only used at subscription setup) but undermines that check.
- **Fix direction:** Use a high-entropy random verify token.

### L3 — Verbose error messages returned to clients
- **Where:** `last_bo\main.py` returns raw `str(e)` to callers in many handlers (e.g. 192-193, 201-202, 266-267, 283-284, 495-496, 510-511, 933-934, 948-949) and renders exceptions into HTML at the OAuth callback (`main.py:128`).
- **Why dangerous:** Internal exception text (stack/DB details) leaks to clients, aiding reconnaissance. `server_err.txt` (`last_bo\server_err.txt`) currently holds only a deprecation warning + startup lines — no secrets at scan time (verified) — but the pattern of dumping stderr to a file risks future PII/secret capture.
- **Fix direction:** Return generic error messages to clients; log details server-side only; avoid persisting raw stderr to a repo-local file.

### L4 — Hardcoded absolute path with embedded username in `run_ngrok.ps1`
- **Where:** `last_bo\run_ngrok.ps1:2` reads `C:\Users\B08F~1\Desktop\last_bo\.env`.
- **Why dangerous:** Minor; brittle and leaks a local username/path, but no direct exploit.
- **Fix direction:** Use a relative path or env var.

---

## Summary table

| ID | Severity | Area | One-line |
|----|----------|------|----------|
| C1 | Critical | Secrets | All live secrets (Supabase service key, Meta token, Fernet key, DB pw, Google OAuth, session secret) sit plaintext in `last_bo\.env` — rotate everything. |
| C2 | Critical | AuthZ / tenant | Most `/api/*` data endpoints have no auth and fall back to a shared tenant, leaking decrypted lead PII to anonymous callers. |
| C3 | Critical | AuthZ / admin | `/admin/migrate-leads` and `/admin/rebuild-rag` are unauthenticated; migration rewrites every tenant's rows. |
| C4 | Critical | Tenant isolation | `PATCH /api/bookings/{id}` updates booking status with no business_id filter — cross-tenant modification. |
| C5 | Critical | Webhook auth | Inbound Meta webhook never verifies `X-Hub-Signature-256`; forged messages accepted. |
| C6 | Critical | Gateway auth | `qr_wa_scanner` ships default token `my-secret-token`, CORS `*`, token via query, and unauthenticated `/status` leaking the login QR. |
| M1 | Medium | Data at rest | Baileys WhatsApp session `creds.json` stored as unencrypted JSON — session cloning = account takeover. |
| M2 | Medium | Crypto | Leads ARE encrypted, but `decrypt()` silently returns ciphertext/plaintext on failure, masking key/migration errors. |
| M3 | Medium | Config | `SESSION_SECRET` falls back to a known constant `change-me-in-env` if unset. |
| M4 | Medium | Input validation | WhatsApp text and public booking fields/`slug` unvalidated (prompt injection, arbitrary booking writes); SQL is parameterized (safe). |
| M5 | Medium | Data at rest | Booking & flow_event client PII (name/email/phone) stored in plaintext while leads are encrypted. |
| L1 | Low | Logging | Gateway prints API tokens to console at startup. |
| L2 | Low | Config | `WEBHOOK_VERIFY_TOKEN=secret` is trivially guessable. |
| L3 | Low | Logging / errors | Raw exception text returned to clients and rendered in OAuth callback HTML. |
| L4 | Low | Config | Hardcoded absolute path with username in `run_ngrok.ps1`. |

---

## M5 try-me (Bizz_up rebuild) — audit 2026-06-19

> Scope: the NEW `bizz_up` backend M5 try-me feature only — the pure bot engine
> `backend\app\services\bot_engine.py`, the `POST /api/bot/tryme` endpoint in
> `backend\app\api\bot_builder.py`, and its request/response models +
> `bot_settings` loader. Read-only audit; no product code was modified. Findings
> are for the main build loop to fix.

**Owner's explicit requirements — verification result:**

- ✅ **Bot can NEVER reveal classified/sensitive customer info.** Verified. The engine (`bot_engine.advance`) reads ONLY the two arguments it is handed — `settings` (this tenant's own config) and the current conversation `state` — and emits only the current conversation's own typed answers. There is no code path that reads a stored lead, another conversation, or another tenant: no DB call, no network, no file I/O, no module-level state anywhere in `bot_engine.py`. The `lead` returned on completion is built solely from `state["collected"]` (engine lines 150-163), i.e. exactly what the user just typed this session.
- ✅ **No LLM in the engine → no prompt-injection / exfiltration path.** Verified. `bot_engine.py` imports only `re` and `typing` (lines 28-29). The free-text fallback is a fixed menu nudge (`_DEFAULT_NUDGE` + `_menu_list`, engine lines 183-186), not a model call. The endpoint `bot_tryme` calls only `bot_settings_service.get_settings(...)` then `bot_engine.advance(...)` — no `bot_builder_ai` / Gemini call (`bot_builder.py:84-95`).
- ✅ **Tenant isolation — business_id from server session only.** Verified. `bot_tryme` takes `business_id: str = Depends(current_business)` (`bot_builder.py:74`), which resolves from the Redis session (`deps.py:50-54`), never from the body or state. `BotTryMeRequest` has no `business_id` field and `model_config = extra="ignore"` (`models/bot_builder.py:272-285`), so a `business_id` in the body is dropped. `get_settings` runs inside `tenant_connection(pool, business_id)` with `WHERE business_id = $1` (`bot_settings.py:52-60`).
- ✅ **try-me writes NOTHING to the DB.** Verified. `bot_tryme` performs a single READ (`get_settings`) and no INSERT/UPDATE/UPSERT. Contrast with `/api/bot/ai/chat`, which DOES persist via `_persist_turn`; try-me deliberately does not. The engine is pure, so it cannot write either.
- ✅ **Input bounds.** Verified. `message` is capped at `MAX_TRYME_MESSAGE_CHARS = 2000` (`models/bot_builder.py:269,284`); `state` is JSON-size-bounded to `MAX_CHAT_CONFIG_BYTES = 65536` via `_bound_state` (`models/bot_builder.py:287-299`). The engine's `_normalize_state` (`bot_engine.py:383-408`) coerces any malformed/huge/wrong-typed state into a safe known shape, so a crafted `state` cannot crash the engine (see T-02 for the one residual concern).
- ✅ **No secrets/PII in logs; errors generic.** Verified for the try-me path: `bot_tryme` logs nothing at all (no `log.*` calls in the handler), so neither message text, collected answers, nor secrets are logged. Settings/secrets are never logged by `get_settings`.

**Overall verdict: PASS — the M5 try-me path meets all six owner requirements.**
No critical or medium issues. The engine is genuinely pure and tenant-safe; try-me
is read-only and LLM-free. Two LOW / hardening notes below; neither is a leak.

### T-01 — try-me uses the SAVED config, including unpublished flows (by design; confirm intent) — LOW
- **Where:** `backend\app\api\bot_builder.py:84-89` (loads `get_settings` and runs the engine regardless of `is_published`).
- **Why dangerous (mild):** try-me runs against whatever is persisted for THIS tenant, even if `is_published` is false. That is correct for an owner testing their own draft (no cross-tenant exposure — still scoped by `business_id`). The only note: try-me reflects the *saved* draft, not the in-browser unsaved working copy. Not a security leak; flagged only so the team confirms this is the intended UX and that `is_published` is enforced on the REAL inbound WhatsApp path (out of M5 scope — *needs verification* when the live bot loop is built).
- **Fix direction:** No code change required for security. Document that try-me = saved config; ensure the future production bot loop refuses to answer when `is_published` is false.

### T-02 — `step_index` upper bound not capped at request validation (engine handles it, but defense-in-depth) — LOW
- **Where:** `backend\app\models\bot_builder.py:287-299` (`_bound_state` checks JSON byte size only); `backend\app\services\bot_engine.py:397-399` (`_normalize_state` accepts any non-negative int `step_index`).
- **Why dangerous (mild):** A crafted `state` with a huge `step_index` (e.g. 10**9) passes validation (it's a small JSON). The engine is safe — `_advance_in_flow` guards `state["step_index"] >= len(steps)` and falls back to the menu (`bot_engine.py:141-142`), and `_advance_menu` uses bounded index math — so there is no crash, OOB read, or leak. This is purely a defense-in-depth note: an absurd index should arguably be rejected/clamped at the edge rather than relied on being caught downstream.
- **Fix direction:** Optionally clamp/validate `step_index` (and `phase`/`active_flow` types) in `_bound_state`, or add a max bound. Low priority — current behavior is already safe.

### M5 try-me — summary table
| ID | Severity | Area | One-line |
|----|----------|------|----------|
| (req 1-6) | — | Verification | All six owner requirements PASS — engine is pure, LLM-free, tenant-scoped from session, no DB writes, input-bounded, no secret/PII logging. |
| T-01 | Low | Scope / UX | try-me runs the saved config incl. unpublished drafts (tenant-scoped, not a leak); confirm `is_published` is enforced on the future live bot loop. |
| T-02 | Low | Input validation | Oversized `step_index` in `state` passes the size check; engine handles it safely — optional edge clamping for defense-in-depth. |
