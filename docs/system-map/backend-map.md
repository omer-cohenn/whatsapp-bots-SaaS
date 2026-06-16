# Backend / Business-Logic Map — `last_bo`

Scan target: `C:\Users\עמר כהן\Desktop\last_bo` (READ-ONLY).
Scope: `bot/`, `main.py`, `client_config/`, `wapy_client/`, `bot/web_scrap/`, `bot/brain/`, and root `*.py` scripts.
Excluded: `node_modules`, `.venv`, `__pycache__`, `.git`, `frontend/` (JS/HTML), `*.jsx`, `*.html`.
Date of scan: 2026-06-15.

Stack: FastAPI + Starlette sessions, LangGraph (single linear graph), Google Gemini (`gemini-3.1-flash-lite`) with function-calling, PostgreSQL via `psycopg2` (pgvector for embeddings), Supabase Storage for RAG files, `pywa` for WhatsApp, `sentence-transformers` (`paraphrase-multilingual-MiniLM-L12-v2`, 384-dim) for embeddings, `crawl4ai` for scraping.

---

## 1. Module Inventory

| File | Responsibility (one line) |
|---|---|
| `main.py` | FastAPI app: WhatsApp webhook router, all REST endpoints (auth, dashboard, leads, conversations, RAG mgmt, bookings, BotBuilder config, AI proxies), lifespan startup, 60s auto-close loop. |
| `bot/__init__.py` | Package marker (empty). |
| `bot/graph.py` | LangGraph definition: linear graph `load_memory → call_gemini → save_memory → send_reply`; `BotState` TypedDict; default-LLM path only. |
| `bot/gemini.py` | Builds system prompt (persona + RAG-use-cases + booking-link injection), calls Gemini with `search_knowledge_base` tool, executes one tool round-trip, returns text. |
| `bot/flow_engine.py` | Menu/flow orchestration: trigger matching, step validation/normalization, human-escalation detection, knowledge (RAG) mode, booking-link, step-by-step lead collection, on-complete persistence. |
| `bot/flow_state.py` | In-memory per-phone flow state (`_flows` dict): step flows and knowledge flows. **Volatile — lost on restart.** |
| `bot/memory.py` | In-memory per-phone chat history (`_store` dict), capped at `MAX_HISTORY=10`. **Volatile — lost on restart.** |
| `bot/chat_status.py` | In-memory cache (`_cache`) + DB-backed get/set of conversation status (`bot`/`human`/`closed`). |
| `bot/crypto.py` | Fernet symmetric encrypt/decrypt helpers keyed by `ENCRYPTION_KEY`; decrypt falls back to plaintext (migration-safe). |
| `bot/auth.py` | Google OAuth 2.0 flow (auth URL, code exchange, userinfo); session-user getters. In-memory `_pending_states` set for CSRF state. |
| `bot/leads_db.py` | All Postgres access: schema init, users, leads (encrypted), flow_events, conversations/chat_status, booking_settings, bookings, dashboard stats. Connection pool. |
| `bot/rag_manager.py` | Per-business RAG lifecycle: extract text (pdf/docx/xlsx/txt/md), chunk, embed, store in pgvector; Supabase Storage upload/download; URL scrape via crawl4ai; `rag_sources` table; list/delete/status/rebuild. |
| `bot/brain/__init__.py` | Package marker. |
| `bot/brain/init_brain.py` | Startup: `vectorstore.init_schema()` only (sources managed per-business via UI). |
| `bot/brain/vectorstore.py` | pgvector core: `brain_chunks` schema, embed (sentence-transformers), `build_index(chunks, business_id)`, `search(query, business_id, k)`, delete/count. Cosine via `<=>`. |
| `bot/brain/tool.py` | Gemini tool declaration `search_knowledge_base` + `handle_tool_call` (top-4 chunk retrieval per business). |
| `bot/brain/chunker.py` | `RecursiveCharacterTextSplitter` (chunk 500 / overlap 50). |
| `bot/brain/loader.py` | Loads documents from local `rag_data/` and from `web_scrap/output/*.md`. **Used only by the dead rag_data path (see §8).** |
| `bot/web_scrap/scrape.py` | Standalone crawl4ai BFS site scraper → cleaned Markdown files (no AI). CLI / `loader.py` only; runtime URL indexing uses its own inline crawler. |
| `bot/web_scrap/decode_filenames.py` | Utility to decode/fix scraped Hebrew filenames. Standalone. |
| `bot/web_scrap/fix_unicode.py` | Utility to fix unicode in scraped files. Standalone. |
| `client_config/__init__.py` | Package marker. |
| `client_config/data_manager.py` | **Airtable** OAuth + table creation + lead append + a `bot_settings` k/v table. NOT imported in the runtime path (legacy/dead — see flags). |
| `wapy_client/__init__.py` | Package marker. |
| `wapy_client/client.py` | `pywa` WhatsApp client singleton + `send_message(phone, text)`. |
| `rebuild_rag.py` (root) | Script: rebuild pgvector index from `rag_data/`. **BROKEN** (calls `build_index(chunks)` with 1 arg). |
| `scrap_to_rag.py` (root) | Script: scrape URLs → copy md to `rag_data/` → rebuild. **BROKEN** (1-arg `build_index`; hard-codes a non-existent scraper path). |
| `test_chat_status.py` (root) | Integration test hitting a running server for the chat_status state machine. |
| `check_import.py`, `ci2.py` (root) | Trivial import/CI smoke scripts (not core logic). |

> `bot/web_scrap/.venv/...` (pip internals) and other venvs excluded as instructed.

---

## 2. The 4 Conversation Paths (in code)

All four converge at `POST /webhook` (`main.py:325-395`). Routing order inside the handler: **closed/human guard → escalation keyword → menu keyword → active flow step → flow trigger → default LLM**.

### (a) Lead collection → encrypted leads
- Triggered when a message matches a flow `trigger` keyword (`find_flow_for_trigger`, `flow_engine.py:109-116`) for a standard step flow.
- `start_flow` (`flow_engine.py:154-160`) sets in-memory state and asks step 0.
- Each subsequent message → `handle_step` (`flow_engine.py:163-238`): validate (`_validate` 38-69), normalize (`_normalize_value` 72-88), store in `collected`, advance.
- On final step → `_on_flow_complete` (`flow_engine.py:241-249`) → `save_lead` + `log_flow_event('completed')` + `set_status(phone,'closed')`.
- Encryption: `save_lead` (`leads_db.py:144-156`) Fernet-encrypts `phone`, `flow_id`, and the whole `data` blob; stored as `data = {"_": "<fernet>"}`. `get_leads` (188-217) handles encrypted, legacy-plaintext-dict, and raw forms.
- Schema: `leads(id, business_id, flow_id[enc], phone[enc], data[jsonb enc blob], submitted_at)`.

### (b) Appointment booking + calendar
Two distinct mechanisms:
1. **Conversational step flow** `book_appointment` (in `menus_chat.json`) — a normal lead-collection flow (path a). It does NOT touch the bookings calendar tables; completion message says "a rep will get back to you."
2. **`booking_link` flow type** (the real calendar) — `start_flow` (`flow_engine.py:131-138`) returns a one-shot URL `{BASE_URL}/book/{safe_business_id}`. `gemini.py:46-70` also injects this link into the system prompt so the LLM offers it.
   - Public page: `GET /book/{slug}` (`main.py:620`) → `frontend/book_client.html`.
   - Slots: `GET /api/book/{slug}/slots` (`main.py:631`) → `_compute_slots` (604-615) from `booking_settings` minus already-booked slots.
   - Create: `POST /api/book/{slug}` (`main.py:642`) → `create_booking` with a double-booking guard (409).
   - Admin views/edits via `/api/bookings*` (auth-gated; public `/book/*` routes are not).
   - Tables: `booking_settings(business_id PK, service_name, working_days jsonb, working_hours jsonb, slot_duration)`, `bookings(id uuid, business_id, client_*, date, time, status, notes)`.
   - "Calendar" = self-built slot math; no external Google/Outlook calendar integration found.

### (c) RAG answering (grounded, zero creativity)
- Entry A — **default LLM** (`compiled_graph.invoke`, webhook fallback `main.py:394`): `gemini.generate_reply` exposes `search_knowledge_base`; prompt (`gemini.py:40-44`) tells the model to ALWAYS use the tool for configured `rag_use_cases`. Grounding here is soft (instruction-only).
- Entry B — **knowledge-menu flow** (`flow_type:"knowledge"`): `handle_step` (`flow_engine.py:188-207`) injects a hard `system_override`: must call `search_knowledge_base` before every answer, answer ONLY from retrieved info, and on no-hit reply exactly `'אין לי מידע על כך בבסיס הידע שלי.'`, no invention. This is the "zero-creativity / grounded" path; same override is reused by `POST /api/rag/chat` (`main.py:917-934`).
- Retrieval: `handle_tool_call` (`brain/tool.py:26-30`) → `vectorstore.search(query, business_id, k=4)` (`vectorstore.py:142-162`), top-4 cosine matches joined with `---`; returns "No relevant information found..." when empty.

### (d) Human handoff (detect → transfer → bot stops)
- Detection: `check_human_escalation` (`flow_engine.py:91-96`) keyword match against `human_escalation_keywords` (default `["נציג","אדם","human","agent"]`), checked early in webhook (`main.py:361`). Also reachable via a `flow_type:"human_handoff"` menu option (`flow_engine.py:124-128`).
- Transfer: `set_status(phone, "human")` then send `human_escalation_message`.
- Bot stops: next inbound message hits webhook guard `if status == "human": return {"status":"ignored"}` (`main.py:349-351`) — silent until an admin flips status back via `POST /api/conversations/{phone_enc}/status`.

---

## 3. Conversation Status Logic (`bot` / `human` / `closed`)

Machine: `bot/chat_status.py` (cache + DB) + `bot/leads_db.py` (persistence) + `main.py` webhook (transitions).

- Storage: `conversations(phone PK, business_id, chat_status default 'bot', last_msg_at, updated_at)` (`leads_db.py:62-69`). In-process cache `chat_status._cache` (`chat_status.py:7`).
- Transitions (`main.py` webhook):
  - `closed` + inbound → reset to `bot`, resend main menu (`main.py:343-347`) — re-engagement.
  - `human` + inbound → bot silent (`main.py:349-351`).
  - escalation keyword → `human` (`main.py:361-368`).
  - lead flow completed → `closed` (`flow_engine.py:247`).
  - admin override → bot/human/closed via `POST /api/conversations/{phone_enc}/status` (`main.py:270-284`).
- Auto-close rules:
  - **Lead collected** → `set_status(phone,'closed')` in `_on_flow_complete` (`flow_engine.py:247`).
  - **60-min no-reply** → `_auto_close_loop` (`main.py:54-63`) runs every 60s → `close_stale_conversations(CLOSE_AFTER_MINUTES)` (`leads_db.py:347-358`), closing rows where `chat_status='bot' AND last_msg_at < NOW() - INTERVAL`. `CLOSE_AFTER_MINUTES` default 60 (env, `main.py:51`). `last_msg_at` bumped in `update_last_msg_at` per inbound (`main.py:354-358`).
  - **"Satisfied customer"** auto-close: **NOT IMPLEMENTED** — no sentiment/satisfaction detection exists; only lead-completion and the 60-min timer close conversations. *(needs verification if expected elsewhere — not found.)*

---

## 4. The LangGraph Flow (`graph.py`)

Minimal linear pipeline used ONLY for the default/fallback LLM reply. All menu/flow/escalation/RAG-menu routing happens in the webhook BEFORE the graph is invoked.

Nodes (`graph.py:61-72`):
1. `load_memory` → `get_history(phone)`; loads `business_id` + `rag_use_cases` from the FLAT `client_config/system_prompt.json` (`graph.py:12-17`, 29-34).
2. `call_gemini` → `generate_reply(history, user_message, business_id, rag_use_cases)`.
3. `save_memory` → append user + model messages to in-memory store.
4. `send_reply` → `wapy_client.send_message`.
Edges: `load_memory → call_gemini → save_memory → send_reply → END`. Compiled once at import (`compiled_graph`, line 75).

Actual routing decision tree lives in `main.py:receive_message` (§2). The graph has no conditional edges — path selection is procedural in the webhook, not graph-native.

---

## 5. RAG Generation

### Runtime per-business pipeline (the live one): `bot/rag_manager.py` + `bot/brain/`
- **`web_scrap/` (website → RAG)**: `rag_manager.index_url` (`rag_manager.py:179-241`) runs an inline `crawl4ai.AsyncWebCrawler` in a thread, caches scraped text in `rag_sources.content`, chunks, embeds, stores in pgvector. (Standalone `web_scrap/scrape.py` BFS crawler is a separate CLI feeding the dead `rag_data` path, NOT this runtime path.)
- **`brain/` (file → RAG)**: `rag_manager.index_file` (`rag_manager.py:144-176`) uploads original to Supabase Storage (`rag-files` bucket, sanitized/hashed path), extracts text via `_extract_text` (73-100: txt/md, pdf via pypdf, docx via python-docx, xlsx/xls via openpyxl). **PPT/PPTX NOT supported** — `_extract_text` raises `ValueError` and the upload allowlist (`main.py:487`) excludes ppt. *(Prompt mentioned "ppt" — current code does not handle it; needs verification.)*
- **Becoming retrievable**: `chunk_documents` (500/50) → `vectorstore.build_index(chunks, business_id)` embeds (sentence-transformers) and INSERTs into `brain_chunks(business_id, text, source, embedding VECTOR(384))`, deleting prior chunks for the same `source` first (idempotent re-index). A `rag_sources` row tracks each source + chunk_count.
- **Staying grounded**: retrieval is business-scoped (`WHERE business_id=%s ORDER BY embedding <=> query LIMIT k`); the knowledge-flow `system_override` forbids invention, mandates the tool, and returns a fixed "no info" sentence when empty. Default-LLM path is instruction-only (weaker).
- **`rag_manager.py` summary**: the single per-business RAG control plane — index file, index URL (cache + force_rescrape), delete source (+ Supabase + chunk cleanup), list sources, status (counts), rebuild_all (re-download from Storage / re-scrape). Every function takes `business_id` and scopes every query by it.

### Schema
- `brain_chunks(id, business_id default 'default', text, source, embedding VECTOR(384))` + `brain_chunks_biz_idx` (`vectorstore.py:33-59`).
- `rag_sources(id, business_id, type, name, content, chunk_count, created_at)` + `rag_sources_biz_idx` (`rag_manager.py:52-66`).

---

## 6. Database Touchpoints

DB access: `bot/leads_db.py` (psycopg2 pool) + `bot/brain/vectorstore.py` / `bot/rag_manager.py` (raw connects). `client_config/data_manager.py` uses Airtable REST plus a `bot_settings` table.

| Table | Columns referenced | Defined in | business_id-scoped? |
|---|---|---|---|
| `users` | google_id(PK), email, name, picture, created_at | leads_db.py:36-42 | N/A (global). |
| `leads` | id, business_id, flow_id(enc), phone(enc), data(jsonb), submitted_at | leads_db.py:43-51 | **Yes** — save/get/delete/stats filter business_id. |
| `flow_events` | id, business_id, flow_id, phone, event, step_index, created_at | leads_db.py:52-61 | **Yes** for reads; **migrate-leads UPDATE has none** (flag). |
| `conversations` | phone(PK), business_id, chat_status, last_msg_at, updated_at | leads_db.py:62-69 | **PARTIAL** — `get_conversations_by_status` filters; **get/set_chat_status, update_last_msg_at, close_stale_conversations key on phone only**. |
| `booking_settings` | business_id(PK), service_name, working_days, working_hours, slot_duration, updated_at | leads_db.py:70-77 | **Yes** (PK). |
| `bookings` | id(uuid), business_id, client_name/email/phone, date, time, status, notes, created_at | leads_db.py:78-90 | **PARTIAL** — get/slots filter; **`update_booking_status` filters by id only** (IDOR, flag). |
| `brain_chunks` | id, business_id, text, source, embedding | vectorstore.py:41-47 | **Yes** — search/build/delete/count filter business_id. |
| `rag_sources` | id, business_id, type, name, content, chunk_count, created_at | rag_manager.py:53-61 | **Yes**. |
| `bot_settings` | key(PK), value | data_manager.py:52-58 | **No** (global k/v; legacy Airtable config). |

**business_id provenance**: authenticated API → `business_id = session user email` (`main.py:_business_id` 95-99). WhatsApp webhook → `business_id = _business_id_from_config()` = flat `system_prompt.json` `business_id` field (`"client_001"`) for ALL traffic (`main.py:338, 87-92`) → inbound channel is effectively single-tenant / mis-attributed (see §security).

---

## 7. Per-Business Config (`client_config/`)

- **Flat (legacy/default) files**: `client_config/system_prompt.json` (`business_id:"client_001"`) + `client_config/menus_chat.json`. The flat `system_prompt.json` is what the webhook uses for inbound routing.
- **Per-user folders**: `client_config/oyc3333_gmail.com/` and `client_config/yonat522_gmail.com/`, each with `system_prompt.json` + `menus_chat.json`. Folder name = `re.sub(r"[^\w.-]","_", email)`.
- **Contents**:
  - `system_prompt.json`: `business_name`, `persona` (with `{business_name}` placeholder), `tone`, `language`, `fallback_message`, `trigger_menu_keywords`, `menu_keywords`, `human_escalation_keywords`, `human_escalation_message`, `auto_close_minutes`, `main_menu` (greeting + options), optionally `rag_use_cases`.
  - `menus_chat.json`: `flows[]` — `id`, `label`, `emoji`, `trigger`, and either `steps[]` (+`completion_message`) or `flow_type` ∈ {`human_handoff`, `booking_link`(+`service_name`), `knowledge`(+`topic`,`opening_message`,`exit_keywords`)}.
- **How they load**: `client_config/data_manager.py` does NOT load them (it is the Airtable integration). Config loading is duplicated across:
  - `main.py`: `_config_dir`/`_config_dir_create` (37-49) resolve per-user folder, fallback to flat dir.
  - `bot/gemini.py:_config_dir` (15-23) and `bot/flow_engine.py:_config_dir` (9-15) — same logic, duplicated.
  - `bot/graph.py:_load_prompt_config` (12-17) — reads ONLY the flat file (no per-user awareness).
- **Migration note**: these JSONs are the slated-to-move-to-Supabase data; BotBuilder round-trips them via `/api/botbuilder/config` (`main.py:873-890`, `_bb_config_to_files`/`_files_to_bb_config`).

---

## 8. `rag_data/` — Used or Dead? **VERDICT: DEAD (broken). Legacy single-tenant path only.**

Evidence (grep across codebase):
- `rag_data/` is referenced only by `bot/brain/loader.py` (`RAG_DATA_DIR`, `load_all_documents`) and three callers: `rebuild_rag.py`, `scrap_to_rag.py`, `main.py:/admin/rebuild-rag` (455-462).
- **All three are broken**: each calls `vectorstore.build_index(chunks)` with ONE arg, but the signature is `build_index(chunks, business_id)` (`vectorstore.py:62`) → `TypeError: missing 1 required positional argument: 'business_id'`.
  - `rebuild_rag.py:18`, `scrap_to_rag.py:31`, `main.py:461`.
- The **live** RAG path never touches `rag_data/`: runtime indexing goes through `rag_manager.index_file`/`index_url` → `vectorstore.build_index(chunks, business_id)` (correct 2-arg), sourcing uploads/Supabase Storage/inline scraping; retrieval reads `brain_chunks` by `business_id`.
- The folder currently holds stale demo files (a PDF, an xlsx, a CV docx) unrelated to any business.
- `scrap_to_rag.py:12` additionally hardcodes a scraper path `C:\Users\...\Desktop\web_scrap\scrape.py` that does not exist (scraper is at `bot/web_scrap/scrape.py`) — doubly dead.

**Conclusion**: `rag_data/` + its loader/scripts/admin endpoint are dead code, vestiges of an earlier single-tenant, file-on-disk RAG design that predates the per-business pgvector + Supabase Storage pipeline. Removable. Note that `/admin/rebuild-rag` is both unauthenticated AND broken.

---

## Flags for `bugs.md`

1. **Broken `build_index` calls (rag_data path)** — `rebuild_rag.py:18`, `scrap_to_rag.py:31`, `main.py:461` call `vectorstore.build_index(chunks)` (1 arg) vs required `(chunks, business_id)` (`vectorstore.py:62`). All raise `TypeError`; `/admin/rebuild-rag` 500s on every call.
2. **`close_stale_conversations` interval parameterization** — `leads_db.py:350-356` uses `INTERVAL '%s minutes'` with a psycopg2 parameter; psycopg2 renders the int as a quoted literal inside the string → malformed `INTERVAL`. *(needs runtime verification; prefer `NOW() - make_interval(mins => %s)`.)*
3. **Volatile in-memory state** — `flow_state._flows`, `memory._store`, `chat_status._cache` are process-local dicts. Restart drops in-progress flows + history; breaks under uvicorn `--workers > 1` (state/cache not shared).
4. **Inconsistent role vocabulary** — `graph.py:49` stores role `"model"`; `memory.py:5` comment says `"user"|"assistant"`; `gemini.py:99-102` passes role through, while `main.py:_gemini_call` (909) maps `"assistant"→"model"`. Two different conventions across paths. *(needs verification of impact.)*
5. **"Satisfied customer" auto-close not implemented** — listed as a rule in design but no sentiment logic exists; only lead-completion + 60-min timer close chats.
6. **PPT/PPTX unsupported** — `rag_manager._extract_text` (73-100) handles txt/md/pdf/docx/xlsx only; upload allowlist (`main.py:487`) excludes ppt → 400 on .ppt/.pptx.
7. **Dead Airtable module** — `client_config/data_manager.py` fully implemented but imported nowhere; leads persist to Postgres (`save_lead`), not Airtable. Wire or remove.
8. **Duplicated `_config_dir` logic** in `main.py`, `gemini.py`, `flow_engine.py` (3 copies) + a 4th flat-only variant in `graph.py` that ignores per-user folders — drift risk.
9. **`scrap_to_rag.py` hardcoded bad path** — `SCRAPER = C:\Users\...\Desktop\web_scrap\scrape.py` does not exist (scraper at `bot/web_scrap/`).
10. **Booking chat-flow vs calendar mismatch** — the `book_appointment` step-flow collects free-text "preferred_time" and files a lead ("a rep will get back to you"); it never creates a `bookings` row or checks availability. Only the `booking_link` URL flow uses the real calendar. Users completing the chat flow are NOT actually booked.

## Flags for `security-issues.md`

1. **Booking status IDOR** — `update_booking_status(booking_id, status)` (`leads_db.py:461-465`) filters by `id` only (no business_id). `PATCH /api/bookings/{booking_id}` (`main.py:593-601`) is auth-gated but never verifies ownership → any logged-in user can confirm/cancel ANY business's booking by enumerating UUIDs.
2. **`conversations` not tenant-isolated on the hot path** — `get_chat_status`/`set_chat_status`/`update_last_msg_at`/`close_stale_conversations` key on `phone` only (PK is `phone`, not `(business_id, phone)`). Two businesses sharing a customer phone collide cross-tenant; `_cache` is global by phone too. **Missing business_id isolation.**
3. **Unauthenticated admin endpoints** — `POST /admin/migrate-leads` (`main.py:398-452`) and `POST /admin/rebuild-rag` (455-462) have NO auth guard. `migrate-leads` iterates ALL `leads` and runs `UPDATE flow_events SET business_id=%s` with **no WHERE** (line 449) → an unauthenticated caller can clobber/steal every tenant's data.
4. **Webhook tenant mis-attribution** — inbound WhatsApp uses `_business_id_from_config()` (flat `system_prompt.json` → `"client_001"`) for ALL traffic (`main.py:338`). Real WhatsApp leads/flow_events/conversations are written under the flat business_id, not the per-user (email) business_id used by dashboards → live-channel multi-tenant isolation is effectively broken; dashboards keyed on email won't show webhook leads.
5. **Public booking endpoints accept arbitrary slug** — `GET/POST /api/book/{slug}/...` (`main.py:625-663`) unauthenticated, `slug` = business_id taken directly. Slugs derive from emails (`oyc3333_gmail.com`) → guessable/enumerable; anyone can read working hours and create bookings with no rate-limit/captcha; client name/email/phone unvalidated.
6. **Session secret default** — `SessionMiddleware secret_key=os.environ.get("SESSION_SECRET", "change-me-in-env")` (`main.py:79`). Unset env in prod → sessions signed with a public key → session forgery / auth bypass. Should fail-closed.
7. **OAuth state in-memory & global** — `auth._pending_states` (`auth.py:15`) and Airtable `_pending_state` (`data_manager.py:82`) are module-level; break across workers/restarts (login fails) and degrade CSRF protection under multi-worker.
8. **Secrets at-rest / `.env`** — `last_bo/.env` (2.7 KB) holds `DATABASE_URL`, `GEMINI_API_KEY`, `ENCRYPTION_KEY`, WhatsApp/Google/Airtable secrets. `.gitignore` is present (confirm coverage). Anyone with `ENCRYPTION_KEY` decrypts all lead PII; `crypto.decrypt` silently returns ciphertext-as-plaintext on failure (`crypto.py:26`), masking key-rotation breakage.
9. **PII in logs** — `print(f"[webhook] {phone}: {text[:60]}")` (`main.py:334`) logs raw phone + message content in plaintext despite at-rest encryption.
10. **(Contrast / OK)** — `/api/rag/*`, `/api/leads`, `/api/dashboard`, `/api/conversations` (list) all scope by `_business_id(request)` (email) and are session-gated — these are correctly isolated, which makes the bookings/admin/webhook gaps above the priority fixes.
