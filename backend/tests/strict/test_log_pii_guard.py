"""Log-PII guard — secrets, tokens and PII must never reach the log stream.

Drives representative requests through the REAL ASGI app (in-process, like
test_auth_gate.py) while capturing everything that reaches the JSON log handler,
then asserts the captured stream contains NONE of:

  - the OAuth `code` + `state`     (GET /auth/callback query string)
  - a booking `cancel_token`       (POST /api/book/{slug}/cancel/{token})
  - a customer phone number + the message text  (POST /webhook/whatsapp body)
  - the gateway service token       (the X-Gateway-Token header value)

This is the runtime backstop for the access-log leak fix (app/core/logging.py
silences uvicorn/gunicorn access logs; app/core/request_log.py logs a redacted
one-liner instead). If anyone re-introduces a raw request line or logs a body,
this goes red.
"""

from __future__ import annotations

import logging
import os
import secrets as _secrets
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.logging import JsonFormatter
from app.main import app

# Unique, unmistakable canaries so a match can only mean a real leak.
OAUTH_CODE = "LEAKCODE_" + _secrets.token_hex(6)
OAUTH_STATE = "LEAKSTATE_" + _secrets.token_hex(6)
CANCEL_TOKEN = "LEAKCANCELTOKEN_" + _secrets.token_hex(8)
CUSTOMER_PHONE = "+97250" + _secrets.token_hex(4)
MESSAGE_TEXT = "LEAKMESSAGEBODY_" + _secrets.token_hex(6)


@asynccontextmanager
async def _lifespan_app():
    async with app.router.lifespan_context(app):
        yield app


@pytest_asyncio.fixture
async def client():
    async with _lifespan_app():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


# Loggers that belong to the TEST DRIVER, not the app-under-test. httpx/httpcore
# log their own outbound request URL (query string included) — that's the test
# client talking to the in-process app, never something the real backend emits.
# We exclude them so the guard measures ONLY the application's log stream.
_NON_APP_LOGGER_PREFIXES = ("httpx", "httpcore", "asyncio", "urllib3")


class _Capture(logging.Handler):
    """Collects the ACTUAL serialized JSON lines the app would emit to stdout."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.split(".")[0] in _NON_APP_LOGGER_PREFIXES:
            return
        self.lines.append(self.format(record))


@pytest_asyncio.fixture
def captured_logs():
    """Attach a capturing handler to the root logger for the duration of a test."""
    handler = _Capture()
    root = logging.getLogger()
    prev_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(prev_level)


async def test_no_secrets_or_pii_in_logs(client, captured_logs):
    gateway_token = os.environ["GATEWAY_API_TOKEN"]

    # 1) OAuth callback — code + state live in the query string.
    await client.get(
        f"/auth/callback?code={OAUTH_CODE}&state={OAUTH_STATE}"
    )

    # 2) Booking cancel — the token lives in the path.
    await client.post(f"/api/book/some-slug/cancel/{CANCEL_TOKEN}")

    # 3) Webhook — carries a phone + message text in the body. A random
    #    gateway_account_id maps to no business, so the bot stays silent; the
    #    point is that the phone/text/token never reach the log.
    await client.post(
        "/webhook/whatsapp",
        headers={"X-Gateway-Token": gateway_token},
        json={
            "gateway_account_id": "unmapped-" + _secrets.token_hex(8),
            "from": CUSTOMER_PHONE,
            "push_name": "Leaky Customer",
            "message_id": "wamid." + _secrets.token_hex(6),
            "type": "text",
            "text": MESSAGE_TEXT,
        },
    )

    blob = "\n".join(captured_logs.lines)
    # Sanity: we actually captured the redacted request lines (guard isn't a no-op).
    assert '"app.request"' in blob or "request" in blob, "no logs captured — check wiring"

    forbidden = {
        "oauth code": OAUTH_CODE,
        "oauth state": OAUTH_STATE,
        "cancel token": CANCEL_TOKEN,
        "customer phone": CUSTOMER_PHONE,
        "message text": MESSAGE_TEXT,
        "gateway token": gateway_token,
    }
    leaked = [label for label, value in forbidden.items() if value in blob]
    assert not leaked, f"log stream leaked: {', '.join(leaked)}"
