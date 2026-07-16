# Bizz_up — Postman / newman CI smoke suite

A pre-deploy smoke suite that walks the backend's **four auth groups** exactly like
the route inventory. Run it with **newman** in CI *before every deploy*; a failed
assertion makes newman exit non-zero and blocks the pipeline.

## Files

| File | Purpose |
|------|---------|
| `bizzup.postman_collection.json` | The requests + `pm.test` assertions, foldered per auth group. |
| `ci.postman_environment.json` | Variables — **all secrets empty**, filled from env/CI at run time. |
| `run.bat` | Double-click / CI runner (uses `npx -y newman` if newman isn't installed). |

## What it covers

1. **Public (no auth)** — `GET /healthz` is 200 for anyone.
2. **Token — Gateway** — `POST /webhook/whatsapp` and `GET /internal/wa/sessions`:
   401 with **no** token, 401 with a **wrong** token, and 200/handled with the **right**
   `X-Gateway-Token`.
3. **Public Booking (by slug)** — the customer flow: `services` → `slots` → create
   (captures the `cancel_token` into a collection variable) → cancel. A **WRONG**
   `cancel_token` must be rejected (404). Create tolerates 201/409/422 (the seed's
   working hours decide whether a slot is bookable); the wrong-token 404 always runs.
4. **Session-gated `/api/*`** — `GET /api/me`, `GET /api/dashboard`: 401 without a
   `{{sessionCookie}}`, 200 with one.
5. **Prod hardening (optional)** — `GET /openapi.json` is 404 against a **prod**
   backend (docs disabled). Enable with `expectProdHardening=true`.

## Secrets — never committed

No secret is hardcoded in the collection. They are Postman variables that CI injects:

| Env var (run.bat) | Postman var | What it is |
|-------------------|-------------|-----------|
| `BASE_URL` | `baseUrl` | Target base URL (default `http://localhost:8000`). |
| `GATEWAY_TOKEN` | `gatewayToken` | The `X-Gateway-Token` (= `GATEWAY_API_TOKEN` from `infra/.env`). |
| `SESSION_COOKIE` | `sessionCookie` | A full `bizzup_session=<sid>` cookie for the `/api` smoke. |
| `BOOKING_SLUG` | `bookingSlug` | A seeded business's public booking slug (optional). |
| `EXPECT_PROD` | `expectProdHardening` | `true` to assert `/openapi.json` is 404. |

If `gatewayToken` / `sessionCookie` / `bookingSlug` are empty, the positive requests
that need them **self-skip** (they log a SKIP assertion and stay green), so the suite
is always runnable — negative/no-auth checks still run and gate the deploy.

## Run locally

```bash
# Windows (double-click or):
tests\postman\run.bat

# with the real token + a seeded slug (bash):
export GATEWAY_TOKEN="$(grep '^GATEWAY_API_TOKEN=' infra/.env | cut -d= -f2-)"
export BOOKING_SLUG="<a seeded booking slug>"
npx -y newman run tests/postman/bizzup.postman_collection.json \
  -e tests/postman/ci.postman_environment.json \
  --env-var "baseUrl=http://localhost:8000" \
  --env-var "gatewayToken=$GATEWAY_TOKEN" \
  --env-var "bookingSlug=$BOOKING_SLUG"
```

## Run in CI (before deploy)

1. Bring the stack (or the freshly built image) up and wait for `/healthz` = 200.
2. Export the secrets from the CI secret store into `GATEWAY_TOKEN` / `SESSION_COOKIE`
   / `BOOKING_SLUG` (never echo them into logs).
3. Run `tests/postman/run.bat` (or the `npx newman` line above). Non-zero exit =
   fail the job = block the deploy.

### Prod note
In production the gateway/internal routes (`/webhook/*`, `/internal/*`) and
`/openapi.json` are **not** exposed through the Caddy proxy — they stay on the
internal network. Point `baseUrl` at the **backend service directly** (internal
network) to exercise the token group in prod, and set `expectProdHardening=true`
to assert `/openapi.json` is 404.
