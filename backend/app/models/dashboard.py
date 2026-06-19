"""Pydantic models for the M7 READ / back-office API (the owner dashboard).

These are the frozen request/response shapes the frontend builds against. The
business id is NEVER part of any model here — it always comes from the server
session (`current_business`) + RLS, never from a body. Decrypted PII appears only
in RESPONSES, served to the authenticated owner of the tenant.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --- GET /api/leads ----------------------------------------------------------


class LeadItem(BaseModel):
    """One lead, decrypted for the owner, with ALL its collected answers."""

    id: str
    lead_name: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    # The full collected answers (decrypted). Owner sees everything — no hiding.
    answers: dict[str, Any] = Field(default_factory=dict)
    status: str
    last_step_index: int | None = None
    is_test: bool = False
    # The live conversation this lead belongs to (derived from cache_chat_ref);
    # None when the lead has no linked conversation. Lets the UI jump lead→chat.
    conversation_id: str | None = None
    started_at: str | None = None
    last_activity_at: str | None = None
    submitted_at: str | None = None


class LeadsResponse(BaseModel):
    """GET /api/leads response: this tenant's leads, newest first."""

    leads: list[LeadItem]


# --- PATCH /api/leads/{lead_id}/status ---------------------------------------


class LeadStatusRequest(BaseModel):
    """Owner-set a lead's status. Validated to the settable status set."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["new", "in_progress", "abandoned", "deal", "closed"]


class LeadStatusResponse(BaseModel):
    """Echo the lead + its new status after a successful change."""

    lead_id: str
    status: str


# --- GET /api/dashboard ------------------------------------------------------


class DashboardResponse(BaseModel):
    """GET /api/dashboard response: funnel counts for the period (real data only)."""

    period: str
    started: int
    completed: int
    abandoned: int
    total_leads: int
    # Orders = leads the owner marked as a won deal (status='deal') in the window.
    orders: int


# --- GET /api/conversations --------------------------------------------------


class ConversationItem(BaseModel):
    """One live conversation summary (from Redis), strictly business-scoped."""

    conversation_id: str
    status: str  # bot | waiting | human | closed
    last_activity_at: str | None = None
    preview: str = ""
    assigned_user_id: str | None = None


class ConversationsResponse(BaseModel):
    """GET /api/conversations response: live conversations, newest activity first."""

    conversations: list[ConversationItem]


# --- GET /api/conversations/{id} (+ /messages) -------------------------------


class MessageItem(BaseModel):
    """One transcript line (from Redis). `role` is who said it; never logged."""

    role: str  # customer | bot | owner
    body: str
    at: str | None = None


class ConversationDetail(BaseModel):
    """GET /api/conversations/{id}: status + linked lead + full transcript."""

    conversation_id: str
    status: str  # bot | waiting | human | closed
    lead: LeadItem | None = None
    messages: list[MessageItem] = Field(default_factory=list)


class MessagesResponse(BaseModel):
    """GET /api/conversations/{id}/messages: just the transcript, oldest first."""

    conversation_id: str
    messages: list[MessageItem] = Field(default_factory=list)


# --- POST /api/conversations/{id}/status -------------------------------------


class ConversationStatusRequest(BaseModel):
    """Set a conversation's status. `status` is validated to the allowed set."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["bot", "waiting", "human", "closed"]


class ConversationStatusResponse(BaseModel):
    """Echo the conversation + its new status after a successful change."""

    conversation_id: str
    status: str


# --- POST /api/conversations/{id}/reply --------------------------------------

# A manual reply is a short owner message; finite bound against oversized bodies.
MAX_REPLY_CHARS = 2000


class ConversationReplyRequest(BaseModel):
    """The owner's manual reply to a human-handled chat (queued; sent in M6)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(..., min_length=1, max_length=MAX_REPLY_CHARS)


class ConversationReplyResponse(BaseModel):
    """Acknowledge a queued reply."""

    conversation_id: str
    queued: bool


# --- PUT /api/bot/publish ----------------------------------------------------


class BotPublishRequest(BaseModel):
    """Focused go-live toggle for the bot."""

    model_config = ConfigDict(extra="forbid")

    is_published: bool


class BotPublishResponse(BaseModel):
    """Echo the published state after the toggle."""

    is_published: bool
