"""Structured (JSON) logging.

Hard rule for this build: logs NEVER carry secrets, the gateway token, a QR,
message bodies, or phone numbers. The formatter here only serializes the log
message plus a small allow-list of `extra` fields; callers are responsible for
passing redacted values only (see app/api/webhook.py for the receive spike).
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import sys
from typing import Any

# Standard LogRecord attributes we never want duplicated in the JSON `extra`.
_RESERVED = set(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter (no third-party dep needed)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": _dt.datetime.fromtimestamp(
                record.created, tz=_dt.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Promote explicitly-attached structured fields (e.g. logger.info(..., extra=...)).
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON formatter on the root logger (idempotent)."""

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn/gunicorn ERROR logs flow through these; let them propagate to the
    # root JSON handler instead of their own plain formatters. These carry no
    # request line, so they cannot leak a query string / path token.
    for name in ("uvicorn", "uvicorn.error", "gunicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    # SECURITY: the access loggers emit the raw request line INCLUDING the query
    # string (e.g. /auth/callback?code=...&state=...) and any token in the path
    # (booking cancel/reschedule). That leaks OAuth code+state and cancel_tokens
    # into the logs. We SILENCE them entirely and replace them with the redacting
    # request-log middleware in app/main.py, which logs method + path (no query,
    # token segments masked) + status + duration only. gunicorn.access is silenced
    # too for the prod image (gunicorn --access-logfile -), even though the current
    # worker routes access lines through uvicorn.access.
    for name in ("uvicorn.access", "gunicorn.access"):
        access = logging.getLogger(name)
        access.handlers.clear()
        access.propagate = False
        access.disabled = True


def get_logger(name: str) -> logging.Logger:
    """Convenience accessor so callers don't import `logging` directly."""

    return logging.getLogger(name)
