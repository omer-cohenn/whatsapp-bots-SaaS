# Connection Contract — Postgres + Redis (M0+M1)

> **Owner:** DATA agent · **Scope:** the **M0+M1 minimal/bootable build** (plumbing only).
> **Status:** schema is **deferred to M2** — there are no tables yet. This document defines only the
> *connection shapes* the backend's `GET /healthz` uses to prove Postgres and Redis are **reachable**.
>
> **Grounds:** the shared M0+M1 spec; `infra/.env.example` (secret names); `docs/spec/data-model.md`
> (real schema, FINAL, lands in M2); `docs/spec/roadmap-parts/data.md` (D0.1–D0.7).

---

## TL;DR

- The backend connects to **two backing stores** for its health check: **Postgres** (via `DATABASE_URL`)
  and **Redis** (via `REDIS_URL`).
- `GET /healthz` returns **200** only if **both** are reachable; otherwise non-200.
- **No tables are touched.** Reachability is proven with a trivial liveness probe per store
  (`SELECT 1` for Postgres, `PING` for Redis) — **not** by reading/writing any application table.
- **Tables, roles, RLS, grants, and the encryption layer are M2.** See `migrations/0000_init.sql`
  (intentionally empty) and `docs/spec/data-model.md`.

---

## What this run needs (and what it deliberately does NOT)

| Concern | M0+M1 (this run) | M2 (later) |
|---|---|---|
| Postgres reachable | ✅ required for `/healthz` | — |
| Redis reachable | ✅ required for `/healthz` | — |
| App schema (9 tables) | ❌ none — **deferred** | ✅ authored |
| Non-service DB roles (`app_role` / `gateway_role`) | ❌ not required to boot | ✅ created with the schema |
| RLS (`USING` + `WITH CHECK`) + grants | ❌ N/A (no tables) | ✅ ships *with* each table |
| `current_business_id()` bridge, `SET LOCAL business_id` | ❌ N/A | ✅ |
| Encryption (PII key / KEK / HMAC, `key_version`) | ❌ N/A | ✅ |

For M0+M1 the health check is a pure **liveness** signal: "can the backend open a connection and get a
response?" It is not a readiness/migration check.

---

## Required config (env, fail-closed)

Read from a **git-ignored `.env`** in dev (names per `infra/.env.example`); in prod from the secret
manager. **FAIL-CLOSED:** the backend must **refuse to boot** if a required value is missing — **no
`change-me` / constant defaults.**

Required by the backend for this minimal run:

| Var | Used by | Shape | Notes |
|---|---|---|---|
| `DATABASE_URL` | backend | Postgres connection string | the connection the `/healthz` Postgres probe opens. In compose, host is the **service name** `db`/`postgres` (not `localhost`). |
| `REDIS_URL` | backend | Redis connection string | the connection the `/healthz` Redis probe opens. In compose, host is the service name `redis`. |

> Out of scope here (other agents / M2): `GATEWAY_API_TOKEN` (gateway↔backend auth — both sides),
> `BACKEND_WEBHOOK_URL` (gateway side), and every M2 secret in `infra/.env.example`
> (`GATEWAY_DATABASE_URL`, `REDIS_AUTH`, `SESSION_SECRET`, `PII_DATA_KEY`, `WA_CRED_KEK`,
> `PHONE_HMAC_KEY`, OAuth, `GEMINI_API_KEY`). They are **not** needed for the backend to boot or to pass
> `/healthz` in M0+M1.

---

## Postgres — `DATABASE_URL`

**Purpose in M0+M1:** liveness only. Prove the backend can open a connection and the server answers.

- **Shape:** a standard Postgres URI:
  `postgresql://<user>:<password>@<host>:<port>/<dbname>`
  - **In docker-compose:** `<host>` is the **service name** (e.g. `postgres` / `db`), `<port>` `5432`,
    reachable on the compose network — e.g. `postgresql://<user>:<pass>@db:5432/bizzup`.
  - **On the host (outside compose):** `<host>` is `localhost`, `<port>` the mapped `5432`.
- **Reachability check (how `/healthz` knows it's up):** open a connection from `DATABASE_URL` and run a
  **trivial probe** — `SELECT 1`. Success (a row back, no error) ⇒ Postgres reachable. Any connection
  error, auth failure, or timeout ⇒ **unhealthy** (non-200).
- **No tables involved.** The probe must **not** reference any application table (none exist yet). Do not
  run migrations as part of the health check.
- **Timeout / fail-closed:** bound the probe with a short connection + statement timeout so `/healthz`
  fails fast (returns non-200) instead of hanging when Postgres is down or starting.

**M2 note (not now):** in M2 the *app* will connect as a **non-service role** and set
`SET LOCAL app.business_id` per request so RLS applies. For M0+M1 there are no tenant queries, so the
role used by the health probe only needs to be able to connect and run `SELECT 1`. Do **not** wire the
service-role key anywhere — that habit is exactly what the rebuild exists to kill.

---

## Redis — `REDIS_URL`

**Purpose in M0+M1:** liveness only. Prove the backend can reach the Redis used (in M2) for the live-chat
cache.

- **Shape:** a standard Redis URI:
  `redis://[:<password>@]<host>:<port>[/<db>]` (and `rediss://…` for TLS in prod).
  - **In docker-compose:** `<host>` is the service name `redis`, `<port>` `6379` —
    e.g. `redis://redis:6379/0`.
  - **On the host (outside compose):** `redis://localhost:6379/0`.
- **Reachability check (how `/healthz` knows it's up):** open a client from `REDIS_URL` and issue
  **`PING`**; a `PONG` reply ⇒ Redis reachable. Any connection error, auth failure, or timeout ⇒
  **unhealthy** (non-200).
- **No keys involved.** `PING` reads/writes nothing. The live-chat cache keys
  (`chat:{business_id}:{customer_phone_hash}`) and their app-layer tenant isolation are **M2** — not part
  of this probe.
- **Timeout / fail-closed:** bound the `PING` with a short timeout so `/healthz` fails fast when Redis is
  down or starting.

**M2 note (not now):** prod Redis uses TLS (`rediss://`) + auth (`REDIS_AUTH`) on a private network; the
cache's tenant isolation is enforced in the app layer (Redis has no RLS). None of that is required for the
M0+M1 reachability probe.

---

## `GET /healthz` contract (backend) — summary

> Implemented by **BACKEND**; this section states the **data contract** `/healthz` must satisfy so it
> stays consistent with the connection shapes above.

- **200** ⇒ Postgres **and** Redis both answered their liveness probe (`SELECT 1` / `PING`).
- **non-200** ⇒ either store is unreachable (connection error / auth failure / timeout).
- Probes are **liveness only**: no application tables, no cache keys, no migrations.
- **Logging:** structured; **never** log secrets, connection strings, the gateway token, the QR, or
  message bodies / phone numbers. A failing probe logs *that* a store is unreachable and (optionally) a
  coarse reason — **never** the URL/credentials.

---

## Why the schema is deferred (and where it goes)

This is the **receive spike**: the goal is "it boots and the WhatsApp message arrives," not features. The
backend needs Postgres + Redis **reachable**, nothing more — so creating tables now would be premature and
risk shipping RLS/grants as an afterthought (the exact anti-pattern the data layer forbids).

The real schema is authored in **M2** as ordered migrations, each carrying its own **RLS (`USING` +
`WITH CHECK`)** and **per-role grants**, with the two **non-service roles** and the encryption layer:

- **Spec / source of truth:** `docs/spec/data-model.md` (FINAL — the 9 tables + Redis live chat).
- **Build sequence:** `docs/spec/roadmap-parts/data.md` (D0.1–D0.7).
- **MUST list (security gate):** `docs/spec/database-schema-security-review.md`.
- **Placeholder migration:** `supabase/migrations/0000_init.sql` — intentionally empty; real schema lands
  in new migrations starting `0001_*` in M2.
