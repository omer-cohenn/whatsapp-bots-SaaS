# Production networking posture

> How Bizz_up is exposed in production: exactly one public door, everything else
> sealed on the internal Docker network. This feeds the AWS deploy phase.

## The model: one reverse proxy, nothing else published

In production we run the base stack **plus** the `infra/docker-compose.prod.yml`
override:

```bash
docker compose --env-file infra/.env \
  -f infra/docker-compose.yml \
  -f infra/docker-compose.prod.yml up -d --build
```

The override adds a single **`reverse-proxy`** service (Caddy) and strips the
host `ports:` off every other service (using the Compose `!override []` reset
tag). The result — verified from the merged config — is that **only the
reverse-proxy publishes host ports**:

| Service         | Host ports (prod) | Reachable from the internet? |
|-----------------|-------------------|------------------------------|
| reverse-proxy   | `80`, `443`       | **YES — the only public door** |
| backend         | none              | No — internal network only   |
| gateway         | none              | No — internal network only   |
| frontend (static) | none            | No — served via the proxy    |
| postgres        | none              | No — internal network only   |
| redis           | none              | No — internal network only   |
| migrate         | none (one-shot)   | No                           |

## What the internet can reach (through the proxy)

The Caddy config (`infra/Caddyfile`) routes only these path families:

| Public path  | Proxied to      | Purpose                                   |
|--------------|-----------------|-------------------------------------------|
| `/`          | `frontend:80`   | The owner dashboard SPA (static build)    |
| `/api/*`     | `backend:8000`  | The owner API **and** the public booking pages (`/api/book/*`) |
| `/auth/*`    | `backend:8000`  | Google OAuth login round-trip             |

TLS: set `PUBLIC_DOMAIN` to your real domain and Caddy obtains a certificate
automatically on `:443`. Left unset it serves plain `:80` — the expected posture
when TLS is terminated upstream by an AWS ALB / CloudFront.

## What is strictly INTERNAL (never publicly routed)

These are **not** routed by the proxy and have **no** published port, so they are
only reachable from inside the Docker network / VPC:

- **`/webhook/*`** — the gateway → backend inbound WhatsApp path. The gateway
  calls `backend:8000/webhook/whatsapp` over the internal network, authenticated
  by the shared `X-Gateway-Token`. It must never be public.
- **`/internal/*`** — the gateway → backend WA session/creds API (same token).
- **`/docs`, `/redoc`, `/openapi.json`** — the interactive API docs + schema.
  These are additionally disabled in code when `APP_ENV=prod` (see
  `create_app` in `backend/app/main.py`): they return 404 in prod even if
  something were to reach the backend directly.
- **The gateway (`:3000`)** — QR page and all dev routes. The owner sees the QR
  via the backend admin endpoints (`GATEWAY_BASE_URL`), which proxy the gateway
  over the internal network. The gateway is never exposed to the host.
- **postgres (`:5432`) and redis (`:6379`)** — data stores; internal only.

## Frontend in production

Production does **not** run the Vite dev server or bind-mount source. The
frontend is a **static build** (`frontend/Dockerfile.prod`: multi-stage Vite
build → tiny Caddy file-server on internal `:80`). The browser always talks
same-origin to the public proxy, so no backend URL or secret is ever shipped to
the client.

## AWS phase notes

- Put the reverse-proxy behind an ALB (TLS there) **or** give Caddy a real
  `PUBLIC_DOMAIN` for auto-HTTPS — not both terminating TLS.
- Security groups should allow inbound only to the proxy (80/443). postgres,
  redis, gateway, backend get **no** inbound from the internet — only from the
  app security group.
- Managed Postgres/Redis (RDS / ElastiCache) replace the in-compose containers;
  keep them in private subnets.
