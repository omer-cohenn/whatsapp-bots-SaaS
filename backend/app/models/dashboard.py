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
    # WHY the conversation closed (decision 0021): 'completed' | 'abandoned' |
    # 'answered' | None (not closed yet). Structural label, separate from the
    # owner's status outcome above; the UI maps it to a Hebrew close-reason label.
    close_reason: str | None = None
    # The owner's outcome note (decrypted), e.g. why a deal closed; None if unset.
    outcome_note: str | None = None
    last_step_index: int | None = None
    is_test: bool = False
    # The live conversation this lead belongs to (derived from cache_chat_ref);
    # None when the lead has no linked conversation. Lets the UI jump lead→chat.
    conversation_id: str | None = None
    started_at: str | None = None
    last_activity_at: str | None = None
    submitted_at: str | None = None
    # When the owner dismissed this lead from the home feed (decision 0022).
    feed_seen_at: str | None = None


class LeadsResponse(BaseModel):
    """GET /api/leads response: this tenant's leads, newest first."""

    leads: list[LeadItem]


# --- PATCH /api/leads/{lead_id}/status ---------------------------------------


# An outcome note is a short owner message; finite bound against oversized bodies.
MAX_NOTE_CHARS = 2000


class LeadSeenResponse(BaseModel):
    """POST /api/leads/{id}/seen — confirms the lead was marked as seen."""
    lead_id: str


class LeadsSeenAllResponse(BaseModel):
    """POST /api/leads/seen-all — how many leads were marked as seen."""
    count: int


class LeadDeleteResponse(BaseModel):
    """DELETE /api/leads/{id} — always empty; status 204 is the signal."""


class LeadStatusRequest(BaseModel):
    """Owner-set a lead's status. Validated to the settable status set.

    `note` is OPTIONAL on the API (the UI requires it for deal/closed, but the
    contract accepts it for any status). When present it is encrypted at rest into
    the lead's `outcome_note`. Whitespace-stripped; bounded length.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: Literal["new", "in_progress", "abandoned", "deal", "closed"]
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)


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
    # Meetings = non-cancelled bookings created in the window (the home "פגישות" card).
    meetings: int


# --- GET /api/conversations --------------------------------------------------


class ConversationItem(BaseModel):
    """One live conversation summary (from Redis), strictly business-scoped."""

    conversation_id: str
    status: str  # bot | waiting | human | closed
    last_activity_at: str | None = None
    preview: str = ""
    assigned_user_id: str | None = None
    # M18 — the customer's name + phone, joined from the linked lead so the inbox
    # can show a real name and an initials avatar per row (the Redis conversation
    # record holds neither). Both are DECRYPTED for the owner and are PII: they
    # must never be logged. None when the conversation has no lead yet (the
    # customer messaged but never started a flow) — the UI falls back to the
    # phone, then to a neutral placeholder.
    contact_name: str | None = None
    phone: str | None = None
    # WhatsApp-style unread badge (decision 0021): inbound CUSTOMER messages the
    # owner hasn't read on THIS conversation. Reset to 0 when the owner opens it.
    unread: int = 0


class ConversationsResponse(BaseModel):
    """GET /api/conversations response: live conversations, newest activity first."""

    conversations: list[ConversationItem]
    # Sum of `unread` across this tenant's conversations — the single number the
    # dashboard renders as a green badge over the "שיחות" tab (decision 0021).
    unread_total: int = 0


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
    """Acknowledge a queued reply.

    `delivered` (M6a.2) is the best-effort WhatsApp send result on TOP of the
    queue: the reply is ALWAYS queued (`queued=True`); `delivered` is True only
    when the gateway confirmed it actually sent the message. Backward-compatible:
    defaults to False, so older clients that ignore it still see `queued`.
    """

    conversation_id: str
    queued: bool
    delivered: bool = False


# --- PUT /api/bot/publish ----------------------------------------------------


class BotPublishRequest(BaseModel):
    """Focused go-live toggle for the bot."""

    model_config = ConfigDict(extra="forbid")

    is_published: bool


class BotPublishResponse(BaseModel):
    """Echo the published state after the toggle."""

    is_published: bool
