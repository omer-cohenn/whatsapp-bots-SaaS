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
from app.api.internal_media import router as internal_media_router
from app.api.internal_wa import router as internal_wa_router
from app.api.me import api as api_router
from app.api.public_booking import router as public_booking_router
from app.api.webhook import router as webhook_router
from app.core.clients import create_gateway_pool, create_pg_pool, create_redis
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.request_log import install_request_logging
from app.services import google_calendar
from app.services.abandoned_sweep import sweep_loop
from app.services.booking_reminders import sweep_loop as booking_reminders_loop
from app.services.stale_handoff_sweep import sweep_loop as stale_handoff_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open infra clients on startup; close them on shutdown."""
    settings = app.state.settings
    log = get_logger("app.lifespan")

    app.state.pg_pool = await create_pg_pool(settings)
    # M6b: the gateway_role pool — the ONLY route to the crown-jewel
    # whatsapp_credentials table (app_role has zero grant). Used exclusively by
    # the internal WA API to read/write each business's encrypted auth_state.
    app.state.gw_pool = await create_gateway_pool(settings)
    app.state.redis = create_redis(settings)

    # M11: register the Google Calendar sync hook with the booking core. The hook
    # captures the pool (it opens its own tenant_connection per call) and fires
    # AFTER each booking mutation commits. It no-ops for businesses that haven't
    # connected Google and swallows any Google failure, so this never affects
    # booking reliability even when calendar isn't configured.
    google_calendar.register(app.state.pg_pool)

    # Background: the abandoned-lead sweep (M5). A single-runner loop guarded by a
    # Redis lock so multiple workers never double-sweep. Started here, cancelled on
    # shutdown below.
    sweep_task = asyncio.create_task(
        sweep_loop(app.state.pg_pool, app.state.redis)
    )

    # Background: the M11 booking-reminders sweep. Same single-runner pattern —
    # queues confirmations + day-before reminders into the Redis outbox (sent for
    # real once M6 WhatsApp sending is wired). Cancelled on shutdown below.
    booking_reminders_task = asyncio.create_task(
        booking_reminders_loop(app.state.pg_pool, app.state.redis)
    )

    # Background: the proactive stale-handoff close. Same single-runner pattern —
    # closes waiting/human chats gone silent past the threshold and sends the
    # customer a closing message, without waiting for them to message again.
    stale_handoff_task = asyncio.create_task(
        stale_handoff_loop(app.state.pg_pool, app.state.redis)
    )

    log.info("backend started", extra={"app_env": settings.app_env})

    try:
        yield
    finally:
        # Stop the background loops first (await their clean CancelledError exit),
        # then dispose the infra clients. Never log connection details.
        sweep_task.cancel()
        booking_reminders_task.cancel()
        stale_handoff_task.cancel()
        for task in (sweep_task, booking_reminders_task, stale_handoff_task):
            try:
                await task
            except asyncio.CancelledError:
                pass
        await app.state.pg_pool.close()
        await app.state.gw_pool.close()
        await app.state.redis.aclose()
        log.info("backend stopped")


def create_app() -> FastAPI:
    """Build and return the FastAPI app. Validates settings (fail-closed)."""
    # Constructing settings here is what makes a missing secret fail the boot.
    settings = get_settings()
    configure_logging(settings.log_level)

    # SECURITY: the interactive API docs (/docs, /redoc) + the OpenAPI schema
    # (/openapi.json) enumerate every route and shape — useful in dev, but an
    # unnecessary information leak in production. Serve them ONLY in dev; in any
    # non-dev environment they 404.
    docs_enabled = settings.app_env == "dev"

    app = FastAPI(
        title="Bizz_up backend",
        version="0.0.1",
        summary="M0+M1 minimal: boots, health-checks PG+Redis, WhatsApp webhook landing pad.",
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    app.state.settings = settings

    # One redacted access-log line per request (method + path w/o query + status +
    # duration). Replaces uvicorn.access, which leaked OAuth code/state + booking
    # tokens via the raw request line. See app/core/request_log.py.
    install_request_logging(app)

    # Public routes: /healthz, /webhook/*, /auth/*, and the M11 public booking
    # page (/api/book/*). The /api/* group below is gated (deny-by-default) by a
    # router-level session dependency. The public booking router is mounted
    # SEPARATELY here (on the app root, NOT under the gated api_router) precisely
    # because customers have no session — it secures itself by resolving the
    # tenant from the verified slug + RLS (see app/api/public_booking.py).
    app.include_router(health_router)
    app.include_router(webhook_router)
    # M6b: the internal WA API the gateway calls (session list + encrypted creds +
    # status). PUBLIC-path like /webhook/*, but protected by the SAME
    # X-Gateway-Token header check — NOT the owner session gate. Mounted on the
    # app root (outside the gated /api group) because the gateway has no session.
    app.include_router(internal_wa_router)
    # M16: the internal MEDIA upload the gateway calls when a customer sends a
    # file (POST /internal/wa/media). Same trust model + same X-Gateway-Token as
    # internal_wa above; kept in its own module because it is the only multipart
    # route in the app. NO new pool/client is needed: it reuses app.state.gw_pool,
    # and the R2 client inside services/file_storage.py is built lazily on first
    # use (so the app still boots with no object storage configured at all).
    app.include_router(internal_media_router)
    app.include_router(auth_router)
    app.include_router(public_booking_router)
    app.include_router(api_router)
    return app


# Module-level ASGI app for `uvicorn app.main:app` / gunicorn.
app = create_app()
