# Target Architecture — MVP (Phase 1)

> The blueprint for the **rebuilt** Bizz_up (not the old system — that's in `../system-map/`).
> Draft from the re-spec on 2026-06-16. Open to change. Reflects decisions 0001–0006.

## The 7 parts

**What we build (3):**
1. **React + Tailwind frontend** — the business owner's app: login, the **AI bot builder**, the
   **try-me test** chat, and the dashboard (leads + conversations + bot↔human toggle). Static files.
2. **FastAPI backend** — the brain: auth, the REST API for the frontend, the conversation engine
   (LangGraph flows for lead collection + handoff), the AI-assist endpoints, the **webhook that
   receives** inbound WhatsApp messages, and the logic that **sends** replies out.
3. **Baileys gateway (Node)** — the WhatsApp connection. The **business owner links their own WhatsApp
   number by scanning a QR** (one-time), so the gateway **holds one session per business** (multi-tenant).
   It receives the customers' messages → forwards them to the backend webhook; backend → gateway
   `/send` → WhatsApp.

**External services (4):**
4. **Supabase** — Postgres for all **persisted** data **and** the per-business bot config (moved off disk);
   pgvector + Storage reserved for RAG in Phase 3.
5. **Gemini (`gemini-3.1-flash-lite`)** — writes bot replies and powers the bot-builder AI assistant.
6. **Secrets manager** — all API keys/secrets, out of `.env`.
7. **Redis** — fast in-memory **cache for live chat** (last ~10 messages + bot/human/closed status,
   auto-expiring). Shared across server instances; **not** the database.

## How a message flows

**0) Setup (one-time):** the **business owner** opens the dashboard and **scans a QR with their phone**,
which **links the business's own WhatsApp number** into the gateway. From then on the gateway is logged
in as that business. (Customers never scan anything — they just message the number.)

**A) Incoming lead (customer → bot):**
Customer WhatsApp → Baileys gateway (the business's session) → `POST` webhook → FastAPI identifies
*which business* by the session that received it → conversation engine routes to the lead-collection
flow → asks the next question / saves an **encrypted lead** in Supabase (scoped by `business_id`) →
reply text → gateway `/send` → WhatsApp → customer.

**B) Human handoff:**
Customer asks for a human (or the owner jumps in) → engine flips the conversation status to `human` in the
**Redis live-chat cache** → bot goes silent → owner sees the recent chat in the dashboard and replies (dashboard → backend → gateway
`/send`) → owner can flip back to `bot`.

**C) Owner builds & tests (no WhatsApp needed):**
Owner opens the React bot builder → describes the bot to the AI assistant → backend proxies to Gemini →
returns a flow/config → saved to Supabase config (per `business_id`) → owner uses **try-me test mode**
(same engine, a test conversation, no WhatsApp) → when happy, connects WhatsApp via **QR** and goes live.

## What's NEW vs the old system (the upgrades)
- 🗂️ **Config moves to Supabase** — no more per-user JSON files on disk.
- 🔌 **Gateway ↔ backend actually wired** — the missing link in the old code, with a **stable** webhook
  URL (kills ngrok, fixes B1/B3/B15).
- 🏢 **True multi-tenant** — one WhatsApp session per business; every query filtered by `business_id`.
- 🔒 **Auth enforced everywhere** + secrets pulled out of `.env` into a manager (fixes C1/C2/C3).
- 🧪 **Try-me test mode** is a first-class part of the build loop.
- ⚡ **Live chat in Redis** — last ~10 messages + status in a shared cache (replaces the old volatile
  in-memory state, fixes B11); only the lead data is persisted to Supabase.

## Text diagram (for the record)
```
     Business owner (browser)                 Customer (WhatsApp)
              | uses app                              | WhatsApp
              v                                       v
   [ React + Tailwind ] <--API--> [ FastAPI backend ] <--msgs--> [ Baileys gateway ]
    dashboard·builder·test          brain·API·flows               1 session / business
                                       |        |
                            data+config|        | AI
                                       v        v
                              [ Supabase ]   [ Gemini ]   [ Secrets ]   [ Redis ]
                              data + config  replies      all keys      live chat(10)
```

## Resolved (decisions 0005–0006)
- **Auth:** ✅ Google login via FastAPI + hand-wired RLS (0005).
- **Gateway session creds:** ✅ own envelope-encrypted `whatsapp_credentials` table (see data-model.md).
- **Live / shared state:** ✅ Redis cache for live chat (0006).
