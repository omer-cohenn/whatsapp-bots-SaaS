# 0004 — MVP scope (Phase 1)

- **Date:** 2026-06-16
- **Status:** accepted

## Context
The old system already does four things (lead collection, booking, RAG, human handoff), so Omer's
instinct was "rebuild all of it." But the real MVP cost is `4 features × (clean rebuild + multi-tenant
+ React UI + security + AWS deploy)` — doing it all before anyone uses it risks never shipping. First
target customers: an **insurance agency** and a **service pro** (barber/beauty).

## Decision
**Phase 1 (the MVP) has two sides** — the customer experience *and* the owner's tooling to create it.

**A. What the bot does for end-customers (on WhatsApp):**
- **Lead collection** + **Human handoff**.
- (Booking → **Phase 2**, incl. fixing the "chat flow doesn't actually book" bug B7. RAG → **Phase 3**.)

**B. What the business owner needs to create & run the bot (the SaaS app) — ALL required, because no
bot exists without them:**
- 📱 Connect WhatsApp via the **Baileys QR gateway**.
- 🤖 **AI-assisted bot builder** — build the system prompt + menus/flows with an AI assistant (the old
  `botbuilder` + `/api/ai/*` endpoints). **Without this there is no MVP — it's how a bot gets created.**
- 🧪 **"Try-me" test mode** — chat with your own bot to test it before/while it's live (like the old
  test-chat tool).
- 🖥️ **Minimal dashboard** — log in, read leads, see conversations, flip a chat bot↔human.

Multi-tenant throughout.

### Baked into Phase 1 (not optional — foundations everything depends on)
- Real **login/auth** (fixes security C2).
- Strict **`business_id` isolation** on every query (fixes C2/C3/C4).
- **Secrets** pulled out of `.env`, rotated, into a secret manager (fixes C1).
- One real **end-to-end inbound test** on the Baileys gateway (the unverified receive path, decision 0001).

### Why the owner tooling counts as "minimum"
The product has a **build → test → go-live → collect** loop. The **AI bot builder** (create) and
**try-me test mode** (trust) are not extra features — they are the only way an owner produces a working
bot at all, so they are as foundational as login. We keep the *customer-facing* bot abilities minimal
(leads + handoff); the *owner-facing* tooling is necessarily included.

## Why
Both first customers need **lead capture**; **handoff** is a cheap, natural companion. **Booking** is
more complex (and currently buggy) and only the service pro needs it first. **RAG** needs content
upload + careful grounding. Sequencing by customer need = shortest path to one real business going live.

## Consequences
- Build order: **leads + handoff → booking → RAG**.
- "Human responses" is interpreted as **human handoff** (a person takes over the chat) — *to confirm
  with Omer.*
- Keeps time-to-first-live-business short; later phases get real user feedback to guide them.
