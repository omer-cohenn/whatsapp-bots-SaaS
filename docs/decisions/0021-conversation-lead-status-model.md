# 0021 — Conversation & Lead status model (unified state machine + close reasons + unread badge)

> Status: **approved, building** · Date: 2026-06-26 · Owner: Omer
> Reconciles the existing (M5/M8/M9/M10/M14) status logic into one clear model, fixes the
> human-mode abandon-clock bug, adds an explicit `close_reason`, and adds a WhatsApp-style
> unread badge on the conversations tab. **NO commit until Omer approves.**

## The story (plain language)
A customer messages the business. No open conversation → the bot sends a **greeting + main menu**.
The customer picks a flow; the bot **asks questions and answers** (state "bot"). If they ask for a
person → **human agent** and the bot goes silent. A conversation closes one of three ways, each with
a clear label: the customer **completed** all details ("ליד הושלם"), or **vanished for 60 min**
("ליד ננטש"), or the business **finished handling it** manually ("מענה הושלם"). After it closes, the
customer's next message opens a brand-new conversation (greeting again). Meanwhile the owner sees a
**WhatsApp-style unread badge** over the "שיחות" tab counting messages they haven't read yet.

## Decisions locked
1. **`close_reason` = new column** on `leads`: `completed` | `abandoned` | `answered` | null. Separate
   from the owner OUTCOME (`deal`/`closed`) so "why it closed" ≠ "what the owner marked".
2. **Keep `waiting` + `human` internally** (no risky M8/M9 refactor); UI shows one "נציג אנושי" label.
   The visibility Omer wanted comes from the new **unread badge**, not from merging the states.
3. **Unread badge** (WhatsApp-style): a per-conversation unread counter in Redis, summed for the tab.

## Existing vs new (grounded)
| Layer | Today | Change |
|---|---|---|
| Conversation status (Redis) | `bot`/`waiting`/`human`/`closed` (`conversation_state.py:49`) | unchanged + auto-close on abandon |
| Lead status (Postgres) | `in_progress`/`new`/`abandoned`/`deal`/`closed` (`leads/_common.py:19`) | + `close_reason` column |
| Abandon clock | `last_activity_at`, 60 min (`abandoned_sweep.py`, `ABANDONED_AFTER_MINUTES=60`) | resets on ANY inbound (incl. human) |
| Auto-close | sweep flips the lead only | on abandon, ALSO close the Redis conversation |
| Unread | — | per-conversation counter in Redis + tab badge |

## The unified state machine
| Conversation state | Who talks | Enter | Exit |
|---|---|---|---|
| no conversation | — | new customer / prior closed | inbound → greeting+menu → `bot` |
| **bot** | the bot | after greeting / mid-flow | complete→`closed`; ask human→`human`(via `waiting`); 60-min silence→abandon→`closed` |
| **human** (`waiting`→`human`) | a person | customer asked / owner took over | owner closes ("מענה הושלם")→`closed`; 60-min silence→abandon→`closed` |
| **closed** | — | one of the 3 closes | inbound → reset → no conversation |

### The 3 close reasons (stamped on the lead as `close_reason`)
| Reason (he) | `close_reason` | lead status | When |
|---|---|---|---|
| ליד הושלם | `completed` | `new` | all flow details collected (`bot_runtime.py:253` already closes the chat) |
| ליד ננטש | `abandoned` | `abandoned` | 60 min with no customer message (bot or human) |
| מענה הושלם | `answered` | `closed` | business closed it manually after human handling |

## Contract (API / data)
| What | Type | Guard |
|---|---|---|
| `leads.close_reason` | new column `completed`/`abandoned`/`answered`/null | additive migration; existing RLS covers it |
| `sweep_abandoned_leads` | existing SD fn (0006) | also stamps `close_reason='abandoned'` + returns conversation_ids to close |
| unread counter | Redis per-conversation; reset on owner open | tenant-scoped key (mirrors `live_chat.py`) |
| `GET /api/conversations` (+ `/api/leads`) | existing | return `close_reason`; conversations return unread total |
| open-conversation read / new mark-read | existing GET or new `POST .../read` | resets that conversation's unread to 0 (tenant-scoped) |
| `PATCH /api/leads/{id}/status` | existing | "מענה הושלם" path stamps `close_reason='answered'` |

## The 12 goals
1. Canonical state-machine doc (this file) — single source of truth.
2. **Migration**: `leads.close_reason` column (+ sweep fn stamps `abandoned`, returns conversation_ids).
3. **Clock fix**: every inbound (incl. `waiting`/`human`) bumps the active lead's `last_activity_at`.
4. **Auto-close on abandon**: when the sweep abandons a lead, also close its Redis conversation.
5. **Completed**: stamp `close_reason='completed'` on `lead_completed` (chat already closes).
6. **Answered**: owner manual close after human → `close_reason='answered'` + lead `closed` + chat `closed`.
7. **No-conversation→greeting**: verify + document the existing `closed`→reset→greeting path (+ brand-new number).
8. waiting/human kept internal; UI shows one label (per decision 2).
9. **Frontend**: clear Hebrew status + close-reason labels on conversation/lead cards.
10. **QA + security**: a test per transition + the human-mode clock fix + regress M8/M9/M10/M14 + isolation.
11. **Unread counter**: Redis per-conversation counter (+1 per customer inbound, reset on owner open); summed in an API field.
12. **Unread badge**: WhatsApp-green badge with white count over the "שיחות" tab; hidden when zero.

## Agents & workflow
```
A (data) ──► B (backend) ──► C (frontend)  ┐
                       └────────────────────► D (QA + security, read-only)
                                                │
                                                ▼
                                 main loop verifies (stack + tests) until green → (commit ONLY after Omer approves)
```
- **A — bizzup-data-builder**: Goal 2 (column + sweep fn). Returns column/fn names + applied proof.
- **B — bizzup-backend-builder**: Goals 3,4,5,6,7,8,11. Returns the API contract.
- **C — bizzup-frontend-builder**: Goals 9,12. Consumes B's contract.
- **D — bizzup-test-runner** (read-only): Goal 10 + regression + isolation. Runs ∥ to C.
Serial because B needs A's column; C and D need B's contract; D only reads → parallel with C.

## Security & isolation
- Every query stays filtered by `business_id` (RLS); the sweep only via the existing SECURITY DEFINER.
- `close_reason` is structural (no PII); funnel stays PII-free; unread counter keyed per tenant+conversation.
- No secrets, no logging of message content / phone numbers.

## Deferred
- Engine-level cap enforcement is unrelated (see 0020). This milestone is status clarity + the badge.
- A hard merge of `waiting`→`human` is NOT done (kept internal per decision 2).
