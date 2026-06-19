"""FastAPI application factory + lifespan (M0+M1 minimal build).

Boot sequence:
  - Load + validate settings (FAIL-CLOSED: raises if GATEWAY_API_TOKEN /
    DATABASE_URL / REDIS_URL are missing — the app will not start).
  - Configure JSON logging.
  - On lifespan startup: open the asyncpg pool + redis client, store on
    app.state. On shutdown: close both.
  - Mount the health + webhook routers.

There is intentionally no auth/bot/leads/DB-schema here — just the plumbing
that boots and the M1 webhook landing pad.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.me import api as api_router
from app.api.webhook import router as webhook_router
from app.core.clients import create_pg_pool, create_redis
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.services.abandoned_sweep import sweep_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open infra clients on startup; close them on shutdown."""
    settings = app.state.settings
    log = get_logger("app.lifespan")

    app.state.pg_pool = await create_pg_pool(settings)
    app.state.redis = create_redis(settings)

    # Background: the abandoned-lead sweep (M5). A single-runner loop guarded by a
    # Redis lock so multiple workers never double-sweep. Started here, cancelled on
    # shutdown below.
    sweep_task = asyncio.create_task(
        sweep_loop(app.state.pg_pool, app.state.redis)
    )

    log.info("backend started", extra={"app_env": settings.app_env})

    try:
        yield
    finally:
        # Stop the sweep loop first (await its clean CancelledError exit), then
        # dispose the infra clients. Never log connection details.
        sweep_task.cancel()
        try:
            await sweep_task
        except asyncio.CancelledError:
            pass
        await app.state.pg_pool.close()
        await app.state.redis.aclose()
        log.info("backend stopped")


def create_app() -> FastAPI:
    """Build and return the FastAPI app. Validates settings (fail-closed)."""
    # Constructing settings here is what makes a missing secret fail the boot.
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="Bizz_up backend",
        version="0.0.1",
        summary="M0+M1 minimal: boots, health-checks PG+Redis, WhatsApp webhook landing pad.",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Public routes: /healthz, /webhook/*, /auth/*. The /api/* group below is
    # gated (deny-by-default) by a router-level session dependency.
    app.include_router(health_router)
    app.include_router(webhook_router)
    app.include_router(auth_router)
    app.include_router(api_router)
    return app


# Module-level ASGI app for `uvicorn app.main:app` / gunicorn.
app = create_app()
