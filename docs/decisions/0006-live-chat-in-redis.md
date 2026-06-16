# 0006 — Live chat in Redis (ephemeral); persist only the lead data

- **Date:** 2026-06-16
- **Status:** accepted

## Context
The first data model put chat messages + conversation state in Postgres. Omer wants the **live chat to run in the
server cache (RAM), not the database** — keeping only the **last ~10 messages**, discarding the rest — but still be
able to **follow up with customers who abandoned** the questionnaire mid-way.

## Decision
1. **Live chat → Redis** (a shared in-memory cache): per `(business_id, customer_phone_hash)`, holds the last ~10
   messages + `bot/human/closed` status, with a **~60-min TTL** (= auto-close). Chosen over plain process-RAM
   because at scale (multiple AWS instances) process memory isn't shared and would break handoff/continuity.
2. **Drop** the persistent `messages`, `conversations`, and `conversation_events` tables.
3. **Keep the lead data:** a `leads` row is created at questionnaire **start** (`in_progress`), updated as answers
   arrive, then marked `new` (completed) or `abandoned` (by a 60-min sweep). It holds the phone + partial answers
   (encrypted) → this is the owner's **abandoned-lead follow-up list**.
4. `flow_events` links to `lead_id` and powers the funnel (started / completed / abandoned).

## Rule of thumb
**Keep the lead data, throw away the chatter.** Persist what's actionable (contact + answers + funnel); let the raw
conversation live briefly in cache and expire.

## Trade-offs / notes
- **Redis has no RLS** → tenant isolation for the cache is enforced in the **app layer** (`business_id` in every key,
  re-checked on access), plus private network + auth + TLS.
- Resolves old bug **B11** (volatile process-local in-memory state).
- **Net tables: 12 → 9 + Redis.**

## Consequences
- Redis is now required in dev **and** prod (the `devops_aws` agent will provision it).
- "Abandoned" detection runs as a periodic sweep over `in_progress` leads idle > 60 min.
