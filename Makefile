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
# --env-file makes infra/.env.local the source for BOTH in-container env AND the
# ${VAR} interpolation in the compose file (e.g. building DATABASE_URL). Without
# it, compose only looks for a .env in the project dir and the URLs come out blank.
COMPOSE := docker compose --env-file infra/.env.local -f infra/docker-compose.yml

.PHONY: help dev down logs ps build test lint isolation migrate seed

help:
	@echo "Bizz_up dev verbs:"
	@echo "  make dev        - bring the whole stack up (build + health-gated startup)   [M0]"
	@echo "  make down       - tear the stack down (keeps the postgres volume)"
	@echo "  make logs       - follow logs from all services (Ctrl-C to stop)"
	@echo "  make ps         - show each service + its health status"
	@echo "  make build      - (re)build all images without starting them"
	@echo "  make test       - run unit/integration tests for all apps              [M0-8]"
	@echo "  make lint       - lint/format backend + gateway + frontend             [M0-8]"
	@echo "  make isolation  - run the multi-tenant isolation suite (the gate)      [M2]"
	@echo "  make migrate    - apply DB migrations                                  [M2]"
	@echo "  make seed       - seed demo tenants (is_test)                          [M2]"
	@echo ""
	@echo "First run: copy infra/.env.local.example -> infra/.env.local and fill it in."

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

# --- Stubs owned by later milestones (kept so the verb is discoverable) ----
test:
	@echo "TODO(M0-8): run test suites (backend pytest + gateway + frontend)"
lint:
	@echo "TODO(M0-8): run linters/formatters (ruff/black + eslint/prettier)"
isolation:
	@echo "TODO(M2): run tests/isolation (must connect as the non-service role)"
migrate:
	@echo "TODO(M2): apply supabase/migrations"
seed:
	@echo "TODO(M2): apply supabase/seed via the real app roles"
