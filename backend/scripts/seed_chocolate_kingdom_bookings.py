"""Extend the "chocolate kingdom" demo tenant — bookings + the AI build-chat.

A follow-up to `seed_chocolate_kingdom.py`. It touches NOTHING that script made
(page, gallery, services, hours, bot config, 500 leads, 15 conversations) and
adds only the two things the demo was still missing:

  1. ~50 BOOKINGS — a believable appointment book: some already happened, a few
     today, and a spread over the coming weeks, across all six services and all
     four statuses. Plus a handful of CUSTOMER-initiated cancellations and
     reschedules, so the owner's alerts inbox is not empty.
  2. The AI BOT-BUILDER conversation — 14 Hebrew messages in which the owner
     describes the business and the assistant converges on the FIVE flows that
     already exist in `bot_settings`. The demo blocks POST /api/bot/ai/chat on
     purpose (it costs a Gemini call), so the history has to be here already.

EVERYTHING goes through the real services, so encryption, key_version, the
double-booking guard and RLS behave exactly as in production:

  * bookings + their leads  → booking.create_public_booking  (the SAME function
                              the public page calls: PII encrypted, key_version
                              stamped, slot re-validated against compute_slots)
  * slot choice             → booking.compute_slots          (working hours,
                              min_notice=120, buffer=15, max_days=45, Asia/Jerusalem)
  * status changes          → booking.admin_update_booking
  * customer cancellations  → booking.cancel_booking_by_token + booking_alerts.push_alert
  * customer reschedules    → booking.reschedule_booking_by_token + push_alert
  * the build chat          → the SAME INSERT the /api/bot/ai/chat route runs
                              (bot_builder_messages is plaintext by design — it
                              is the owner's own config chat, not customer PII)

TWO deliberate exceptions to "everything through a service", both raw UPDATEs on
the SAME tenant-bound (RLS-scoped) connection, both touching only timestamps —
never PII, never ciphertext, never key_version:

  a) PAST bookings. `create_public_booking` re-validates the chosen time against
     `compute_slots`, which by design refuses anything before now()+min_notice.
     There is no service call that can put an appointment in the past. So a past
     booking is created on a real, currently-free FUTURE slot (full encryption
     path, full guard) and then its `scheduled_at`/`created_at` are moved back to
     a slot computed on the SAME honest grid: that weekday's working ranges,
     stepping by duration+buffer, with an occupancy check that reuses the
     service's own `_overlaps_any`. It is moved out of the future immediately, so
     the slot it borrowed is free again for the next row.
  b) The build-chat `created_at`, so the conversation reads as one sitting three
     weeks ago instead of 14 messages in the same millisecond.

MARKERS — everything this script writes is removable:
    bookings  : lead_id IN (SELECT id FROM leads WHERE business_id='<BID>'
                            AND cache_chat_ref LIKE 'conv:<BID>:ck-demo-bk-%')
    leads     : business_id='<BID>' AND cache_chat_ref LIKE 'conv:<BID>:ck-demo-bk-%'
    build chat: business_id='<BID>' AND author_user_id IS NULL
                (the real route always stamps the session user, so NULL is
                 exactly "seeded, not typed by a person")
    alerts    : Redis list `booking:alerts:<BID>`

Run inside the backend container:
  docker compose --env-file infra/.env -f infra/docker-compose.yml \
    exec -T backend sh -c "cd /app && PYTHONPATH=/app python scripts/seed_chocolate_kingdom_bookings.py"

Re-running is safe: the script wipes its own marked rows first.
All customer names/phones/emails below are INVENTED demo values.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, time, timedelta, timezone

from app.core.clients import create_pg_pool, create_redis
from app.core.config import get_settings
from app.db.session import tenant_connection
from app.services import booking as booking_service
from app.services import booking_alerts
from app.services.booking._helpers import BUSINESS_TZ
from app.services.booking.slots import _overlaps_any

BID = "fab99cce-f844-4fd4-8f95-c5ef2f6eda10"

# Same convention as the first seed: every conversation id this script mints
# starts with this, so the leads it creates carry a marker narrower than the
# tenant itself. `bk` distinguishes it from the first seed's `ck-demo-lead-*`
# and `ck-demo-wa-*`, so this batch can be dropped on its own.
MARKER = "ck-demo-bk-"

SEED = 20260723  # deterministic: a re-run reproduces the same book


# ============================================================================
# people + notes — Hebrew, and about chocolate
# ============================================================================

FIRST_NAMES = [
    "נועה", "יעל", "שירה", "תמר", "מיכל", "רונית", "אורלי", "הילה", "דנה", "ליאת",
    "מאיה", "אפרת", "סיגל", "ענבל", "קרן", "שני", "אביגיל", "רותם", "גל", "טל",
    "יוסי", "אבי", "רן", "עומר", "איתי", "ניר", "דור", "אלון", "גיא", "עידו",
    "אורי", "יונתן", "אסף", "רועי", "עמית", "שחר", "ליאור", "בר", "נדב", "תומר",
]
LAST_NAMES = [
    "כהן", "לוי", "מזרחי", "פרץ", "ביטון", "דהן", "אברהם", "פרידמן", "שפירא", "אזולאי",
    "גבאי", "אוחיון", "מלכה", "בן דוד", "חדד", "אמסלם", "שרון", "ברקוביץ", "נחום",
    "רוזנברג", "קפלן", "אדרי", "סבן", "יעקובי", "הראל", "זהבי", "עמר", "נגר",
]
EMAIL_HOSTS = ["gmail.com", "walla.co.il", "outlook.com", "hotmail.com"]

# Notes are per-service, so a note never contradicts what was booked.
NOTES_BY_SERVICE = {
    "סדנת שוקולד ליום הולדת": [
        "החוגגת בת 8, מבקשים נושא יוניקורן לסינרים",
        "יש ילד עם אלרגיה לאגוזים — חשוב מאוד",
        "18 ילדים + 4 מלווים, נגיע ברכב אחד",
        "אפשר להוסיף עוגת יום הולדת בסוף?",
        "מבקשים לסיים בזמן, יש הסעה ב-17:00",
        None,
    ],
    "Happy Hour שוקולד לחברות": [
        "כ-45 עובדים, צריך חשבונית עם מספר הזמנה",
        "חלק מהצוות כשר למהדרין",
        "רוצים מזרקת שוקולד ותחנת יצירה",
        "האירוע לסיום רבעון, נשמח לתמונות",
        None,
    ],
    "חדר בריחה: צ׳רלי בממלכת השוקולד": [
        "5 משתתפים, הצעיר בן 9",
        "יום הולדת להפתעה — לא לספר לחוגג",
        "פעם שנייה אצלכם, הפעם בלי רמזים",
        None,
    ],
    "סיור וטעימות במרכז המבקרים": [
        "כיתה ד' — 28 ילדים ו-3 מלוות",
        "משפחה עם עגלה, צריך גישה",
        "אורחים מחו\"ל, אפשר הסבר באנגלית?",
        "12 אנשים מהמשרד, בהפסקת צהריים",
        None,
    ],
    "סדנת יצירה ולימוד למבוגרים": [
        "מתנת יום נישואין, זוג",
        "רוצה להתמקד בטמפרינג",
        "אני קונדיטורית ביתית, מחפשת עומק",
        None,
    ],
    "מארז מתנה ממותג — הרכבה אישית": [
        "מארז אחד לספק, עם לוגו החברה בזהב",
        "לוקחים לחתונה — 3 מארזים",
        "בלי אלכוהול בבקשה",
        "צריך את זה עד ה-15 לחודש",
        None,
    ],
}


def _phone(rng: random.Random) -> str:
    return f"05{rng.choice('02345689')}{rng.randint(1000000, 9999999)}"


_TRANSLIT = {
    "א": "a", "ב": "b", "ג": "g", "ד": "d", "ה": "h", "ו": "v", "ז": "z", "ח": "h",
    "ט": "t", "י": "y", "כ": "k", "ך": "k", "ל": "l", "מ": "m", "ם": "m", "נ": "n",
    "ן": "n", "ס": "s", "ע": "a", "פ": "p", "ף": "f", "צ": "tz", "ץ": "tz", "ק": "k",
    "ר": "r", "ש": "sh", "ת": "t",
}


def _translit(hebrew: str) -> str:
    return "".join(_TRANSLIT.get(ch, "") for ch in hebrew) or "user"


def _person(rng: random.Random) -> tuple[str, str, str | None]:
    """One invented customer: (name, phone, email-or-None)."""
    name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
    email = None
    if rng.random() < 0.65:
        email = f"{_translit(name.split()[0])}{rng.randint(1, 99)}@{rng.choice(EMAIL_HOSTS)}"
    return name, _phone(rng), email


# ============================================================================
# the AI build-chat — it must agree with the FIVE flows already in bot_settings
# ============================================================================
#
# Cross-checked against the live config: birthday_workshop / company_event /
# gift_boxes (flow_type=lead), book_visit (flow_type=booking, bound to the
# service "סיור וטעימות במרכז המבקרים") and talk_to_human (human_handoff).
# The file steps mentioned below are the two that really exist:
# birthday_workshop.הזמנה_מעוצבת and gift_boxes.קובץ_לוגו.

BUILD_CHAT = [
    ("user",
     "היי, יש לי עסק לסדנאות שוקולד בנתניה — chocolate kingdom. אנחנו מארחים "
     "ימי הולדת לילדים, אירועי חברות, יש לנו גם חדר בריחה ומרכז מבקרים. "
     "אני רוצה בוט שיענה בוואטסאפ במקומי, כי אני מפספסת פניות."),

    ("assistant",
     "איזה כיף, ממלכת שוקולד 🍫 בוא נבנה את זה נכון.\n"
     "לפני שאני מציע מבנה — כשמישהו פונה אליכם היום, מה הדבר הראשון שאת "
     "צריכה לדעת ממנו? ומה בסוף השיחה גורם לך להגיד \"יש, זה ליד אמיתי\"?"),

    ("user",
     "בעיקר שם וטלפון, כי בסוף אני מתקשרת. אחרי זה זה מאוד תלוי — ליום הולדת "
     "אני צריכה לדעת גיל וכמה ילדים, ולחברות אני צריכה שם חברה ומייל כדי "
     "לשלוח הצעת מחיר."),

    ("assistant",
     "זה בדיוק הסימן שלא צריך שאלון אחד אלא כמה מסלולים — אחרת כולם עונים על "
     "שאלות שלא רלוונטיות להם ונוטשים באמצע.\n\n"
     "מהתיאור שלך אני מזהה שלושה קהלים שונים לגמרי: הורים ליום הולדת, אנשי "
     "רכש/רווחה בחברות, ומי שרוצה מארזי מתנה. נכון?"),

    ("user",
     "נכון. ומארזי מתנה זה באמת נושא בפני עצמו, יש לנו הרבה חברות שמזמינות "
     "מארזים ממותגים לחגים."),

    ("assistant",
     "מעולה. אז נתחיל בשלושה מסלולי איסוף פרטים:\n\n"
     "1. *סדנת יום הולדת לילדים* — שם מלא, טלפון, גיל החוגג (בחירה: 4-6 / 7-9 / "
     "10-12 / 13+), כמה ילדים, ותאריך מבוקש.\n"
     "2. *Happy Hour ואירועי חברות* — שם, חברה, טלפון, אימייל, סוג האירוע "
     "ומספר משתתפים.\n"
     "3. *מארזי מתנה ממותגים* — שם, טלפון וכמות מארזים.\n\n"
     "שאלת הגיל והכמות כבחירה מתוך רשימה ולא כטקסט חופשי — זה מוריד טעויות "
     "ומאפשר לך לסנן אחר כך."),

    ("user",
     "אהבתי. שאלה — הרבה הורים שולחים לי את ההזמנה המעוצבת של יום ההולדת "
     "בוואטסאפ, ואנחנו מתאימים לפיה את הסינרים. וגם החברות שולחות לוגו "
     "למארזים. הבוט יכול לקבל קבצים?"),

    ("assistant",
     "כן, ושווה לנצל את זה. אוסיף שלב קובץ *לא חובה* בשני מקומות בלבד:\n"
     "• במסלול יום ההולדת — \"הזמנה מעוצבת\" (תמונה או PDF).\n"
     "• במסלול מארזי המתנה — \"קובץ לוגו\" (תמונה או PDF).\n\n"
     "לא חובה, כדי שמי שאין לו קובץ ביד לא ייתקע ויעזוב. הקבצים נשמרים "
     "מוצפנים ואת רואה אותם בכרטיס הליד."),

    ("user",
     "מושלם. יש לנו גם את מרכז המבקרים — שם זה סיפור אחר, אנשים פשוט רוצים "
     "לתפוס תאריך לסיור. אני לא רוצה שהם יחכו לי בטלפון בשביל זה."),

    ("assistant",
     "אז זה לא מסלול ליד אלא מסלול *הזמנת תור* — הבוט יציג את הזמנים הפנויים "
     "בפועל ויסגור מועד בלי שתתערבי.\n\n"
     "אקרא לו *הזמנת סיור במרכז המבקרים* ואקשר אותו לשירות \"סיור וטעימות "
     "במרכז המבקרים\", כך שיאסוף רק שם מלא, "
     "טלפון ומספר מבקרים. שאר החוויות (יום הולדת, חברות, חדר בריחה) נשארות "
     "כליד, כי שם את רוצה לדבר איתם לפני שסוגרים תאריך."),

    ("user",
     "בדיוק. ומה קורה כשמישהו שואל משהו שהבוט לא יודע? יש לנו שאלות אלרגיות, "
     "כשרות, ביטולים — אני לא רוצה שהוא ימציא."),

    ("assistant",
     "שני דברים.\n"
     "ראשית, אוסיף מסלול חמישי — *דברו עם נציג* — שלא שואל כלום ומעביר אליכם "
     "ישירות. הוא גם ייתפס אוטומטית ממילים כמו \"נציג\", \"אדם\", \"תלונה\", "
     "בכל שלב בשיחה.\n"
     "שנית, בהנחיות של הבוט ייכתב במפורש: אל תמציא מחירים, תאריכים או זמינות. "
     "אם אינך יודע — אמור שנציג יבדוק ויחזור. זה מה שמונע ממנו לענות מדעתו על "
     "אלרגיות וכשרות."),

    ("user",
     "מצוין. אנחנו פתוחים ראשון עד חמישי 9:00-13:00 ו-14:00-18:00, בחמישי עד "
     "19:00, ושישי רק בבוקר עד 13:00. שבת סגור. תן לו איזה אופי מתוק, שיתאים "
     "לנו."),

    ("assistant",
     "קיבלתי — השעות האלה כבר מוגדרות במסך הזמינות, אז מסלול הסיור יציע רק "
     "מועדים אמיתיים מתוכן, ולא יציע שבת.\n\n"
     "קראתי לו *מתוקי*, עם ברכת פתיחה חמה ואימוג'ים במידה, וסגרתי סגירת שיחה "
     "אוטומטית אחרי שעתיים של שקט.\n\n"
     "אז המבנה הסופי: חמישה מסלולים — יום הולדת, אירועי חברות, מארזי מתנה, "
     "הזמנת סיור (תור אמיתי) ומעבר לנציג. אפשר לפרסם ולנסות בלייב 🍫"),
]


# ============================================================================
# the past-slot grid (see exception (a) in the module docstring)
# ============================================================================

def _past_candidates(
    day: datetime.date, working_hours: dict, duration: int, buffer_min: int
) -> list[datetime]:
    """Candidate UTC starts on a past LOCAL day, on the SAME grid compute_slots uses.

    Mirrors compute_slots step 2 exactly: that weekday's ranges, stepping by
    duration+buffer, and the appointment itself (not the trailing buffer) must
    fit before the range end. What it deliberately does NOT do is apply the
    notice/max-days window — that window is precisely why a past booking cannot
    go through the service.
    """
    weekday_key = str((day.weekday() + 1) % 7)  # Python Mon=0 → our Sun=0
    out: list[datetime] = []
    for rng_ in working_hours.get(weekday_key) or []:
        try:
            sh, sm = (int(x) for x in rng_["s"].split(":"))
            eh, em = (int(x) for x in rng_["e"].split(":"))
        except (KeyError, ValueError, TypeError):
            continue
        cursor = datetime.combine(day, time(sh, sm), tzinfo=BUSINESS_TZ)
        end_local = datetime.combine(day, time(eh, em), tzinfo=BUSINESS_TZ)
        while cursor + timedelta(minutes=duration) <= end_local:
            out.append(cursor.astimezone(timezone.utc))
            cursor += timedelta(minutes=duration + buffer_min)
    return out


# ============================================================================
# the seed
# ============================================================================

async def _wipe(pool, redis) -> None:
    """Remove everything a previous run of THIS script wrote (marked rows only)."""
    async with tenant_connection(pool, BID) as conn:
        ref = f"conv:{BID}:{MARKER}%"
        n_bk = await conn.fetchval(
            "SELECT count(*) FROM bookings WHERE business_id = $1 AND lead_id IN "
            "(SELECT id FROM leads WHERE business_id = $1 AND cache_chat_ref LIKE $2)",
            BID, ref,
        )
        await conn.execute(
            "DELETE FROM bookings WHERE business_id = $1 AND lead_id IN "
            "(SELECT id FROM leads WHERE business_id = $1 AND cache_chat_ref LIKE $2)",
            BID, ref,
        )
        await conn.execute(
            "DELETE FROM flow_events WHERE business_id = $1 AND lead_id IN "
            "(SELECT id FROM leads WHERE business_id = $1 AND cache_chat_ref LIKE $2)",
            BID, ref,
        )
        n_ld = await conn.fetchval(
            "SELECT count(*) FROM leads WHERE business_id = $1 AND cache_chat_ref LIKE $2",
            BID, ref,
        )
        await conn.execute(
            "DELETE FROM leads WHERE business_id = $1 AND cache_chat_ref LIKE $2",
            BID, ref,
        )
        n_msg = await conn.fetchval(
            "SELECT count(*) FROM bot_builder_messages "
            "WHERE business_id = $1 AND author_user_id IS NULL", BID,
        )
        await conn.execute(
            "DELETE FROM bot_builder_messages "
            "WHERE business_id = $1 AND author_user_id IS NULL", BID,
        )
    await redis.delete(f"booking:alerts:{BID}")
    print(f"  wiped: bookings={n_bk} leads(marked)={n_ld} "
          f"build_chat={n_msg} + the alerts list")


async def _make_booking(
    conn, rng, *, service, date_str, time_str, conv_suffix
) -> dict:
    """One booking through the REAL public-booking service (PII encrypted there)."""
    name, phone, email = _person(rng)
    note = rng.choice(NOTES_BY_SERVICE.get(service["name"], [None]))
    return await booking_service.create_public_booking(
        conn, BID,
        service_id=service["id"],
        date_str=date_str,
        time_str=time_str,
        name=name,
        phone=phone,
        email=email,
        notes=note,
        conversation_id=f"{MARKER}{conv_suffix}",
    ) | {"_name": name, "_service": service["name"]}


async def _borrow_slot_for(conn, rng, svc, today_local, tried: set) -> tuple[str, str]:
    """A currently-OFFERED (date, time) for this service — the landing pad for a
    booking that will immediately be moved into the past.

    It has to be for the SAME service as the past booking, because the row keeps
    the service (and its duration) it was created with; only the timestamps move.
    """
    for _ in range(400):
        day = today_local + timedelta(days=rng.randint(2, 44))
        date_str = day.isoformat()
        slots = await booking_service.compute_slots(
            conn, BID, service_id=svc["id"], date_str=date_str
        )
        free = [s for s in slots if (svc["id"], date_str, s) not in tried]
        if free:
            t = rng.choice(free)
            tried.add((svc["id"], date_str, t))
            return date_str, t
    raise RuntimeError(f"no free future slot to borrow for {svc['name']}")


async def main() -> None:
    rng = random.Random(SEED)
    s = get_settings()
    pool = await create_pg_pool(s)
    redis = create_redis(s)
    try:
        print("== wiping any previous run of THIS script ==")
        await _wipe(pool, redis)

        async with tenant_connection(pool, BID) as conn:
            settings = await booking_service.get_settings(conn, BID)
            services = await booking_service.list_services(conn, BID)
        services = [dict(x) for x in services if x["active"]]
        working_hours = settings["working_hours"] or {}
        buffer_min = int(settings["buffer_minutes"])
        print(f"  services={len(services)} buffer={buffer_min} "
              f"notice={settings['min_notice_minutes']} max_days={settings['max_days_ahead']}")

        today_local = datetime.now(BUSINESS_TZ).date()
        made: list[dict] = []
        seq = 0

        # ------------------------------------------------------------------
        # 1. PAST — 20 appointments over the last ~5 weeks
        # ------------------------------------------------------------------
        print("== past bookings ==")
        past_plan = (["completed"] * 13 + ["cancelled"] * 4 + ["confirmed"] * 3)
        rng.shuffle(past_plan)
        occupied: dict[str, list[tuple[datetime, int]]] = {}
        borrowed: set = set()

        async with tenant_connection(pool, BID) as conn:
            for status in past_plan:
                # pick a real past slot on the honest grid, free of our own rows
                for _ in range(300):
                    svc = rng.choice(services)
                    dur = int(svc["duration_minutes"])
                    day = today_local - timedelta(days=rng.randint(1, 35))
                    cands = _past_candidates(day, working_hours, dur, buffer_min)
                    rng.shuffle(cands)
                    key = day.isoformat()
                    hit = next(
                        (c for c in cands if not _overlaps_any(
                            c, c + timedelta(minutes=dur), dur, buffer_min,
                            occupied.get(key, []))),
                        None,
                    )
                    if hit is not None:
                        break
                else:
                    raise RuntimeError("could not place a past booking")

                b_date, b_time = await _borrow_slot_for(
                    conn, rng, svc, today_local, borrowed
                )
                seq += 1
                bk = await _make_booking(
                    conn, rng, service=svc, date_str=b_date, time_str=b_time,
                    conv_suffix=f"{seq:03d}",
                )
                # --- exception (a): move it to the past (timestamps only) ---
                created = hit - timedelta(days=rng.randint(2, 9),
                                          hours=rng.randint(0, 20))
                await conn.execute(
                    "UPDATE bookings SET scheduled_at = $3::timestamptz, "
                    "created_at = $4::timestamptz "
                    "WHERE id = $1 AND business_id = $2",
                    bk["booking_id"], BID, hit, created,
                )
                # keep the linked lead's history coherent with its booking
                await conn.execute(
                    "UPDATE leads SET started_at = $3::timestamptz, "
                    "last_activity_at = $3::timestamptz, "
                    "submitted_at = $3::timestamptz "
                    "WHERE id = $1 AND business_id = $2",
                    bk["lead_id"], BID, created,
                )
                occupied.setdefault(day.isoformat(), []).append(
                    (hit, int(svc["duration_minutes"]))
                )
                if status != "pending":
                    await booking_service.admin_update_booking(
                        conn, BID, bk["booking_id"],
                        status=status, date_str=None, time_str=None,
                    )
                made.append({**bk, "when": hit, "status": status, "bucket": "past"})
        print(f"  {len(made)} past bookings placed")

        # ------------------------------------------------------------------
        # 2. TODAY — 3 earlier today (moved back) + up to 3 on real open slots
        # ------------------------------------------------------------------
        print("== today ==")
        today_made = 0
        async with tenant_connection(pool, BID) as conn:
            # (a) earlier today — same past-move path
            now_utc = datetime.now(timezone.utc)
            for status in ["completed", "completed", "cancelled"]:
                svc = rng.choice(services)
                dur = int(svc["duration_minutes"])
                cands = [
                    c for c in _past_candidates(today_local, working_hours, dur, buffer_min)
                    if c + timedelta(minutes=dur) < now_utc
                ]
                rng.shuffle(cands)
                hit = next(
                    (c for c in cands if not _overlaps_any(
                        c, c + timedelta(minutes=dur), dur, buffer_min,
                        occupied.get(today_local.isoformat(), []))),
                    None,
                )
                if hit is None:
                    print(f"  (no free earlier-today slot for {svc['name']}, skipped)")
                    continue
                b_date, b_time = await _borrow_slot_for(
                    conn, rng, svc, today_local, borrowed
                )
                seq += 1
                bk = await _make_booking(
                    conn, rng, service=svc, date_str=b_date, time_str=b_time,
                    conv_suffix=f"{seq:03d}",
                )
                created = hit - timedelta(days=rng.randint(1, 6))
                await conn.execute(
                    "UPDATE bookings SET scheduled_at = $3::timestamptz, "
                    "created_at = $4::timestamptz "
                    "WHERE id = $1 AND business_id = $2",
                    bk["booking_id"], BID, hit, created,
                )
                await conn.execute(
                    "UPDATE leads SET started_at = $3::timestamptz, "
                    "last_activity_at = $3::timestamptz, "
                    "submitted_at = $3::timestamptz "
                    "WHERE id = $1 AND business_id = $2",
                    bk["lead_id"], BID, created,
                )
                occupied.setdefault(today_local.isoformat(), []).append((hit, dur))
                await booking_service.admin_update_booking(
                    conn, BID, bk["booking_id"],
                    status=status, date_str=None, time_str=None,
                )
                made.append({**bk, "when": hit, "status": status, "bucket": "today"})
                today_made += 1

            # (b) later today — genuinely offered slots, no move at all
            for status in ["confirmed", "confirmed", "pending"]:
                placed = False
                for svc in rng.sample(services, len(services)):
                    slots = await booking_service.compute_slots(
                        conn, BID, service_id=svc["id"],
                        date_str=today_local.isoformat(),
                    )
                    if not slots:
                        continue
                    t = rng.choice(slots)
                    seq += 1
                    bk = await _make_booking(
                        conn, rng, service=svc,
                        date_str=today_local.isoformat(), time_str=t,
                        conv_suffix=f"{seq:03d}",
                    )
                    if status != "pending":
                        await booking_service.admin_update_booking(
                            conn, BID, bk["booking_id"],
                            status=status, date_str=None, time_str=None,
                        )
                    made.append({
                        **bk,
                        "when": datetime.fromisoformat(bk["scheduled_at"]),
                        "status": status, "bucket": "today",
                    })
                    today_made += 1
                    placed = True
                    break
                if not placed:
                    print("  (no offered slot left today — the day is short, skipped)")
        print(f"  {today_made} bookings today")

        # ------------------------------------------------------------------
        # 3. FUTURE — 26 over the coming weeks, all on genuinely offered slots
        # ------------------------------------------------------------------
        print("== future bookings ==")
        future_plan = ["confirmed"] * 15 + ["pending"] * 8 + ["cancelled"] * 3
        rng.shuffle(future_plan)
        future_made = 0
        async with tenant_connection(pool, BID) as conn:
            for status in future_plan:
                for _ in range(300):
                    svc = rng.choice(services)
                    d = today_local + timedelta(days=rng.randint(1, 44))
                    slots = await booking_service.compute_slots(
                        conn, BID, service_id=svc["id"], date_str=d.isoformat()
                    )
                    if slots:
                        break
                else:
                    print("  (no free future slot left, stopping early)")
                    break
                t = rng.choice(slots)
                seq += 1
                bk = await _make_booking(
                    conn, rng, service=svc, date_str=d.isoformat(), time_str=t,
                    conv_suffix=f"{seq:03d}",
                )
                if status != "pending":
                    await booking_service.admin_update_booking(
                        conn, BID, bk["booking_id"],
                        status=status, date_str=None, time_str=None,
                    )
                made.append({
                    **bk,
                    "when": datetime.fromisoformat(bk["scheduled_at"]),
                    "status": status, "bucket": "future",
                })
                future_made += 1
        print(f"  {future_made} future bookings")

        # ------------------------------------------------------------------
        # 4. CUSTOMER-initiated changes → the alerts inbox
        # ------------------------------------------------------------------
        print("== customer cancellations / reschedules (alerts) ==")
        alerts_made = 0
        async with tenant_connection(pool, BID) as conn:
            # reschedules: 3 future bookings the customer moved themselves
            # A booking gets at most ONE customer action — a row that was already
            # moved must not then be cancelled, or the alerts feed tells a story
            # the calendar doesn't back up.
            touched: set[str] = set()
            movable = [m for m in made
                       if m["bucket"] == "future" and m["status"] in ("confirmed", "pending")]
            rng.shuffle(movable)
            for m in movable[:3]:
                target = None
                # re-read the booking to get its service id for the slot lookup
                bk_row = await booking_service.get_booking(conn, BID, m["booking_id"])
                for _ in range(200):
                    d = today_local + timedelta(days=rng.randint(1, 44))
                    slots = await booking_service.compute_slots(
                        conn, BID, service_id=bk_row["service_id"],
                        date_str=d.isoformat(),
                    )
                    if slots:
                        target = (d.isoformat(), rng.choice(slots))
                        break
                if target is None:
                    continue
                res = await booking_service.reschedule_booking_by_token(
                    conn, BID, m["cancel_token"],
                    date_str=target[0], time_str=target[1],
                )
                if res:
                    await booking_alerts.push_alert(
                        redis, BID, res["booking_id"], "rescheduled"
                    )
                    alerts_made += 1
                    touched.add(m["booking_id"])
                    print(f"  rescheduled → {target[0]} {target[1]}  ({m['_service']})")

            # cancellations: 4 the customer cancelled via their link
            cancellable = [m for m in made
                           if m["status"] in ("confirmed", "pending")
                           and m["bucket"] in ("future", "today")
                           and m["booking_id"] not in touched]
            rng.shuffle(cancellable)
            for m in cancellable[:4]:
                res = await booking_service.cancel_booking_by_token(
                    conn, BID, m["cancel_token"]
                )
                if res:
                    await booking_alerts.push_alert(
                        redis, BID, res["booking_id"], "cancelled"
                    )
                    alerts_made += 1
                    print(f"  cancelled     ({m['_service']})")
        print(f"  {alerts_made} alerts pushed")

        # ------------------------------------------------------------------
        # 5. the AI build-chat
        # ------------------------------------------------------------------
        print("== bot-builder conversation ==")
        # One sitting, three weeks ago: each turn a couple of minutes apart, so
        # the history endpoint's ORDER BY created_at is unambiguous.
        base = datetime.now(timezone.utc) - timedelta(days=21, hours=3)
        async with tenant_connection(pool, BID) as conn:
            for i, (role, content) in enumerate(BUILD_CHAT):
                await conn.execute(
                    """
                    INSERT INTO bot_builder_messages
                        (business_id, author_user_id, role, content, created_at)
                    VALUES ($1, NULL, $2, $3, $4::timestamptz)
                    """,
                    BID, role, content, base + timedelta(minutes=i * 2 + (0 if role == "user" else 1)),
                )
        print(f"  {len(BUILD_CHAT)} messages "
              f"({sum(1 for r, _ in BUILD_CHAT if r == 'user')} user / "
              f"{sum(1 for r, _ in BUILD_CHAT if r == 'assistant')} assistant)")

        print(f"\nDone. bookings created = {len(made)}")
    finally:
        await pool.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
