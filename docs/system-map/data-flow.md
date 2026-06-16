# Data Flow — the journey of one message

> Follows one WhatsApp message all the way through the system, then details the
> lead-collection and booking flows end to end. Assembled from the backend and
> whatsapp-gateway scanner reports. Last updated 2026-06-15.

Read [`architecture.md`](architecture.md) first if you want the component map.

A quick note before we start: the routing and the 4 paths are **not** done inside LangGraph.
LangGraph (`bot/graph.py`) is only a tiny linear pipeline used for the *default LLM fallback*.
All path selection is procedural code inside the webhook handler in `main.py`. This is a
common point of confusion, so it is called out again where it matters below.

---

## Part 1 — One inbound message, start to finish

```
 Customer types in WhatsApp
        |
        v
 Meta WhatsApp Cloud API
        |
        v  (HTTPS, public URL via ngrok)
 POST /webhook   (main.py:325)
        |
        |  parse Meta envelope: entry[0].changes[0].value.messages[0]  (main.py:329-333)
        |  -> phone, text          (bad shape -> {"status":"ignored"})
        |
        |  business_id = _business_id_from_config()  ==  flat system_prompt.json "client_001"
        |  (main.py:338 — SAME business for ALL inbound traffic; see note below)
        v
   +----------------------------------------------------------+
   |              ROUTER (procedural, in main.py)             |
   |  order of checks:                                        |
   |   1. status == "closed"  -> reset to bot, resend menu    |  (main.py:343-347)
   |   2. status == "human"   -> stay silent, return ignored  |  (main.py:349-351)
   |   3. escalation keyword  -> PATH D (human handoff)       |  (main.py:361-368)
   |   4. menu keyword        -> show main menu               |
   |   5. active flow step    -> continue current flow        |
   |   6. flow trigger word   -> start a flow (PATH A/B/C)    |
   |   7. none of the above   -> PATH (default LLM via graph) |  (main.py:394)
   +----------------------------------------------------------+
        |
        v
   one of the 4 paths runs (see Part 2)
        |
        v
   reply text produced
        |
        v
   wapy_client.send_message(phone, text)   (PyWa -> Meta Graph API)
        |
        v
   Meta WhatsApp Cloud API  -->  Customer's WhatsApp
```

Along the way the backend also:
- bumps `last_msg_at` for the conversation on every inbound message (`update_last_msg_at`),
- keeps a short in-RAM chat history per phone (capped at 10 turns, `bot/memory.py`),
- stores conversation status (`bot`/`human`/`closed`) in the `conversations` table plus an
  in-RAM cache (`bot/chat_status.py`).

> **Important caveat — single-tenant inbound.** Every inbound message resolves to the one
> business found in the flat `client_config/system_prompt.json` (`business_id = "client_001"`),
> regardless of who the message was for. Dashboards key on the logged-in user's **email**
> instead. So live WhatsApp leads/conversations are written under `client_001` and **do not
> appear** in per-user dashboards. Whether multi-tenant inbound is intended is
> *needs verification*. (Source: backend-map §6, whatsapp-gateway §5.)

> **Where LangGraph fits.** Only step 7 (the default LLM fallback) runs through LangGraph:
> `load_memory → call_gemini → save_memory → send_reply` (`graph.py:61-72`), compiled once at
> import. It has no conditional edges — it is a straight line. Steps 1–6 never touch it.

---

## Part 2 — The 4 paths in detail

### Path A — Lead collection (→ encrypted lead)
1. A message matches a flow's `trigger` keyword (`find_flow_for_trigger`, `flow_engine.py:109`).
2. `start_flow` sets in-memory state and asks step 0 (`flow_engine.py:154`).
3. Each reply runs `handle_step` (`flow_engine.py:163`): **validate** the answer → **normalize**
   it → store it in `collected` → ask the next step.
4. On the final step `_on_flow_complete` (`flow_engine.py:241`) runs:
   - `save_lead` — Fernet-**encrypts** `phone`, `flow_id`, and the whole answer blob, then
     inserts a `leads` row (`leads_db.py:144-156`);
   - `log_flow_event("completed")`;
   - `set_status(phone, "closed")` — the conversation auto-closes.

```
 trigger word -> start_flow -> [step 0] -> validate/normalize/store -> [step 1] -> ... 
   -> final step -> save_lead (ENCRYPTED) + log_flow_event + status=closed
```

### Path B — Appointment booking
There are **two different mechanisms**, and they behave differently:

**B1 — `booking_link` flow (the real calendar).**
```
 customer triggers booking_link flow
   -> start_flow returns a one-shot URL: {BASE_URL}/book/{slug}   (flow_engine.py:131-138)
   -> (gemini.py also injects this link into the prompt so the LLM can offer it)
   -> customer opens /book/{slug}            -> book_client.html
   -> GET /api/book/{slug}/settings          -> service name + working days
   -> GET /api/book/{slug}/slots?date=...    -> free slots = settings minus already-booked
   -> POST /api/book/{slug} {date,time,name,phone,...}
        -> create_booking  (double-book guard: 409 if taken)  -> bookings row created
```
This path creates a real `bookings` row and respects availability.

**B2 — conversational `book_appointment` step flow (NOT a real booking).**
This is just a normal lead-collection flow (Path A). It collects a free-text "preferred time"
and files a lead with the message "a rep will get back to you." It **never** creates a
`bookings` row and **never** checks availability.

> **Bug.** Customers who finish the chat booking flow (B2) are **not actually booked**. Only
> the booking-link URL flow (B1) puts an appointment on the calendar. (backend-map flag #10.)

### Path C — RAG answering (grounded knowledge)
Two entry points, with different strictness:
- **Default LLM (soft grounding):** the model is *told* to always use the
  `search_knowledge_base` tool for configured use-cases, but it is only an instruction.
- **Knowledge-menu flow (hard grounding / "zero creativity"):** `handle_step` injects a
  `system_override` (`flow_engine.py:188-207`) that forces the model to call
  `search_knowledge_base` before every answer, answer **only** from the retrieved text, and —
  if nothing is found — reply exactly `אין לי מידע על כך בבסיס הידע שלי.` ("I have no
  information on that in my knowledge base"). The same override backs `POST /api/rag/chat`.

```
 question -> search_knowledge_base tool
          -> vectorstore.search(query, business_id, k=4)   (cosine, top-4 chunks)
          -> chunks joined with "---"  (or "No relevant information found")
          -> Gemini answers grounded in those chunks
```
Retrieval is always scoped by `business_id` (`brain_chunks WHERE business_id=%s`).

### Path D — Human handoff
```
 escalation keyword (e.g. "נציג","human","agent")  (flow_engine.py:91)
   -> set_status(phone, "human")
   -> send human_escalation_message
   -> next inbound message hits the guard: status=="human" -> bot stays SILENT
   -> remains silent until an admin flips status back via
      POST /api/conversations/{phone_enc}/status
```

---

## Part 3 — Conversation status machine (bot / human / closed)

Status lives in the `conversations` table plus an in-RAM cache. Transitions:

```
            inbound + escalation keyword
   [bot] ---------------------------------> [human]
     ^  \                                      |
     |   \ lead flow completed                 | admin override
     |    \---------------------> [closed]     | (any -> any)
     |                               |         |
     |   inbound (re-engage:         |         |
     |   reset to bot, resend menu)  |         |
     +-------------------------------+         |
     |                                         |
     +-----------<-----------------------------+
        admin override sets status back to bot
```

Auto-close happens in two ways (only):
1. **Lead completed** → `set_status(phone, "closed")` (`flow_engine.py:247`).
2. **60 minutes idle** → the `_auto_close_loop` runs every 60s and closes rows where
   `chat_status='bot' AND last_msg_at < now - INTERVAL` (`main.py:54-63`, default 60 min).

> A "satisfied customer" auto-close was expected by the design but is **not implemented** —
> there is no sentiment detection anywhere (backend-map §3). *needs verification* if expected.

> Also note: `get/set_chat_status`, `update_last_msg_at`, and `close_stale_conversations` key
> on **phone only** (the table's primary key is `phone`, not `(business_id, phone)`), so two
> businesses sharing a customer phone number would collide. (security flag, see
> [`../security-issues.md`](../security-issues.md).)

---

## Part 4 — How a knowledge document becomes answerable (RAG ingestion)

This is the offline counterpart to Path C. The owner uploads a file or a URL in the bot
builder:

```
 FILE upload  (POST /api/rag/upload)
   -> store original in Supabase Storage (rag-files bucket)
   -> _extract_text (txt/md/pdf/docx/xlsx)      [PPT/PPTX NOT supported — see bugs.md]
   -> chunk (500 chars / 50 overlap)
   -> embed (sentence-transformers, 384-dim)
   -> INSERT into brain_chunks (business_id, text, source, embedding)   [old chunks for that
                                                                          source deleted first]
   -> record a rag_sources row (name + chunk_count)

 URL scrape  (POST /api/rag/add-url)
   -> crawl4ai fetches the page (inline crawler, in a thread)
   -> cache text in rag_sources.content -> chunk -> embed -> brain_chunks   (same as above)
```

The live RAG pipeline (`rag_manager.py` + `bot/brain/`) never touches the legacy `rag_data/`
folder. That folder and its scripts are **dead and broken** (see [`../bugs.md`](../bugs.md)).

---

## Quick reference — the message-handling files

| Concern | File |
|---------|------|
| Webhook + router + the 4 paths | `last_bo/main.py` (`receive_message`) |
| Flow orchestration (steps, triggers, escalation, RAG override) | `bot/flow_engine.py` |
| Default-LLM pipeline (LangGraph) | `bot/graph.py` |
| Gemini call + system prompt + tool round-trip | `bot/gemini.py` |
| In-RAM chat history | `bot/memory.py` |
| In-RAM flow state | `bot/flow_state.py` |
| Conversation status (bot/human/closed) | `bot/chat_status.py` + `bot/leads_db.py` |
| Encryption of lead PII | `bot/crypto.py` |
| Database access | `bot/leads_db.py` |
| RAG ingestion + retrieval | `bot/rag_manager.py`, `bot/brain/vectorstore.py`, `bot/brain/tool.py` |
| Outbound send (live path) | `wapy_client/client.py` (PyWa → Meta) |
