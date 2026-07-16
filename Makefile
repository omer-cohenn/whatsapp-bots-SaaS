# Bizz_up — one-command developer verbs.
# ============================================================================
# These are the portable replacement for the old machine-specific .bat/.ps1
# scripts (kills B14). `make dev` brings the whole local stack up health-gated
# (kills B13 — no blind sleeps). Real verbs wired in M0: dev / down / logs.
# The rest (test / lint / isolation / migrate / seed) are wired in their own
# milestones (M0-8 / M2) by the owning agents — left as labeled stubs here so
# `make <verb>` is discoverable from day one.
#
# Windows note: run these from Git Bash / WSL2 (where `make` + `docker` live).
# If you don't have `make`, every recipe is just a docker-compose call you can
# run directly — see README / the command echoed by each verb.
# ============================================================================

# Single source of truth for the compose invocation.
# --env-file makes infra/.env the source for BOTH in-container env AND the
# ${VAR} interpolation in the compose file (e.g. building DATABASE_URL). Without
# it, compose only looks for a .env in the project dir and the URLs come out blank.
COMPOSE := docker compose --env-file infra/.env -f infra/docker-compose.yml

.PHONY: help dev down logs ps build test lint isolation migrate seed demo-isolation demo-break

help:
	@echo "Bizz_up dev verbs:"
	@echo "  make dev        - bring the whole stack up (build + health-gated startup)   [M0]"
	@echo "  make down       - tear the stack down (keeps the postgres volume)"
	@echo "  make logs       - follow logs from all services (Ctrl-C to stop)"
	@echo "  make ps         - show each service + its health status"
	@echo "  make build      - (re)build all images without starting them"
	@echo "  make test       - run unit/integration tests for all apps              [M0-8]"
	@echo "  make lint       - lint/format backend + gateway + frontend             [M0-8]"
	@echo "  make migrate    - apply DB migrations (9 tables + roles + RLS)         [M2]"
	@echo "  make seed       - seed the two demo tenants (Avi / Bella)              [M2]"
	@echo "  make isolation  - run the multi-tenant isolation suite (the CI gate)   [M2]"
	@echo "  make demo-isolation - WATCH the wall hold (plain-language story)       [M2]"
	@echo "  make demo-break - prove the gate catches a regression, then restore    [M2]"
	@echo ""
	@echo "First run: copy infra/.env.example -> infra/.env and fill it in."

# --- M0: the real, working verbs ------------------------------------------
# `up --build` builds images if needed, then starts in dependency/health order.
# Because dependents use `condition: service_healthy`, this blocks until each
# upstream service is actually healthy — no sleeps, no races.
dev:
	$(COMPOSE) up --build

# Stop and remove containers + network. Named volumes (postgres data) are kept
# so you don't lose local DB state; add `-v` yourself for a clean wipe.
down:
	$(COMPOSE) down

# Follow combined logs. Apps log structured JSON and NEVER print secrets/QR/PII.
logs:
	$(COMPOSE) logs -f

# Quick health view: STATUS column shows (healthy)/(starting)/(unhealthy).
ps:
	$(COMPOSE) ps

# Build (or rebuild) every image without starting the stack.
build:
	$(COMPOSE) build

# --- M2: the tenant wall verbs --------------------------------------------
# `compose run --rm migrate` waits for postgres to be healthy (depends_on), then
# applies every supabase/migrations/*.sql in order as the superuser, injecting
# the two role passwords as psql vars. Idempotent.
migrate:
	$(COMPOSE) run --rm migrate

# Seed the two demo tenants (Avi Insurance / Bella Barber) as the superuser, by
# reusing the migrate image (it has psql + the /supabase mount + PG* env).
seed: migrate
	$(COMPOSE) run --rm --entrypoint sh migrate -c "psql -v ON_ERROR_STOP=1 -f /supabase/seed.sql"

# The CI gate: the isolation suite + the runtime secret guard. Runs inside a
# throwaway backend container (has the app deps + the app_role/gateway_role env);
# pytest is a dev-only dep, installed on the fly so it stays out of the prod image.
isolation: seed
	$(COMPOSE) run --rm backend sh -c "cd /app && pip install -q pytest==8.3.4 pytest-asyncio==0.25.2 && PYTHONPATH=/app python -m pytest tests/isolation tests/test_secret_guard.py -q"

# Alias kept friendly: `make test` runs the same gate for now.
test: isolation

# WATCH IT WORK: the plain-language demo (no pytest). Seeds, then tries every
# old attack and prints ✅/❌ per line. This is the one to read.
demo-isolation: seed
	$(COMPOSE) run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/demo_isolation.py"

# Prove the gate is real: drop the WITH CHECK on leads (a regression), run the
# demo (expect a LEAK on the cross-tenant insert), then re-apply migrations to
# restore the wall. The leading '-' lets the breached run report without aborting.
demo-break: seed
	@echo ">>> Breaking the WITH CHECK on leads (simulating a regression)..."
	$(COMPOSE) run --rm --entrypoint sh migrate -c "psql -v ON_ERROR_STOP=1 -c \"DROP POLICY IF EXISTS p_tenant_isolation ON leads; CREATE POLICY p_tenant_isolation ON leads USING (business_id = current_business_id()) WITH CHECK (true);\""
	-$(COMPOSE) run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/demo_isolation.py"
	@echo ">>> Restoring the wall (re-applying migrations)..."
	$(COMPOSE) run --rm migrate

lint:
	@echo "TODO(M0-8): run linters/formatters (ruff/black + eslint/prettier)"
