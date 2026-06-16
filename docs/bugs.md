# Bugs — consolidated from all scanner reports

> Every "Flags for bugs.md" item from the backend, whatsapp-gateway, and infrastructure
> reports, merged into one table and de-duplicated. Security issues live separately in
> [`security-issues.md`](security-issues.md); a few items overlap and are cross-referenced.
> Severities are the scanners' own ratings; "needs verification" means the scanner could not
> confirm it from code alone. Last assembled 2026-06-15.

`B##` = bug id. Sources: BE = backend-map.md, WA = whatsapp-gateway.md, INF = infrastructure.md.

| ID | Severity | Where | Description | Fix direction |
|----|----------|-------|-------------|---------------|
| B1 | High (architectural) | `last_bo` vs `qr_wa_scanner` | **The two WhatsApp halves are not wired together.** `last_bo` uses Meta Cloud API via PyWa; nothing registers `last_bo` as the Baileys gateway's webhook, and the payload shapes are incompatible (Baileys flat `{from,text,accountId}` vs Meta envelope `main.py:329-333`). A gateway-forwarded message would parse as `{"status":"ignored"}`. (WA #1, INF #10) *Intent: needs verification.* | Decide the canonical path. If Baileys feeds the bot, add an adapter that translates its flat payload into what `/webhook` expects. |
| B2 | High | `last_bo\run.bat:7` | **`pip install -r requirements.txt` on every launch.** Heavy, **unpinned** deps (`sentence-transformers`, `crawl4ai`, `langchain*`) make this the slowest, most fragile startup step; first run also downloads the embedding model. (INF #1) | Install once during setup, not per-run. Pin versions. Cache the model. |
| B3 | Medium | `qr_wa_scanner\index.js:104,239` | **Registered webhook URL is not persisted.** `account.webhookUrl` lives only in RAM; any restart drops it and inbound forwarding silently stops until `POST /webhook` is re-sent. `.env WEBHOOK_URL` is defined but never read. (WA #2) | Persist the webhook URL (DB/file) and re-seed it on boot; optionally read `.env WEBHOOK_URL`. |
| B4 | High | `last_bo\.env` | **Live secrets committed to disk in plaintext** (Gemini, Meta token, Supabase service key, Google secret, Fernet key, DB password). (INF #7) — full detail as security **C1**. | Rotate everything; move to a secret manager. See [`security-issues.md`](security-issues.md) C1. |
| B5 | Medium | `rebuild_rag.py:18`, `scrap_to_rag.py:31`, `main.py:461` | **Broken `build_index` calls (the `rag_data/` path).** All call `vectorstore.build_index(chunks)` with 1 arg, but the signature is `build_index(chunks, business_id)` (`vectorstore.py:62`) → `TypeError`. `/admin/rebuild-rag` 500s on every call. (BE #1) | Either delete the dead path (see B6) or fix the calls to pass a `business_id`. |
| B6 | Cleanup | `rag_data/` + loader/scripts | **`rag_data/` is DEAD code (verdict).** Referenced only by `bot/brain/loader.py` and the three broken callers in B5; the live RAG pipeline (`rag_manager.py` → pgvector `brain_chunks` → Supabase Storage) never touches it. Folder holds only stale demo files. (BE §8) | Remove `rag_data/`, `loader.py`, `rebuild_rag.py`, `scrap_to_rag.py`, and the `/admin/rebuild-rag` endpoint. |
| B7 | High | `main.py` book_appointment flow | **Chat booking flow does not actually book.** The conversational `book_appointment` step flow only files a free-text lead ("a rep will get back to you"); it never creates a `bookings` row or checks availability. Only the `booking_link` URL flow uses the real calendar. (BE #10) | Make the chat flow create a real `bookings` row (and check slots), or make it always hand off to the booking link. |
| B8 | Medium | `main.py` (frontend↔backend contract) | **`/api/bookings` param-name mismatch.** `index.html` calls `GET /api/bookings?from=&to=` but the handler declares `date_from`/`date_to` (`main.py:585`), so the calendar is effectively unfiltered (FastAPI ignores the unknown params). (frontend-map) *needs verification of intended behaviour.* | Align the names — send `date_from`/`date_to` from the client, or rename the handler params. |
| B9 | Medium | frontend `index.html:652` | **CONFIRMED (2026-06-16): `GET /api/config` does not exist.** The dashboard calls `/api/config` (`index.html:652`) but the backend only defines `/api/botbuilder/config` (GET at `main.py:873`). The failed call is swallowed by a try/catch, so active/old lead classification is left empty. | Point the client at `/api/botbuilder/config`, or add an `/api/config` route in the rebuild. |
| B10 | Medium | `rag_manager._extract_text` (73-100); `main.py:487` | **PPT/PPTX unsupported in RAG ingestion** despite being expected. `_extract_text` handles txt/md/pdf/docx/xlsx only and raises on ppt; the upload allowlist excludes ppt → 400 on `.ppt`/`.pptx`. (BE #6) *needs verification it is expected.* | Add a PPT/PPTX text extractor and allow the extension, or document it as unsupported. |
| B11 | Medium | `bot/flow_state.py`, `bot/memory.py`, `bot/chat_status.py` | **Volatile in-memory state.** `_flows`, `_store`, `_cache` are process-local dicts. Restart drops in-progress flows + chat history; breaks under `uvicorn --workers > 1` (state not shared). (BE #3, INF #8) | Externalize to Redis/DynamoDB so state survives restarts and works multi-instance. |
| B12 | Medium | `bot/auth.py:15` | **In-RAM OAuth CSRF state.** `_pending_states` is module-level; lost on restart and not multi-instance safe → login can fail and CSRF protection degrades under multiple workers. (INF #8, BE security #7) | Store pending OAuth state in a shared store with TTL. |
| B13 | Medium | `setup.bat:11,17`; `run_ngrok.ps1:12`; `start.bat:66` | **Blind `timeout`/`Start-Sleep` waits instead of health checks** (17s+ in `setup.bat`). Race conditions if a service is slower than the fixed wait. (INF #2) | Poll a health endpoint / readiness check instead of sleeping. |
| B14 | Medium | `setup.bat:8,14`, `run_server.ps1:1-2`, `run_ngrok.ps1:2` | **Hardcoded machine-specific paths** `C:\Users\B08F~1\Desktop\last_bo` (the Windows 8.3 short name for the Hebrew profile folder). Non-portable; breaks on any other host. (INF #3) | Use relative paths or env vars; replace with container entrypoints for prod. |
| B15 | High (prod) | `run_ngrok.ps1`; `README.md:189` | **ngrok free-tier URL rotates every session**, forcing webhook re-registration with Meta each run. Not viable for production. (INF #4) | Use a stable public endpoint (ALB/API Gateway + TLS + DNS) so re-registration stops. |
| B16 | Medium | `bot/gemini.py:5`; `server_err.txt` | **Deprecated `google.generativeai` SDK** (EOL; FutureWarning captured at startup). (INF #5) | Migrate to the `google-genai` SDK. |
| B17 | Medium | `bot/gemini.py:96` vs `README.md:45` | **Gemini model-name mismatch** — code uses `gemini-3.1-flash-lite`, README says `gemini-1.5-flash-8b`. (INF #6) *needs verification.* | Confirm the correct model name and make code + README agree. |
| B18 | Medium | `main.py` webhook (`:338`, `:87-92`) | **Inbound bot path is single-tenant.** `/webhook` resolves the tenant from one global `client_config/system_prompt.json` (`business_id="client_001"`), so one Meta number → one business; per-business config dirs exist but inbound routing ignores the recipient. Live leads/conversations are mis-attributed and won't show in per-user dashboards. (WA #7, BE security #4) *Intent: needs verification.* | Route inbound by the receiving phone number / a per-tenant mapping; align webhook `business_id` with the dashboard's email-based id. |
| B19 | Medium | `qr_wa_scanner\index.js:213` | **Hardcoded Israel (`972`) phone normalization** in `/send` corrupts non-Israeli numbers despite the README claiming international support. (WA #4) | Accept full international numbers; only default the country prefix when explicitly configured. |
| B20 | Low/Medium | `qr_wa_scanner\index.js:129-130` | **Unconditional reconnect can hot-loop.** `connection==='close'` always reschedules `startAccount` after 3s regardless of cause; a banned/failing session retries forever with no backoff. (WA #5) | Add exponential backoff and stop retrying on permanent failures. |
| B21 | Medium | `qr_wa_scanner\index.js:159-161` | **No retry/durability on inbound webhook delivery.** A failed/timed-out (8s) `axios.post` is only logged; the message is lost. No queue/retry/dead-letter. (WA #3) | Add a retry queue / dead-letter for failed webhook deliveries. |
| B22 | Low | `qr_wa_scanner\index.js:88-92,307` | **Startup path has no error handling.** If `fetchLatestBaileysVersion()` rejects at boot, the first `startAccount` fails uncaught. (WA #6) | Wrap startup in try/catch with a clear error + retry. |
| B23 | Info | `qr_wa_scanner\credentials\default\` | **Empty `credentials/default/`** — the default account dir exists but has no `creds.json`, so no session is persisted; first run requires a fresh QR scan. (WA #8) | Informational; expected on a clean machine. |
| B24 | Low | `run.bat:10-11` | **Legacy FAISS cleanup is a dead startup step** — deletes `bot\brain\_faiss.index`/`_chunks.pkl`, but the live code uses Postgres/pgvector, not FAISS. (INF #11) | Remove the dead cleanup lines. |
| B25 | Medium | `run_server.ps1:2`, `run.bat:13`; `start.bat:63` | **Production runs dev servers** — uvicorn `--reload` and Vite dev mode (no `vite build`). (INF #9) | Use a production process model: gunicorn/uvicorn without reload; `vite build` + static serving. |
| B26 | Low | `leads_db.py:350-356` | **Possibly-malformed `INTERVAL` in `close_stale_conversations`** — uses `INTERVAL '%s minutes'` with a psycopg2 parameter, which may render the int as a quoted literal inside the string. (BE #2) *needs runtime verification.* | Prefer `NOW() - make_interval(mins => %s)`. |
| B27 | Low | `graph.py:49`, `memory.py:5`, `gemini.py:99-102`, `main.py:909` | **Inconsistent role vocabulary** — `graph.py` stores role `"model"`; `memory.py` comment says `"user"/"assistant"`; `main.py:_gemini_call` maps `"assistant"→"model"`. Two conventions across paths. (BE #4) *needs verification of impact.* | Standardize on one role vocabulary across all call sites. |
| B28 | Low | design vs code | **"Satisfied customer" auto-close not implemented.** Listed in the design, but no sentiment logic exists; only lead-completion and the 60-min timer close chats. (BE #5) *needs verification if expected.* | Implement satisfaction detection, or drop it from the design. |
| B29 | Cleanup | `client_config/data_manager.py` | **Dead Airtable module** — fully implemented but imported nowhere; leads persist to Postgres, not Airtable. (BE #7) | Wire it in or remove it (and its `bot_settings` table). |
| B30 | Cleanup | `main.py`, `gemini.py`, `flow_engine.py` (+ `graph.py`) | **Duplicated `_config_dir` logic** — three copies of per-user config resolution plus a 4th flat-only variant in `graph.py` that ignores per-user folders. Drift risk. (BE #8) | Extract one shared config-loading helper. |
| B31 | Cleanup | `scrap_to_rag.py:12` | **Hardcoded bad scraper path** — `SCRAPER = C:\Users\...\Desktop\web_scrap\scrape.py` does not exist (scraper is at `bot/web_scrap/scrape.py`). Doubly dead (also B5/B6). (BE #9) | Remove with the dead `rag_data` path (B6). |

---

## Cross-references to security

Some items are primarily security issues but also behave as bugs. They are tracked in full in
[`security-issues.md`](security-issues.md):

- **No auth on most `/api/*` endpoints + shared-tenant fallback** (security C2).
- **Unauthenticated, destructive `/admin/*` endpoints** — `migrate-leads` UPDATE has no WHERE
  (security C3; touches the `flow_events` table — see [`system-map/database-schema.md`](system-map/database-schema.md)).
- **`PATCH /api/bookings/{id}` ignores `business_id`** (IDOR, security C4).
- **Inbound Meta webhook has no signature check** (security C5).
- **Gateway default token / wildcard CORS / unauthenticated `/status` leaks QR** (security C6).
- **Baileys `creds.json` stored unencrypted** (security M1).
- **`SESSION_SECRET` falls back to a known constant** (security M3).

---

## Notes on confidence

- Items tagged *needs verification* (B1, B8, B9, B10, B17, B18, B26, B27, B28) were not fully
  confirmable from static code — they need a running instance or a product-intent answer.
- Where reports overlapped (the two-WhatsApp-paths finding, the secrets-on-disk finding, the
  single-tenant-inbound finding) they **agreed**; those are merged into single rows above.
- No SQL-injection bugs were found — queries are parameterized throughout (security M4).
