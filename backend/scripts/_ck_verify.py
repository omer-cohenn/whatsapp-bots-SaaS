"""Verify the chocolate-kingdom demo by READING IT BACK through the app services.

Nothing here asserts from the seed script's own variables — every number is
measured by calling the same function the dashboard / public page calls.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx

from app.core.clients import create_pg_pool, create_redis
from app.core.config import get_settings
from app.db.session import tenant_connection
from app.services import booking as booking_service
from app.services import bot_settings as bot_settings_service
from app.services import conversation_state as cs
from app.services import file_storage
from app.services import leads as leads_service

BID = "fab99cce-f844-4fd4-8f95-c5ef2f6eda10"
OTHER_BID = "7fca1b13-902a-4ce2-a4a4-28ecd48f96eb"  # Omer's real business


def head(t: str) -> None:
    print(f"\n{'=' * 68}\n{t}\n{'=' * 68}")


async def main() -> None:
    s = get_settings()
    pool = await create_pg_pool(s)
    redis = create_redis(s)
    try:
        # ---------------------------------------------------------------- leads
        head("1. LEADS — read back via leads.list_leads (decrypts)")
        async with tenant_connection(pool, BID) as conn:
            allleads = await leads_service.list_leads(
                conn, BID, period="all", limit=5000
            )
            week = await leads_service.list_leads(conn, BID, period="week", limit=5000)
            month = await leads_service.list_leads(conn, BID, period="month", limit=5000)
            deals = await leads_service.list_leads(
                conn, BID, status="deal", period="all", limit=5000
            )
        print(f"total leads (period=all)   : {len(allleads)}")
        print(f"period=week                : {len(week)}")
        print(f"period=month               : {len(month)}")
        print(f"status=deal                : {len(deals)}")
        print(f"status mix                 : {dict(Counter(l['status'] for l in allleads))}")
        print(f"flow mix                   : {dict(Counter(l['lead_name'] for l in allleads))}")
        print(f"close_reason mix           : {dict(Counter(str(l['close_reason']) for l in allleads))}")

        starts = sorted(l["started_at"] for l in allleads)
        print(f"started_at oldest          : {starts[0]}")
        print(f"started_at newest          : {starts[-1]}")
        span = (
            datetime.fromisoformat(starts[-1]) - datetime.fromisoformat(starts[0])
        ).days
        print(f"span                       : {span} days")

        with_note = [l for l in allleads if l["outcome_note"]]
        print(f"leads with an outcome_note : {len(with_note)}")

        head("2. DECRYPTION spot-check — 3 leads, plaintext through the service")
        for l in allleads[:3]:
            print(f"  [{l['status']}] flow={l['lead_name']}")
            print(f"     contact_name = {l['contact_name']}")
            print(f"     phone        = {l['phone']}")
            print(f"     answers      = {l['answers']}")
            print(f"     outcome_note = {l['outcome_note']}")
            print(f"     key_version  = (row decrypted OK)")

        head("3. DEAL / CLOSED carry close_reason + outcome_note")
        for st in ("deal", "closed", "abandoned"):
            sub = [l for l in allleads if l["status"] == st]
            noted = sum(1 for l in sub if l["outcome_note"])
            reasons = dict(Counter(str(l["close_reason"]) for l in sub))
            print(f"  {st:11s} n={len(sub):3d}  with_note={noted:3d}  close_reason={reasons}")

        # ------------------------------------------------------------ file answers
        head("4. FILE ANSWERS — decrypt a real attachment out of the bucket")
        filed = [
            (l, k, v)
            for l in allleads
            for k, v in l["answers"].items()
            if isinstance(v, dict) and "file_id" in v
        ]
        print(f"leads carrying a file answer: {len(filed)}")
        if filed:
            lead, key, ans = filed[0]
            print(f"  step key   : {key}")
            print(f"  answer     : {ans}")
            async with tenant_connection(pool, BID) as conn:
                row = await conn.fetchrow(
                    "SELECT storage_key, wrapped_dek, key_version, mime_type, "
                    "size_bytes FROM lead_files WHERE id = $1 AND business_id = $2",
                    ans["file_id"], BID,
                )
            print(f"  lead_files : mime={row['mime_type']} size={row['size_bytes']}")
            raw = file_storage.get_decrypted(
                row["storage_key"], row["wrapped_dek"], row["key_version"]
            )
            print(f"  DECRYPTED  : {len(raw)} bytes, magic={raw[:3]!r} "
                  f"(JPEG={raw[:3] == b'\xff\xd8\xff'})")

        # ------------------------------------------------------------ bot config
        head("5. BOT CONFIG — read back via bot_settings.get_settings")
        bot = await bot_settings_service.get_settings(pool, BID)
        print(f"is_published     : {bot['is_published']}")
        print(f"handoff_keywords : {bot['handoff_keywords']}")
        print(f"bot_profile.name : {bot['bot_profile']['name']}")
        print(f"greeting         : {bot['bot_profile']['greeting'][:60]}...")
        print(f"escalation       : {bot['bot_profile']['escalation_message'][:60]}...")
        print(f"tone / language  : {bot['bot_profile']['tone']} / {bot['bot_profile']['language']}")
        types_seen = set()
        for fkey, flow in bot["lead_steps"].items():
            st = [s["type"] for s in flow["steps"]]
            types_seen.update(st)
            print(f"  {fkey:20s} flow_type={flow['flow_type']:13s} steps={len(flow['steps'])} {st}")
        print(f"flow_types present : {sorted({f['flow_type'] for f in bot['lead_steps'].values()})}")
        print(f"step types present : {sorted(types_seen)}")

        # ------------------------------------------------------- conversations
        head("6. CONVERSATIONS — conversation_state.list_conversations + names")
        convs = await cs.list_conversations(redis, BID)
        ids = [c["conversation_id"] for c in convs]
        async with tenant_connection(pool, BID) as conn:
            names = await leads_service.contacts_for_conversations(conn, BID, ids)
        print(f"live conversations : {len(convs)}")
        print(f"state mix          : {dict(Counter(c['status'] for c in convs))}")
        print(f"total unread       : {await cs.unread_total(redis, BID)}")
        for c in sorted(convs, key=lambda x: x["conversation_id"]):
            n = names.get(c["conversation_id"], {})
            print(f"  {c['conversation_id']:18s} {c['status']:8s} unread={c['unread']} "
                  f"name={n.get('contact_name')!s:14s} phone={n.get('phone')} "
                  f"| {c['preview'][:38]}")

        head("7. TRANSCRIPT decrypts (one waiting chat, full)")
        sample = next(c for c in convs if c["status"] == "waiting")
        for m in await cs.get_messages(redis, BID, sample["conversation_id"]):
            print(f"  {m['role']:9s} | {m['body']}")

        # -------------------------------------------------- public page + slots
        head("8. PUBLIC PAGE endpoint (no session) — /api/book/{slug}/page")
        async with tenant_connection(pool, BID) as conn:
            bsettings = await booking_service.get_settings(conn, BID)
        slug = bsettings["slug"]
        base = "http://localhost:8000"
        async with httpx.AsyncClient(base_url=base, timeout=30) as http:
            r = await http.get(f"/api/book/{slug}/page")
            print(f"GET /api/book/{slug}/page -> {r.status_code}")
            page = r.json()
            for k, v in page.items():
                if k == "images":
                    print(f"  images ({len(v)}):")
                    for im in v:
                        print(f"     [{im['storage_path'][-12:]}] {im['caption']}")
                else:
                    txt = str(v)
                    print(f"  {k:15s} = {txt[:70]}{'…' if len(txt) > 70 else ''}")
            empty = [k for k, v in page.items() if v in (None, "", [], {})]
            print(f"  EMPTY FIELDS   = {empty or 'none'}")

            r2 = await http.get(f"/api/book/{slug}/services")
            print(f"\nGET /api/book/{slug}/services -> {r2.status_code}")
            svc = r2.json()
            print(f"  business_name   = {svc['business_name']}")
            print(f"  welcome_message = {svc['welcome_message']}")
            for x in svc["services"]:
                print(f"   - {x['name']:38s} {x['duration_minutes']:3d}min  ₪{x['price']}")

            # slots on the next few days, per service
            print(f"\nGET /api/book/{slug}/slots")
            today = datetime.now(timezone.utc).date()
            for x in svc["services"][:3]:
                for d in range(1, 5):
                    day = (today + timedelta(days=d)).isoformat()
                    rs = await http.get(
                        f"/api/book/{slug}/slots",
                        params={"service_id": x["id"], "date": day},
                    )
                    sl = rs.json()["slots"]
                    if sl:
                        print(f"   {x['name'][:30]:30s} {day} -> {len(sl)} slots "
                              f"{sl[:6]}{'…' if len(sl) > 6 else ''}")
                        break

            rav = await http.get(
                f"/api/book/{slug}/availability",
                params={
                    "service_id": svc["services"][0]["id"],
                    "from": today.isoformat(),
                    "to": (today + timedelta(days=30)).isoformat(),
                },
            )
            print(f"\nGET availability (30d) -> {rav.status_code} "
                  f"{len(rav.json()['dates'])} bookable days")

        # ------------------------------------------------------ tenant isolation
        head("9. TENANT ISOLATION — can anyone else see this data?")
        async with tenant_connection(pool, OTHER_BID) as conn:
            other_leads = await conn.fetchval(
                "SELECT count(*) FROM leads WHERE business_id = $1", BID
            )
            other_any = await conn.fetchval("SELECT count(*) FROM leads")
            other_imgs = await conn.fetchval(
                "SELECT count(*) FROM business_images WHERE business_id = $1", BID
            )
            other_svc = await conn.fetchval(
                "SELECT count(*) FROM services WHERE business_id = $1", BID
            )
            other_files = await conn.fetchval(
                "SELECT count(*) FROM lead_files WHERE business_id = $1", BID
            )
            other_bot = await conn.fetchval(
                "SELECT count(*) FROM bot_settings WHERE business_id = $1", BID
            )
            other_bs = await conn.fetchval(
                "SELECT count(*) FROM booking_settings WHERE business_id = $1", BID
            )
        print(f"other tenant selecting CK leads           : {other_leads}  (want 0)")
        print(f"other tenant selecting CK business_images : {other_imgs}  (want 0)")
        print(f"other tenant selecting CK services        : {other_svc}  (want 0)")
        print(f"other tenant selecting CK lead_files      : {other_files}  (want 0)")
        print(f"other tenant selecting CK bot_settings    : {other_bot}  (want 0)")
        print(f"other tenant selecting CK booking_settings: {other_bs}  (want 0)")
        print(f"other tenant's OWN visible lead count     : {other_any}")

        # no tenant context at all → deny by default
        async with pool.acquire() as conn:
            async with conn.transaction():
                nocx = await conn.fetchval("SELECT count(*) FROM leads")
                nocx_i = await conn.fetchval("SELECT count(*) FROM business_images")
        print(f"NO tenant context, leads                  : {nocx}  (want 0)")
        print(f"NO tenant context, business_images        : {nocx_i}  (want 0)")

        # the Redis layer refuses a foreign conversation key outright
        try:
            await cs.get_messages(redis, OTHER_BID, "ck-demo-wa-05")
            print("Redis: other tenant read CK conversation -> RETURNED (checking)")
            msgs = await cs.get_messages(redis, OTHER_BID, "ck-demo-wa-05")
            print(f"   messages visible to other tenant: {len(msgs)}  (want 0)")
        except cs.CrossTenantConversationError as e:
            print(f"Redis: cross-tenant read raised {type(e).__name__}")
        other_convs = await cs.list_conversations(redis, OTHER_BID)
        leaked = [c for c in other_convs if c["conversation_id"].startswith("ck-demo-")]
        print(f"other tenant's conversation list contains CK chats: {len(leaked)}  (want 0)")

        # a WRITE labelled as CK from another tenant must be rejected
        try:
            async with tenant_connection(pool, OTHER_BID) as conn:
                await conn.execute(
                    "INSERT INTO services (business_id, name, duration_minutes) "
                    "VALUES ($1, 'poison', 30)", BID,
                )
            print("!! other tenant INSERTED into CK — RLS WITH CHECK FAILED")
        except asyncpg.PostgresError as e:
            print(f"other tenant INSERT into CK rejected: {type(e).__name__}")

        print("\nVERIFICATION COMPLETE")
    finally:
        await pool.close()
        await redis.aclose()


asyncio.run(main())
