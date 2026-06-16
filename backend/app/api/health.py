"""GET /healthz — liveness + dependency reachability (Postgres + Redis).

Returns 200 with per-dependency detail when both are reachable, else 503.
Error details are reduced to the exception *class name* only — never the
message or DSN — so a connection string can't leak into a health response.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.core.clients import ping_postgres, ping_redis
from app.core.logging import get_logger
from app.models.health import DependencyHealth, HealthResponse

router = APIRouter(tags=["health"])
log = get_logger("app.health")


async def _check(coro) -> DependencyHealth:
    """Run a ping coroutine, mapping success/failure to DependencyHealth."""
    try:
        await coro
        return DependencyHealth(ok=True, detail="reachable")
    except Exception as exc:  # noqa: BLE001 — report class only, no message
        return DependencyHealth(ok=False, detail=type(exc).__name__)


@router.get("/healthz", response_model=HealthResponse)
async def healthz(request: Request, response: Response) -> HealthResponse:
    pg = await _check(ping_postgres(request.app.state.pg_pool))
    rd = await _check(ping_redis(request.app.state.redis))

    healthy = pg.ok and rd.ok
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        # Secret-free: only the boolean reachability of each dependency.
        log.warning(
            "healthz degraded", extra={"postgres_ok": pg.ok, "redis_ok": rd.ok}
        )

    return HealthResponse(
        status="ok" if healthy else "degraded", postgres=pg, redis=rd
    )
