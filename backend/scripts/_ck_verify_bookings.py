"""Verify the bookings + build-chat extension by READING IT BACK.

Every number below is measured through the app's OWN protected HTTP endpoints —
GET /api/bookings, GET /api/bookings/alerts, GET /api/bot/ai/history — using a
real server-side session, so the answer is exactly what the browser gets. It
asserts nothing from the seed script's own variables.
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
from app.services import auth as auth_service
from app.services.booking._helpers import BUSINESS_TZ

BID = "fab99cce-f844-4fd4-8f95-c5ef2f6eda10"
OTHER_BID = "7fca1b13-902a-4ce2-a4a4-28ecd48f96eb"  # Omer's real business
BASE = "http://localhost:8000"


def head(t: str) -> None:
    print(f"\n{'=' * 70}\n{t}\n{'=' * 70}")


async def _session(redis, business_id: str, name: str) -> str:
    return await auth_service.create_session(
        redis,
        {"id": "115290069609723973257", "email": "oyc3333@gmail.com", "name": "verify"},
        {"id": business_id, "name": name},
        is_demo=False,
    )


async def main() -> None:
    s = get_settings()
    pool = await create_pg_pool(s)
    redis = create_redis(s)
    try:
        sid = await _session(redis, BID, "chocolate kingdom")
        cookies = {auth_service.SESSION_COOKIE_NAME: sid}
        today = datetime.now(BUSINESS_TZ).date()

        async with httpx.AsyncClient(base_url=BASE, timeout=60, cookies=cookies) as http:
            # ------------------------------------------------------ bookings
            head("1. GET /api/bookings — the list screen (PII decrypted server-side)")
            r = await http.get("/api/bookings")
            print(f"HTTP {r.status_code}")
            bookings = r.json()["bookings"]
            print(f"total bookings          : {len(bookings)}")
            print(f"status mix              : {dict(Counter(b['status'] for b in bookings))}")
            print(f"service mix             : ")
            for k, v in Counter(b["service_name"] for b in bookings).items():
                print(f"    {v:3d}  {k}")

            now = datetime.now(timezone.utc)
            past = [b for b in bookings if datetime.fromisoformat(b["scheduled_at"]) < now]
            fut = [b for b in bookings if datetime.fromisoformat(b["scheduled_at"]) >= now]
            tdy = [b for b in bookings
                   if datetime.fromisoformat(b["scheduled_at"])
                   .astimezone(BUSINESS_TZ).date() == today]
            print(f"in the PAST             : {len(past)}")
            print(f"TODAY ({today})     : {len(tdy)}")
            print(f"in the FUTURE           : {len(fut)}")
            times = sorted(b["scheduled_at"] for b in bookings)
            print(f"earliest                : {times[0]}")
            print(f"latest                  : {times[-1]}")
            with_notes = sum(1 for b in bookings if b["notes"])
            with_email = sum(1 for b in bookings if b["client_email"])
            print(f"carrying a note         : {with_notes}")
            print(f"carrying an email       : {with_email}")
            print(f"is_test rows            : {sum(1 for b in bookings if b['is_test'])}")

            head("2. Decrypted client PII — 6 rows straight off the endpoint")
            for b in bookings[:3] + bookings[-3:]:
                local = datetime.fromisoformat(b["scheduled_at"]).astimezone(BUSINESS_TZ)
                print(f"  {local:%Y-%m-%d %H:%M} ({local:%a})  {b['status']:9s} "
                      f"{b['duration_minutes']:3d}min  {b['client_name']}  "
                      f"{b['client_phone']}  {b['client_email']}")
                print(f"      {b['service_name']}")
                print(f"      note: {b['notes']}")

            head("3. Do the times land on REAL slots? (working hours + grid)")
            # Sat is closed; Sun-Thu 09:00-13:00 & 14:00-18:00/19:00; Fri 09:00-13:00.
            bad = []
            for b in bookings:
                local = datetime.fromisoformat(b["scheduled_at"]).astimezone(BUSINESS_TZ)
                wd = (local.weekday() + 1) % 7          # our Sun=0 keys
                mins = local.hour * 60 + local.minute
                end = mins + b["duration_minutes"]
                ok = False
                ranges = {
                    0: [(540, 780), (840, 1080)], 1: [(540, 780), (840, 1080)],
                    2: [(540, 780), (840, 1080)], 3: [(540, 780), (840, 1140)],
                    4: [(540, 780), (840, 1080)], 5: [(540, 780)], 6: [],
                }[wd]
                for lo, hi in ranges:
                    if mins >= lo and end <= hi and (mins - lo) % (
                        b["duration_minutes"] + 15
                    ) == 0:
                        ok = True
                if not ok:
                    bad.append((b["scheduled_at"], b["service_name"], b["duration_minutes"]))
            print(f"bookings OFF the working-hours grid : {len(bad)}  (want 0)")
            for x in bad[:10]:
                print(f"    {x}")
            print(f"bookings on a SATURDAY              : "
                  f"{sum(1 for b in bookings if (datetime.fromisoformat(b['scheduled_at']).astimezone(BUSINESS_TZ).weekday() + 1) % 7 == 6)}  (want 0)")

            head("4. CALENDAR range queries — GET /api/bookings?from=&to=")
            for label, lo, hi in [
                ("last 7 days ", today - timedelta(days=7), today - timedelta(days=1)),
                ("today only  ", today, today),
                ("next 7 days ", today + timedelta(days=1), today + timedelta(days=7)),
                ("next 30 days", today + timedelta(days=1), today + timedelta(days=30)),
                ("this month  ", today.replace(day=1), today.replace(day=28)),
            ]:
                rr = await http.get("/api/bookings", params={
                    "from": lo.isoformat(), "to": hi.isoformat()})
                got = rr.json()["bookings"]
                print(f"  {label} [{lo} .. {hi}] -> HTTP {rr.status_code}  "
                      f"{len(got):3d} bookings  {dict(Counter(g['status'] for g in got))}")

            head("5. STATUS filter — GET /api/bookings?status=")
            for st in ("pending", "confirmed", "cancelled", "completed"):
                rr = await http.get("/api/bookings", params={"status": st})
                print(f"  status={st:10s} -> HTTP {rr.status_code}  "
                      f"{len(rr.json()['bookings']):3d}")

            head("6. ALERTS — GET /api/bookings/alerts")
            ra = await http.get("/api/bookings/alerts")
            alerts = ra.json()["alerts"]
            print(f"HTTP {ra.status_code}   alerts: {len(alerts)}  (want > 0)")
            for a in alerts:
                when = (datetime.fromisoformat(a["scheduled_at"]).astimezone(BUSINESS_TZ)
                        if a["scheduled_at"] else None)
                print(f"  {a['kind']:11s} {a['client_name']:16s} "
                      f"{str(when):25s} {a['service_name']}")

            head("7. BUILD CHAT — GET /api/bot/ai/history (oldest → newest)")
            rh = await http.get("/api/bot/ai/history")
            msgs = rh.json()["messages"]
            print(f"HTTP {rh.status_code}   messages: {len(msgs)}   "
                  f"roles: {dict(Counter(m['role'] for m in msgs))}")
            order_ok = all(
                msgs[i]["created_at"] <= msgs[i + 1]["created_at"]
                for i in range(len(msgs) - 1)
            )
            alt_ok = all(msgs[i]["role"] != msgs[i + 1]["role"] for i in range(len(msgs) - 1))
            print(f"ascending by created_at : {order_ok}")
            print(f"strictly alternating    : {alt_ok}")
            print(f"first message           : {msgs[0]['created_at']} ({msgs[0]['role']})")
            print(f"last  message           : {msgs[-1]['created_at']} ({msgs[-1]['role']})")
            print()
            for m in msgs:
                who = "בעל העסק" if m["role"] == "user" else "העוזר   "
                body = m["content"].replace("\n", "\n            ")
                print(f"  [{who}] {body}\n")

            head("8. Does the chat agree with the LIVE bot config?")
            rb = await http.get("/api/bot/settings")
            cfg = rb.json()
            flows = cfg["lead_steps"]
            print(f"configured flows ({len(flows)}):")
            for k, f in flows.items():
                print(f"  {k:20s} flow_type={f['flow_type']:14s} {f['label']}")
            text = " ".join(m["content"] for m in msgs)
            for label in [f["label"] for f in flows.values()]:
                # the chat names each flow by its label (or an obvious variant)
                print(f"  label mentioned in the chat: {label!r:40s} "
                      f"-> {label in text}")
            file_steps = [(k, st["key"]) for k, f in flows.items()
                          for st in f["steps"] if st["type"] == "file"]
            print(f"  file steps really configured: {file_steps}")
            print(f"  booking-flow service binding : "
                  f"{[(k, f.get('service_name')) for k, f in flows.items() if f['flow_type'] == 'booking']}")
            print(f"  bot name in config           : {cfg['bot_profile']['name']}")
            print(f"  'מתוקי' appears in the chat   : {'מתוקי' in text}")
            print(f"  handoff keywords in config   : {cfg['handoff_keywords']}")

        # ------------------------------------------------------ tenant isolation
        head("9. TENANT ISOLATION — can another business see any of it?")
        async with tenant_connection(pool, OTHER_BID) as conn:
            print(f"other tenant SELECT CK bookings            : "
                  f"{await conn.fetchval('SELECT count(*) FROM bookings WHERE business_id=$1', BID)}  (want 0)")
            print(f"other tenant SELECT any booking at all     : "
                  f"{await conn.fetchval('SELECT count(*) FROM bookings')}  (its own only)")
            print(f"other tenant SELECT CK bot_builder_messages: "
                  f"{await conn.fetchval('SELECT count(*) FROM bot_builder_messages WHERE business_id=$1', BID)}  (want 0)")
            print(f"other tenant SELECT any build message      : "
                  f"{await conn.fetchval('SELECT count(*) FROM bot_builder_messages')}  (its own only)")
            try:
                await conn.execute(
                    "INSERT INTO bot_builder_messages (business_id, role, content) "
                    "VALUES ($1, 'user', 'poison')", BID)
                print("!! other tenant INSERTED a CK build message — WITH CHECK FAILED")
            except asyncpg.PostgresError as e:
                print(f"other tenant INSERT into CK build chat rejected: {type(e).__name__}")

        async with pool.acquire() as conn:
            async with conn.transaction():
                print(f"NO tenant context, bookings                : "
                      f"{await conn.fetchval('SELECT count(*) FROM bookings')}  (want 0)")
                print(f"NO tenant context, bot_builder_messages    : "
                      f"{await conn.fetchval('SELECT count(*) FROM bot_builder_messages')}  (want 0)")

        # the OTHER tenant's own HTTP view
        sid2 = await _session(redis, OTHER_BID, "other")
        async with httpx.AsyncClient(
            base_url=BASE, timeout=60,
            cookies={auth_service.SESSION_COOKIE_NAME: sid2},
        ) as http2:
            r1 = await http2.get("/api/bookings")
            r2 = await http2.get("/api/bot/ai/history")
            r3 = await http2.get("/api/bookings/alerts")
            other_ids = {b["id"] for b in r1.json().get("bookings", [])}
            ck_ids = {b["id"] for b in bookings}
            other_msgs = {m["content"] for m in r2.json().get("messages", [])}
            ck_msgs = {m["content"] for m in msgs}
            # The other tenant HAS its own rows — the test is that NONE of them
            # are ours, not that the list is empty.
            print(f"other tenant GET /api/bookings        : HTTP {r1.status_code}  "
                  f"{len(other_ids)} of ITS OWN rows; overlap with CK = "
                  f"{len(other_ids & ck_ids)}  (want 0)")
            print(f"other tenant GET /api/bot/ai/history  : HTTP {r2.status_code}  "
                  f"{len(other_msgs)} of ITS OWN msgs; overlap with CK = "
                  f"{len(other_msgs & ck_msgs)}  (want 0)")
            print(f"other tenant GET /api/bookings/alerts : HTTP {r3.status_code}  "
                  f"{len(r3.json().get('alerts', []))} alerts (want 0 — the "
                  f"alerts key is business-prefixed)")

        # ----------------------------------------------------- raw-ciphertext check
        head("10. Is the PII actually ciphertext on disk?")
        async with tenant_connection(pool, BID) as conn:
            row = await conn.fetchrow(
                "SELECT client_name, client_phone, notes, key_version FROM bookings "
                "WHERE business_id=$1 AND notes IS NOT NULL LIMIT 1", BID)
        print(f"  raw client_name  : {row['client_name'][:60]}…")
        print(f"  raw client_phone : {row['client_phone'][:60]}…")
        print(f"  raw notes        : {row['notes'][:60]}…")
        print(f"  key_version      : {row['key_version']}")
        looks_plain = any(
            "֐" <= ch <= "ת" for ch in (row["client_name"] or "")
        )
        print(f"  contains Hebrew letters in plaintext? {looks_plain}  (want False)")

        # ------------------------------------------------- the sweep did not bite
        head("11. Marked-row counts (re-run this block again in a few minutes)")
        async with tenant_connection(pool, BID) as conn:
            ref = f"conv:{BID}:ck-demo-bk-%"
            print(f"  leads   marked ck-demo-bk-* : "
                  f"{await conn.fetchval('SELECT count(*) FROM leads WHERE business_id=$1 AND cache_chat_ref LIKE $2', BID, ref)}")
            mix = await conn.fetch(
                "SELECT status, count(*) AS n FROM leads WHERE business_id=$1 "
                "AND cache_chat_ref LIKE $2 GROUP BY status", BID, ref)
            print("  their status mix            :",
                  {r["status"]: r["n"] for r in mix})
            print(f"  bookings via those leads    : "
                  f"{await conn.fetchval('SELECT count(*) FROM bookings WHERE business_id=$1 AND lead_id IN (SELECT id FROM leads WHERE business_id=$1 AND cache_chat_ref LIKE $2)', BID, ref)}")
            print(f"  build messages (author NULL): "
                  f"{await conn.fetchval('SELECT count(*) FROM bot_builder_messages WHERE business_id=$1 AND author_user_id IS NULL', BID)}")
            print(f"  TOTAL leads for the tenant  : "
                  f"{await conn.fetchval('SELECT count(*) FROM leads WHERE business_id=$1', BID)}")

        print("\nVERIFICATION COMPLETE")
    finally:
        await pool.close()
        await redis.aclose()


asyncio.run(main())
