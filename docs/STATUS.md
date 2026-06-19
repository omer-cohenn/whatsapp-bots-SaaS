# STATUS — read this first to resume 📍

> **Last updated: 2026-06-17.** This is the single "where are we / how do I continue" file. A new session
> should read this, then [`spec/mvp-checklist.md`](spec/mvp-checklist.md).

## Phase: BUILD (the MVP). Mapping + ground-up re-spec are DONE.
- ✅ **M0** — the stack runs (one command, all services healthy).
- ✅ **M1** — WhatsApp receive works **end-to-end** (real inbound messages reach the backend webhook).
- ✅ **M2** — the tenant wall: 9 tables + 2 non-service DB roles + RLS (`USING`+`WITH CHECK`) + dual-key fail-loud encryption + Redis cache isolation + the isolation suite. Migrations auto-apply via the compose `migrate` step. **Verify:** `make demo-isolation` (9/9), `make isolation` (10 passing), `make demo-break` (8/9 then restored).
- ✅ **M3** — login & accounts: Google OAuth + opaque Redis-backed sessions (`bizzup_session`) + the **deny-by-default** `/api` gate, wired onto the M2 tenant session. `provision_owner` auto-creates a business on first login (idempotent); logout truly destroys the session. **Verify:** `tests/test_m3.bat` → M3 narrated **5/5**, the `test_auth_gate.py` pytest gate green, and the M2 wall still **12/12** (no regression). A real Google click-through is a one-time manual check at `:5173`.
- ✅ **M4** — the AI bot builder (per-tenant config, validated/grounded). **Verify:** `tests/test_m4.bat` → M4 narrated **9/9**.
- ✅ **M5** — the bot brain + leads: the **pure conversation engine** + the **lead-memory runtime** (`bot_runtime.run_turn` + `/api/bot/sim`, is_test) + **human-handoff silence** + the **abandoned sweep** (migration 0006 `sweep_abandoned_leads`). Leads walk in_progress→new/abandoned with started/step/completed/abandoned funnel events; **PII (phone/contact_name/answers) encrypted at rest — asserted on the raw columns**. **Verify:** `tests/test_m5.bat` (try-me **18/18**) + `tests/test_m5b.bat` (lead-memory narrated **10/10**, strict `test_bot_sim.py` **6/6**), with M2 **12/12** + M3 + M4 + try-me all still green. (try-me chat UI is frontend, not part of this backend verification.)
- ✅ **M7** — the owner dashboard (back-office): `GET /api/leads` (decrypted phone/name/ALL answers; period/status incl. synthetic 'open'/flow filters; is_test excluded by default), `GET /api/dashboard` (funnel started/completed/abandoned/total, matches DB truth), `GET /api/conversations` + `POST .../status` (bot/human/closed) + `POST .../reply` (queued to outbox), `PUT /api/bot/publish` (reflected by GET /api/bot/settings). All six session-gated (401) + tenant-isolated (A never sees B). **Verify:** `tests/test_m7.bat`/`test_m7b.bat` → M7 narrated **15/15**, strict `test_dashboard.py` green (the `period=week|month` interval bug is **FIXED** — `leads._PERIOD_INTERVALS` now uses `datetime.timedelta`), frontend `tsc --noEmit` clean, full strict bundle **91 passed**, and M2–M5 all still green. **M7 polish:** owner-settable lead statuses `deal` (בוצעה עסקה) / `closed` (ליד סגור) via `PATCH /api/leads/{id}/status`; an `orders` KPI (= deals) on `GET /api/dashboard`; the home shows a recent-activity feed (replaced system-health); each lead has a WhatsApp (`wa.me`) button + manual status buttons.
- ⬜ **M6 — next:** per the checklist.
- Then M6→M9 per the checklist.

## What works RIGHT NOW
- Full local stack via `run.bat` (or `make dev`): **backend `:8000` · gateway `:3000` · frontend `:5173` · postgres · redis**, health-gated startup.
- **WhatsApp gateway is connected** (Baileys). Real inbound messages → gateway → backend `/webhook/whatsapp` (200, **redacted** log — no phone/text).
- Backend `/healthz` confirms Postgres + Redis reachable. Webhook auth (`X-Gateway-Token`) enforced (401 on bad token).
- Frontend: RTL Hebrew page + a live "stack health" panel.

## How to run & test
- **Start:** double-click `run.bat` (Docker Desktop must be running). **Stop:** `stop.bat`.
- **URLs** (use `127.0.0.1` if `localhost` is flaky on Windows):
  - Frontend: `http://127.0.0.1:5173`
  - Connect WhatsApp (QR): `http://127.0.0.1:3000/qr`
  - 📥 Dev inbox (see received message content): `http://127.0.0.1:3000/inbox`
  - 📤 Dev send (send a message): `http://127.0.0.1:3000/send`
- **Secrets:** `infra/.env.local` (generated, git-ignored). If missing, `run.bat` regenerates it.

## What's built (the code so far)
- `backend/` — FastAPI: fail-closed config, `/healthz`, `/webhook/whatsapp` (+ redacted log).
- `gateway/` — Node/Baileys: QR connect, `/healthz`, forwards inbound; **+ dev-only `/inbox` & `/send`**.
- `frontend/` — Vite + React + Tailwind + RTL: hero + StackHealth.
- `infra/` — `docker-compose.yml` (health-gated), `.env.local.example`; plus root `Makefile`, `run.bat`, `stop.bat`.
- `supabase/` — **real schema** `migrations/0001…0004` (roles+pgcrypto, RLS bridge, 9 tables, RLS+grants) + `seed.sql` (2 demo tenants). `0000_init.sql` stays an empty marker.
- `backend/app/` — **M2 additions:** `core/crypto.py` (dual-key, fail-loud), `db/session.py` (tenant `SET LOCAL`), `services/live_chat.py` (Redis cache isolation); `core/config.py` now requires the encryption keys (fail-closed).
- `backend/tests/` — `isolation/` suite (10 passing) + `demo_isolation.py` (the readable 9/9 story) + `test_secret_guard.py`; **M3:** `m3_full_test.py` (the 5/5 story) + `test_auth_gate.py` (strict gate).
- `backend/app/` — **M3 additions:** `services/auth.py` (Google OAuth + opaque Redis sessions), `core/deps.py` (`current_session/current_user/current_business`), `api/auth.py` (`/auth/google|callback|logout`), `api/me.py` (gated `/api/*` group + `GET /api/me`), `models/auth.py`; `core/config.py` now also requires `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` + `SESSION_SECRET` (fail-closed). `supabase/migrations/0005_auth_bootstrap.sql` adds the `provision_owner` / `get_user_businesses` SECURITY DEFINER funcs.

## Fixes we already made today (don't re-hit these)
- **Port 6379 clash** → postgres/redis are **not** published to the host (internal-only on the Docker network).
- **Redis "unhealthy"** → added `REDISCLI_AUTH` env so the healthcheck can authenticate.
- **Frontend crash (`@rollup/rollup-linux-x64-gnu`)** → Windows `node_modules` leaked via the bind mount; fixed with an **anonymous volume** for `/app/node_modules` + the frontend Dockerfile uses `npm install`.
- **Gateway restart** reconnects automatically from saved creds in `gateway/auth/` (no QR re-scan).

## DEV-ONLY — must be cleaned up before production (tracked for M6)
- `gateway` `/qr`, `/inbox`, `/send` are **unauthenticated dev tools that expose content** — remove/secure them.
- Baileys creds sit as files in `gateway/auth/` (spike) — must move to the **encrypted DB** (crown jewel, `whatsapp_credentials`).

## Next steps
1. *(recommended)* a **git checkpoint** of the M3 working state.
2. **One-time manual check:** click "Sign in with Google" at `http://localhost:5173`, confirm you land logged-in on your own business, then log out (OAuth needs a real browser, so a script can't do this part).
3. Continue M4→M9 per [`spec/mvp-checklist.md`](spec/mvp-checklist.md).

## How to verify M3 (anytime)
- Double-click `tests/test_m3.bat`, or by hand:
  - M3 story: `docker compose --env-file infra/.env.local -f infra/docker-compose.yml run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m3_full_test.py"` → **5/5**.
  - M3 gate: same wrapper, `pip install -q pytest pytest-asyncio && PYTHONPATH=/app python -m pytest tests/test_auth_gate.py -q`.
  - No-regression: re-run `tests/m2_full_test.py` → still **12/12**.

## How to verify M2 (anytime)
- `make demo-isolation` → reads the 9/9 "wall holds" story (start here).
- `make isolation` → the pytest gate (10 passing), connecting as the real non-service roles.
- `make demo-break` → drops a `WITH CHECK`, shows the demo catch it (8/9), then restores.
- Note: in plain Git Bash `make` may be absent; the equivalent `docker compose … run` commands are in the `Makefile`.

## The map of everything
- **Plan:** [`spec/roadmap.md`](spec/roadmap.md) · [`spec/mvp-checklist.md`](spec/mvp-checklist.md) · [`spec/build-guide.md`](spec/build-guide.md) · [`spec/architecture.md`](spec/architecture.md) · [`spec/data-model.md`](spec/data-model.md)
- **Decisions:** [`decisions/`](decisions/) (0001 Baileys/QR · 0002 multi-tenant · 0003 model · 0004 MVP scope · 0005 auth/data · 0006 Redis live-chat)
- **Old-system map:** [`system-map/`](system-map/), [`bugs.md`](bugs.md), [`security-issues.md`](security-issues.md)
- **AI tooling:** `.claude/agents/` (scanners + `data-architect` + `devops_aws`), `.claude/skills/progress_report`, `.claude/workflows/`
