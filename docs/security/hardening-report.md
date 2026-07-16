# Bizz_up security hardening report

> Branch: `chore/security-hardening`. Five workstreams, each verified against the
> running local stack where possible. No secret VALUE was rotated or overwritten
> (a few are flagged for rotation below). No commit/push performed.

---

## A. Single `.env` (env consolidation)

**What changed**
- `infra/.env.local` → **`infra/.env`** (renamed, exact contents preserved; still
  git-ignored). Removed the 5 DEAD DUPLICATE keys (`APP_DB_PASSWORD`,
  `GATEWAY_DB_PASSWORD`, `PII_DATA_KEY`, `WA_CRED_KEK`, `PHONE_HMAC_KEY`) whose
  first definitions were shadowed by the authoritative M2 block; kept every real
  value. `SESSION_SECRET` (not duplicated) was untouched.
- Every reference to `.env.local` across the repo was updated to `.env`:
  `infra/docker-compose.yml` (3 `env_file:` + all comments), `backend/app/core/config.py`
  (`env_file=".env"`), `run.bat` (existence check, auto-generation, `--env-file`,
  error message), `stop.bat`, `Makefile`, all `tests/test_m*.bat`, the 3
  `.claude/agents/*.md`, and every doc (`ENV_SETUP.md`, `infra/README.md`,
  `STRUCTURE.md`, `docs/STATUS.md`, `backend/README.md`, `tests/README.md`,
  `docs/CODEBASE.md`, the narrated/helper tests, migration `0001`, etc.).
- **One** template now: `infra/.env.example` (rewritten to cover every variable
  the whole stack needs, names + placeholders + comments, no real secrets).
  Deleted `infra/.env.local.example`, `backend/.env.example`, `gateway/.env.example`,
  `frontend/.env.example`.
- `.gitignore`: dropped the `!.env.local.example` whitelist; `infra/.env` stays
  ignored (`.env` / `.env.*` rules) and only `infra/.env.example` is tracked.

**Verified**
- `grep -rn "\.env\.local"` across the repo → **0 hits**.
- `docker compose --env-file infra/.env -f infra/docker-compose.yml config` → parses (exit 0).
- Restarted `bizz_up-backend-1` + `bizz_up-gateway-1` → both `healthy`; `/healthz`
  returns **200** on both.

---

## B. Access-log leak (HIGH) — fixed

**Problem**: `uvicorn.access` (propagating to the JSON handler) logged the raw
request line INCLUDING the query string and path tokens, leaking OAuth
`code`+`state` (`/auth/callback`, `/api/google/callback`) and the booking
`cancel_token` (`/api/book/{slug}/cancel/{token}`, `.../reschedule/{token}`).

**What changed**
- `backend/app/core/logging.py`: `uvicorn.access` **and** `gunicorn.access` are
  now silenced (`handlers.clear()`, `propagate=False`, `disabled=True`).
  `uvicorn` / `uvicorn.error` / `gunicorn.error` still propagate (no request line).
- `backend/app/core/request_log.py` (new) + wired in `backend/app/main.py`: one
  redacted structured line per request — `method`, `path` **without** query
  string (cancel/reschedule token segment masked to `***`), `status`,
  `duration_ms`. No client IP, no headers.

**Verified (before/after evidence)** — with the stack running, fired:
```
GET  /auth/callback?code=LEAKTEST123&state=CSRFLEAK456          -> 400
GET  /api/google/callback?code=LEAKTEST789&state=CSRFLEAK000    -> 401
POST /api/book/some-slug/cancel/CANCELTOKENLEAK999              -> 404
POST /api/book/some-slug/reschedule/RESCHEDTOKENLEAK888         -> 422
```
`docker logs bizz_up-backend-1` scan for each canary → **0 occurrences** of
`LEAKTEST123`, `CSRFLEAK456`, `LEAKTEST789`, `CSRFLEAK000`, `CANCELTOKENLEAK999`,
`RESCHEDTOKENLEAK888`. The emitted request lines instead read:
```
{"logger":"app.request","method":"GET","path":"/auth/callback","status":400,...}
{"logger":"app.request","method":"GET","path":"/api/google/callback","status":401,...}
{"logger":"app.request","method":"POST","path":"/api/book/some-slug/cancel/***","status":404,...}
{"logger":"app.request","method":"POST","path":"/api/book/some-slug/reschedule/***","status":422,...}
```
Post-restart 15s window: **0** `uvicorn.access` lines, app's own redacted logs
(`app.request`, `app.webhook`, `app.lifespan`, sweeps) still present — no regression.

---

## C. Production networking posture (new artifacts, dev untouched)

**What changed**
- `infra/docker-compose.prod.yml` (new OVERRIDE): adds a single **`reverse-proxy`**
  (Caddy) — the ONLY service publishing host ports (`80`/`443`). It removes host
  `ports:` from backend/gateway/frontend via the Compose `!override []` reset tag,
  drops the dev source bind-mounts on backend/frontend, and sets `APP_ENV=prod`
  on the backend.
- `infra/Caddyfile` (new): routes `/` → static frontend, `/api/*` + `/auth/*`
  (covers `/api/book/*`) → `backend:8000`. `/webhook/*`, `/internal/*`, `/docs`,
  the gateway QR routes are **not** routed → stay internal. Auto-HTTPS when
  `PUBLIC_DOMAIN` is set.
- `frontend/Dockerfile.prod` (new): multi-stage Vite build → tiny Caddy file-server
  on internal `:80` (no dev server, no bind-mount, no host port).
- `backend/app/main.py`: when `app_env != "dev"`, FastAPI is built with
  `docs_url=None, redoc_url=None, openapi_url=None` (docs stay ON in dev).
- `docs/security/production-networking.md` (new): the public-vs-internal map.

**Verified**
- `docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml config`
  → parses (exit 0). Merged config published-ports audit:
  ```
  backend/frontend/gateway/migrate/postgres/redis -> NONE (internal only)
  reverse-proxy                                    -> ['80','443']
  ```
- The running local stack was **not** switched to prod mode.

---

## D. Automated security guards (new tests)

All under `backend/tests/strict/`, style-matched to the strict suite:
- **`test_frontend_secret_guard.py`** — greps `frontend/src` + `frontend/dist`
  (if built) for secret fingerprints (`GATEWAY_API_TOKEN`, `WA_CRED_KEK`,
  `PII_DATA_KEY`, `PHONE_HMAC_KEY`, `GOCSPX-`, `AIza`, `postgresql://`,
  `SESSION_SECRET`); fails if any appears. **PASSED** (frontend is clean).
- **`test_log_pii_guard.py`** — in-process ASGI; drives `/auth/callback`,
  `/api/book/.../cancel/{token}`, and a `/webhook/whatsapp` post (phone + text),
  captures the app's log stream and asserts none of the code/state/cancel-token/
  phone/message-text/gateway-token appear. Runs in the backend container. **PASSED**.
- **`test_port_exposure_guard.py`** — yaml-parses `infra/docker-compose.prod.yml`
  (tolerating the `!override`/`!reset` tags) and asserts NO service except
  `reverse-proxy` publishes ports (and that the proxy does). **PASSED**.

Regression check: the existing `test_auth_gate.py` (5) + `test_secret_guard.py`
suites pass. (3 `test_m6a.py` failures are **pre-existing** on this M6b branch —
the `WhatsAppStatusResponse` model gained an `error` field per migration 0027 but
the test still asserts the old shape; the lead-questionnaire test passes in
isolation and only flakes under shared-state ordering. Neither is caused by this
work.)

---

## E. Residual items for the AWS / go-live phase

1. **ROTATE the two real third-party secrets** currently sitting in `infra/.env`
   before go-live (they were committed to a local file and shared across dev):
   - `GOOGLE_CLIENT_SECRET` (a `GOCSPX-…` value) — rotate in Google Cloud Console.
   - `GEMINI_API_KEY` (an `AIza…` value) — rotate in Google AI Studio.
   Also regenerate the DB/Redis/session/encryption secrets when moving to a real
   secret manager. **Not rotated here** (would break the running stack / is a
   deploy-time action).
2. **`GATEWAY_AUTH_DIR` on-disk vs DB creds** — the gateway still has a dev
   `GATEWAY_AUTH_DIR=/app/auth` file-based Baileys credential path alongside the
   M6b encrypted-in-DB design. Reconcile to a single source of truth (DB, KEK-
   encrypted) and stop persisting session creds to disk in production.
3. **`ADMIN_EMAILS` fail-open** — an empty `ADMIN_EMAILS` silently means "no
   admins" (not fail-closed). Acceptable for the panel-lockout case, but for prod
   confirm the value is set intentionally and monitored (an accidental blank
   silently removes all admin access rather than erroring).

---

## Files changed / created / deleted (this workstream only)

**New**: `backend/app/core/request_log.py`, `backend/tests/strict/test_frontend_secret_guard.py`,
`backend/tests/strict/test_log_pii_guard.py`, `backend/tests/strict/test_port_exposure_guard.py`,
`infra/docker-compose.prod.yml`, `infra/Caddyfile`, `frontend/Dockerfile.prod`,
`docs/security/production-networking.md`, `docs/security/hardening-report.md`.

**Renamed**: `infra/.env.local` → `infra/.env` (git-ignored, dead duplicates removed).

**Deleted**: `infra/.env.local.example`, `backend/.env.example`, `gateway/.env.example`,
`frontend/.env.example`.

**Edited (code/config)**: `backend/app/core/logging.py`, `backend/app/core/config.py`,
`backend/app/main.py`, `infra/docker-compose.yml`, `infra/.env.example`, `.gitignore`,
`run.bat`, `stop.bat`, `Makefile`, `gateway/src/config.js`, all `tests/test_m*.bat`.

**Edited (docs / tests / agents — reference updates)**: `ENV_SETUP.md`, `STRUCTURE.md`,
`infra/README.md`, `backend/README.md`, `tests/README.md`, `docs/STATUS.md`,
`docs/CODEBASE.md`, `docs/decisions/0013…`, `docs/decisions/0019…`,
`docs/spec/roadmap-parts/infra.md`, `supabase/connection-contract.md`,
`supabase/migrations/0001_roles_extensions.sql`, `backend/scripts/seed_m8_demo.py`,
`backend/tests/narrated/*`, `backend/tests/strict/_m12_helpers.py`,
`backend/tests/strict/_m13_helpers.py`, `.claude/agents/bizzup-{backend,data,test}-*.md`.

_Not part of this work (pre-existing uncommitted edits, left untouched):_
`.claude/launch.json`, `frontend/src/components/landing/{FeaturesSection,HeroSection}.tsx`,
`frontend/src/components/landing/data.ts`.
