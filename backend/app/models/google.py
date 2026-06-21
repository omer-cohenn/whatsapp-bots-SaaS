"""Response schemas for the M11 Google Calendar connect surface.

The frozen shapes the frontend builds against. Like all M11 models, there is NO
`business_id` here — the tenant always comes from the server session. The refresh
token / access token NEVER appear in any model (crown jewel; never serialized).
"""

from __future__ import annotations

from pydantic import BaseModel


class GoogleStatusResponse(BaseModel):
    """GET /api/google/status — is Google Calendar connected for this tenant?

    `email` is the connected Google account (null when not connected). `scope` is
    the granted OAuth scope string, for display/debug. No token is ever exposed.
    """

    connected: bool
    email: str | None = None
    scope: str | None = None


class GoogleConnectResponse(BaseModel):
    """GET /api/google/connect — the Google consent URL the owner is sent to.

    The frontend redirects the browser to `auth_url`. (We return JSON rather than
    a 302 so the SPA can drive the redirect itself, consistent with a fetch-based
    UI.)
    """

    auth_url: str


class GoogleDisconnectResponse(BaseModel):
    """POST /api/google/disconnect — confirms the credentials were removed."""

    connected: bool = False
