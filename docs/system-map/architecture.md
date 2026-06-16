# Architecture — how the pieces connect

> How every component wires together: frontend ↔ FastAPI backend ↔ WhatsApp ↔ Supabase ↔
> Gemini ↔ ngrok. Assembled from the backend, frontend, whatsapp-gateway, and infrastructure
> scanner reports. Last updated 2026-06-15.

For a one-page summary read [`../00_overview.md`](../00_overview.md) first. For the live
message journey read [`data-flow.md`](data-flow.md).

---

## The big picture (component diagram)

```
                                         CUSTOMER on WhatsApp
                                                  |  ^
                                  message in      |  |  reply out
                                                  v  |
                                  +---------------------------------+
                                  |   Meta WhatsApp Cloud API       |   (the LIVE path)
                                  +---------------------------------+
                                       |   ^
                          POST /webhook|   | send_message (PyWa / Graph API)
                          via ngrok    |   |
                          HTTPS tunnel |   |
                                       v   |
   BUSINESS OWNER                +-------------------------------------------------+
   (browser)                     |        FastAPI backend  —  last_bo/main.py      |
      |                          |                    (uvicorn, port 8000)         |
      | HTML pages + /api/*      |                                                 |
      | (same origin, cookies)   |  webhook router · REST API · Google login ·     |
      +------------------------> |  60s auto-close loop · serves the HTML files    |
                                 |                                                 |
                                 |   bot/ package:                                 |
                                 |     flow_engine · gemini · graph (LangGraph) ·  |
                                 |     memory · chat_status · crypto · auth ·      |
                                 |     leads_db · rag_manager · brain/vectorstore  |
                                 +-------------------------------------------------+
                                    |            |              |             |
                  generate reply    |            | SQL          | Storage     | OAuth
                                    v            v              v             v
                            +-----------+  +-------------+  +-----------+  +-----------+
                            |  Google   |  |  Supabase   |  | Supabase  |  |  Google   |
                            |  Gemini   |  |  Postgres   |  |  Storage  |  |  OAuth    |
                            |  (LLM +   |  | + pgvector  |  | (rag-     |  | (login)   |
                            |  tool use)|  | (all tables)|  |  files)   |  |           |
                            +-----------+  +-------------+  +-----------+  +-----------+

   ALSO ON DISK (local state, not a managed service):
     client_config/<email>/*.json  ·  airtable_tokens.json  ·  in-RAM memory & OAuth state


  ====================  SEPARATE, NOT WIRED IN  ====================
   +--------------------------------------+        +------------------------+
   |  Node.js Baileys gateway (index.js)  |<------>|  Gateway React UI      |
   |  "WA Gateway", port 3000             |  REST  |  (Vite dev, port 5173) |
   |  QR login · /send · /webhook · /status|        |  API_BASE=localhost:3000|
   +--------------------------------------+        +------------------------+
            |                       ^
            | WhatsApp Web          | forwards inbound to a runtime-registered
            v (Baileys socket)      | webhook URL (flat JSON, lost on restart)
       WhatsApp servers
   (This whole box is an alternative WhatsApp path. Nothing in last_bo calls it,
    and its message format is incompatible with main.py's webhook. See "Two WhatsApp
    paths" below. Canonical choice: needs verification.)
```

---

## Component-by-component

### 1. Frontend (vanilla HTML/JS, served by FastAPI)
There is **no separate frontend server** for the live app. FastAPI serves four static HTML
files directly and mounts `/static` to the `frontend/` folder (`main.py:80`):

| URL | File | Audience | Auth |
|-----|------|----------|------|
| `GET /` | `frontend/index.html` | owner dashboard | JS self-guards via `/api/me` |
| `GET /botbuilder` | `frontend/botbuilder.html` | owner bot editor | server-side redirect if no session |
| `GET /book/{slug}` | `frontend/book_client.html` | public customer | none (public) |
| `GET /test-chat-status` | `frontend/test_chat_status.html` | QA/dev | *needs verification* |

The dashboard currently embeds the bot builder via an `<iframe src="/botbuilder">`. The bot
builder is already React 18 (Babel-in-browser via CDN). The frontend talks to the backend
through ~30 `/api/*` endpoints, all same-origin so the session cookie is sent automatically.
Full endpoint inventory is in [`frontend-map.md`](frontend-map.md).

### 2. FastAPI backend (`last_bo/main.py` + `bot/` package)
The heart of the system. One large `main.py` holds the WhatsApp webhook, every REST
endpoint, Google login, and a background loop that closes idle conversations every 60
seconds. The `bot/` package contains the engine modules (flow orchestration, the Gemini
caller, the LangGraph pipeline, in-memory chat memory, conversation status, encryption,
auth, database access, and the RAG pipeline). Runs under `uvicorn` on port **8000** (with
`--reload`, a dev flag). Details: [`backend-map.md`](backend-map.md).

### 3. Google Gemini (the LLM)
Reached from `bot/gemini.py` via the `google.generativeai` SDK (model name
`gemini-3.1-flash-lite` in code; README says `gemini-1.5-flash-8b` — *needs verification*).
The backend builds a system prompt (persona + RAG instructions + booking link), then calls
Gemini with a single tool, `search_knowledge_base`, and runs one tool round-trip. The SDK in
use is end-of-life and should migrate to `google-genai`. The bot-builder's AI endpoints
(`/api/ai/chat`, `/api/ai/validate`, `/api/rag/chat`) are also Gemini proxies — they accept
Anthropic-style request fields but **ignore the `model` field** and return an
Anthropic-shaped `{content:[{text}]}` body.

### 4. Supabase Postgres + pgvector (the database)
The one piece already externalized. Reached via `psycopg2` over `DATABASE_URL` (Supabase
pooler). Holds every table: `users`, `leads`, `flow_events`, `conversations`,
`booking_settings`, `bookings`, plus the RAG tables `brain_chunks` (384-dim vectors) and
`rag_sources`. Vector similarity uses cosine (`<=>`). Schema details:
[`database-schema.md`](database-schema.md).

### 5. Supabase Storage (RAG file store)
Reached from `bot/rag_manager.py` via the `supabase` Python client. Uploaded knowledge-base
files (pdf/docx/xlsx/txt/md) are stored in the `rag-files` bucket; their text is extracted,
chunked, embedded (sentence-transformers, `paraphrase-multilingual-MiniLM-L12-v2`), and
stored as vectors in `brain_chunks`.

### 6. Google OAuth (login)
Reached from `bot/auth.py`. Standard Google OAuth 2.0 (auth URL → code exchange → userinfo).
The logged-in user's **email becomes the `business_id`** for all dashboard/API calls. The
CSRF "state" is kept in an in-RAM set, which breaks across restarts and multiple instances.

### 7. ngrok (public tunnel — local dev only)
Meta must reach the webhook over a public HTTPS URL. `run_ngrok.ps1` opens an `ngrok http
8000` tunnel, reads the public URL from ngrok's local API on port **4040**, and registers
that URL with Meta via the Graph API. The free-tier URL rotates every session, so the
webhook must be re-registered on each run — a production blocker.

### 8. The Baileys gateway (separate Node.js service — not wired in)
`qr_wa_scanner/index.js` is an Express + Baileys app on port **3000** with its own React UI
(Vite dev server, port **5173**). It logs into WhatsApp by QR scan, can send/receive
messages, and forwards inbound messages to a webhook URL registered at runtime. It is a
**self-contained alternative** WhatsApp integration; see the next section.

---

## The two WhatsApp paths (important)

The codebase contains **two independent WhatsApp integrations that do not talk to each
other** (verified by grep — nothing in `last_bo` references the gateway, port 3000, or
Baileys):

| | Live path (`last_bo`) | Gateway path (`qr_wa_scanner`) |
|--|----------------------|-------------------------------|
| Tech | Meta WhatsApp **Cloud API** via PyWa | **Baileys** (WhatsApp Web), QR login |
| Inbound shape | Meta envelope `entry[0].changes[0].value.messages[0]` (`main.py:329-333`) | Flat JSON `{from, text, accountId, raw}` (`index.js:146-156`) |
| Who consumes it | the FastAPI bot | only the gateway's own React UI |
| Status | the live system | standalone, not connected |

Because the two payload shapes are incompatible, even if the gateway were pointed at
`main.py:/webhook`, every message would hit the `except: return {"status":"ignored"}` branch.
**An adapter/translation layer would be needed to connect them, and the canonical choice for
production is unresolved (*needs verification*).** This is the single biggest open
architectural question — see [`infrastructure.md`](infrastructure.md) §6.

---

## How a request flows (two quick examples)

**Owner opens the dashboard:** browser → `GET /` → FastAPI returns `index.html` → JS calls
`GET /api/me` (session cookie) → if logged in, loads leads/dashboard/bookings via `/api/*`;
if `401`, shows the Google login screen → `/auth/google` → Google OAuth → callback sets the
session.

**Customer sends a WhatsApp message:** WhatsApp → Meta Cloud API → ngrok HTTPS →
`POST /webhook` → backend routes into one of the 4 paths → reply sent back via PyWa → Meta →
customer. The full trace is in [`data-flow.md`](data-flow.md).

---

## Where state lives (and why it matters for deployment)

| State | Location today | Problem |
|-------|----------------|---------|
| Tables + vectors | Supabase Postgres/pgvector | OK (managed) |
| RAG source files | Supabase Storage (`rag-files`) | OK (managed) |
| Per-business bot config | local JSON in `client_config/<email>/` | on disk, not shared across instances |
| Baileys WhatsApp session | local `credentials/<id>/creds.json` | on disk, single-socket, hard to scale |
| Airtable tokens | local `airtable_tokens.json` | on disk |
| Chat memory, flow state, chat-status cache | in-process RAM | lost on restart; breaks with >1 worker |
| OAuth CSRF state | in-process RAM | lost on restart; breaks with >1 worker |
| Secrets | plaintext `.env` files | should move to a secret manager |

The AWS-migration notes (ngrok → real endpoint, `.env` → secret manager, on-disk state →
durable storage, in-RAM → Redis/Dynamo, dev servers → production process model) are detailed
in [`infrastructure.md`](infrastructure.md) §6.
