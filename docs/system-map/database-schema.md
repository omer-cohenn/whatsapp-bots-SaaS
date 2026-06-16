# Database Schema — Supabase (PostgreSQL + pgvector)

> The tables behind the system, in plain English: what each one is for, its columns, how they
> relate, and which ones carry the `business_id` tenant key. Derived from the backend scanner
> report (`backend-map.md`) — no raw SQL file was present, so columns are read from the schema
> defined in `bot/leads_db.py`, `bot/brain/vectorstore.py`, and `bot/rag_manager.py`. Gaps are
> marked *needs verification*. Last updated 2026-06-15.

The prompt asked for six core tables (`users`, `leads`, `flow_events`, `conversations`,
`booking_settings`, `bookings`). Two more tables exist and are included for completeness:
`brain_chunks` and `rag_sources` (the RAG/knowledge tables). A ninth table, `bot_settings`,
belongs to a dead Airtable module and is noted at the end.

---

## The `business_id` tenant key — read this first

Most tables are scoped per business by a `business_id` column. **What that value is depends
on the entry point**, and this inconsistency is the source of several bugs:

- **Dashboard / API (authenticated):** `business_id` = the logged-in user's **email**
  (`main.py:_business_id`).
- **Inbound WhatsApp webhook:** `business_id` = the value in the flat
  `client_config/system_prompt.json` (literally `"client_001"`), the **same for all
  traffic** (`main.py:338`).

So data created by the live WhatsApp channel and data shown in dashboards can end up under
**different** `business_id` values. See [`data-flow.md`](data-flow.md) and
[`../security-issues.md`](../security-issues.md).

Tenant-scoping status at a glance:

| Table | Carries `business_id`? | Properly isolated on all queries? |
|-------|------------------------|-----------------------------------|
| `users` | No (global) | N/A |
| `leads` | Yes | Yes |
| `flow_events` | Yes | Reads yes; the admin migrate UPDATE has **no WHERE** (bug) |
| `conversations` | Yes | **Partial** — hot-path queries key on `phone` only |
| `booking_settings` | Yes (it is the PK) | Yes |
| `bookings` | Yes | **Partial** — `update_booking_status` filters by `id` only (IDOR) |
| `brain_chunks` | Yes | Yes |
| `rag_sources` | Yes | Yes |

---

## Relationships (text diagram)

```
   users (google_id, email)                 [global; identifies the owner]
     |
     | email is used AS the business_id for dashboard/API calls
     v
   business_id  ---------------------------------------------------------+
     |              |              |                |          |         |
     v              v              v                v          v         v
   leads      flow_events    conversations   booking_settings bookings  brain_chunks / rag_sources
 (per lead)  (per flow event) (per phone)    (1 per business) (per appt) (per knowledge chunk/source)

   Links are by shared business_id (and phone for conversations/flow_events/leads).
   There are NO declared SQL foreign keys in the scanned code — relationships are by
   convention only. (needs verification if FKs exist in Supabase itself.)
```

Note: `phone` appears in `leads` (encrypted), `flow_events` (plaintext), and `conversations`
(encrypted token used as the primary key). It loosely ties a customer's records together but
is not a formal key relationship.

---

## Table-by-table

### `users` — who owns each account
The Google-login identity for business owners. Global (no tenant key).

| Column | Type | Purpose |
|--------|------|---------|
| `google_id` | text, **PK** | Google account id |
| `email` | text | Owner's email — **also used as `business_id` elsewhere** |
| `name` | text | Display name |
| `picture` | text | Avatar URL |
| `created_at` | timestamp | Row creation |

Defined: `leads_db.py:36-42`. Tenant key: N/A (global).

---

### `leads` — collected customer submissions (ENCRYPTED)
Each completed lead-collection flow writes one row. PII is Fernet-encrypted at rest.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | (serial/uuid) **PK** | Row id |
| `business_id` | text | Tenant key |
| `flow_id` | text (**encrypted**) | Which flow produced the lead |
| `phone` | text (**encrypted**) | Customer phone |
| `data` | jsonb | The answers, stored as an encrypted blob `{"_": "<fernet>"}` |
| `submitted_at` | timestamp | When completed |

Defined: `leads_db.py:43-51`. Written by `save_lead` (`leads_db.py:144-156`); read by
`get_leads` (handles encrypted, legacy-plaintext-dict, and raw forms). Tenant key:
**Yes** — save/get/delete/stats all filter by `business_id`.

---

### `flow_events` — analytics trail of flow activity
Logs events such as a flow starting or completing; powers "abandoned"/funnel stats.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | (serial) **PK** | Row id |
| `business_id` | text | Tenant key |
| `flow_id` | text | Which flow |
| `phone` | text (**plaintext**) | Customer phone (NOT encrypted — see security M5) |
| `event` | text | e.g. `started`, `completed` |
| `step_index` | int | How far the customer got |
| `created_at` | timestamp | Event time |

Defined: `leads_db.py:52-61`. Tenant key: **Yes for reads.** ⚠️ But the unauthenticated
`/admin/migrate-leads` runs `UPDATE flow_events SET business_id=%s` with **no WHERE clause**
(`main.py:449`) — it rewrites every tenant's rows (see [`../bugs.md`](../bugs.md) and
security C3).

---

### `conversations` — the bot/human/closed state machine
One row per customer phone, tracking the current conversation status.

| Column | Type | Purpose |
|--------|------|---------|
| `phone` | text, **PK** | Customer phone (this is the primary key — see caveat) |
| `business_id` | text | Tenant key |
| `chat_status` | text (default `bot`) | `bot` / `human` / `closed` |
| `last_msg_at` | timestamp | Last inbound time; drives the 60-min auto-close |
| `updated_at` | timestamp | Row update time |

Defined: `leads_db.py:62-69`. Tenant key: **Partial.** `get_conversations_by_status` filters
by `business_id`, but `get/set_chat_status`, `update_last_msg_at`, and
`close_stale_conversations` key on **`phone` only** — the PK is `phone`, not
`(business_id, phone)`, so two businesses sharing a customer phone collide. The in-RAM
`chat_status._cache` is also keyed by phone alone. (security flag #2.)

---

### `booking_settings` — each business's availability rules
One row per business defining the bookable calendar.

| Column | Type | Purpose |
|--------|------|---------|
| `business_id` | text, **PK** | Tenant key (and primary key) |
| `service_name` | text | Service shown on the booking page |
| `working_days` | jsonb | Which weekdays are bookable |
| `working_hours` | jsonb | Start/end hours |
| `slot_duration` | int | Minutes per slot |
| `updated_at` | timestamp | Row update time |

Defined: `leads_db.py:70-77`. Free slots are computed from this minus already-booked times
(`_compute_slots`). Tenant key: **Yes** (it is the PK). Note: `get/save_booking_settings`
auto-create defaults for any `business_id`, which is reachable from the public, unauthenticated
booking endpoints (security M4).

---

### `bookings` — actual appointments
One row per real appointment created through the booking-link page.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | uuid, **PK** | Booking id |
| `business_id` | text | Tenant key |
| `client_name` | text (**plaintext**) | Customer name |
| `client_email` | text (**plaintext**) | Customer email |
| `client_phone` | text (**plaintext**) | Customer phone |
| `date` | date | Appointment date |
| `time` | text/time | Appointment time |
| `status` | text | e.g. pending / confirmed / cancelled |
| `notes` | text | Free-text notes |
| `created_at` | timestamp | Row creation |

Defined: `leads_db.py:78-90`. Created by `create_booking` (`leads_db.py:448-458`) with a
double-booking guard (returns 409). Tenant key: **Partial.** Reads/slots filter by
`business_id`, but ⚠️ `update_booking_status` (`leads_db.py:461-465`, used by
`PATCH /api/bookings/{id}`) filters by `id` **only** → any logged-in user can change any
business's booking by guessing UUIDs (IDOR, security C4). Also note client PII here is
**plaintext** while leads are encrypted (security M5).

---

### `brain_chunks` — the RAG vector store
The embedded text chunks the bot searches to answer knowledge questions.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | (serial) **PK** | Chunk id |
| `business_id` | text (default `default`) | Tenant key |
| `text` | text | The chunk of source text |
| `source` | text | Where the chunk came from (file name / URL) |
| `embedding` | `VECTOR(384)` | sentence-transformers embedding |

Defined: `vectorstore.py:41-47`, with index `brain_chunks_biz_idx`. Searched with cosine
(`<=>`) scoped by `business_id` (top-4). Tenant key: **Yes** — search/build/delete/count all
filter by `business_id`.

---

### `rag_sources` — catalogue of knowledge sources
One row per uploaded file or scraped URL, tracking how many chunks it produced.

| Column | Type | Purpose |
|--------|------|---------|
| `id` | (serial) **PK** | Source id |
| `business_id` | text | Tenant key |
| `type` | text | `file` or `url` |
| `name` | text | File name / URL |
| `content` | text | Cached extracted/scraped text |
| `chunk_count` | int | Number of chunks produced |
| `created_at` | timestamp | Row creation |

Defined: `rag_manager.py:53-61`, with index `rag_sources_biz_idx`. Tenant key: **Yes**.

---

## Legacy / not part of the live schema

### `bot_settings` — dead Airtable key/value table
A global `key`(PK)/`value` table defined in `client_config/data_manager.py:52-58`. That whole
Airtable module is **imported nowhere** in the runtime path; leads persist to Postgres, not
Airtable. Listed here only so it is not mistaken for a live table. Tenant key: **No** (global).

---

## Gaps / needs verification

- **No raw SQL/migration file** was found by the scanner — all column lists above are read
  from the Python `CREATE TABLE` strings. Exact column types (serial vs uuid, text vs
  timestamptz) should be confirmed against the live Supabase schema.
- **Foreign keys / RLS policies:** none observed in the scanned code. Whether Supabase itself
  enforces FKs or Row-Level Security is *needs verification* (note: the service-role key in
  `.env` bypasses RLS regardless — see security C1).
- **`conversations.phone` as PK** vs a composite `(business_id, phone)` — confirm the intended
  key before fixing the tenant-collision bug.
