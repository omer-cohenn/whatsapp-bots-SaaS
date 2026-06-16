# backend/ — FastAPI brain 🧠

**Owner agent:** Backend · **This build:** M0+M1 (minimal boot + WhatsApp receive spike)

The Python / FastAPI service. Later it grows the auth gate, conversation engine,
leads, AI-assist, and back-office (see [`../docs/spec/roadmap-parts/backend.md`](../docs/spec/roadmap-parts/backend.md)).
**Right now it is intentionally minimal:** it boots fail-closed, health-checks
Postgres + Redis, and accepts the frozen WhatsApp webhook — nothing else.

## Layout (this build)
```
backend/
├── app/
│   ├── main.py            # FastAPI factory + lifespan (opens PG pool + Redis)
│   ├── api/
│   │   ├── health.py      # GET /healthz  (PG + Redis reachability)
│   │   └── webhook.py     # POST /webhook/whatsapp  (M1 landing pad)
│   ├── core/
│   │   ├── config.py      # fail-closed pydantic-settings loader
│   │   ├── logging.py     # JSON logging (never logs secrets/PII)
│   │   └── clients.py     # asyncpg pool + redis client + ping_* probes
│   └── models/            # pydantic schemas (frozen webhook contract, health)
├── pyproject.toml         # pinned top-level deps
├── requirements.lock      # full transitive pin (Docker installs from this)
├── Dockerfile             # python:3.12-slim · non-root · gunicorn+uvicorn · NO --reload
└── .env.example           # required env names (no values)
```

## Routes
| Method | Path                | Auth                              | Returns |
|--------|---------------------|-----------------------------------|---------|
| GET    | `/healthz`          | none                              | `200 {status, postgres, redis}` when both reachable, else `503 degraded` |
| POST   | `/webhook/whatsapp` | `X-Gateway-Token: <GATEWAY_API_TOKEN>` | `200 {"status":"received"}`; `401` bad/missing token; `422` malformed body |

### Frozen webhook contract (gateway → backend)
`POST /webhook/whatsapp` with header `X-Gateway-Token: <GATEWAY_API_TOKEN>` and JSON body:
```json
{ "gateway_account_id": "...", "from": "+9725...", "push_name": "...",
  "message_id": "...", "timestamp": 0, "type": "text", "text": "...", "raw": {} }
```

## Config (fail-closed)
Reads env (a git-ignored `.env.local` in dev — copy `.env.example`). The app
**refuses to boot** if any of these is missing/blank/placeholder — no defaults:
- `GATEWAY_API_TOKEN` · `DATABASE_URL` · `REDIS_URL`

## Run it
**Local (venv):**
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps -r requirements.lock
# create .env.local with GATEWAY_API_TOKEN / DATABASE_URL / REDIS_URL
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000   # dev; add --reload if you want
```

**Docker (prod image — gunicorn+uvicorn, no reload):**
```bash
docker build -t bizzup-backend ./backend
docker run --rm -p 8000:8000 --env-file ./backend/.env.local bizzup-backend
```
In docker-compose the backend reaches peers by service name
(`postgresql://...@postgres:5432/...`, `redis://redis:6379/0`).

## The M1 receive proof — what to watch for
On a valid POST to `/webhook/whatsapp`, the backend logs exactly one JSON line.
**REDACTED — only `gateway_account_id`, `message_id`, `type`, and the text
*length*. Never the phone (`from`), `push_name`, `text`, or `raw`:**
```json
{"ts":"…","level":"INFO","logger":"app.webhook","msg":"whatsapp message received","gateway_account_id":"<id>","message_id":"<id>","type":"text","text_len":<int>}
```
A rejected token logs `{"...","logger":"app.webhook","msg":"webhook auth failed"}` and returns 401.
