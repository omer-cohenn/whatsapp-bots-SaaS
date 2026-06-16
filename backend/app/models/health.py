"""Response schemas for /healthz."""

from __future__ import annotations

from pydantic import BaseModel


class DependencyHealth(BaseModel):
    """Per-dependency reachability result."""

    ok: bool
    detail: str  # "reachable" or a short, secret-free error class name


class HealthResponse(BaseModel):
    """Overall health: 200 only when every dependency is reachable."""

    status: str  # "ok" | "degraded"
    postgres: DependencyHealth
    redis: DependencyHealth
