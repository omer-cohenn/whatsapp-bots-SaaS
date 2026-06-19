"""M10 — the narrated, baby-language test (read this one).

M10 has two promises (decision 0010):

  1) THE TRANSCRIPT MUST NOT VANISH WHILE A HUMAN IS NEEDED.
     A live chat in Redis normally fades after ~60 minutes of silence. But once a
     customer asks for a human (status 'waiting') or an owner takes over (status
     'human'), the chat must STAY until someone answers — it must PERSIST (no
     timer). When it's finally 'closed', it lingers 30 days, then is swept.
     The sneaky bug M10 kills: every new message used to slam a fresh 60-min timer
     back on the chat — which would quietly delete a 'waiting' transcript on the
     NEXT message. We prove that can't happen anymore.

  2) THE OWNER'S OUTCOME NOTE IS PRIVATE.
     When the owner marks a lead as a deal/closed, they jot a short "what happened"
     note. That note is sensitive, so it is ENCRYPTED in the database (the raw
     column is gibberish) and only DECRYPTED for the owner who owns it. Another
     business can never read or write it.

Each check prints: what we're testing, why it matters, and a clear pass/fail. A
scoreboard prints at the end. Nothing here prints a secret, a token, or PII.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time

import asyncpg
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import conversation_state as cs
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella
AVI_USER = "google-sub-avi"

_passed = 0
_failed = 0


def check(name: str, why: str, ok: bool) -> None:
    global _passed, _failed
    print(f"\n🧪 {name}")
    print(f"   💡 {why}")
    if ok:
        _passed += 1
        print("   ✅ PASS")
    else:
        _failed += 1
        print("   ❌ FAIL")


async def _login(rds, http, business_id: str) -> None:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": AVI_USER, "email": "x@example.com", "name": "x", "picture": "",
        "business_id": business_id, "business_name": "x", "created_at": int(time.time()),
    }
    await rds.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)


async def _seed_lead(pool, business_id: str, status: str) -> str:
    async with tenant_connection(pool, business_id) as conn:
        row = await conn.fetchrow(
            "INSERT INTO leads (business_id, lead_name, status, is_test, "
            "started_at, last_activity_at) VALUES ($1,$2,$3,true,now(),now()) "
            "RETURNING id",
            business_id, "test-flow", status)
    return str(row["id"])


async def main() -> int:
    pool = await asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=4)
    rds = aioredis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    made_convs: list[tuple[str, str]] = []

    print("=" * 74)
    print("  BIZZ_UP — M10 (transcript TTL by status + private outcome note)")
    print("=" * 74)

    try:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app, raise_app_exceptions=False)
            async with AsyncClient(transport=transport, base_url="http://test") as http:

                # ---- PART 1: TTL by status ----
                print("\n----- PART 1: the chat must not vanish while a human is needed -----")

                # bot → ~60 min timer
                conv = f"sim:{secrets.token_hex(6)}"; made_convs.append((BIZ_A, conv))
                await cs.append_message(rds, BIZ_A, conv, "customer", "שלום")
                await cs.set_status(rds, BIZ_A, conv, cs.STATUS_BOT)
                key, logk = cs._key(BIZ_A, conv), cs._log_key(BIZ_A, conv)
                kttl, lttl = await rds.ttl(key), await rds.ttl(logk)
                check("'bot' chat has a ~60-minute timer",
                      "while the bot drives, a quiet chat should fade after ~1h.",
                      3500 <= kttl <= 3600 and 3500 <= lttl <= 3600)

                # waiting → persist
                conv = f"sim:{secrets.token_hex(6)}"; made_convs.append((BIZ_A, conv))
                await cs.append_message(rds, BIZ_A, conv, "customer", "אני רוצה נציג")
                await cs.set_status(rds, BIZ_A, conv, cs.STATUS_WAITING)
                key, logk = cs._key(BIZ_A, conv), cs._log_key(BIZ_A, conv)
                check("'waiting' chat PERSISTS (no timer, TTL == -1)",
                      "the customer asked for a human — the chat must wait, not expire.",
                      await rds.ttl(key) == -1 and await rds.ttl(logk) == -1)

                # human → persist
                conv = f"sim:{secrets.token_hex(6)}"; made_convs.append((BIZ_A, conv))
                await cs.append_message(rds, BIZ_A, conv, "customer", "שלום")
                await cs.set_status(rds, BIZ_A, conv, cs.STATUS_HUMAN)
                key, logk = cs._key(BIZ_A, conv), cs._log_key(BIZ_A, conv)
                check("'human' chat PERSISTS (no timer, TTL == -1)",
                      "an owner is handling it — it must stay alive while they work.",
                      await rds.ttl(key) == -1 and await rds.ttl(logk) == -1)

                # closed → 30 days
                conv = f"sim:{secrets.token_hex(6)}"; made_convs.append((BIZ_A, conv))
                await cs.append_message(rds, BIZ_A, conv, "customer", "תודה")
                await cs.set_status(rds, BIZ_A, conv, cs.STATUS_CLOSED)
                key, logk = cs._key(BIZ_A, conv), cs._log_key(BIZ_A, conv)
                kttl = await rds.ttl(key)
                check("'closed' chat lingers ~30 days, then is swept",
                      "a finished chat is kept a while for review, not forever.",
                      cs.CLOSED_TTL_SECONDS - 30 <= kttl <= cs.CLOSED_TTL_SECONDS
                      and kttl > cs.CONVERSATION_TTL_SECONDS)

                # THE bug: append on 'waiting' must NOT bring back a 60-min timer
                conv = f"sim:{secrets.token_hex(6)}"; made_convs.append((BIZ_A, conv))
                await cs.append_message(rds, BIZ_A, conv, "customer", "נציג בבקשה")
                await cs.set_status(rds, BIZ_A, conv, cs.STATUS_WAITING)
                key, logk = cs._key(BIZ_A, conv), cs._log_key(BIZ_A, conv)
                before_ok = await rds.ttl(key) == -1
                # The customer messages AGAIN while still waiting.
                await cs.append_message(rds, BIZ_A, conv, "customer", "מתי תענו?")
                after_ok = await rds.ttl(key) == -1 and await rds.ttl(logk) == -1
                check("a NEW message on a 'waiting' chat does NOT resurrect a timer",
                      "the old bug: each message reset a 60-min timer → the chat "
                      "would silently vanish. M10 keeps it persisting.",
                      before_ok and after_ok)

                # NEGATIVE CONTROL: prove the test would CATCH the old bug.
                conv = f"sim:{secrets.token_hex(6)}"; made_convs.append((BIZ_A, conv))
                await cs.append_message(rds, BIZ_A, conv, "customer", "נציג")
                await cs.set_status(rds, BIZ_A, conv, cs.STATUS_WAITING)
                key = cs._key(BIZ_A, conv)
                # Simulate the OLD broken behaviour by hand: slam a 60-min timer on.
                await rds.expire(key, cs.CONVERSATION_TTL_SECONDS)
                broke = await rds.ttl(key) != -1  # the test would see this and FAIL
                # Restore the correct (persisted) state.
                await rds.persist(key)
                restored = await rds.ttl(key) == -1
                check("NEGATIVE CONTROL: break it on purpose → the check catches it",
                      "we force the old 60-min timer back, confirm a real failure "
                      "would be detected, then restore PERSIST.",
                      broke and restored)

                # ---- PART 2: private outcome note ----
                print("\n----- PART 2: the owner's outcome note is encrypted + private -----")
                await _login(rds, http, BIZ_A)
                lead_id = await _seed_lead(pool, BIZ_A, "new")
                note = "הלקוח חתם על חוזה שנתי"  # private business detail

                r = await http.patch(f"/api/leads/{lead_id}/status",
                                     json={"status": "deal", "note": note})
                ok_patch = r.status_code == 200 and r.json()["status"] == "deal"

                async with tenant_connection(pool, BIZ_A) as conn:
                    raw = await conn.fetchval(
                        "SELECT outcome_note FROM leads WHERE id=$1 AND business_id=$2",
                        lead_id, BIZ_A)
                check("the outcome note is ENCRYPTED at rest (raw column is gibberish)",
                      "the note is sensitive — the database row must not hold plaintext.",
                      ok_patch and raw is not None and note not in raw)

                rows = (await http.get("/api/leads?status=deal&include_test=true")).json()["leads"]
                got = [x for x in rows if x["id"] == lead_id]
                check("the OWNER reads the note back, decrypted",
                      "only the owning business may see the plaintext note.",
                      bool(got) and got[0]["outcome_note"] == note)

                # LeadItem always carries the field (null when unset)
                lead2 = await _seed_lead(pool, BIZ_A, "new")
                rows = (await http.get("/api/leads?status=new&include_test=true")).json()["leads"]
                g2 = [x for x in rows if x["id"] == lead2]
                check("every lead payload carries outcome_note (null when unset)",
                      "the UI relies on the field existing on every lead.",
                      bool(g2) and "outcome_note" in g2[0] and g2[0]["outcome_note"] is None)

                # ---- PART 3: tenant isolation on the new column ----
                print("\n----- PART 3: another business can't touch the note -----")
                b_lead = await _seed_lead(pool, BIZ_B, "new")
                # Avi (A) is still logged in; try to write a note onto Bella's lead.
                r = await http.patch(f"/api/leads/{b_lead}/status",
                                     json={"status": "deal", "note": "A-tries-to-write"})
                blocked = r.status_code == 404
                async with tenant_connection(pool, BIZ_B) as conn:
                    brow = await conn.fetchrow(
                        "SELECT status, outcome_note FROM leads WHERE id=$1 AND business_id=$2",
                        b_lead, BIZ_B)
                check("business A CANNOT set business B's outcome note",
                      "isolation: A gets a 404 and B's lead stays untouched.",
                      blocked and brow["status"] == "new" and brow["outcome_note"] is None)

    finally:
        for bid, cid in made_convs:
            await cs.clear_state(rds, bid, cid)
            await rds.delete(f"conv:{bid}:{cid}:log")
            await rds.delete(f"conv:{bid}:{cid}:outbox")
        for bid in (BIZ_A, BIZ_B):
            async with tenant_connection(pool, bid) as conn:
                await conn.execute(
                    "DELETE FROM leads WHERE business_id=$1 AND is_test=true", bid)
        await rds.aclose()
        await pool.close()

    total = _passed + _failed
    print("\n" + "=" * 74)
    print(f"  M10 RESULT: {_passed}/{total} checks held"
          + ("  🎉 transcript persists for humans + the note stays private."
             if _failed == 0 else f"  ⚠️ {_failed} FAILED"))
    print("=" * 74)
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
