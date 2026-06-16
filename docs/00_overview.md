# System Overview — WhatsApp AI Bot Manager

> One-page, plain-English tour of the whole system. For deeper detail follow the links to
> the system-map documents and the issue lists.
> Last assembled: 2026-06-15. Sources: the five scanner reports under `docs/`.

---

## What is this system?

It is a **WhatsApp chatbot platform for small businesses**. A business owner logs in to a
web dashboard, designs their own chatbot (greetings, menus, the questions it asks, a
knowledge base it can answer from, and a booking page), and then customers chat with that
bot over WhatsApp. The bot answers questions, collects "leads" (customer details), books
appointments, and hands off to a human when needed.

Under the hood it is built from a handful of separate pieces:

- A **Python FastAPI backend** (the brain + the API + the web pages).
- A **Google Gemini** large-language-model that writes the actual replies.
- A **Supabase** database (Postgres + the `pgvector` extension) plus Supabase Storage for files.
- A **WhatsApp connection**. There are actually **two different, unconnected** WhatsApp
  approaches in the codebase (see the health snapshot and the architecture doc) — the live
  one uses Meta's official WhatsApp Cloud API; a second Node.js "Baileys" gateway exists but
  is not wired in.
- A **vanilla HTML/JavaScript frontend** (dashboard, bot builder, public booking page).

---

## Who uses it?

| User | What they do | How they reach it |
|------|--------------|-------------------|
| **Business owner** | Logs in with Google, builds the bot, reads leads, manages the appointment calendar. | Web dashboard at `/` and bot builder at `/botbuilder`. |
| **Customer (end user)** | Chats with the bot on WhatsApp; can also open a public booking page. | WhatsApp; public page `/book/{slug}`. |
| **Developer / QA** | Tests the bot/human/closed conversation states. | Internal tool at `/test-chat-status`. |

---

## The 4 conversation paths

Every inbound WhatsApp message is routed by the backend (in `main.py`'s webhook handler)
into one of four "paths". Routing is decided in order: *closed/human guard → escalation
keyword → menu keyword → active flow step → flow trigger → default LLM.*

1. **Lead collection.** A keyword triggers a step-by-step questionnaire (e.g. name, phone,
   service). Answers are validated, collected, and saved as an **encrypted lead** in the
   database. When the last step is done the conversation auto-closes.

2. **Appointment booking.** Two flavours exist:
   - A **booking link** flow that sends the customer a URL to the real calendar page
     (`/book/{slug}`), where slots are computed from the owner's availability settings and a
     real `bookings` row is created.
   - A **conversational "book_appointment" flow** that only collects free text and files a
     lead — it does **not** create a real booking (this is a known bug, see below).

3. **RAG answering (grounded knowledge).** The bot answers from the business's own uploaded
   documents/website. A "knowledge" menu flow forces the model to answer **only** from
   retrieved text (zero invention); if nothing matches it replies "I have no information on
   that in my knowledge base" (in Hebrew).

4. **Human handoff.** Certain keywords (e.g. "נציג", "human", "agent") flip the conversation
   to `human` status; the bot then goes silent until an admin flips it back.

Full step-by-step traces are in [`system-map/data-flow.md`](system-map/data-flow.md).

---

## The main moving parts

```
 Customer (WhatsApp)
        |
        v
 Meta WhatsApp Cloud API  --(via ngrok public URL)-->  FastAPI backend (main.py, :8000)
        ^                                                   |
        |                                                   |--> Gemini  (writes replies)
        +-----------------(replies via PyWa)----------------+--> Supabase Postgres/pgvector
                                                            |--> Supabase Storage (RAG files)
 Business owner (browser) --> FastAPI-served HTML pages ----+

 [ Separate, NOT wired in: Node.js "Baileys" WhatsApp gateway on :3000 + its React UI on :5173 ]
```

- **`main.py`** — the single big FastAPI file: webhook router, all REST endpoints, login,
  and a 60-second loop that auto-closes idle chats.
- **`bot/` package** — the conversation engine: flow orchestration, in-memory chat memory,
  conversation status, encryption, Google login, database access, and the RAG (knowledge)
  pipeline.
- **`client_config/`** — per-business bot configuration stored as JSON files on disk.
- **Frontend HTML** — `index.html` (dashboard), `botbuilder.html` (bot editor, already
  React-in-browser), `book_client.html` (public booking), `test_chat_status.html` (QA tool).

See [`system-map/architecture.md`](system-map/architecture.md) for the full wiring and
[`system-map/database-schema.md`](system-map/database-schema.md) for the tables.

---

## Current health snapshot

### Top 3 bugs at a glance

1. **The two WhatsApp halves are not connected.** The live bot uses Meta's Cloud API; the
   Node.js Baileys gateway speaks a different, incompatible message format and nothing wires
   them together. Which one is meant to be canonical is unresolved (*needs verification*).
2. **The chat "book appointment" flow does not actually book anything.** It only files a
   free-text lead; only the booking-link URL flow creates a real calendar entry.
3. **Slow, fragile startup.** `run.bat` runs `pip install` on every launch against heavy,
   unpinned dependencies, and the setup scripts use blind fixed-time waits instead of health
   checks. (The dead `rag_data/` code path is also broken — see [`bugs.md`](bugs.md).)

Full list with severities and fix directions: [`bugs.md`](bugs.md).

### Top 3 security issues at a glance

1. **No authentication on most data endpoints.** Anonymous callers can read decrypted lead
   PII, rewrite the bot config (which also deletes leads), and call destructive, unauthenticated
   `/admin/*` endpoints that rewrite every tenant's data.
2. **All live secrets sit in plaintext** in `last_bo\.env` (Supabase service key, Meta token,
   the Fernet key that decrypts every lead, DB password, Google OAuth secret, session secret).
   Not in git history, but everything should be rotated.
3. **WhatsApp entry points are unguarded.** The inbound Meta webhook never verifies its
   signature (forged messages accepted), and the Baileys gateway ships a default token
   `my-secret-token`, wildcard CORS, and an unauthenticated `/status` that leaks the live
   login QR code.

Full audit with severities and fixes: [`security-issues.md`](security-issues.md).

---

## Open questions — RESOLVED by Omer (2026-06-16)

See [`decisions/`](decisions/) for the full decision records.

- **Which WhatsApp path is canonical?** → **The Baileys QR gateway** (`qr_wa_scanner`), not Meta
  Cloud API. ⚠️ Note: unofficial lib (ban risk), creds need encrypting, and the **receive path is
  unverified** (sending works, receiving was never tested). See `decisions/0001`.
- **Is multi-tenant inbound expected?** → **Yes, full multi-tenancy is required.** See `decisions/0002`.
- **Is `GET /api/config` a real endpoint?** → **No — confirmed it does not exist** (only
  `/api/botbuilder/config` does). The frontend call always fails. See bug B9.
- **Gemini model name?** → **`gemini-3.1-flash-lite`** is the default (now in CLAUDE.md). See
  `decisions/0003`; bug B17 resolved.
- **Was a Baileys session ever connected?** → **Yes**, but only **sending** was verified, **not
  receiving**. (The `credentials/default/` folder was empty at scan time.)
