"""Watch the tenant wall hold — a plain-language isolation demo.

Run it with `make demo-isolation` (it runs INSIDE the backend container, which
connects as the real non-service roles and can reach Postgres + Redis). It seeds
two fake businesses, then tries every attack the OLD system fell for, printing a
human-readable ✅ / ❌ line for each. No pytest, no jargon — just the story.

It connects as:
  * app_role     (DATABASE_URL)          — the dashboard/API role, RLS applies.
  * gateway_role (GATEWAY_DATABASE_URL)  — only role allowed near the crown jewel.
Seeding (the two businesses) is done by `make seed` as the superuser first.
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

# The two seeded tenants (fixed UUIDs from supabase/seed.sql).
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber

passed = 0
total = 0


def check(label: str, ok: bool, detail: str) -> None:
    global passed, total
    total += 1
    if ok:
        passed += 1
    mark = "✅" if ok else "❌ LEAK:"
    dots = "." * max(2, 56 - len(label))
    print(f"[{total}] {label} {dots} {detail} {mark}")


async def insert_lead(pool, business_id, name, phone) -> None:
    """Insert one encrypted test lead under the given tenant context (app_role)."""
    async with tenant_connection(pool, business_id) as conn:
        await conn.execute(
            "INSERT INTO leads (business_id, lead_name, contact_name, phone, "
            "answers, status, is_test) VALUES ($1,$2,$3,$4,$5,'new',true)",
            business_id, "demo_lead", encrypt_pii(name), encrypt_pii(phone),
            None,
        )


async def main() -> int:
    app_dsn = os.environ["DATABASE_URL"]
    gw_dsn = os.environ["GATEWAY_DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]

    app_pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=4)
    gw_pool = await asyncpg.create_pool(dsn=gw_dsn, min_size=1, max_size=2)
    redis = aioredis.from_url(redis_url, decode_responses=True)

    print("=== Bizz_up Tenant-Wall Demo ===")

    # --- setup: clean prior test rows, then seed one lead per business --------
    for biz in (BIZ_A, BIZ_B):
        async with tenant_connection(app_pool, biz) as conn:
            await conn.execute("DELETE FROM leads WHERE is_test = true")
    await insert_lead(app_pool, BIZ_A, "Dana", "050-111-1111")
    await insert_lead(app_pool, BIZ_B, "Yossi", "052-222-2222")
    print('Seeded: A=Avi Insurance (lead: "Dana")  B=Bella Barber (lead: "Yossi")\n')

    # [1] A asks for ITS OWN leads → sees exactly its one lead.
    async with tenant_connection(app_pool, BIZ_A) as conn:
        rows = await conn.fetch("SELECT contact_name FROM leads")
    own_name = decrypt_pii(rows[0]["contact_name"]) if rows else None
    check("A logs in, asks for ITS leads", len(rows) == 1 and own_name == "Dana",
          f'sees {len(rows)} lead ("{own_name}")')

    # [2] A tries to read B's leads (even with an explicit WHERE) → 0 rows.
    async with tenant_connection(app_pool, BIZ_A) as conn:
        rows = await conn.fetch("SELECT * FROM leads WHERE business_id = $1", BIZ_B)
    check("A logs in, tries to read B's leads", len(rows) == 0,
          f"{len(rows)} rows returned (RLS blocked it)")

    # [3] A tries to INSERT a lead labelled as B's business → WITH CHECK rejects.
    blocked = False
    try:
        async with tenant_connection(app_pool, BIZ_A) as conn:
            await conn.execute(
                "INSERT INTO leads (business_id, status, is_test) "
                "VALUES ($1,'new',true)", BIZ_B)
    except asyncpg.PostgresError:
        blocked = True
    check("A tries to INSERT a lead labelled as B's business", blocked,
          "REJECTED by WITH CHECK" if blocked else "insert SUCCEEDED — A wrote into B!")

    # [4] Nobody logged in (no business set) → 0 rows. Deny-by-default.
    async with app_pool.acquire() as conn:  # NOTE: no tenant_connection → no app.business_id
        rows = await conn.fetch("SELECT * FROM leads")
    check("Nobody logged in asks for leads", len(rows) == 0,
          f"{len(rows)} rows (deny-by-default, old C2 bug is dead)")

    # [5] The dashboard role tries to read the WhatsApp key → permission denied.
    denied = False
    try:
        async with tenant_connection(app_pool, BIZ_A) as conn:
            await conn.fetch("SELECT auth_state FROM whatsapp_credentials")
    except asyncpg.InsufficientPrivilegeError:
        denied = True
    check("Dashboard role tries to read the WhatsApp key", denied,
          "PERMISSION DENIED (crown jewel safe)")

    # [6] The raw stored lead is ciphertext, not readable plaintext.
    async with tenant_connection(app_pool, BIZ_A) as conn:
        raw = await conn.fetchval(
            "SELECT phone FROM leads WHERE is_test = true LIMIT 1")
    check("We look at the raw 'leads' row in the DB",
          raw is not None and "050-111-1111" not in raw,
          "phone is ciphertext, not readable")

    # [7] Decrypt with the RIGHT key → the real value comes back.
    check("We decrypt Dana's lead with the RIGHT key",
          decrypt_pii(raw) == "050-111-1111", '"050-111-1111"')

    # [8] Decrypt with a WRONG key → raises (no silent plaintext — old M2 bug).
    wrong_token = Fernet(Fernet.generate_key()).encrypt(b"050-111-1111").decode()
    raised = False
    try:
        decrypt_pii(wrong_token)
    except DecryptionError:
        raised = True
    check("We decrypt with a WRONG key", raised,
          "RAISED an error (no silent plaintext)")

    # [9] A peeks at B's live Redis chat → the app-layer guard rejects it.
    ph_b = phone_hash("052-222-2222")
    await live_chat.set_status(redis, BIZ_B, ph_b, "human")  # B's real chat exists
    rejected = False
    try:
        # Attacker code: caller is A but hand-builds B's key prefix.
        live_chat._assert_owns(BIZ_A, f"chat:{BIZ_B}:{ph_b}")
    except CrossTenantCacheError:
        rejected = True
    # And the honest accessor for A simply never sees B's data:
    a_view = await live_chat.get_chat(redis, BIZ_A, ph_b)
    check("A peeks at B's live Redis chat",
          rejected and a_view["status"] is None,
          "REJECTED (app-layer cache isolation)")

    await app_pool.close()
    await gw_pool.close()
    await redis.aclose()

    print()
    if passed == total:
        print(f"RESULT: {passed}/{total} walls held. "
              "One business can NOT see another's data. 🧱🔒")
        return 0
    print(f"RESULT: {passed}/{total} — WALL BREACHED. "
          "(this is what a regression looks like)")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
