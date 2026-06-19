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
