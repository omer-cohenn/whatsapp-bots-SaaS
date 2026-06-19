### M5 try-me — summary table
| ID | Severity | Area | One-line |
|----|----------|------|----------|
| (req 1-6) | — | Verification | All six owner requirements PASS — engine is pure, LLM-free, tenant-scoped from session, no DB writes, input-bounded, no secret/PII logging. |
| T-01 | Low | Scope / UX | try-me runs the saved config incl. unpublished drafts (tenant-scoped, not a leak); confirm `is_published` is enforced on the future live bot loop. |
| T-02 | Low | Input validation | Oversized `step_index` in `state` passes the size check; engine handles it safely — optional edge clamping for defense-in-depth. |

---

## M5 lead memory (Bizz_up rebuild) — audit 2026-06-19

> Scope: the NEW `bizz_up` M5 lead-MEMORY layer that ties the pure engine to
> persistence — `backend\app\services\bot_runtime.py`, `backend\app\services\leads.py`,
> `backend\app\services\conversation_state.py`, `backend\app\services\abandoned_sweep.py`,
> `supabase\migrations\0006_abandoned_sweep.sql`, and `POST /api/bot/sim` in
> `backend\app\api\bot_builder.py` (+ its models). Cross-checked against
> `app\core\crypto.py` and `app\db\session.py`. Read-only audit; no product code
> was modified. Findings are for the main build loop.

**Owner's explicit requirements — verification result:**

- ✅ **PII at rest is ENCRYPTED; plaintext PII never written to Postgres.** Verified. `update_lead` and `complete_lead` (`leads.py:121-123,158-160`) encrypt `phone` (`crypto.encrypt_pii`), `contact_name` (`crypto.encrypt_pii`), and the WHOLE `collected` dict (`crypto.encrypt_answers` → `{"_": ciphertext}`) BEFORE the SQL runs; the bound params receive only ciphertext. `key_version` is stamped on every write (`crypto.CURRENT_KEY_VERSION`, `leads.py:98,142,180`). `create_lead` writes no PII columns at all — only `lead_name`, which is the engine's `active_flow` flow-key (an internal identifier matching `KEY_PATTERN`, `models/bot_builder.py:38`), not customer data. `flow_events` carries only structural signal (`flow_key`, `event`, `step_index`, `is_test`) — no PII (`leads.py:202-214`). The crypto module fails LOUD on decrypt error (no plaintext fallback, `crypto.py:70-101`).
- ✅ **Tenant isolation — Postgres via `tenant_connection`, business_id from SESSION only; every Redis key carries business_id.** Verified. `run_turn` opens exactly one `tenant_connection(pool, business_id)` for all writes (`bot_runtime.py:115`), which sets transaction-local `app.business_id` so RLS scopes the rows (`db/session.py:42-49`); every leads/flow_events write ALSO carries `business_id` in the INSERT/UPDATE (and the UPDATEs include `WHERE ... business_id = $2`, `leads.py:134,172`) so RLS `WITH CHECK` matches. The only caller, `POST /api/bot/sim`, takes `business_id = Depends(current_business)` from the server session (`bot_builder.py:111`); `BotSimRequest` has no `business_id` field and `extra="ignore"` (`models/bot_builder.py:333-336`). Every Redis key is `conv:{business_id}:{conversation_id}` and is re-checked by `_assert_owns` on every accessor (`conversation_state.py:45-56`), and the sweep lock key is global-but-harmless (holds no tenant data). Business A cannot reach business B's leads/events/state.
- ✅ **No secrets / PII in logs; errors generic.** Verified. `bot_runtime.py` has zero `log.*` calls on any data path. `conversation_state.py` / `leads.py` log nothing. `bot_sim` logs nothing. The sweep logs a count only (`abandoned_sweep.py:92`, `extra={"swept": swept}` — an integer) and its failure path is a bare `log.warning("abandoned sweep pass failed")` with no `str(e)`, no ids, no PII (`abandoned_sweep.py:95-97`). The SECURITY DEFINER function touches no PII columns (`0006:48,55` select only id/business_id/lead_name/last_step_index/is_test).
- ✅ **`/api/bot/sim` is session-gated, input-bounded, flags is_test.** Verified. The route is under the gated `/api` group and uses `current_business` (`bot_builder.py:108-113`). `BotSimRequest.message` is `min_length=1, max_length=2000`; `conversation_id` is `max_length=200` (`models/bot_builder.py:335-336`). `run_turn(..., is_test=True)` is hard-coded at the call site (`bot_builder.py:136`), and `is_test` threads into `create_lead`, `update_lead`-events, `complete_lead`-events, and every `log_event` — so sim rows are tagged and never pollute real funnel metrics. A null `conversation_id` mints a `sim:{uuid4}` id (`bot_builder.py:128`), keeping test conversations visibly distinct.
- ✅ **Bot stays SILENT while `chat_status == 'human'`.** Verified. `run_turn` reads the status FIRST and, if `STATUS_HUMAN`, returns `{"replies": [], ..., "silent": True}` WITHOUT loading state, settings, or running the engine (`bot_runtime.py:84-86`). The handoff itself sets status to `human` inside the same transaction (`bot_runtime.py:131-136`) so the NEXT turn is silent. (Belt-and-braces: the engine also emits only `_HANDED_OFF_NOTE` if its own state is `handed_off`, `bot_engine.py:104-106`, but the runtime guard means the engine isn't even consulted once human takes over.)
- ✅ **Abandoned sweep is single-runner (Redis-locked) and tenant-safe.** Verified. `sweep_loop` takes `SET lock:abandoned_sweep NX EX 30` each tick and skips the pass if it loses the lock (`abandoned_sweep.py:84-88`); the lock auto-expires so a crashed worker can't wedge it. The DB UPDATE is itself idempotent (already-abandoned rows no longer match `status='in_progress'`, `0006:46`). Cross-tenant access is delegated to one tightly-scoped `SECURITY DEFINER` function with `SET search_path = public, pg_temp`, `REVOKE ALL FROM PUBLIC`, `GRANT EXECUTE ... TO app_role` (`0006:33,66-67`); it keeps each row's OWN `business_id` on both the flipped lead and the inserted `abandoned` event (`0006:48,55`), so the funnel stays per-tenant. The loop never raises (`CancelledError` re-raised cleanly; all else swallowed, `abandoned_sweep.py:93-100`).

**Overall verdict: PASS — the M5 lead-memory layer meets all six owner requirements.**
No critical or medium issues. PII is encrypted with key_version on every write,
tenancy is enforced both by RLS context and explicit business_id predicates, the
bot is silent under human handoff, /sim is gated + bounded + is_test-flagged, and
the sweep is single-runner and tenant-correct. Findings below are LOW hardening
notes; none is a leak or isolation gap.

### LM-01 — `update_lead` accepts `phone`/`contact_name` by GENERIC key guessing — confirm engine key contract — LOW
- **Where:** `backend\app\services\leads.py:54-67,121-122` (`_PHONE_KEYS` / `_NAME_KEYS` heuristics) vs the engine, which stores answers under the step's owner-defined machine `key` (`bot_engine.py:151-152`).
- **Why dangerous (mild):** If an owner names a phone step with a key NOT in `_PHONE_KEYS` (e.g. Hebrew `"טלפון"`, or `"contact_phone"`), the value still gets encrypted inside the `answers` blob (so it is NOT exposed in plaintext — no leak), but the dedicated encrypted `phone`/`contact_name` columns stay NULL. Downstream features that read those columns (dashboard, dedup, the future `customer_phone_hash`) would miss the data. This is a data-completeness/correctness gap, not a confidentiality gap. Note also `customer_phone_hash` (the planned deterministic lookup, `crypto.phone_hash`) is not populated on this write path — needs verification that lead dedup/lookup is wired elsewhere.
- **Fix direction:** Derive the PII column mapping from the step `type` (`phone`/`email`) in the validated config rather than guessing by key name, so any owner-named phone step lands in the right column regardless of language. Confirm whether `customer_phone_hash` should be stamped here.

### LM-02 — `complete_lead` may skip the final answer/PII write when the flow completes in the same turn it started — LOW
- **Where:** `backend\app\services\bot_runtime.py:107-129` + `leads.py:200-221`.
- **Why dangerous (mild):** When a flow ENTERS and emits `lead_completed` in the SAME turn (a 1-step flow), `entered_flow` runs `_start_lead` (creates the row, no answers written), then `_complete_lead` is called with `active_lead_id` still being the PRE-turn value (`None`) — so the `if active_lead_id is not None` guard in `complete_lead` (`leads.py:215`) is FALSE and `complete_lead` does NOT run; only a `completed` flow_event with `lead_id=None` is logged. Result: the newly created lead row stays `in_progress` with NULL answers, and the completion event isn't tied to the row. The runtime passes `active_lead_id` (pre-turn), not `new_lead_id` (the just-created id), into `_complete_lead` (`bot_runtime.py:127-128`). This is a data-loss/funnel-accuracy bug for single-step flows, not a security leak (no plaintext is written anywhere). The docstring at `leads.py:208-213` acknowledges the case but the code doesn't actually persist the answers for it.
- **Fix direction:** Pass `new_lead_id` (the id from `_start_lead`) into `_complete_lead`, and have `_complete_lead` write the encrypted answers even when the row was created earlier in the same transaction. Verify multi-step flows are unaffected (they are: `active_lead_id` is set from a prior turn).

### LM-03 — Redis `get_status` value comparison assumes `str`; confirm `decode_responses` on the client — LOW (needs verification)
- **Where:** `backend\app\services\conversation_state.py:113-122` returns `redis.hget(...)` directly and `bot_runtime.py:84-85` compares it `== STATUS_HUMAN` (a `str`); same assumption for stored JSON in `get_state` (`json.loads(raw)`).
- **Why dangerous (mild):** If the shared `aioredis` client was created WITHOUT `decode_responses=True`, `hget` returns `bytes`, so `b"human" == "human"` is False — the human-handoff silence guard would silently fail and the bot would talk over a live agent. This is a real product-rule failure if the client config is wrong, but it depends on app-level client setup outside the audited files. JSON state decoding tolerates bytes (`json.loads` accepts bytes), so only the status comparison is brittle.
- **Fix direction:** Confirm the Redis client uses `decode_responses=True` (or normalize bytes→str inside `get_status`). Add a test asserting handoff produces `silent=True` on the next turn end-to-end through the real client.

### M5 lead memory — summary table
| ID | Severity | Area | One-line |
|----|----------|------|----------|
| (req 1-6) | — | Verification | All six owner requirements PASS — PII encrypted w/ key_version, RLS+explicit business_id on every write, Redis keys business-prefixed, bot silent under human handoff, /sim session-gated+bounded+is_test, sweep single-runner + tenant-correct SECURITY DEFINER. |
| LM-01 | Low | Crypto / data | `phone`/`contact_name` columns filled by key-name guessing; an owner-named (e.g. Hebrew) phone key lands only in the encrypted answers blob (no leak) but leaves the dedicated columns NULL — map by step `type` instead; confirm `customer_phone_hash` wiring. |
| LM-02 | Low | Data integrity | Single-turn flow (enter+complete same turn) passes pre-turn `active_lead_id=None` to `_complete_lead`, so answers aren't finalized and the row stays in_progress — pass `new_lead_id` through. Not a leak. |
| LM-03 | Low | Runtime config (verify) | Human-handoff silence relies on `hget` returning `str`; if the Redis client lacks `decode_responses=True` the `== 'human'` check fails and the bot talks over a human — verify client config + add an end-to-end test. |
