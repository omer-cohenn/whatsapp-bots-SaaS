"""
============================================================================
  M2 — THE TENANT WALL — FULL TEST, EXPLAINED LIKE YOU'RE FIVE
============================================================================

WHAT IS THIS FILE?
  Bizz_up is one app used by MANY businesses at the same time. The #1 rule is:
  ONE business must NEVER see another business's stuff (their leads, phone
  numbers, WhatsApp key...). "M2 — the tenant wall" is the set of locks that
  make that impossible. This script tries to BREAK every lock, on purpose, and
  tells you — in plain words — whether each lock held.

  Two pretend businesses are used as the guinea pigs:
      🅰️  "Avi Insurance"   (lead: a person named "Dana")
      🅱️  "Bella Barber"    (lead: a person named "Yossi")

  Every check prints:
      🧪 WHAT we try to do
      💡 WHY it matters (what would go wrong in real life)
      ✅ / ❌ what actually happened

  Run it with the test_m2.bat file (double-click), or read HOW-TO at the bottom.
============================================================================
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import redis.asyncio as aioredis
from cryptography.fernet import Fernet

from app.core.crypto import (
    DecryptionError,
    decrypt_pii,
    encrypt_pii,
    phone_hash,
)
from app.db.session import tenant_connection
from app.services import live_chat
from app.services.live_chat import CrossTenantCacheError

# The two pretend businesses (their fixed IDs come from supabase/seed.sql).
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber

# Scoreboard.
_passed = 0
_total = 0


# --- tiny printing helpers (all the "baby language" lives here) --------------

def banner(num: int, title: str) -> None:
    print()
    print("─" * 74)
    print(f"  TEST {num}: {title}")
    print("─" * 74)


def explain(what: str, why: str) -> None:
    print(f"  🧪 We try : {what}")
    print(f"  💡 Because: {why}")


def result(ok: bool, detail: str) -> None:
    global _passed, _total
    _total += 1
    if ok:
        _passed += 1
        print(f"  ✅ GOOD   : {detail}")
    else:
        print(f"  ❌ BAD    : {detail}   <-- THIS IS A LEAK!")


# --- helper to put one encrypted lead into a business ------------------------

async def put_lead(pool, business_id: str, name: str, phone: str) -> None:
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            "INSERT INTO leads (business_id, lead_name, contact_name, phone, "
            "status, is_test) VALUES ($1,'demo_lead',$2,$3,'new',true)",
            business_id, encrypt_pii(name), encrypt_pii(phone))


async def main() -> int:
    print(__doc__)

    app_dsn = os.environ["DATABASE_URL"]          # the everyday "app" key (app_role)
    gw_dsn = os.environ["GATEWAY_DATABASE_URL"]   # the special "gateway" key
    redis_url = os.environ["REDIS_URL"]

    app_pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=2)
    gw_pool = await asyncpg.create_pool(dsn=gw_dsn, min_size=1, max_size=2)
    redis = aioredis.from_url(redis_url, decode_responses=True)

    # Fresh start: wipe old test leads, then give each business exactly one lead.
    for biz in (BIZ_A, BIZ_B):
        async with tenant_connection(app_pool, biz) as conn:
            await conn.execute("DELETE FROM leads WHERE is_test = true")
    await put_lead(app_pool, BIZ_A, "Dana", "050-111-1111")
    await put_lead(app_pool, BIZ_B, "Yossi", "052-222-2222")
    print("\n  (set-up done: Avi has lead 'Dana', Bella has lead 'Yossi')")

    # ── TEST 1 ────────────────────────────────────────────────────────────
    banner(1, "The app does NOT log in as the all-powerful 'master' user")
    explain("ask the database who we are",
            "the OLD app used a MASTER key that could see EVERYTHING — that was "
            "the bug. The new app must use a weak 'app_role' so the locks apply.")
    async with app_pool.acquire() as conn:
        whoami = await conn.fetchval("SELECT current_user")
        is_master = await conn.fetchval("SELECT usesuper FROM pg_user WHERE usename = current_user")
    result(whoami == "app_role" and not is_master,
           f"the app is '{whoami}', and it is NOT a master user (super={is_master})")

    # ── TEST 2 ────────────────────────────────────────────────────────────
    banner(2, "Avi sees Avi's leads (the normal, allowed case)")
    explain("log in as Avi and ask for our leads",
            "a business must be able to see ITS OWN data — the wall blocks "
            "others, not yourself.")
    async with tenant_connection(app_pool, BIZ_A) as conn:
        rows = await conn.fetch("SELECT contact_name FROM leads")
    name = decrypt_pii(rows[0]["contact_name"]) if rows else None
    result(len(rows) == 1 and name == "Dana",
           f'Avi sees {len(rows)} lead, and it is "{name}"')

    # ── TEST 3 ────────────────────────────────────────────────────────────
    banner(3, "Avi tries to READ Bella's leads (should get NOTHING)")
    explain("log in as Avi but ask for Bella's leads on purpose",
            "this is the core leak: one business reading another's customers. "
            "Even asking directly for Bella's id must return zero rows.")
    async with tenant_connection(app_pool, BIZ_A) as conn:
        rows = await conn.fetch("SELECT * FROM leads WHERE business_id = $1", BIZ_B)
    result(len(rows) == 0, f"Avi got {len(rows)} of Bella's leads (the wall hid them)")

    # ── TEST 4 ────────────────────────────────────────────────────────────
    banner(4, "Avi tries to PLANT a lead inside Bella's business (should fail)")
    explain("log in as Avi and insert a row labelled as Bella's",
            "writing into someone else's business is just as bad as reading. "
            "The 'WITH CHECK' lock must reject it.")
    blocked = False
    try:
        async with tenant_connection(app_pool, BIZ_A) as conn:
            await conn.execute(
                "INSERT INTO leads (business_id, status, is_test) VALUES ($1,'new',true)",
                BIZ_B)
    except asyncpg.PostgresError:
        blocked = True
    result(blocked, "the database refused to let Avi write into Bella's business"
           if blocked else "Avi managed to write into Bella — DATA POISONING")

    # ── TEST 5 ────────────────────────────────────────────────────────────
    banner(5, "A stranger with NO login asks for leads (should get NOTHING)")
    explain("ask for leads without saying which business we are",
            "the OLD app quietly fell back to a 'shared' business and leaked it. "
            "The new rule is: no login = no data, full stop.")
    async with app_pool.acquire() as conn:  # note: we never say who we are
        rows = await conn.fetch("SELECT * FROM leads")
    result(len(rows) == 0, f"a no-login stranger got {len(rows)} leads (deny-by-default)")

    # ── TEST 6 ────────────────────────────────────────────────────────────
    banner(6, "The app key tries to touch the WhatsApp 'crown jewel' (should be denied)")
    explain("log in as the normal app and read the WhatsApp session key table",
            "that key = full control of a business's WhatsApp. Only the special "
            "gateway key may touch it; the everyday app must be locked out entirely.")
    denied = False
    try:
        async with tenant_connection(app_pool, BIZ_A) as conn:
            await conn.fetch("SELECT auth_state FROM whatsapp_credentials")
    except asyncpg.InsufficientPrivilegeError:
        denied = True
    result(denied, "the app key was DENIED even from looking at the crown jewel")

    # ── TEST 7 ────────────────────────────────────────────────────────────
    banner(7, "Stored phone numbers are SCRAMBLED, not plain text")
    explain("look at the raw phone value sitting in the database",
            "if a thief copied the database, the phone numbers must be unreadable "
            "gibberish, not '050-...'.")
    async with tenant_connection(app_pool, BIZ_A) as conn:
        raw_phone = await conn.fetchval(
            "SELECT phone FROM leads WHERE is_test = true LIMIT 1")
    looks_scrambled = raw_phone is not None and "050-111-1111" not in raw_phone
    result(looks_scrambled, f"the stored phone is scrambled: {str(raw_phone)[:24]}...")

    # ── TEST 8 ────────────────────────────────────────────────────────────
    banner(8, "The RIGHT key unlocks the scrambled phone")
    explain("decrypt the scrambled phone with the correct key",
            "the business itself must still be able to read its real data.")
    unlocked = decrypt_pii(raw_phone)
    result(unlocked == "050-111-1111", f'unlocked back to the real number "{unlocked}"')

    # ── TEST 9 ────────────────────────────────────────────────────────────
    banner(9, "A WRONG key SCREAMS instead of quietly handing back gibberish")
    explain("decrypt with a wrong key and see what happens",
            "the OLD app, on a wrong key, silently returned the gibberish as if it "
            "were fine — hiding a broken lock. The new rule: fail LOUD, never fake it.")
    wrong = Fernet(Fernet.generate_key()).encrypt(b"050-111-1111").decode()
    screamed = False
    try:
        decrypt_pii(wrong)
    except DecryptionError:
        screamed = True
    result(screamed, "a wrong key raised a clear error (no silent fake-success)")

    # ── TEST 10 ───────────────────────────────────────────────────────────
    banner(10, "Phone 'fingerprint' is steady but cannot be reversed")
    explain("fingerprint the same phone twice, and a different phone once",
            "we need to find a customer again WITHOUT storing their real phone. "
            "Same phone → same fingerprint; different phone → different fingerprint.")
    f1 = phone_hash("050-111-1111")
    f2 = phone_hash("050-111-1111")
    f3 = phone_hash("052-999-9999")
    result(f1 == f2 and f1 != f3 and "050" not in f1,
           "same phone gave the same fingerprint, a different phone gave a different one")

    # ── TEST 11 ───────────────────────────────────────────────────────────
    banner(11, "The live-chat lockbox (Redis) keeps businesses apart too")
    explain("store Bella's live chat, then try to grab it while pretending to be Avi",
            "the fast live-chat store has no built-in wall, so OUR CODE is the wall: "
            "each key carries its business and is re-checked on every access.")
    ph_b = phone_hash("052-222-2222")
    await live_chat.set_status(redis, BIZ_B, ph_b, "human")
    rejected = False
    try:
        live_chat._assert_owns(BIZ_A, f"chat:{BIZ_B}:{ph_b}")  # Avi grabbing Bella's key
    except CrossTenantCacheError:
        rejected = True
    avi_view = await live_chat.get_chat(redis, BIZ_A, ph_b)
    result(rejected and avi_view["status"] is None,
           "Avi was rejected, and Avi's honest view never showed Bella's chat")

    # ── TEST 12 ───────────────────────────────────────────────────────────
    banner(12, "Many users at the SAME TIME never get mixed up")
    explain("run lots of Avi and Bella requests at once on a shared connection",
            "apps reuse database connections. If one request's identity 'leaks' "
            "to the next, Avi could suddenly see Bella. This is the scariest bug.")
    mixed_up = []

    async def hammer(business_id, expected):
        for _ in range(15):
            async with tenant_connection(app_pool, business_id) as conn:
                r = await conn.fetch("SELECT contact_name FROM leads")
                got = decrypt_pii(r[0]["contact_name"]) if len(r) == 1 else f"{len(r)} rows"
                if got != expected:
                    mixed_up.append((business_id, got))
            await asyncio.sleep(0)  # force them to interleave

    await asyncio.gather(
        hammer(BIZ_A, "Dana"), hammer(BIZ_B, "Yossi"),
        hammer(BIZ_A, "Dana"), hammer(BIZ_B, "Yossi"))
    result(not mixed_up,
           "after 60 mixed-up concurrent requests, nobody ever saw the wrong business"
           if not mixed_up else f"identities leaked: {mixed_up[:3]}")

    await app_pool.close()
    await gw_pool.close()
    await redis.aclose()

    # ── Scoreboard ─────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    if _passed == _total:
        print(f"  🎉 RESULT: {_passed}/{_total} locks held. "
              "One business CANNOT see another's data.  🧱🔒")
        print("=" * 74)
        return 0
    print(f"  🚨 RESULT: {_passed}/{_total} held — {_total - _passed} LOCK(S) FAILED. "
          "Do not ship until green.")
    print("=" * 74)
    return 1


# ── HOW TO RUN ───────────────────────────────────────────────────────────────
#   Easiest : double-click  tests/test_m2.bat   (it sets everything up for you).
#   By hand : from the project root, with the stack running (run.bat / make dev):
#     docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m2_full_test.py"
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
