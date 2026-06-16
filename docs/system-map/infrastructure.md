# Infrastructure / Run Map

Scan of how the original system runs, across two folders:

- **`last_bo`** — `C:\Users\עמר כהן\Desktop\last_bo` — Python FastAPI backend ("WhatsApp AI Bot"), uses the **Meta WhatsApp Cloud API** via PyWa.
- **`qr_wa_scanner`** — `C:\Users\עמר כהן\Desktop\qr_wa_scanner` — Node.js Express + Baileys "WA Gateway" (self-hosted WhatsApp Web client) with a React UI.

> NOTE on relationship: These are **two independent WhatsApp integration approaches that are NOT currently wired to each other.** `last_bo` receives messages from Meta's Cloud API webhook and replies via PyWa (`wapy_client/client.py`). `qr_wa_scanner` is a standalone Baileys gateway that forwards inbound messages to whatever `WEBHOOK_URL` is registered with it. Both happen to expose a route literally named `/webhook`, but the payload shapes differ (Meta envelope vs. the gateway's flat JSON). No file in `last_bo` references the gateway, port 3000, or Baileys (verified by grep — no matches). Whether the gateway is meant to eventually replace the Meta path is **needs verification**.

> Hebrew username caveat: All hardcoded paths in the `.bat`/`.ps1` scripts use the Windows 8.3 short name `C:\Users\B08F~1\Desktop\last_bo`. `B08F~1` is the short alias for the Hebrew-named profile folder `C:\Users\עמר כהן`. The scripts are machine-specific and will break on any host where that short name differs.

---

## 1. Startup / Run Scripts

### `last_bo` (Python backend)

#### `setup.bat` — primary orchestrator (`last_bo\setup.bat`, lines 1-20)
Runs, in order:
1. `taskkill /F /IM ngrok.exe` and kills any process LISTENING on `:8000` (lines 4-5) — clean slate.
2. Launches a new PowerShell window running `run_server.ps1` (line 8) — the FastAPI/uvicorn server.
3. `timeout /t 7` — blind 7-second wait for the server (line 11).
4. Launches a new PowerShell window running `run_ngrok.ps1` (line 14) — ngrok tunnel + Meta webhook registration.
5. `timeout /t 10` — blind 10-second wait for ngrok (line 17).
6. Opens `http://localhost:8000` in the browser (line 19).
- **FLAG:** Uses fixed `timeout` waits (7s + 10s = 17s minimum) instead of health-polling. Fragile and slow; if the server or ngrok is slower than the timeout, downstream steps run against a not-yet-ready service. Hardcoded `B08F~1` paths.

#### `run_server.ps1` (`last_bo\run_server.ps1`, lines 1-2)
- `Set-Location` to the hardcoded `B08F~1` project dir, then runs `.venv\Scripts\uvicorn.exe main:app --reload --host 0.0.0.0 --port 8000`.
- `--reload` is a dev-mode flag (file-watcher); not for production.

#### `run_ngrok.ps1` (`last_bo\run_ngrok.ps1`, lines 1-45)
1. Manually parses `.env` line-by-line and sets each as a process env var (lines 1-6).
2. Starts `ngrok http 8000` in the background (line 9).
3. `Start-Sleep -Seconds 4` (line 12) — blind wait for ngrok.
4. Queries ngrok's local API `http://localhost:4040/api/tunnels` to get the public HTTPS URL (lines 16-18).
5. **Auto-registers the webhook with Meta** via `POST https://graph.facebook.com/v18.0/$APP_ID/subscriptions` using `WHATSAPP_APP_ID`, `WHATSAPP_APP_SECRET`, `WEBHOOK_VERIFY_TOKEN` (lines 23-34). Callback URL = `<ngrok-url>/webhook`.
6. Blocks on `Read-Host` and kills ngrok on exit (lines 43-44).
- **FLAG:** Relies on the ngrok free-tier URL, which rotates every session; the webhook must be re-registered each run (confirmed in `last_bo\README.md` line 189). Hardcoded `v18.0` Graph API version.

#### `run.bat` — alternative/legacy starter (`last_bo\run.bat`, lines 1-17)
1. Activates `.venv` (line 4).
2. **`pip install -r requirements.txt` on every run** (line 7).
3. Deletes stale FAISS index files `bot\brain\_faiss.index` and `_chunks.pkl` if present (lines 10-11). (Note: the live code path uses Postgres/pgvector, not FAISS — these are legacy artifacts.)
4. Starts uvicorn (`--reload`, port 8000) and `ngrok http 8000` in two separate PowerShell windows (lines 13-14).
- **FLAG (startup speed):** Re-running `pip install -r requirements.txt` on every launch is the slowest step in the system. `requirements.txt` pulls `sentence-transformers`, `crawl4ai`, and `langchain*` — heavy dependency trees — so even a no-op resolve is slow, and a cold install is very slow.

#### `test_if.bat` (`last_bo\test_if.bat`, lines 1-6)
- Sets UTF-8 codepage (`chcp 65001`), runs `python test_chat_status.py`, pauses. A manual test helper, not part of normal startup.

#### `server_err.txt` (`last_bo\server_err.txt`, present, lines 1-12)
- Captured stderr from a previous run. Contains a **`FutureWarning` from `bot/gemini.py:5`**: the `google.generativeai` package is end-of-life and should be migrated to `google-genai`. Last lines show normal uvicorn startup. Mojibake in the path line confirms a Hebrew-path/encoding mismatch when the log was written.
- **FLAG:** Deprecated `google.generativeai` SDK in use.

### `qr_wa_scanner` (Node gateway)

#### `start.bat` (`qr_wa_scanner\start.bat`, lines 1-73)
1. Checks `node` is on PATH; errors out with a link if missing (lines 12-17).
2. Installs backend deps only if `node_modules\` is missing (`npm install`) (lines 20-28).
3. Installs frontend deps only if `frontend\node_modules\` is missing (lines 31-41).
4. Reads `PORT` from `.env` (default 3000) (lines 44-51).
5. Starts the backend in a new window: `node -r dotenv/config index.js` with `LOG_LEVEL=info` (line 60).
6. Starts the frontend (Vite dev server) in a new window: `cd frontend && npm run dev` → port 5173 (line 63).
7. `timeout /t 4`, then opens `http://localhost:5173` (lines 66-67).
- Better-behaved than `last_bo`'s scripts: it guards installs behind existence checks (no reinstall on every run) and uses relative paths (no hardcoded user dir).
- **FLAG (minor):** Same blind `timeout /t 4` before opening the browser; frontend dev server may not be ready.

---

## 2. Processes & Ports

| Process | Folder | Port | Started by | Role |
|---|---|---|---|---|
| FastAPI / uvicorn (`main:app`) | last_bo | **8000** | `run_server.ps1` / `run.bat` | Backend: Meta webhook receiver, REST API, serves HTML frontend, admin/RAG/booking endpoints |
| ngrok tunnel | last_bo | tunnels 8000; local API on **4040** | `run_ngrok.ps1` / `run.bat` | Public HTTPS URL so Meta can reach the webhook |
| Node Express + Baileys (`index.js`) | qr_wa_scanner | **3000** (from `.env PORT`) | `start.bat` | Self-hosted WhatsApp gateway: QR login, send/receive, REST API |
| Vite dev server (React UI) | qr_wa_scanner/frontend | **5173** (`vite.config.js` line 8) | `start.bat` | Gateway admin UI (QR display, send test, webhook config) |

### How they talk
- **last_bo frontend serving:** FastAPI serves the HTML directly — `GET /` → `frontend/index.html` (`main.py:148-150`), plus `/botbuilder`, `/book/{slug}`, `/test-chat-status`, and `/static` mounted to `frontend/` (`main.py:80`). There is **no separate frontend server** for `last_bo`; the `.jsx`/`.html` files are served as static assets.
- **last_bo inbound:** Meta Cloud API → ngrok HTTPS → `POST /webhook` (`main.py:325`). Payload parsed as Meta envelope `body["entry"][0]["changes"][0]["value"]["messages"][0]` (`main.py:329-333`).
- **last_bo outbound:** replies sent via `wapy_client.client.send_message` → PyWa → `graph.facebook.com` (`main.py:315-316, 364-365, 381-382, 389-390`).
- **qr_wa_scanner UI → backend:** React `App.jsx` hardcodes `const API_BASE = "http://localhost:3000"` (`frontend/src/App.jsx:3`) and calls `/status`, `/send`, `/webhook`, `/logout` with header `x-api-token` (lines 332-400).
- **qr_wa_scanner inbound:** Baileys `messages.upsert` → HTTP `POST` to the registered `account.webhookUrl` with an 8s timeout (`index.js:141-162`).

---

## 3. Config / Env (names + locations only — no secret values printed)

### `last_bo\.env` (29 lines; gitignored via `.gitignore:1`)
| Var | Read at | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | `bot/gemini.py:12` | Gemini auth |
| `SYSTEM_PROMPT` | `bot/gemini.py:38` | Default persona fallback |
| `WHATSAPP_TOKEN` | `wapy_client/client.py:8` | Meta Cloud API token |
| `WHATSAPP_PHONE_NUMBER_ID` | `wapy_client/client.py:9` | Meta phone id |
| `WHATSAPP_APP_ID` | `wapy_client/client.py:10`, `run_ngrok.ps1:23` | Meta app id / webhook reg |
| `WHATSAPP_APP_SECRET` | `wapy_client/client.py:11`, `run_ngrok.ps1:24` | Meta app secret |
| `WEBHOOK_VERIFY_TOKEN` | `main.py:82`, `run_ngrok.ps1:25` | Webhook verification |
| `APP_PORT` | `.env:13` (declared; server port is hardcoded 8000 in scripts) | App port |
| `DATABASE_URL` | `bot/leads_db.py:15`, `bot/brain/vectorstore.py:27` | Supabase Postgres (pgvector) connection |
| `SUPABASE_URL` | `bot/rag_manager.py:107` | Supabase project URL (Storage) |
| `SUPABASE_SERVICE_KEY` | `bot/rag_manager.py:108` | Supabase service-role key |
| `ENCRYPTION_KEY` | `bot/crypto.py:7` | Fernet symmetric key for at-rest token encryption |
| `SESSION_SECRET` | `main.py:79` | Starlette SessionMiddleware signing key |
| `GOOGLE_CLIENT_ID` | `bot/auth.py:7` | Google OAuth client |
| `GOOGLE_CLIENT_SECRET` | `bot/auth.py:8` | Google OAuth secret |
| `GOOGLE_REDIRECT_URI` | `bot/auth.py:9` | OAuth callback (`http://localhost:8000/auth/google/callback`) |
| `BASE_URL` (optional) | `bot/gemini.py:58` | Booking-link base; defaults to `http://localhost:8000` |
| `CLOSE_AFTER_MINUTES` (optional) | `main.py:51` | Stale-conversation auto-close window |

- **WARNING:** `last_bo\.env` currently contains **live-looking real secret values** (Gemini key, Meta token, Supabase service key, Google client secret, Fernet key, DB password). Despite `.gitignore`, these are on disk in plaintext. Treat as compromised / rotate before any AWS migration. (Values intentionally not reproduced here.)

### `qr_wa_scanner\.env` (gitignored via `.gitignore:2`)
| Var | Read at | Purpose |
|---|---|---|
| `PORT` | `index.js:14`, `start.bat:44-51` | Backend port (default 3000) |
| `API_TOKENS` (CSV) / `API_TOKEN` | `index.js:12-13` | Bearer tokens for `x-api-token` auth |
| `WEBHOOK_URL` | declared in `.env`; not read at startup (webhook is set per-account at runtime via `POST /webhook`) | Inbound message forwarding target |

- `qr_wa_scanner\.env` contains only a placeholder token (`my-secret-token`) — no high-value secrets.

### Config files (not env)
- `last_bo\client_config\system_prompt.json`, `menus_chat.json` — per-business bot config (`main.py:87-92`, `bot/gemini.py:27-68`). Per-user subfolders exist: `client_config\oyc3333_gmail.com\`, `client_config\yonat522_gmail.com\`.
- `last_bo\client_config\airtable_tokens.json` — gitignored (`.gitignore:7`); used by `client_config/data_manager.py` for Airtable OAuth (`requests` to a `_TOKEN_URL` / `_META_BASE`).
- `qr_wa_scanner\credentials\<accountId>\creds.json` — per-account Baileys WhatsApp session files (`index.js:11,17-69`). `credentials/default/` exists. Gitignored (`.gitignore:3`).
- `last_bo\server_err.txt` — present; see section 1.

---

## 4. External Services

| Service | Reached from | How |
|---|---|---|
| **Gemini** | `last_bo/bot/gemini.py:5,12,93` | `google.generativeai` SDK, `model_name="gemini-3.1-flash-lite"`. **Conflict: README says `gemini-1.5-flash-8b`; code says `gemini-3.1-flash-lite` — needs verification which is correct.** Deprecated SDK (see flags). |
| **Supabase Postgres / pgvector** | `last_bo/bot/leads_db.py`, `bot/brain/vectorstore.py` | `psycopg2` over `DATABASE_URL` (Supabase pooler host on port 6543). `vectorstore` creates `vector` extension and `brain_chunks VECTOR(384)` table (`vectorstore.py:39-47`). Connection pool size 1-10 (`leads_db.py:15`). |
| **Supabase Storage** | `last_bo/bot/rag_manager.py:105-139` | `supabase` Python client, bucket `rag-files` for uploaded RAG source files. |
| **Google OAuth** | `last_bo/bot/auth.py:11-50` | Direct HTTP to `accounts.google.com/o/oauth2/v2/auth`, `oauth2.googleapis.com/token`, `googleapis.com/oauth2/v2/userinfo`. In-memory `_pending_states` set for CSRF (`auth.py:15`) — **lost on restart / not multi-instance safe.** |
| **Meta WhatsApp Cloud API** | `last_bo/wapy_client/client.py`, `run_ngrok.ps1:30-32` | PyWa client for sending; Graph API `v18.0` for webhook subscription registration. |
| **WhatsApp Web (Baileys)** | `qr_wa_scanner/index.js:1,88-164` | `@whiskeysockets/baileys` WebSocket, QR login, session persisted to `credentials/`. Independent of the Meta path. |
| **ngrok** | `last_bo/run_ngrok.ps1`, `run.bat:14` | Local CLI tunnel to port 8000; public URL fetched from local API `:4040`. Free-tier URL rotates each session. |
| **Airtable** (secondary) | `last_bo/client_config/data_manager.py:101-261` | OAuth + Airtable Meta API (`requests`), tokens in `airtable_tokens.json`. |

---

## 5. Dependencies & Runtime Versions

### `last_bo` — Python (`requirements.txt`, 18 deps, **no version pins**)
`fastapi`, `uvicorn[standard]`, `python-dotenv`, `google-generativeai` (deprecated), `langgraph`, `langchain-core`, `langchain-text-splitters`, `pywa`, `pypdf`, `python-docx`, `psycopg2-binary`, `sentence-transformers`, `openpyxl`, `crawl4ai`, `python-multipart`, `cryptography`, `itsdangerous`, `supabase`.
- Runtime observed: `.venv` Python **3.12.0** (README requests 3.11+).
- **FLAG:** No version pinning anywhere — non-reproducible builds. Heavy ML/scraping deps (`sentence-transformers`, `crawl4ai`) drive slow installs. `sentence-transformers` also downloads the `paraphrase-multilingual-MiniLM-L12-v2` embedding model on first use (`vectorstore.py:14`), an extra cold-start cost.

### `qr_wa_scanner` backend — Node (`package.json`)
- Runtime: depends on Node 18+ (README); host has Node **v24.15.0** installed.
- deps: `@whiskeysockets/baileys ^6.7.8`, `@hapi/boom ^10.0.1`, `axios ^1.6.8`, `cors ^2.8.5`, `express ^4.18.3`, `pino ^8.19.0`, `qrcode ^1.5.3`, `dotenv ^16.4.5`. devDep: `nodemon ^3.1.0`.

### `qr_wa_scanner` frontend — Node/Vite (`frontend/package.json`)
- deps: `react ^18.2.0`, `react-dom ^18.2.0`. devDeps: `@vitejs/plugin-react ^4.2.1`, `vite ^5.2.0`. Dev server port 5173 (`vite.config.js`).
- **Note:** no `build` step is run by `start.bat`; the UI runs in Vite **dev mode** even for normal use. For production it must be `vite build` + static-served.

---

## 6. AWS Production — High-Level Notes

### Where state lives today (all local / single-host)
- **Postgres + vectors:** already managed (Supabase). The one externalized piece.
- **RAG source files:** Supabase Storage bucket `rag-files`. Also managed.
- **Per-business config:** local JSON files under `last_bo\client_config\<email>\` — **on disk, not in a DB.** Lost if the host dies; not shared across instances.
- **WhatsApp/Baileys sessions:** `qr_wa_scanner\credentials\<accountId>\creds.json` — **on local disk.** Must persist across restarts and cannot be safely duplicated across horizontally scaled instances (one socket per credential).
- **Airtable tokens:** `client_config\airtable_tokens.json` — on disk (Fernet-encrypted values via `crypto.py`).
- **OAuth CSRF state & conversation memory:** **in-process RAM** (`auth.py:_pending_states`, README confirms `memory.py` is an in-RAM dict). Breaks under multiple instances or restarts.
- **Secrets:** plaintext `.env` files on disk.

### Local-only pieces that must become managed services for AWS
1. **ngrok tunnel** → replace with a real public endpoint: ALB/API Gateway + ACM TLS + stable DNS. The webhook URL must be stable so it stops needing per-session re-registration with Meta.
2. **`.env` secrets on disk** → AWS Secrets Manager / SSM Parameter Store; rotate the currently-exposed keys first.
3. **`client_config/*.json` + `credentials/*` on disk** → durable shared storage (S3, or EFS if filesystem semantics are needed) or a DB table. Baileys creds especially need careful single-writer handling.
4. **In-RAM state** (OAuth states, conversation memory) → externalize to Redis/ElastiCache or DynamoDB so the app can run >1 instance and survive restarts.
5. **`--reload` uvicorn + Vite dev server** → production process model: containerize (ECS/Fargate or EKS), `uvicorn`/`gunicorn` without reload, and `vite build` static assets behind CloudFront/S3.
6. **Hardcoded `localhost` URLs** (`API_BASE = http://localhost:3000` in `App.jsx:3`; `GOOGLE_REDIRECT_URI`, `BASE_URL` defaults) → environment-driven config.
7. **Machine-specific `.bat`/`.ps1` with `B08F~1` paths** → not portable; replace with container entrypoints / IaC.

### Biggest blocker
The **WhatsApp connectivity layer** is the hardest to move: Baileys credentials (`credentials/`) are stateful single-socket sessions that resist horizontal scaling and require durable shared storage with single-writer guarantees, and the whole local flow depends on **ngrok** for the public webhook. On top of that, the system runs **two unreconciled WhatsApp paths** (Meta Cloud API in `last_bo` vs. Baileys in `qr_wa_scanner`); which one is canonical for production is unresolved and **needs verification** before any AWS architecture is finalized.

---

## Flags for bugs.md

1. **Slow startup — `pip install -r requirements.txt` on every launch** (`last_bo\run.bat:7`). Heavy deps (`sentence-transformers`, `crawl4ai`, `langchain*`, all **unpinned**) make this the slowest, most fragile step. Should be a one-time setup, not per-run.
2. **Blind `timeout`/`Start-Sleep` waits instead of health checks** (`setup.bat:11,17` = 17s; `run_ngrok.ps1:12`; `start.bat:66`). Race conditions if a service is slower than the fixed wait.
3. **Hardcoded machine-specific paths** `C:\Users\B08F~1\Desktop\last_bo` in `setup.bat:8,14`, `run_server.ps1:1-2`, `run_ngrok.ps1:2`. Non-portable; breaks on any other host.
4. **ngrok free-tier URL rotates every session**, forcing webhook re-registration each run (`run_ngrok.ps1`; `last_bo\README.md:189`). Not viable for production.
5. **Deprecated `google.generativeai` SDK** (`bot/gemini.py:5`; warning captured in `server_err.txt:1-9`). Package is EOL; migrate to `google-genai`.
6. **Gemini model name mismatch** — code uses `gemini-3.1-flash-lite` (`bot/gemini.py:96`) but README says `gemini-1.5-flash-8b` (`README.md:45`). Needs verification.
7. **Live secrets committed to disk in plaintext `.env`** (`last_bo\.env`) — Gemini, Meta token, Supabase service key, Google secret, Fernet key, DB password. Rotate and move to a secret manager.
8. **In-RAM state that breaks on restart / multi-instance** — OAuth CSRF `_pending_states` (`bot/auth.py:15`) and conversation memory (`README.md:40`).
9. **Production runs dev servers** — uvicorn `--reload` (`run_server.ps1:2`, `run.bat:13`) and Vite dev mode for the gateway UI (`start.bat:63`); no `vite build`.
10. **Two unreconciled WhatsApp integrations** (Meta Cloud API in `last_bo` vs. Baileys gateway in `qr_wa_scanner`); not wired together, canonical path unclear. Needs verification.
11. **Legacy FAISS cleanup in `run.bat:10-11`** deletes `bot\brain\_faiss.index` / `_chunks.pkl`, but the live code uses Postgres/pgvector — dead startup step.
12. **Weak auth defaults** — `SESSION_SECRET` falls back to `"change-me-in-env"` (`main.py:79`); `.env WEBHOOK_VERIFY_TOKEN` is the literal `secret`; gateway `API_TOKENS` default is `my-secret-token` (`index.js:12`).
