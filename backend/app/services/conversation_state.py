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

TTL DEPENDS ON STATUS (decision 0010) — the transcript must NOT vanish while a
human is needed:
  * bot     → sliding 72-HOUR inactivity window (M19; was 30 minutes).
  * waiting → PERSIST (no expiry): the customer asked for a human; keep the chat
              alive until a person answers.
  * human   → PERSIST (no expiry): an owner is handling it; keep it alive.
  * closed  → 30-day window, then swept.
This is centralized in `_apply_ttl`, called by BOTH `set_status` and
`append_message` so a new message can never resurrect a TTL on a chat that should
persist.

ENCRYPTED AT REST (M19). Message bodies and the inbox preview are customer words,
so they are Fernet-encrypted with the same PII key the leads use before they are
written; Redis stores ciphertext only. See `_enc`/`_dec` below. Redis is also
configured with `appendonly yes` so a restart no longer wipes every live
conversation, and `noeviction` so nothing is silently dropped under memory
pressure — a retention promise that could be evicted would not be a promise.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from app.core import crypto

# Sliding inactivity window: silence for this long ⇒ the conversation expires.
#
# M19: raised from 30 MINUTES to 72 HOURS. The old window was the bot's working
# memory, but the same key also holds the transcript the OWNER reads — so a quiet
# chat evaporated within half an hour and the owner lost the record of it. 72h is
# the retention the owner asked for.
#
# Note this is a SLIDING window, refreshed on each message, so 72h is a floor
# measured from the LAST activity, not from the start of the conversation.
CONVERSATION_TTL_SECONDS = 72 * 60 * 60

# A CLOSED conversation lingers this long before it's swept (kept so the owner can
# still review a finished chat for a while). 30 days.
CLOSED_TTL_SECONDS = 30 * 24 * 60 * 60

# The chat statuses we persist (kept tiny + explicit on purpose).
STATUS_BOT = "bot"          # the engine is driving.
STATUS_WAITING = "waiting"  # customer asked for a human; nobody has picked up yet.
STATUS_HUMAN = "human"      # an owner took over; the engine is paused.
STATUS_CLOSED = "closed"    # finished/expired.
# The bot must stay SILENT in 'waiting' and 'human' (see bot_runtime.run_turn).
_VALID_STATUSES = {STATUS_BOT, STATUS_WAITING, STATUS_HUMAN, STATUS_CLOSED}

# The conversation transcript roles (who said a line). Kept explicit so a bad
# value is rejected rather than silently stored.
_VALID_ROLES = {"customer", "bot", "owner"}

# Keep at most this many messages in a conversation's transcript (LTRIM bound).
TRANSCRIPT_MAX = 200


# --- message-body encryption (M19) -------------------------------------------
#
# Conversation bodies are what the CUSTOMER actually wrote on WhatsApp, so they
# are PII and are encrypted at rest with the same PII key the leads use. Redis
# holds ciphertext only; plaintext exists only inside this process.
#
# This closes the last plaintext store in the system: leads, lead files and the
# WhatsApp credentials were already encrypted, conversations were not.
#
# Two fields carry customer words and both go through here: the transcript
# `body`, and the `preview` denormalized onto the conversation hash for the inbox
# list.

# Marks a value as ciphertext written by THIS scheme. Needed because Redis will
# hold pre-M19 plaintext rows until they age out (≤72h), and a transcript that
# spans the upgrade must stay readable rather than turn into error text.
_ENC_PREFIX = "enc1:"


def _enc(text: str | None) -> str:
    """Encrypt one customer-authored string for storage. '' stays ''."""
    if not text:
        return ""
    return _ENC_PREFIX + crypto.encrypt_pii(text)


def _dec(stored: str | None) -> str:
    """Decrypt a stored body/preview, tolerating pre-M19 plaintext.

    A value without our prefix is legacy plaintext and is returned as-is — the
    alternative would be showing the owner an error for every message written
    before the upgrade.

    A value WITH the prefix that fails to decrypt is a real problem (wrong key,
    corruption), but it must not take down the whole transcript, so it degrades
    to a visible placeholder for that one line. This is the ONE place we soften
    `decrypt_pii`'s loud contract, and only for display.
    """
    if not stored:
        return ""
    if not stored.startswith(_ENC_PREFIX):
        return stored
    try:
        return crypto.decrypt_pii(stored[len(_ENC_PREFIX):]) or ""
    except crypto.DecryptionError:
        return "[הודעה שלא ניתן לפענח]"


class CrossTenantConversationError(Exception):
    """Raised if a conversation key's business prefix doesn't match the caller."""


def _key(business_id: str, conversation_id: str) -> str:
    """The tenant-scoped Redis key for one conversation's state + status."""
    return f"conv:{business_id}:{conversation_id}"


def _log_key(business_id: str, conversation_id: str) -> str:
    """The tenant-scoped Redis LIST key for one conversation's transcript.

    A list of JSON {role, body, at} lines, oldest→newest, capped at TRANSCRIPT_MAX.
    Business-prefixed exactly like `_key`, so it can never name another tenant's
    transcript; `_assert_owns` re-checks the prefix on every accessor.
    """
    return f"conv:{business_id}:{conversation_id}:log"


def _unread_key(business_id: str, conversation_id: str) -> str:
    """Tenant-scoped Redis key for one conversation's unread counter (decision 0021).

    A WhatsApp-style badge: how many inbound CUSTOMER messages the owner has not
    yet read on this conversation. A plain integer string. Business-prefixed
    exactly like `_key`, so it can never name another tenant's counter;
    `_assert_owns` re-checks the prefix on every accessor. Same TTL discipline as
    the conversation (it must not outlive the chat) — see `_apply_ttl`.
    """
    return f"conv:{business_id}:{conversation_id}:unread"


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


async def reset_conversation(
    redis: aioredis.Redis, business_id: str, conversation_id: str
) -> None:
    """Wipe a conversation back to brand-new so the next inbound starts fresh.

    Deletes ALL three Redis keys for this conversation:
      * the conv hash (status + last-activity + preview)  → `_key`
      * the engine state lives inside that same hash field → cleared with it
      * the transcript LIST                                → `_log_key`
    and drops it from this tenant's index set.

    After this, `get_state` → None (engine falls back to `initial_state()`),
    `get_status` → None (callers treat None as the default 'bot'), and the
    transcript is empty — i.e. exactly the state of a conversation that has
    never been seen. Used when a CLOSED chat receives a new inbound, so the
    customer effectively begins a clean new conversation (the old closed lead
    row stays in Postgres untouched, preserving history).

    Tenant-isolated: `_assert_owns` is re-checked on both per-conversation keys;
    `business_id` is the caller's verified id, never client-supplied.
    """
    key = _key(business_id, conversation_id)
    log_key = _log_key(business_id, conversation_id)
    unread_key = _unread_key(business_id, conversation_id)
    _assert_owns(business_id, key)
    _assert_owns(business_id, log_key)
    _assert_owns(business_id, unread_key)
    # Delete the hash (carries both status AND the engine `state` field), the
    # transcript list, and the unread counter, then unregister from the index set.
    await redis.delete(key, log_key, unread_key)
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


async def get_last_activity_at(
    redis: aioredis.Redis, business_id: str, conversation_id: str
) -> str | None:
    """Return the ISO-8601 timestamp of the last activity on this conversation, or None."""
    key = _key(business_id, conversation_id)
    _assert_owns(business_id, key)
    return await redis.hget(key, "last_activity_at")


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
    await _register(redis, business_id, conversation_id)
    # Apply the TTL policy for the NEW status (persist for waiting/human, slide for
    # bot, 30-day for closed) — NOT a flat 30-min expire (decision 0010).
    await _apply_ttl(redis, business_id, conversation_id, status)
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
            "preview": _dec(meta.get("preview")),
            "assigned_user_id": meta.get("assigned_user_id") or None,
            # Per-conversation unread count (decision 0021) — 0 when none/read.
            "unread": await get_unread(redis, business_id, conv_id),
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
    # Encrypted like the transcript (M19). Nothing drains this queue today — the
    # real send goes through whatsapp.send_outbound — but it still holds message
    # text, so it is not left as the one plaintext leftover.
    msg = json.dumps({"role": "owner", "body": _enc(text), "at": _now_iso()},
                     ensure_ascii=False)
    await redis.rpush(outbox, msg)
    await redis.hset(
        key,
        mapping={"preview": _enc(_preview(text)), "last_activity_at": _now_iso()},
    )
    await redis.expire(key, CONVERSATION_TTL_SECONDS)
    await redis.expire(outbox, CONVERSATION_TTL_SECONDS)
    await _register(redis, business_id, conversation_id)
    # Mirror the owner's reply into the shared transcript so the in-app chat view
    # and the (future) WhatsApp outbox stay in sync — same key both sides read.
    await append_message(redis, business_id, conversation_id, "owner", text)


# --- transcript (M8 in-app human-handoff chat) ------------------------------

async def append_message(
    redis: aioredis.Redis,
    business_id: str,
    conversation_id: str,
    role: str,
    body: str,
) -> None:
    """Append one line to THIS conversation's transcript (tenant-scoped, TTL'd).

    Pushes a JSON {role, body, at} onto the per-conversation LIST, then LTRIMs to
    the last TRANSCRIPT_MAX so the log can't grow without bound. Also bumps the
    conversation hash's `preview` + `last_activity_at`, refreshes the TTL on BOTH
    the list and the hash, and (re)registers the conversation in this tenant's
    index so it shows up in the dashboard. `role` must be customer|bot|owner.

    Tenant-isolated: `_assert_owns` is checked on both keys; `business_id` is the
    caller's verified id, never client-supplied. We NEVER log the message body.
    """
    if role not in _VALID_ROLES:
        raise ValueError(f"invalid transcript role: {role!r}")

    key = _key(business_id, conversation_id)
    log_key = _log_key(business_id, conversation_id)
    _assert_owns(business_id, key)
    _assert_owns(business_id, log_key)

    # The body is encrypted BEFORE it touches Redis; role/timestamp stay clear so
    # the transcript can still be ordered and filtered without decrypting.
    line = json.dumps({"role": role, "body": _enc(body), "at": _now_iso()},
                      ensure_ascii=False)
    await redis.rpush(log_key, line)
    # Keep only the last TRANSCRIPT_MAX entries (negative indices = from the tail).
    await redis.ltrim(log_key, -TRANSCRIPT_MAX, -1)
    await redis.hset(
        key,
        mapping={
            # The preview is customer text too — truncate FIRST, then encrypt, so
            # only the shown fragment is stored at all.
            "preview": _enc(_preview(body)),
            "last_activity_at": _now_iso(),
        },
    )
    await _register(redis, business_id, conversation_id)
    # Apply the TTL policy for the CURRENT status, NOT an unconditional 30-min
    # expire — otherwise a new message would resurrect a TTL on a waiting/human
    # chat that must PERSIST (decision 0010). Default to 'bot' if none set yet.
    current_status = await redis.hget(key, "status") or STATUS_BOT
    await _apply_ttl(redis, business_id, conversation_id, current_status)


async def get_messages(
    redis: aioredis.Redis, business_id: str, conversation_id: str
) -> list[dict[str, Any]]:
    """Return THIS conversation's transcript, oldest→newest (empty if none).

    Each item is {role, body, at}. A single corrupt/unreadable entry is skipped
    rather than failing the whole read. Tenant-scoped via `_assert_owns`.
    """
    log_key = _log_key(business_id, conversation_id)
    _assert_owns(business_id, log_key)
    raw_items = await redis.lrange(log_key, 0, -1)

    messages: list[dict[str, Any]] = []
    for raw in raw_items:
        try:
            item = json.loads(raw)
        except (ValueError, TypeError):
            # Tolerate a single bad line — never let it break the transcript view.
            continue
        if isinstance(item, dict):
            item["body"] = _dec(item.get("body"))
            messages.append(item)
    return messages


# --- unread counter (M / decision 0021 — WhatsApp-style badge) --------------

async def incr_unread(
    redis: aioredis.Redis, business_id: str, conversation_id: str
) -> int:
    """Bump this conversation's unread counter by 1 and return the new value.

    Called on EVERY inbound CUSTOMER message (both the silent waiting/human path
    AND the normal bot path in run_turn) — "unread" means the OWNER hasn't opened
    the chat yet, regardless of who is answering. The counter inherits the SAME
    TTL as the live conversation (via the current status' policy) so it can never
    outlive the chat. Tenant-scoped: `_assert_owns` re-checks the prefix;
    `business_id` is the caller's verified id, never client-supplied.
    """
    key = _key(business_id, conversation_id)
    unread_key = _unread_key(business_id, conversation_id)
    _assert_owns(business_id, key)
    _assert_owns(business_id, unread_key)
    new_value = await redis.incr(unread_key)
    # Match the conversation's TTL policy so the counter expires WITH the chat.
    current_status = await redis.hget(key, "status") or STATUS_BOT
    if current_status in (STATUS_WAITING, STATUS_HUMAN):
        await redis.persist(unread_key)
    else:
        ttl = CLOSED_TTL_SECONDS if current_status == STATUS_CLOSED else CONVERSATION_TTL_SECONDS
        await redis.expire(unread_key, ttl)
    return int(new_value)


async def mark_read(
    redis: aioredis.Redis, business_id: str, conversation_id: str
) -> None:
    """Reset this conversation's unread counter to 0 (owner opened/read the chat).

    Wired into the single-conversation read (GET /api/conversations/{id}); opening
    a chat clears its badge, exactly like WhatsApp. Tenant-scoped via `_assert_owns`.
    """
    unread_key = _unread_key(business_id, conversation_id)
    _assert_owns(business_id, unread_key)
    await redis.delete(unread_key)


async def get_unread(
    redis: aioredis.Redis, business_id: str, conversation_id: str
) -> int:
    """Return this conversation's unread count (0 if unset). Tenant-scoped."""
    unread_key = _unread_key(business_id, conversation_id)
    _assert_owns(business_id, unread_key)
    raw = await redis.get(unread_key)
    try:
        return int(raw) if raw is not None else 0
    except (ValueError, TypeError):
        return 0


async def unread_total(redis: aioredis.Redis, business_id: str) -> int:
    """Sum the unread counts across ALL of THIS tenant's live conversations.

    Reads the per-business index set (same source as `list_conversations`) and
    sums each conversation's unread counter — so the dashboard can render one
    badge over the "שיחות" tab. O(this tenant's conversations); strictly
    business-scoped (`_assert_owns` on every per-conversation key).
    """
    conv_ids = await redis.smembers(_index_key(business_id))
    total = 0
    for conv_id in conv_ids:
        total += await get_unread(redis, business_id, conv_id)
    return total


# --- internal helpers -------------------------------------------------------

async def _apply_ttl(
    redis: aioredis.Redis,
    business_id: str,
    conversation_id: str,
    status: str,
) -> None:
    """Apply the status-driven TTL to a conversation's keys (decision 0010).

    Keeps the conv hash key, its `:log` transcript list, AND this tenant's index
    set consistent:
      * waiting / human → PERSIST all three (no expiry) — a human is (or will be)
        on it, so the transcript must not disappear.
      * bot             → slide all three to CONVERSATION_TTL_SECONDS (~30 min).
      * closed          → set all three to CLOSED_TTL_SECONDS (30 days).

    Tenant-scoped: `_assert_owns` is re-checked on the conv + log keys; the index
    key is itself business-prefixed. `status` is one of the persisted statuses;
    an unknown value falls back to the bot (sliding) policy defensively.
    """
    key = _key(business_id, conversation_id)
    log_key = _log_key(business_id, conversation_id)
    unread_key = _unread_key(business_id, conversation_id)
    index = _index_key(business_id)
    _assert_owns(business_id, key)
    _assert_owns(business_id, log_key)
    _assert_owns(business_id, unread_key)

    if status in (STATUS_WAITING, STATUS_HUMAN):
        # PERSIST: drop any expiry so the chat survives until a human answers.
        await redis.persist(key)
        await redis.persist(log_key)
        # The unread badge must persist alongside the chat (only expire/persist
        # if the counter actually exists — `persist` on a missing key is a no-op).
        await redis.persist(unread_key)
        await redis.persist(index)
        return

    ttl = CLOSED_TTL_SECONDS if status == STATUS_CLOSED else CONVERSATION_TTL_SECONDS
    await redis.expire(key, ttl)
    await redis.expire(log_key, ttl)
    # Keep the unread counter on the same TTL clock as the chat (no-op if absent).
    await redis.expire(unread_key, ttl)
    await redis.expire(index, ttl)


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
