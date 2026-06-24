# CLAUDE.md — Master Rulebook for Bizz_up

> This file is the **first thing every AI agent reads** before touching this project.
> It is pinned to the "front door" (project root) so Claude Code auto-loads it every session.
> If any instruction conflicts with this file, **this file wins**.

---

## 1. What this project is

**Bizz_up** is a multi-tenant WhatsApp Bot SaaS platform. Business owners connect WhatsApp and
build conversational chat menus. The bot handles four conversation paths:

1. **Lead collection** — structured questionnaires saved as encrypted leads.
2. **Appointment booking** — each business gets a booking link + calendar tab.
3. **RAG info answering** — answers from the business's own uploaded files/websites, **zero creativity**.
4. **Human handoff** — bot detects the request, transfers to a human, and stops answering.

The original working system lives in **two** read-only folders, and we are rebuilding it cleanly here:
- `C:\Users\עמר כהן\Desktop\last_bo` — backend (FastAPI/LangGraph), frontend (vanilla HTML), per-business config, RAG.
- `C:\Users\עמר כהן\Desktop\qr_wa_scanner` — the standalone Node.js / Baileys **WhatsApp gateway** (with its own small React/Vite UI). Note: `last_bo/wapy_client/client.py` is the Python side that talks to this gateway.

---

## 2. The Golden Rules (NON-NEGOTIABLE)

### 🔒 Rule 1 — the original folders are READ-ONLY and SACRED
The original projects at `C:\Users\עמר כהן\Desktop\last_bo` **and**
`C:\Users\עמר כהן\Desktop\qr_wa_scanner` must **NEVER** be modified.
- ✅ Allowed: read, search, analyze, copy *into* `Bizz_up`.
- ❌ Forbidden: create, edit, move, rename, or delete **anything** under `last_bo`.
- This is also enforced in `.claude/settings.json`, but the behavioral rule is the real guarantee.

### 🏢 Rule 2 — Multi-tenant isolation by `business_id`
One business must **NEVER** see another business's data.
- Every database query that touches tenant data **MUST** filter by `business_id`.
- Never trust a `business_id` coming from the client without verifying it belongs to the authenticated user.
- When in doubt, scope it down. A missing filter = a data leak = a dead startup.

### 🛡️ Rule 3 — Security by default
- **No secrets in code.** API keys, tokens, encryption keys → environment variables only.
- **Encrypt sensitive data at rest** (leads, WhatsApp credentials).
- **Validate all input** coming from WhatsApp users and from the frontend.
- Never log secrets, tokens, or raw personal data.

### 🎨 Rule 4 — Frontend is React + Tailwind CSS
- All UI is built with **React + Tailwind CSS**. No new vanilla HTML/JS pages.
- The React rebuild must **not break existing FastAPI backend endpoints**.

---

## 3. Where we are right now (project phase)

**Current phase: BUILD (the MVP).** Mapping + the ground-up re-spec are DONE.
- 📍 **Resume point — read [`docs/STATUS.md`](docs/STATUS.md) first**, then [`docs/spec/mvp-checklist.md`](docs/spec/mvp-checklist.md).
- ✅ **M0–M5, M7–M11.2** (full MVP: tenant wall, auth, AI bot builder, engine, dashboard, handoff chat, lead outcomes, appointments/booking) **and ✅ M6a + M6a.1 + M6a.2** (WhatsApp: owner self-chat self-test, ≤5 named test-number allowlist, owner handoff replies sent back over WhatsApp) are **done, committed on `main`, and pushed to GitHub `omer-cohenn/ManBuizz`**. **Next: M6b** — multi-tenant WhatsApp (one socket per business, encrypted creds in DB, drain outboxes, lock down the gateway dev routes), then AWS deploy. Exact per-milestone detail lives in `docs/STATUS.md` (always read it first).
- ▶️ **Run the local stack:** double-click `run.bat` (Docker Desktop must be running); stop with `stop.bat`. URLs: frontend `:5173`, gateway QR `:3000/qr`, dev inbox/send `:3000/inbox` · `:3000/send`.
- New code lives in `backend/ gateway/ frontend/ infra/ supabase/`. The full plan is in `docs/spec/`. (We ARE writing production code now — per the locked decisions + checklist.)

---

## 4. Folder map

Five clear domains in ONE monorepo. **Full human-readable map → [`STRUCTURE.md`](STRUCTURE.md)**
(Hebrew "signs" over the technical names) + a `README.md` inside each domain folder.

```
Bizz_up/
├── CLAUDE.md              ← you are here (the rulebook)
├── STRUCTURE.md           ← the master map (5 domains, every folder/key file explained in Hebrew)
├── ENV_SETUP.md           ← what to fill to run with REAL APIs (env vars + generators)
├── README.md
├── run.bat / stop.bat / Makefile   ← one-command run/stop/verbs
├── backend/              🧠 FastAPI — api/(doors) services/(brain) models/(forms) core/(vault) db/(pipe) tests/
├── gateway/             💬 Node/Baileys — src/{index,socket,webhook,routes,contract,config,logger}.js
├── frontend/            🎨 React+Tailwind — src/{pages/,components/(landing,whatsapp,admin,booking,dashboard,ui,botbuilder),lib/,i18n/}
├── infra/               🧱 docker-compose.yml + .env(.local).example
├── supabase/            🗄️ migrations/ 0001…0021 (RLS lives here) + seed.sql
├── tests/               🛡️ test_*.bat runners (test code lives in backend/tests/)
├── docs/                📚 STATUS.md + decisions/ + spec/ + system-map/
└── .claude/             🤖 the "AI control room": agents/ workflows/ settings.json (+ last_bo write-deny)
```

---

## 5. Coding standards (for when we DO build)

- **Clarity over cleverness.** Omer is a beginner — code should be readable and commented where non-obvious.
- **Small, focused files.** One responsibility per module.
- **Names say what they do.** No cryptic abbreviations.
- **Match the surrounding style** when editing existing files.
- **Backend:** Python / FastAPI / LangGraph. **Gateway:** Node.js / Express / Baileys. **DB:** Supabase (PostgreSQL).
- **AI model (DEFAULT):** Google **Gemini `gemini-3.1-flash-lite`** for AI + RAG. This is the single source of truth for the model name. RAG answering = strictly grounded, no invented facts.

---

## 6. How to behave with Omer

- Explain concepts in **simple, plain language**.
- Go **step by step**; ask before assuming; don't overwhelm.
- When proposing changes, show the plan first and wait for a green light.

---

## 7. Key product decisions (LOCKED)

Full rationale lives in `docs/decisions/`. Locked so far (2026-06-16):

1. **WhatsApp = the Baileys QR gateway** (`qr_wa_scanner`), NOT Meta Cloud API. ⚠️ Baileys is an
   *unofficial* library → manage ban risk; session creds must be **encrypted at rest**; the
   **receive/inbound path still needs to be built and verified** (sending was confirmed, receiving was not).
   See `docs/decisions/0001-whatsapp-baileys-canonical.md`.
2. **Multi-tenant SaaS** — full per-business isolation: each business gets its own QR session, its own
   config (moved from disk JSON into Supabase), and **every tenant query MUST filter by `business_id`**.
   See `docs/decisions/0002-multi-tenant-required.md`.
3. **Default AI model = `gemini-3.1-flash-lite`.** See `docs/decisions/0003-default-ai-model.md`.
4. **MVP = Phase 1.** Bot (for customers): **lead collection + human handoff**. Owner tooling (all
   required): **AI-assisted bot builder**, **"try-me" test mode**, minimal dashboard, WhatsApp QR
   connect — multi-tenant + auth + secret-cleanup baked in. Booking → Phase 2, RAG → Phase 3.
   See `docs/decisions/0004-mvp-scope.md`.
5. **Data model = 9 Postgres tables + live chat in Redis** (`docs/spec/data-model.md`). Auth =
   **Google-login-via-FastAPI + hand-wired RLS** (must be tested); WhatsApp key isolated in its own encrypted table
   (crown jewel); **live chat (last ~10 msgs + status) is ephemeral in Redis, not the DB**; abandoned leads persisted
   for follow-up; funnel included. See decisions 0005 + 0006.
