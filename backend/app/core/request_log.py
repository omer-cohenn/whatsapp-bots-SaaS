"""One redacted access-log line per request (replaces uvicorn.access).

Why this exists: uvicorn's own access logger prints the RAW request line,
including the query string and any token embedded in the path. That leaks the
OAuth `code`+`state` (GET /auth/callback, GET /api/google/callback) and the
booking `cancel_token` (POST /api/book/{slug}/cancel/{token} and .../reschedule/
{token}). We silence uvicorn.access (see app/core/logging.py) and emit this ONE
structured line instead, carrying ONLY:

  - method            (GET/POST/...)
  - path              WITHOUT the query string, sensitive segments masked
  - status            the HTTP status code
  - duration_ms       how long the handler took

We deliberately do NOT log the client IP (not even coarsened) or any header.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request

from app.core.logging import get_logger

log = get_logger("app.request")

# Path segments whose FOLLOWING segment is a secret token to mask. Covers the
# public booking cancel/reschedule routes: /api/book/{slug}/cancel/{token} and
# /api/book/{slug}/reschedule/{token}.
_TOKEN_PARENT_SEGMENTS = frozenset({"cancel", "reschedule"})


def redact_path(path: str) -> str:
    """Return `path` with any cancel/reschedule token segment replaced by ***.

    Only the path is considered — the query string is never passed in here (the
    middleware logs `request.url.path`, which excludes `?...`). So OAuth code/
    state can't appear; this only masks tokens that live IN the path.
    """
    parts = path.split("/")
    for i, segment in enumerate(parts):
        if segment in _TOKEN_PARENT_SEGMENTS and i + 1 < len(parts) and parts[i + 1]:
            parts[i + 1] = "***"
    return "/".join(parts)


def install_request_logging(app: FastAPI) -> None:
    """Register the one-line redacted request logger on `app`."""

    @app.middleware("http")
    async def _log_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        # request.url.path is the path ONLY (no query string) → code/state never
        # reach the log; redact_path additionally masks any path token.
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": redact_path(request.url.path),
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
