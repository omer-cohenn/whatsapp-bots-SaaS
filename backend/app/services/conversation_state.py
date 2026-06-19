"""Conversation persistence (Redis) — the bot's short-term notebook (M5).

The pure engine (`app/services/bot_engine.py`) is stateless: each turn it is HANDED
the current conversation state and returns the next one. SOMETHING has to remember
that state between messages — that's this module. We keep it in Redis (not Postgres)
for the same reason as the live chat cache (decision 0006): it's ephemeral, hot, and
auto-expires when a customer goes quiet.

We store two things per conversation:
  * the engine `ConvState` (the dict shaped by `bot_engine.initial_state()`), and
  * a `chat_status` — 'bot' (the engine is driving), 'human' (handed off to a
    person, engine paused), or 'closed' (finished/expired).

Tenant isolation lives in the APP layer (decision 0006): Redis has no row-level
security, so `business_id` is ALWAYS baked into the key AND re-checked on every
accessor (mirrors `live_chat.py`). The caller passes an already-verified
`business_id` (from the request's auth context), never a raw client value, so
there is no path to read/write another tenant's conversation.

TTL is a sliding ~60 minutes: every write refreshes it; if the customer goes
silent the entry expires and the conversation is effectively closed.
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

# Sliding inactivity window: silence for this long ⇒ the conversation expires.
CONVERSATION_TTL_SECONDS = 60 * 60

# The chat statuses we persist (kept tiny + explicit on purpose).
STATUS_BOT = "bot"
STATUS_HUMAN = "human"
STATUS_CLOSED = "closed"
_VALID_STATUSES = {STATUS_BOT, STATUS_HUMAN, STATUS_CLOSED}


class CrossTenantConversationError(Exception):
    """Raised if a conversation key's business prefix doesn't match the caller."""


def _key(business_id: str, conversation_id: str) -> str:
    """The tenant-scoped Redis key for one conversation's state + status."""
    return f"conv:{business_id}:{conversation_id}"


def _assert_owns(business_id: str, key: str) -> None:
    """Defense-in-depth: the key MUST start with this caller's business prefix."""
    expected_prefix = f"conv:{business_id}:"
    if not key.startswith(expected_prefix):
        raise CrossTenantConversationError(
            "conversation key does not belong to this business"
        )


# --- engine ConvState -------------------------------------------------------

async def get_state(
    redis: aioredis.Redis, business_id: str, conversation_id: str
) -> dict[str, Any] | None:
    """Load the engine state for THIS business's conversation, or None if absent.

    None means "no saved turn yet" — the caller should fall back to
    `bot_engine.initial_state()`. (We don't import the engine here to keep this
    module free of any flow logic.)
    """
    key = _key(business_id, conversation_id)
    _assert_owns(business_id, key)
    raw = await redis.hget(key, "state")
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        # A corrupt/unreadable blob is treated as "no state" rather than crashing
        # the turn; the caller will reset to the initial state.
        return None
    return value if isinstance(value, dict) else None


async def set_state(
    redis: aioredis.Redis,
    business_id: str,
    conversation_id: str,
    state: dict[str, Any],
) -> str:
    """Persist the engine state for THIS conversation and slide the TTL.

    Returns the (tenant-scoped) key. The `state` is the dict the engine returned;
    it carries only the conversation's OWN inputs, never another tenant's data.
    """
    key = _key(business_id, conversation_id)
    _assert_owns(business_id, key)
    await redis.hset(key, "state", json.dumps(state, ensure_ascii=False))
    await redis.expire(key, CONVERSATION_TTL_SECONDS)
    return key


async def clear_state(
    redis: aioredis.Redis, business_id: str, conversation_id: str
) -> None:
    """Delete this conversation's persisted state + status entirely."""
    key = _key(business_id, conversation_id)
    _assert_owns(business_id, key)
    await redis.delete(key)


# --- chat status ------------------------------------------------------------

async def get_status(
    redis: aioredis.Redis, business_id: str, conversation_id: str
) -> str | None:
    """Read the chat status ('bot'|'human'|'closed') for THIS conversation.

    None means no status has been set yet (a brand-new conversation).
    """
    key = _key(business_id, conversation_id)
    _assert_owns(business_id, key)
    return await redis.hget(key, "status")


async def set_status(
    redis: aioredis.Redis,
    business_id: str,
    conversation_id: str,
    status: str,
) -> str:
    """Set the chat status for THIS conversation and slide the TTL.

    Returns the (tenant-scoped) key. `status` must be one of 'bot'|'human'|'closed';
    anything else is a programming error and is rejected loudly.
    """
    if status not in _VALID_STATUSES:
        raise ValueError(f"invalid chat status: {status!r}")
    key = _key(business_id, conversation_id)
    _assert_owns(business_id, key)
    await redis.hset(key, "status", status)
    await redis.expire(key, CONVERSATION_TTL_SECONDS)
    return key
