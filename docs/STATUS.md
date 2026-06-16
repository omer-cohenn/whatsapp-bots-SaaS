# STATUS — read this first to resume 📍

> **Last updated: 2026-06-16.** This is the single "where are we / how do I continue" file. A new session
> should read this, then [`spec/mvp-checklist.md`](spec/mvp-checklist.md).

## Phase: BUILD (the MVP). Mapping + ground-up re-spec are DONE.
- ✅ **M0** — the stack runs (one command, all services healthy).
- ✅ **M1** — WhatsApp receive works **end-to-end** (real inbound messages reach the backend webhook).
- ⬜ **M2 — next:** the tenant wall (9 Postgres tables + RLS + 2 DB roles + the isolation test suite).
- Then M3→M9 per the checklist.

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
- `supabase/` — placeholder migration only (real 9-table schema = M2).

## Fixes we already made today (don't re-hit these)
- **Port 6379 clash** → postgres/redis are **not** published to the host (internal-only on the Docker network).
- **Redis "unhealthy"** → added `REDISCLI_AUTH` env so the healthcheck can authenticate.
- **Frontend crash (`@rollup/rollup-linux-x64-gnu`)** → Windows `node_modules` leaked via the bind mount; fixed with an **anonymous volume** for `/app/node_modules` + the frontend Dockerfile uses `npm install`.
- **Gateway restart** reconnects automatically from saved creds in `gateway/auth/` (no QR re-scan).

## DEV-ONLY — must be cleaned up before production (tracked for M6)
- `gateway` `/qr`, `/inbox`, `/send` are **unauthenticated dev tools that expose content** — remove/secure them.
- Baileys creds sit as files in `gateway/auth/` (spike) — must move to the **encrypted DB** (crown jewel, `whatsapp_credentials`).

## Next steps
1. *(recommended)* a **git checkpoint** of this working state (project is not yet under git).
2. **M2 — the tenant wall**: build with the data + security + infra agents (9 tables, RLS, roles, isolation suite).
3. Continue M3→M9 per [`spec/mvp-checklist.md`](spec/mvp-checklist.md).

## The map of everything
- **Plan:** [`spec/roadmap.md`](spec/roadmap.md) · [`spec/mvp-checklist.md`](spec/mvp-checklist.md) · [`spec/build-guide.md`](spec/build-guide.md) · [`spec/architecture.md`](spec/architecture.md) · [`spec/data-model.md`](spec/data-model.md)
- **Decisions:** [`decisions/`](decisions/) (0001 Baileys/QR · 0002 multi-tenant · 0003 model · 0004 MVP scope · 0005 auth/data · 0006 Redis live-chat)
- **Old-system map:** [`system-map/`](system-map/), [`bugs.md`](bugs.md), [`security-issues.md`](security-issues.md)
- **AI tooling:** `.claude/agents/` (scanners + `data-architect` + `devops_aws`), `.claude/skills/progress_report`, `.claude/workflows/`
