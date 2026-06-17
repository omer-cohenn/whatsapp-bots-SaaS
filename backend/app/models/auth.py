"""Response schemas for the auth + /api/me surface.

These mirror the FROZEN /api/me contract the frontend is built against:

    { user:{id,email,name,picture}, business:{id,name}, connection:{status} }
"""

from __future__ import annotations

from pydantic import BaseModel


class MeUser(BaseModel):
    """The authenticated user's public profile (no tokens, no secrets)."""

    id: str
    email: str
    name: str
    picture: str


class MeBusiness(BaseModel):
    """The user's tenant (verified server-side, never from the client)."""

    id: str
    name: str


class MeConnection(BaseModel):
    """WhatsApp connection status for the business (QR connect is a later milestone)."""

    status: str  # e.g. "disconnected" | "connected" | "connecting"


class MeResponse(BaseModel):
    """GET /api/me — who am I + which tenant + WhatsApp status."""

    user: MeUser
    business: MeBusiness
    connection: MeConnection
