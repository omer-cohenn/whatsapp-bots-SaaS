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
from datetime import datetime, timezone
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


def _index_key(business_id: str) -> str:
    """Per-business index set of this tenant's conversation ids (for listing).

    See `list_conversations` for why we keep an explicit index instead of SCANning
    the whole keyspace. The key itself is business-prefixed, so the set can never
    name another tenant's conversation.
    """
    return f"convindex:{business_id}"


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
    await _register(redis, business_id, conversation_id)
    return key


async def clear_state(
    redis: aioredis.Redis, business_id: str, conversation_id: str
) -> None:
    """Delete this conversation's persisted state + status entirely."""
    key = _key(business_id, conversation_id)
    _assert_owns(business_id, key)
    await redis.delete(key)
    await redis.srem(_index_key(business_id), conversation_id)


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
    await redis.hset(key, mapping={"status": status, "last_activity_at": _now_iso()})
    await redis.expire(key, CONVERSATION_TTL_SECONDS)
    await _register(redis, business_id, conversation_id)
    return key


# --- listing + preview + manual reply (M7 dashboard) ------------------------

async def list_conversations(
    redis: aioredis.Redis,
    business_id: str,
    *,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List THIS tenant's live conversations (status + last-activity + preview).

    Listing choice (documented): we keep a per-business INDEX SET
    (`convindex:{business_id}`) that every write registers the conversation in,
    and read the set here — instead of `SCAN conv:{business_id}:*` over the whole
    Redis keyspace. Why: SCAN cost grows with the GLOBAL keyspace (all tenants'
    keys), so a busy neighbour would slow one owner's dashboard; the index set is
    O(this tenant's conversations) and its key is itself business-prefixed, so it
    can never name another tenant's conversation. Entries whose hash has expired
    (TTL) are pruned from the index lazily on read.

    `status` (optional) filters to 'bot' | 'human' | 'closed'. Results are sorted
    newest-activity first. Strictly business-scoped: every per-conversation read
    goes through `_assert_owns`.
    """
    index = _index_key(business_id)
    conv_ids = await redis.smembers(index)

    items: list[dict[str, Any]] = []
    stale: list[str] = []
    for conv_id in conv_ids:
        key = _key(business_id, conv_id)
        _assert_owns(business_id, key)
        meta = await redis.hgetall(key)
        if not meta:
            # The conversation hash expired (TTL) but lingered in the index → prune.
            stale.append(conv_id)
            continue
        conv_status = meta.get("status") or STATUS_BOT
        if status and conv_status != status:
            continue
        items.append({
            "conversation_id": conv_id,
            "status": conv_status,
            "last_activity_at": meta.get("last_activity_at"),
            "preview": meta.get("preview") or "",
            "assigned_user_id": meta.get("assigned_user_id") or None,
        })

    if stale:
        await redis.srem(index, *stale)

    # Newest activity first; missing timestamps sort last.
    items.sort(key=lambda c: c["last_activity_at"] or "", reverse=True)
    return items


async def append_reply(
    redis: aioredis.Redis,
    business_id: str,
    conversation_id: str,
    text: str,
) -> None:
    """Queue an owner's manual reply on THIS conversation (M6 will actually send it).

    For now we record the reply on the live conversation: it becomes the preview,
    bumps last-activity, and is pushed onto a per-conversation outbound queue so
    the future WhatsApp sender (M6) can drain it. Tenant-scoped + TTL-refreshed.
    We NEVER log the reply text.
    """
    key = _key(business_id, conversation_id)
    _assert_owns(business_id, key)
    outbox = f"{key}:outbox"
    _assert_owns(business_id, outbox)
    msg = json.dumps({"role": "owner", "body": text, "at": _now_iso()},
                     ensure_ascii=False)
    await redis.rpush(outbox, msg)
    await redis.hset(key, mapping={"preview": _preview(text), "last_activity_at": _now_iso()})
    await redis.expire(key, CONVERSATION_TTL_SECONDS)
    await redis.expire(outbox, CONVERSATION_TTL_SECONDS)
    await _register(redis, business_id, conversation_id)


# --- internal helpers -------------------------------------------------------

async def _register(
    redis: aioredis.Redis, business_id: str, conversation_id: str
) -> None:
    """Add a conversation to this tenant's index set (TTL-refreshed)."""
    index = _index_key(business_id)
    await redis.sadd(index, conversation_id)
    await redis.expire(index, CONVERSATION_TTL_SECONDS)


def _preview(text: str, limit: int = 80) -> str:
    """A short, single-line preview of a message (never logged)."""
    one_line = " ".join(text.split())
    return one_line[:limit]


def _now_iso() -> str:
    """Current UTC time as an ISO-8601 string (stored on the conv hash)."""
    return datetime.now(timezone.utc).isoformat()
