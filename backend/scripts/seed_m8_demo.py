"""Seed realistic M8 demo data (handoff conversations) for Omer's business.

Creates a few live conversations in Redis (full transcript + status) plus a
linked, ENCRYPTED lead in Postgres for each — exactly the way the runtime would,
so the dashboard shows real, consistent data:

  * 2 conversations "waiting" (המתנה לנציג)  → show up in the home "מחכים לך" alert
  * 1 conversation "human"   (בשיחה עם נציג) → already taken over, has owner replies
  * 1 conversation "closed"  (טופל)          → a finished chat

Run inside the backend container:
  docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
    run --rm backend sh -c "cd /app && PYTHONPATH=/app python scripts/seed_m8_demo.py"

Re-running is safe: it first clears these demo conversations + their demo leads
(scoped to the demo conversation refs only) so nothing piles up.

NOTE: Redis conversations have a ~60-minute sliding TTL, so the live rows expire
after about an hour of no activity. The leads in Postgres persist. Re-run this
script to refresh the live rows. All names/phones below are FAKE demo values.
"""

from __future__ import annotations

import asyncio

from app.core.clients import create_pg_pool, create_redis
from app.core.config import get_settings
from app.db.session import tenant_connection
from app.services import conversation_state as cs
from app.services import leads as leads_service

# Omer's business (found earlier via admin psql; identity tables are RLS-locked).
BUSINESS_ID = "7fca1b13-902a-4ce2-a4a4-28ecd48f96eb"

# Each demo conversation: a stable id, a final chat status, the linked lead's
# flow + collected answers (Hebrew keys → phone/name get their own columns), and
# the transcript (role, body) in order.
DEMOS = [
    {
        "conv_id": "demo-wa-0541112233",
        "status": cs.STATUS_WAITING,
        "flow": "ביטוח רכב",
        "lead_complete": False,
        "answers": {
            "שם_מלא": "דנה לוי",
            "טלפון": "0541112233",
            "סוג_רכב": "טויוטה קורולה 2021",
        },
        "handoff": True,
        "messages": [
            ("customer", "היי, אני מעוניינת בהצעת מחיר לביטוח רכב"),
            ("bot", "שלום! אשמח לעזור 😊 מה השם המלא שלך?"),
            ("customer", "דנה לוי"),
            ("bot", "נעים מאוד דנה! מה מספר הטלפון שלך?"),
            ("customer", "0541112233"),
            ("bot", "מצוין. איזה סוג רכב יש לך?"),
            ("customer", "טויוטה קורולה 2021"),
            ("bot", "תודה! רוצה שאעביר אותך לנציג אנושי להמשך?"),
            ("customer", "כן, אני מעדיפה לדבר עם נציג"),
            ("bot", "מעביר אותך לנציג שלנו, הוא יחזור אליך בהקדם 🙏"),
            ("customer", "אפשר היום בבוקר?"),
        ],
    },
    {
        "conv_id": "demo-wa-0529998877",
        "status": cs.STATUS_WAITING,
        "flow": "פנייה כללית",
        "lead_complete": False,
        "answers": {
            "שם_מלא": "יוסי מזרחי",
            "טלפון": "0529998877",
        },
        "handoff": True,
        "messages": [
            ("customer", "שלום, יש לי שאלה על השירות שלכם"),
            ("bot", "היי! אשמח לעזור. מה השם שלך?"),
            ("customer", "יוסי מזרחי"),
            ("bot", "תודה יוסי. מה מספר הטלפון ליצירת קשר?"),
            ("customer", "0529998877"),
            ("customer", "בעצם אני מעדיף לדבר עם נציג אנושי בבקשה"),
            ("bot", "בהחלט, מעביר אותך לנציג 🙏"),
        ],
    },
    {
        "conv_id": "demo-wa-0507776655",
        "status": cs.STATUS_HUMAN,
        "flow": "ביטוח דירה",
        "lead_complete": True,
        "answers": {
            "שם_מלא": "אורן ביטון",
            "טלפון": "0507776655",
            "סוג_נכס": "דירת 4 חדרים",
        },
        "handoff": True,
        "messages": [
            ("customer", "אהלן, רציתי לבדוק לגבי ביטוח דירה"),
            ("bot", "שלום! מה השם המלא שלך?"),
            ("customer", "אורן ביטון"),
            ("bot", "תודה. רוצה שאחבר אותך לנציג?"),
            ("customer", "כן עדיף נציג"),
            ("bot", "מעביר אותך לנציג 🙏"),
            ("owner", "היי אורן, כאן רועי מהצוות 👋 איך אפשר לעזור?"),
            ("customer", "רציתי לדעת אם יש מסלול משפחתי"),
            ("owner", "כן בהחלט! יש לנו מסלול משפחתי משתלם, אשלח לך פרטים עכשיו 📄"),
        ],
    },
    {
        "conv_id": "demo-wa-0533334444",
        "status": cs.STATUS_CLOSED,
        "flow": "פנייה כללית",
        "lead_complete": True,
        "answers": {
            "שם_מלא": "מיכל אברהם",
            "טלפון": "0533334444",
        },
        "handoff": True,
        "messages": [
            ("customer", "שלום, אפשר לעזור לי עם חידוש פוליסה?"),
            ("bot", "שלום מיכל! מעביר אותך לנציג שיעזור עם החידוש 🙏"),
            ("owner", "היי מיכל, טיפלתי בחידוש — הפוליסה שלך פעילה לשנה נוספת ✅"),
            ("customer", "וואו תודה רבה! 🙏"),
            ("owner", "בכיף, שיהיה יום נעים! 😊"),
        ],
    },
]


async def _wipe_demo_leads(pool) -> None:
    """Remove prior demo leads + their events (scoped to the demo conv refs only)."""
    refs = [f"conv:{BUSINESS_ID}:{d['conv_id']}" for d in DEMOS]
    async with tenant_connection(pool, BUSINESS_ID) as conn:
        # Delete events first (FK), then the leads — only rows we seeded.
        await conn.execute(
            "DELETE FROM flow_events WHERE business_id = $1 AND lead_id IN "
            "(SELECT id FROM leads WHERE business_id = $1 AND cache_chat_ref = ANY($2::text[]))",
            BUSINESS_ID, refs,
        )
        await conn.execute(
            "DELETE FROM leads WHERE business_id = $1 AND cache_chat_ref = ANY($2::text[])",
            BUSINESS_ID, refs,
        )


async def seed() -> None:
    settings = get_settings()
    pool = await create_pg_pool(settings)
    redis = create_redis(settings)
    try:
        await _wipe_demo_leads(pool)

        for d in DEMOS:
            conv_id = d["conv_id"]

            # 1) Reset any prior live transcript/state for this conversation.
            await cs.clear_state(redis, BUSINESS_ID, conv_id)

            # 2) Create + populate the linked lead (encrypted at rest, RLS-scoped).
            async with tenant_connection(pool, BUSINESS_ID) as conn:
                lead_id = await leads_service.create_lead(
                    conn, BUSINESS_ID,
                    lead_name=d["flow"], conversation_id=conv_id, is_test=False,
                )
                await leads_service.update_lead(
                    conn, BUSINESS_ID, lead_id,
                    collected=d["answers"], last_step_index=len(d["answers"]),
                )
                if d["lead_complete"]:
                    await leads_service.complete_lead(
                        conn, BUSINESS_ID, lead_id, d["answers"]
                    )
                if d["handoff"]:
                    await leads_service.log_event(
                        conn, BUSINESS_ID, lead_id, d["flow"],
                        leads_service.EVENT_HANDOFF, step_index=None, is_test=False,
                    )

            # 3) Write the full transcript into Redis (oldest → newest).
            for role, body in d["messages"]:
                await cs.append_message(redis, BUSINESS_ID, conv_id, role, body)

            # 4) Set the final chat status.
            await cs.set_status(redis, BUSINESS_ID, conv_id, d["status"])

            print(f"  ✓ {conv_id:22s} status={d['status']:8s} "
                  f"msgs={len(d['messages'])} flow={d['flow']}")

        print(f"\nDone. Seeded {len(DEMOS)} demo conversations for the business.")
        print("Open the dashboard → 'שיחות' to see them (and the home 'מחכים לך' alert).")
        print("Note: live conversations expire from Redis after ~60 min — re-run to refresh.")
    finally:
        await pool.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(seed())
