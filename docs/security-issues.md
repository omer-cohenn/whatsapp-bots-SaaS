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

---

## M7 dashboard / back-office (Bizz_up rebuild) — audit 2026-06-19

> Scope: the NEW M7 READ / back-office surface — `backend\app\api\dashboard.py`,
> `backend\app\models\dashboard.py`, the READ helpers in `backend\app\services\leads.py`
> (`list_leads`, `_decrypt_lead_row`, `funnel_stats`, `_period_clause`), the listing/reply
> helpers in `backend\app\services\conversation_state.py` (`list_conversations`,
> `append_reply`, `_register`, `_index_key`), `set_published` in
> `backend\app\services\bot_settings.py`, and the mount in `backend\app\api\me.py`.
> Cross-checked against `app\core\deps.py`, `app\db\session.py`, `app\core\crypto.py`,
> `app\core\logging.py`, and `supabase\migrations\0004_rls_policies_grants.sql`.
> Read-only audit; no product code was modified.

**Owner's explicit requirements — verification result:**

- ✅ **TENANT ISOLATION on every READ — business_id from session only; Postgres via `tenant_connection` (RLS); Redis strictly business-scoped.** Verified. Every one of the six routes takes `business_id = Depends(current_business)` (`dashboard.py:65,103,121,147,170,187`), which resolves only from the server-side session (`deps.py:50-54`); no model exposes a `business_id` field (`models/dashboard.py`), and none of the endpoints read a tenant id from path/query/body. The two Postgres readers (`get_leads`→`list_leads`, `get_dashboard`→`funnel_stats`) run inside `tenant_connection(pool, business_id)` (`dashboard.py:79,111`), which sets transaction-local `app.business_id` so RLS scopes the rows (`db/session.py:42-49`); both queries ALSO carry `business_id = $1` explicitly (`leads.py:285,369,384`). RLS is enabled + FORCEd with USING + WITH CHECK on `leads`, `flow_events`, and `bot_settings`, and `app_role` is the non-bypassing role (`0004:50-76,104-111`). The Redis listing reads only `convindex:{business_id}` (`conversation_state.py:182-183`) and then `conv:{business_id}:{conv_id}`, re-checked by `_assert_owns` on every per-conversation read (`conversation_state.py:188-189`). Business A can never name, list, read, or write B's leads/funnel/conversations.
- ✅ **PII decrypted ONLY for the authenticated owner of that row, only on these owner endpoints; never cross-tenant, never logged.** Verified. Decryption happens only in `_decrypt_lead_row` (`leads.py:320-352`), reached only from `list_leads`, reached only from the session-gated `GET /api/leads` over an RLS-scoped connection — so the rows decrypted are by construction this tenant's own. Each row decrypts under its OWN stamped `key_version` (`leads.py:327,337-338`), and crypto fails LOUD on a key mismatch (no plaintext fallback, `crypto.py:70-101`). The endpoint catches `DecryptionError` and returns a generic `500 "could not read leads"` with no `str(e)` (`dashboard.py:88-95`). No decrypted value is logged anywhere on the read path.
- ✅ **Publish toggle and conversation status/reply are tenant-scoped (can't flip another tenant's bot or chat).** Verified. `PUT /api/bot/publish` → `set_published(pool, business_id, ...)` runs inside `tenant_connection` and the UPDATE/INSERT is keyed `WHERE business_id = $1` / `(business_id, is_published)` with RLS WITH CHECK on `bot_settings` (`bot_settings.py:126-151`, `0004:50-55`) — only the caller's own row can be touched. `POST /conversations/{id}/status` → `set_status` and `/reply` → `append_reply` build the key as `conv:{business_id}:{conversation_id}` and re-assert the prefix via `_assert_owns` (`conversation_state.py:151,227-230`), so a forged `conversation_id` path param cannot address another tenant's chat (a `..`-style id just yields a non-existent key under THIS tenant's prefix; it can never escape it).
- ✅ **No secrets/PII in logs; generic errors.** Verified. `dashboard.py` has exactly one log call — `log.error("lead decryption failed")` (`dashboard.py:91`), a static string with no ids, no `str(e)`, no plaintext. The reply/status services log nothing; `append_reply` explicitly never logs the text (`conversation_state.py:226,231-234`). The JSON formatter only serializes the message + allow-listed `extra` (`logging.py:23-41`), and no `extra` carrying PII is passed on this surface. Errors are generic (the decryption path returns a fixed detail; other failures surface as framework 500s with no app-supplied detail).

**Input validation — mostly enforced, ONE gap (see M7-01):**

- `period` is a `Literal["week","month","all"]` on both leads + dashboard (`dashboard.py:66,104`) — invalid values are rejected `422`; the SQL interval is parameterized (`leads.py:248-258`), never interpolated.
- `flow` is bounded `max_length=40` (`dashboard.py:68`) and bound as a `$n` param (`leads.py:299-301`) — no injection.
- conversation `status` body value is a `Literal["bot","human","closed"]` with `extra="forbid"` (`models/dashboard.py:79-81`); `set_status` re-validates against `_VALID_STATUSES` (`conversation_state.py:149-150`). The query-side `status` filter on `/conversations` is also a `Literal` (`dashboard.py:122-124`).
- reply `text` is `min_length=1, max_length=2000`, stripped, `extra="forbid"` (`models/dashboard.py:97-102`).
- `is_published` is a strict `bool` with `extra="forbid"` (`models/dashboard.py:115-120`).
- `conversation_id` path param is bounded `min_length=1, max_length=200` (`dashboard.py:146,169`).
- ⚠️ **EXCEPTION:** the `/api/leads` `status` filter is a raw `str = Query("all", alias="status")` (`dashboard.py:67`), NOT a `Literal`. It is SAFE (no injection — the value is matched against an allow-list in `list_leads` and any unknown value falls through to "no status predicate", `leads.py:290-297`), but it is INCONSISTENT with every other validated filter and lets a typo silently return ALL statuses instead of erroring. See M7-01.

**Overall verdict: PASS — the M7 back-office surface is tenant-correct and confidentiality-safe.**
business_id comes only from the session on all six routes; Postgres reads are
RLS-scoped + explicit-business_id; Redis listing/reply/status are strictly
business-prefixed and re-asserted; PII is decrypted only for the owner and never
logged; the publish/status/reply mutations cannot reach another tenant. No
critical or medium isolation/leak issues. Findings below are LOW hardening notes.

### M7-01 — `/api/leads` `status` filter is an unvalidated free `str` (silent fall-through) — LOW
- **Where:** `backend\app\api\dashboard.py:67` (`status_filter: str = Query("all", alias="status")`) → `leads.py:290-297`.
- **Why dangerous (mild):** Unlike `period`/`flow`/conversation-status (all `Literal`/bounded), the leads `status` accepts ANY string. There is NO injection risk — it is matched against `STATUS_OPEN`/`_REAL_STATUSES` and bound as a `$n` param, and an unrecognized value simply yields no status predicate (returns ALL statuses). The mild risk is correctness/UX: a typo (`?status=neww`) silently returns every lead instead of a `422`, and the value is also unbounded in length. Not a leak, not an isolation gap. (Note: as of the M7 polish this filter IS now a `Literal` at `dashboard.py:69-71` — verify M7-01 is resolved.)
- **Fix direction:** Make it a `Literal["all","new","in_progress","abandoned","open"]` (matching the other filters) so invalid values 422 instead of silently widening the result set.

### M7-02 — `list_conversations` does N+1 `HGETALL` per index member with no cap — LOW (DoS/perf, not a leak)
- **Where:** `backend\app\services\conversation_state.py:182-211`.
- **Why dangerous (mild):** The index set `convindex:{business_id}` is read in full and one `HGETALL` is issued per member (`conversation_state.py:187-190`) with no LIMIT. The set is tenant-bounded (no cross-tenant exposure) and entries auto-expire with the index TTL, but a single very busy tenant with thousands of live conversations turns one dashboard GET into thousands of sequential Redis round-trips — a self-inflicted latency/availability hit on that owner's own request. Stale members are pruned lazily, which helps, but there is no upper bound on the working set per call.
- **Fix direction:** Cap the listing (e.g. most-recent N) and/or pipeline the `HGETALL`s; consider a sorted-set index keyed by `last_activity_at` so the dashboard reads the top-N directly without scanning every member.

### M7-03 — `_register` re-adds a conversation to the index on every status/reply write; closed/expired chats can linger until TTL — LOW (verify)
- **Where:** `backend\app\services\conversation_state.py:138-156,214-237,242-248`.
- **Why dangerous (mild):** `set_status(..., "closed")` and `append_reply` both call `_register`, so even a just-closed conversation is (re)added to the index and keeps a sliding TTL refreshed by each write. Only `clear_state` removes it (`conversation_state.py:121`), and listing prunes only entries whose hash has fully EXPIRED (`conversation_state.py:191-192`). Net effect: a `closed` conversation stays visible in the default (`status=None`) listing for up to the full TTL after the last touch. This is a tenant-internal UX/accuracy nit (no cross-tenant exposure), but worth confirming it matches the intended "closed disappears" behavior.
- **Fix direction:** On `set_status == "closed"` either `srem` from the index immediately or have `list_conversations` exclude `closed` by default; confirm the intended lifecycle with the product spec.

### M7 dashboard — summary table
| ID | Severity | Area | One-line |
|----|----------|------|----------|
| (req 1-4 + validation) | — | Verification | PASS — business_id from session on all six routes; Postgres reads RLS-scoped + explicit business_id; Redis listing/reply/status strictly business-prefixed + `_assert_owns`; PII decrypted only for the owner, never logged; publish/status/reply mutations tenant-scoped; filters/status/reply/is_published validated; generic errors. |
| M7-01 | Low | Input validation | `/api/leads` `status` is a free `str` (not `Literal`) — safe (allow-list + param-bound, no injection) but a typo silently returns ALL statuses; tighten to a `Literal`. |
| M7-02 | Low | Perf / availability | `list_conversations` does an uncapped N+1 `HGETALL` per index member — a busy tenant slows its own dashboard (no cross-tenant impact); cap/pipeline or use a sorted-set top-N. |
| M7-03 | Low | Lifecycle (verify) | `closed`/replied conversations are re-registered and linger in the index until TTL; only `clear_state` removes them — confirm intended "closed disappears" behavior. |

**Top fixes:** (1) M7-01 — make the leads `status` filter a `Literal` for parity with the other filters; (2) M7-02 — bound/pipeline conversation listing before any tenant accumulates many live chats; (3) M7-03 — confirm/adjust the closed-conversation lifecycle in the index.

---

## M7 polish — lead status mutation + orders metric — audit 2026-06-19

> Scope: the M7 POLISH delta only — `PATCH /api/leads/{lead_id}/status` in
> `backend\app\api\dashboard.py:104-138`; `set_lead_status` + the `orders` add to
> `funnel_stats` in `backend\app\services\leads.py:46-59,209-239,404-461`;
> `LeadStatusRequest`/`LeadStatusResponse` + `orders` in `backend\app\models\dashboard.py:44-71`.
> Frontend (informational): `frontend\src\components\dashboard\LeadCard.tsx` +
> `frontend\src\lib\waLink.ts`. Cross-checked against `app\core\deps.py` and `app\api\me.py`.
> Read-only audit; no product code was modified.

**Owner's explicit requirements — verification result:**

- ✅ **`business_id` comes ONLY from `current_business` (never path/body).** Verified. The route signature takes `business_id: str = Depends(current_business)` (`dashboard.py:114`), resolved solely from the server-side session (`deps.py:50-54`). `LeadStatusRequest` has only a `status` field with `extra="forbid"` (`models/dashboard.py:44-49`) — no `business_id` can be smuggled in the body. The only path param is `lead_id` (a bounded `str`); the tenant id is never read from path/query/body.
- ✅ **The UPDATE is RLS-scoped AND carries `business_id` (A cannot change B's lead).** Verified. The endpoint opens `tenant_connection(pool, business_id)` (`dashboard.py:123`), which sets the transaction-local `app.business_id` so RLS's USING + WITH CHECK scopes the row. `set_lead_status` ALSO carries the predicate explicitly: `UPDATE leads SET status=$3 ... WHERE id=$1 AND business_id=$2` (`leads.py:228-237`), with `business_id` = the caller's verified id ($2). Both layers must agree, so business A targeting business B's `lead_id` matches zero rows → command tag `UPDATE 0` → `set_lead_status` returns `False` → endpoint returns `404 "lead not found"` (`dashboard.py:134-137`). No cross-tenant write is possible, and the 404 (not 403) avoids confirming the foreign lead's existence.
- ✅ **The status value is validated (Literal) — no injection.** Verified. `LeadStatusRequest.status` is `Literal["new","in_progress","abandoned","deal","closed"]` (`models/dashboard.py:49`) — any other value is rejected `422` before the handler runs. Defense-in-depth: `set_lead_status` re-checks membership in `_SETTABLE_STATUSES` and raises `ValueError` otherwise (`leads.py:225-226`), which the endpoint maps to `422` (`dashboard.py:127-132`). The value is bound as a `$3` parameter (`leads.py:236`), never string-interpolated — no SQL injection. `lead_id` is bounded `min_length=1, max_length=64` (`dashboard.py:113`) and is also a bound `$1` param.
- ✅ **No PII/secrets logged; generic errors.** Verified. The new handler and `set_lead_status` contain ZERO `log.*` calls — no `lead_id`, no status, no PII is logged on this path. Errors are generic and static: `404 "lead not found"`, `422 "invalid status"`; no `str(e)`, no row data, no stack detail is surfaced to the client.
- ✅ **`orders` count is tenant-scoped.** Verified. The `orders` branch of `funnel_stats` runs on the same RLS-bound `conn` and uses its OWN param list with `business_id = $1` plus `status = 'deal'` (`leads.py:445-453`); it applies the same `is_test = false` (default) and the same `started_at`-keyed period window as `total_leads`, with the interval bound as a parameter via `_period_clause` (`leads.py:449`, never interpolated). The literal `'deal'` is a fixed constant in the SQL (not user input). `DashboardResponse.orders: int` is populated via the unchanged `**stats` spread (`dashboard.py:156`, `models/dashboard.py:71`). Counts cannot cross tenants.

**Frontend (informational) — wa.me phone surface:**

- ✅ **No phone is logged server-side on this surface; the wa.me link is client-side only.** Verified. `waLink(lead.phone)` (`waLink.ts:8-17`) builds `https://wa.me/{digits}` purely in the browser from the already-decrypted `lead.phone` the owner received via `GET /api/leads`; `LeadCard.tsx:44,121-132` renders it as a plain `<a target="_blank" rel="noopener noreferrer">`. Clicking it navigates the user's own browser to wa.me — it does NOT hit the Bizz_up backend, so no server-side log entry carries the phone. The status mutation triggered from the same card (`setLeadStatus(lead.id, next)`, `LeadCard.tsx:53`) sends only `lead.id` + the Literal status, never the phone. The phone IS visible in the owner's DOM (by design — the owner is the authorized viewer of their own leads), which is expected, not a leak.

**Overall verdict: PASS — the M7 polish is tenant-correct, injection-safe, and leak-free.**
`business_id` is taken only from the verified session; the status UPDATE is doubly
scoped (RLS context + explicit `WHERE business_id`) and returns 404 on a foreign/
missing lead; `status` is a Literal (plus a service-layer re-check) and bound as a
parameter; `orders` is tenant-scoped with the same is_test + period semantics as the
other counts; nothing logs PII or secrets and errors are generic; the wa.me link is
client-side only with no server-side phone logging. No critical, medium, or new low
issues found in the polish delta.

### M7 polish — summary table
| ID | Severity | Area | One-line |
|----|----------|------|----------|
| (all checks) | — | Verification | PASS — business_id from session only; status UPDATE RLS-scoped + explicit `WHERE business_id` (404 on foreign lead); status is a Literal + service re-check, param-bound (no injection); `orders` tenant-scoped w/ same is_test+period; no PII/secrets logged, generic errors; wa.me link client-side only (no server-side phone log). |
| (none) | — | — | No new findings in the M7 polish delta. (Pre-existing M7 low notes M7-01..M7-03 stand; M7-01 appears resolved — `/api/leads` status is now a `Literal` at `dashboard.py:69-71` — verify.) |

---

## M8 in-app human-handoff chat (statuses + transcript) — audit 2026-06-19

> Scope: the NEW M8 delta — the transcript layer in `backend\app\services\conversation_state.py`
> (`_log_key`, `append_message`, `get_messages`, the `waiting` status, transcript mirroring in
> `append_reply`), the silence/transcript wiring in `backend\app\services\bot_runtime.py`
> (status-first guard + `append_message` on customer/bot lines), the read-side
> `get_lead_by_conversation` in `backend\app\services\leads.py`, the four conversation
> endpoints in `backend\app\api\dashboard.py` (`GET /conversations/{id}`,
> `GET /conversations/{id}/messages`, extended `POST .../status`, extended `POST .../reply`),
> the M8 models in `backend\app\models\dashboard.py` (`MessageItem`, `ConversationDetail`,
> `MessagesResponse`, `waiting` in the status Literals), and the frontend
> `frontend\src\components\dashboard\ChatPanel.tsx`, `frontend\src\pages\ConversationsPage.tsx`,
> `frontend\src\lib\dashboardClient.ts`. Cross-checked against `app\core\deps.py`,
> `app\api\me.py`, `app\db\session.py`. Read-only audit; no product code was modified.

**M8 contract checks (S1–S4) — verification result:**

- ✅ **S1 — every new endpoint is behind the session gate; `business_id` comes from `current_business` only; the `:log` key is business-prefixed and passes `_assert_owns`.** Verified. All four conversation routes live on the `dashboard_router`, mounted on the `/api` group whose router-level `dependencies=[Depends(current_session)]` is the deny-by-default gate (`me.py:26,34`) — a missing/expired session is 401 before any handler runs. Each of `get_conversation`, `get_conversation_messages`, `set_conversation_status`, `reply_to_conversation` takes `business_id = Depends(current_business)` (`dashboard.py:193,238,263,286`), resolved solely from the server-side session (`deps.py:50-54`). No M8 model carries a `business_id` field (`models/dashboard.py:96-156`); the only client-supplied identifier is `conversation_id` (path) and `status`/`text` (body). The transcript key is built as `conv:{business_id}:{conversation_id}:log` (`conversation_state.py:60-67`) and `_assert_owns(business_id, log_key)` is re-checked in BOTH `append_message` (`conversation_state.py:287-288`) and `get_messages` (`conversation_state.py:311-312`); the companion hash key is asserted alongside it.
- ✅ **S2 — no cross-tenant path to a transcript: A can never read/write B's `conv:{}:{}:log`.** Verified. The `business_id` baked into both `_key` and `_log_key` is the caller's session-verified id, never client-derived, so A's request can only ever name `conv:{A}:...:log`. `_assert_owns` requires the key to start with `conv:{business_id}:`, so even a forged `conversation_id` containing colons or `..` cannot escape the caller's own prefix — at worst it names a non-existent key UNDER A's namespace (a transcript that doesn't exist, returned as `[]`), never B's. `get_lead_by_conversation` (`leads.py:374-402`) is the only Postgres read added; it runs inside `tenant_connection(pool, business_id)` (`dashboard.py:211`) AND carries `WHERE business_id = $1 AND cache_chat_ref = $2` with `cache_chat_ref = conv:{business_id}:{conversation_id}` (`leads.py:388,395`) — doubly tenant-scoped, so the linked lead can never resolve to B's row. Cross-checked with the QA isolation expectation: there is no code path on which A supplies B's `business_id`.
- ✅ **S3 — input bounds; no eval/exec; SQL parameterized.** Verified. `conversation_id` is bounded `min_length=1, max_length=200` on every M8 route (`dashboard.py:192,237,262,285`). Reply `text` is `min_length=1, max_length=2000`, whitespace-stripped, `extra="forbid"` (`models/dashboard.py:147-149`). Status body is `Literal["bot","waiting","human","closed"]` with `extra="forbid"` (`models/dashboard.py:126-128`), re-checked against `_VALID_STATUSES` in `set_status` (`conversation_state.py:168-169`). Transcript `role` is validated against `_VALID_ROLES` in `append_message` (`conversation_state.py:282-283`) and the list is hard-capped by `LTRIM -TRANSCRIPT_MAX -1` (200) so it can't grow without bound (`conversation_state.py:48,294`). No `eval`/`exec`/dynamic import anywhere in the M8 code. The one new SQL statement (`get_lead_by_conversation`) is fully parameterized (`$1`/`$2`, `leads.py:389-401`) — no string interpolation. `get_messages` tolerates a single corrupt JSON line rather than failing the whole read (`conversation_state.py:317-323`).
- ✅ **S4 — no secrets/PII/message text in logs; Gemini/DB errors stay generic.** Verified. The M8 transcript service functions (`append_message`, `get_messages`, `_log_key`) contain ZERO `log.*` calls — the message body is never logged (docstrings at `conversation_state.py:280-281,308-309` state this explicitly; `_preview` truncates for the hash but is also never logged). `bot_runtime.py` logs nothing on the customer/bot transcript path. In `dashboard.py`, `get_conversation` is the only M8 handler that can log: it catches `DecryptionError` and emits the static `log.error("lead decryption failed")` (`dashboard.py:216`) — no `str(e)`, no ids, no plaintext — then returns generic `500 "could not read conversation"` (`dashboard.py:217-220`). The `/messages`, `/status`, `/reply` handlers log nothing. No Gemini call exists on this surface. The JSON formatter only serializes the static message + allow-listed `extra`, and no PII-bearing `extra` is passed.

**Frontend (informational):**

- ✅ The chat panel and conversations page pass only `conversationId` + the typed status/text to the API client; `conversationId` is `encodeURIComponent`-escaped into the path (`dashboardClient.ts:107,120,133,146`), the tenant is never sent from the client (cookie-only, `credentials:'include'`), and the client-side `maxLength={2000}` mirrors the server bound (`ChatPanel.tsx:25,195`). Message bodies render via React JSX text interpolation (`ChatPanel.tsx:232,249`), which auto-escapes — no `dangerouslySetInnerHTML`, so a customer-supplied message body cannot inject script into the owner's dashboard (XSS). The `?conversation=` deep-link param only sets which row is expanded; it is not trusted for tenant scoping (the server re-resolves the tenant). The `at` timestamp is rendered, not the role-as-HTML.

**Overall verdict: SHIP — the M8 in-app handoff chat is tenant-correct, input-bounded, and leak-free.**
Every new endpoint inherits the session gate; `business_id` is taken only from the
verified session on all four routes; the new `:log` transcript key is business-prefixed
and `_assert_owns`-checked on both write (`append_message`) and read (`get_messages`),
so there is NO cross-tenant path to another business's transcript; the one new SQL read
is doubly tenant-scoped (RLS + explicit `business_id`); reply/message sizes, the
`conversation_id` path, the `status` Literal, and the transcript `role` are all bounded;
the transcript is LTRIM-capped at 200; nothing logs message text/PII/secrets and errors
stay generic; the React chat view auto-escapes message bodies (no XSS). No critical or
medium issues found in the M8 delta. The findings below are LOW hardening notes and
inherited (pre-existing) items to keep on the radar — none is a leak or isolation gap
introduced by M8.

### S8-01 — `append_message` mirrors EVERY inbound customer line into the transcript even while a chat is closed/expired — LOW
- **Where:** `backend\app\services\bot_runtime.py:89-100` + `conversation_state.py:264-300`.
- **Why dangerous (mild):** `run_turn` goes silent only for `waiting`/`human`; for `closed` (or a never-set status) it still appends the inbound customer message AND runs the engine. Because `append_message` calls `_register` + refreshes TTL on every line, an inbound message can resurrect a `closed`/expired conversation back into the dashboard index and keep its (ephemeral) transcript alive. This is a tenant-internal lifecycle/accuracy nit, NOT a cross-tenant leak — the resurrected key stays under the caller's own `conv:{business_id}:` prefix. Mirrors the pre-existing M7-03 lifecycle note.
- **Fix direction:** Confirm the intended behavior for an inbound message on a `closed` conversation (re-open vs. ignore); if "closed stays closed," gate the append/register on status, or have the runtime treat `closed` like `waiting` (record-but-silent) without re-registering.

### S8-02 — transcript body is stored in Redis in plaintext (ephemeral), unlike leads which are encrypted at rest — LOW (by design; confirm)
- **Where:** `backend\app\services\conversation_state.py:290-292` (the `{role, body, at}` JSON pushed to `:log`).
- **Why dangerous (mild):** Customer message text (which can contain PII — a name, phone, address typed mid-conversation) is stored as plaintext in Redis, whereas the durable `leads` rows are encrypted at rest (`leads.py`). This matches decision 0006 (live chat is ephemeral, TTL'd, app-isolated in Redis, not the durable store), so it is a deliberate trade-off, not a regression — but it means anyone with direct Redis access (ops, a Redis breach, an unsecured Redis port) can read recent conversation text. Tenant isolation in-app is intact; this is a defense-in-depth/at-rest note.
- **Fix direction:** Confirm Redis is not network-exposed and is access-controlled (auth + TLS in the deployed env); consider whether the ~60-min TTL window of plaintext customer PII is acceptable per the data-protection stance, and document the decision. No code change required if 0006 already covers this.

### S8-03 — `MessageItem.role`/`body` are unconstrained `str` in the response model; trust rests entirely on `append_message`'s write-time validation — LOW
- **Where:** `backend\app\models\dashboard.py:96-101` (`role: str`, `body: str`) vs the write-time guard in `conversation_state.py:282-283`.
- **Why dangerous (mild):** The response model does not re-validate `role` against the allowed set or bound `body` length on the way OUT. In practice the only writer is `append_message`, which enforces `_VALID_ROLES` and the data originates from already-bounded inputs (customer message ≤ the inbound limit, owner reply ≤ 2000, bot replies engine-generated), so a malformed/oversized line cannot normally be stored. The mild risk is only if some future writer bypasses `append_message`. Not exploitable today; no cross-tenant or injection impact (the frontend auto-escapes the body).
- **Fix direction:** Optionally tighten `MessageItem.role` to a `Literal["customer","bot","owner"]` for parity with the write-time guard; keep all transcript writes funneled through `append_message`.

### M8 chat — summary table
| ID | Severity | Area | One-line |
|----|----------|------|----------|
| S1–S4 | — | Verification | PASS — all four endpoints session-gated; business_id from session only; `:log` key business-prefixed + `_assert_owns` on read AND write (no cross-tenant transcript path); the one new SQL read doubly tenant-scoped; conversation_id/status/text/role all bounded, transcript LTRIM-capped at 200; no eval/exec, SQL parameterized; no message text/PII/secrets logged, errors generic; React view auto-escapes bodies (no XSS). |
| S8-01 | Low | Lifecycle | Inbound customer line on a `closed`/expired chat is appended + re-registers/refreshes TTL, resurrecting it in the index (tenant-internal, not a leak) — confirm "closed stays closed" intent. |
| S8-02 | Low | At-rest (by design) | Transcript bodies (may contain PII) stored as plaintext in Redis, TTL'd — deliberate per decision 0006; confirm Redis is access-controlled + the plaintext window is acceptable. |
| S8-03 | Low | Defense-in-depth | `MessageItem.role`/`body` are free `str` on the way out; safe because all writes go through the validating `append_message` — optionally tighten `role` to a `Literal`. |

**Top fixes:** (1) S8-01 — decide + enforce the `closed`-conversation behavior so an inbound line doesn't silently resurrect a closed chat (shares M7-03's root cause; one fix covers both); (2) S8-02 — document/confirm Redis access-control + the plaintext-at-rest TTL window for conversation text; (3) S8-03 — optionally make `MessageItem.role` a `Literal` and keep every transcript write funneled through `append_message`.

---

## M9 unified lead outcomes (deal/closed filters + always-a-lead-on-handoff + conversation_id) — audit 2026-06-19

> Scope: the M9 delta only (decision 0009) —
> `backend\app\services\leads.py` (the `deal`/`closed` settable+filterable statuses,
> `_REAL_STATUSES`, `conversation_id` derivation in `_decrypt_lead_row`),
> `backend\app\api\dashboard.py` (the extended `/api/leads` `status` Literal),
> `backend\app\models\dashboard.py` (`LeadItem.conversation_id`),
> `backend\app\services\bot_runtime.py` (the minimal-lead-on-handoff write), and the
> frontend `frontend\src\pages\LeadsPage.tsx`,
> `frontend\src\components\dashboard\LeadCard.tsx`,
> `frontend\src\components\dashboard\ConversationCard.tsx`. Cross-checked against
> `app\core\deps.py`. Read-only audit; no product code was modified.

**M9 contract checks (S1–S4) — verification result:**

- ✅ **S1 — new `deal`/`closed` filters stay RLS-scoped; `business_id` from `current_business` only; SQL parameterized.** Verified. `GET /api/leads` takes `business_id = Depends(current_business)` (`dashboard.py:72`) — session-only (`deps.py:50-54`); the `status` query is now a closed `Literal["all","new","in_progress","abandoned","open","deal","closed"]` (`dashboard.py:74-76`) so an invalid value is rejected `422` before the handler (this also resolves the old M7-01 note). The read runs inside `tenant_connection(pool, business_id)` (`dashboard.py:88`). In `list_leads`, `deal`/`closed` are in `_REAL_STATUSES` (`leads.py:302-304`) and matched via a BOUND param: `params.append(status_key); where.append("status = $N")` (`leads.py:353-355`) — never string-interpolated, no injection. `business_id = $1` is the first predicate on every branch (`leads.py:343-344`), so RLS context + the explicit predicate both scope `deal`/`closed` exactly like every other status. The `funnel_stats` `orders` branch uses the fixed literal `status = 'deal'` (a constant, not user input) with its own `business_id = $1` param list (`leads.py:502-510`).
- ✅ **S2 — `conversation_id` is derived from THIS tenant's own `cache_chat_ref`; no way to surface another tenant's conversation id; lead→chat still goes through tenant-checked endpoints.** Verified. `_decrypt_lead_row` rebuilds the prefix from the caller's VERIFIED `business_id` (`prefix = f"conv:{business_id}:"`, `leads.py:441`) and strips it ONLY when `cache_chat_ref.startswith(prefix)` — otherwise `conversation_id` stays `None` (`leads.py:438-443`). Because the row itself is already RLS+`business_id`-scoped, `cache_chat_ref` can only ever be this tenant's own `conv:{business_id}:...` value (stamped by `create_lead`, `leads.py:115`), so the derived id is always this tenant's. There is NO path to surface B's conversation id: the prefix uses A's id, the row is A's, and a mismatch yields `None` rather than leaking the raw ref. The frontend then opens the in-app chat by calling `getConversation(lead.conversation_id)` (`LeadCard.tsx:71`) / `ConversationCard` `resolve()` → `setLeadStatus` + `setConversationStatus` (`ConversationCard.tsx:126-145`), all of which hit the SAME session-gated, `_assert_owns`-checked conversation endpoints audited in M8 — so even the derived id is re-validated server-side against the caller's prefix and cannot reach B's chat. On a failed `getConversation` the card falls back to a local `human` panel and exposes no PII (`LeadCard.tsx:73-80`).
- ✅ **S3 — the minimal-lead-on-handoff write is tenant-scoped (RLS), respects `is_test`, carries no PII it shouldn't.** Verified. The handoff path runs inside the SAME `tenant_connection(pool, business_id)` transaction as the rest of the turn (`bot_runtime.py:129`), so the new `create_lead` + `log_event` are RLS-scoped and carry `business_id` explicitly in their INSERTs (`leads.py:118-124,265-270`). `is_test` is threaded straight from `run_turn`'s parameter into both the `create_lead` and the `log_event` calls (`bot_runtime.py:161-167,171-173`), so a try-me/sim handoff is tagged and never pollutes the real funnel. The minimal lead carries NO customer PII: `lead_name="פנייה לנציג"` is a fixed generic label (`bot_runtime.py:164`), `create_lead` writes no `phone`/`contact_name`/`answers` (only the flow label, status, `is_test`, `key_version`, and the tenant-prefixed `cache_chat_ref`, `leads.py:116-130`), and the `EVENT_HANDOFF` event passes `flow_key=None`, `step_index=None` (`bot_runtime.py:171-173`) — purely structural signal. The "always a lead" rule reuses an already-open lead when present (`handoff_lead_id = new_lead_id`, `bot_runtime.py:159-160`) and only mints one when none exists, so it doesn't create duplicate rows mid-flow.
- ✅ **S4 — no secrets/PII/message text in logs; errors generic.** Verified. The M9 code adds ZERO `log.*` calls: `bot_runtime.py`'s handoff branch logs nothing (no message text, no `lead_name`, no ids); `leads.py`'s `set_lead_status`/`list_leads`/`_decrypt_lead_row`/`get_lead_by_conversation` log nothing; the only `dashboard.py` log on the leads path remains the static `log.error("lead decryption failed")` (`dashboard.py:100`) with no `str(e)`/ids/plaintext, returning a generic `500 "could not read leads"`. The `PATCH /leads/{id}/status` handler returns generic `404 "lead not found"` / `422 "invalid status"` (`dashboard.py:134-142`). The new frontend status mutations send only `lead.id` + the typed status / `conversation_id` + the typed status (`LeadCard.tsx:87`, `ConversationCard.tsx:133,135`) — no PII in the request, and the conversation_id is rendered/`encodeURIComponent`-escaped, React JSX auto-escapes lead fields (no XSS). The conversation_id shown in `ConversationCard` (`ConversationCard.tsx:177`) is this tenant's own id by S2, so displaying it is not a leak.

**Overall verdict: SHIP — the M9 unified-outcome delta is tenant-correct, injection-safe, and leak-free.**
The `deal`/`closed` filters reuse the existing param-bound, RLS+`business_id`-scoped
`list_leads` path (and the `status` query is now a closed `Literal`, closing M7-01);
`conversation_id` is derived from the caller's OWN verified prefix and falls back to
`None` on any mismatch, so no foreign conversation id can surface, and opening the
chat still flows through the M8 session-gated + `_assert_owns` endpoints; the
minimal-lead-on-handoff write is in the same tenant transaction, honors `is_test`,
and carries only a generic non-PII label + structural event; nothing new is logged
and all errors stay generic. No critical, medium, or new low issues in the M9 delta.
One pre-existing LOW item is reinforced by M9 (see M9-01); it is not introduced here.

### M9-01 — minimal handoff lead can be created on a `closed`/expired conversation, re-registering it — LOW (inherited, reinforced by M9)
- **Where:** `backend\app\services\bot_runtime.py:84-100,147-174` (handoff branch) — same root cause as S8-01 / M7-03.
- **Why dangerous (mild):** The handoff branch only runs when the turn is NOT already `waiting`/`human`; a `closed` (or never-set) conversation that receives a handoff-triggering message still appends the inbound line, sets status `waiting`, and now (M9) ALSO mints a minimal lead + handoff event. So an inbound message can resurrect a `closed` conversation AND create a fresh "פנייה לנציג" lead for it. This is tenant-internal (the new row is RLS-scoped to the caller, carries no PII) — NOT a cross-tenant leak — but it can produce surprise leads / re-opened chats and slightly inflate the funnel for a tenant whose chat was considered done. The same `is_test` flag is respected, so test data stays separated.
- **Fix direction:** Decide the intended behavior for an inbound message on a `closed` conversation (re-open vs. ignore) and apply it consistently to the append/register AND the new minimal-lead creation — e.g. treat `closed` like `waiting` (record-but-silent, no new lead) or require an explicit re-open. One fix covers S8-01, M7-03, and M9-01.

### M9 unified outcomes — summary table
| ID | Severity | Area | One-line |
|----|----------|------|----------|
| S1–S4 | — | Verification | SHIP — `deal`/`closed` filters param-bound + RLS+`business_id`-scoped (status query now a closed `Literal`); `conversation_id` derived from the caller's OWN verified `conv:{business_id}:` prefix, `None` on mismatch (no foreign id can surface), chat-open still via M8 session-gated + `_assert_owns` endpoints; minimal handoff lead in the same tenant transaction, honors `is_test`, generic non-PII label + structural event only; nothing new logged, errors generic, frontend sends only ids+typed status (no PII, JSX auto-escapes). |
| M9-01 | Low | Lifecycle (inherited) | A handoff on a `closed`/expired chat re-registers it AND mints a minimal "פנייה לנציג" lead (tenant-internal, not a leak) — same root cause as S8-01/M7-03; decide "closed stays closed" and apply to append/register + minimal-lead creation. |

**Top fixes:** (1) M9-01 — settle the `closed`-conversation lifecycle so a handoff/inbound line doesn't silently resurrect a chat and spawn a surprise lead (one fix also resolves S8-01 + M7-03); (2) keep all transcript/lead writes funneled through the existing tenant-scoped service helpers (no new writer should bypass `tenant_connection` / `_assert_owns`); (3) confirm the wider Redis at-rest stance (S8-02) since the always-a-lead rule increases how often a conversation links to a durable lead row.
