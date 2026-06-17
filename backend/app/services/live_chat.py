"""Live-chat cache (Redis) — decision 0006.

The live conversation (status + last ~10 messages) lives briefly in Redis, NOT
Postgres. Redis has NO row-level security, so tenant isolation is enforced
HERE, in the app layer:

  * every key is `chat:{business_id}:{phone_hash}` — business_id baked in, and
  * every accessor RE-CHECKS that the caller's verified business owns the key.

The accessor takes the already-verified `business_id` (from the request's auth
context), never a raw client value — so there is no path to read another
tenant's cache by passing a forged business id or a hand-built key.

What we keep: status (`bot`/`human`/`closed`), who's handling it, and the last
~10 messages. TTL is a sliding ~60 min: if the customer goes quiet the entry
expires and the conversation auto-closes (the old `close_stale_conversations`).
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

# Sliding inactivity window: silence for this long ⇒ the chat auto-closes.
CHAT_TTL_SECONDS = 60 * 60
# Only the most recent messages are kept in the cache; older ones roll off.
MAX_MESSAGES = 10


class CrossTenantCacheError(Exception):
    """Raised if a cache key's business prefix doesn't match the caller."""


def _key(business_id: str, phone_hash: str) -> str:
    return f"chat:{business_id}:{phone_hash}"


def _assert_owns(business_id: str, key: str) -> None:
    """Defense-in-depth: the key MUST start with this caller's business prefix."""
    expected_prefix = f"chat:{business_id}:"
    if not key.startswith(expected_prefix):
        raise CrossTenantCacheError("cache key does not belong to this business")


async def set_status(
    redis: aioredis.Redis,
    business_id: str,
    phone_hash: str,
    status: str,
    assigned_user_id: str | None = None,
) -> str:
    """Create/refresh a live chat's status. Returns the (tenant-scoped) key."""
    key = _key(business_id, phone_hash)
    _assert_owns(business_id, key)
    await redis.hset(key, mapping={
        "status": status,
        "assigned_user_id": assigned_user_id or "",
    })
    await redis.expire(key, CHAT_TTL_SECONDS)
    return key


async def append_message(
    redis: aioredis.Redis,
    business_id: str,
    phone_hash: str,
    role: str,
    body: str,
) -> None:
    """Append a message, keeping only the last MAX_MESSAGES, and slide the TTL."""
    key = _key(business_id, phone_hash)
    _assert_owns(business_id, key)
    msg = json.dumps({"role": role, "body": body})
    msgs_key = f"{key}:msgs"
    _assert_owns(business_id, msgs_key)
    await redis.rpush(msgs_key, msg)
    await redis.ltrim(msgs_key, -MAX_MESSAGES, -1)
    await redis.expire(key, CHAT_TTL_SECONDS)
    await redis.expire(msgs_key, CHAT_TTL_SECONDS)


async def get_chat(
    redis: aioredis.Redis, business_id: str, phone_hash: str
) -> dict[str, Any]:
    """Read a live chat (status + recent messages) for THIS business only.

    `business_id` must be the caller's already-verified business. Because the
    key is derived from it, there is no way to read another tenant's chat here.
    """
    key = _key(business_id, phone_hash)
    _assert_owns(business_id, key)
    meta = await redis.hgetall(key)
    raw_msgs = await redis.lrange(f"{key}:msgs", 0, -1)
    return {
        "status": meta.get("status"),
        "assigned_user_id": meta.get("assigned_user_id") or None,
        "messages": [json.loads(m) for m in raw_msgs],
    }
