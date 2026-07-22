"""Seed the "chocolate kingdom" demo tenant — DATA ONLY, through the real services.

Everything a visitor to the demo sees is created here, and every write goes
through the SAME service function a real owner/customer upload would hit, so the
demo exercises encryption, `key_version`, RLS and the disk/bucket layout exactly
as production does:

  * business page fields   → booking.update_page          (booking_settings row)
  * gallery images         → business_images.save_image   (bytes to /data/...)
                             + booking.create_image       (the rows)
  * bot config             → BotSettings model + bot_settings.save_settings
  * services + hours       → booking.create_service / update_settings
  * 500 leads              → leads.create_lead / update_lead / complete_lead /
                             set_lead_status / log_event
  * lead file answers      → file_storage.put_encrypted + a lead_files row
  * live conversations     → conversation_state (encrypted bodies, M19)

ONE deliberate exception to "everything through a service": the lead timestamps.
`create_lead` hard-codes `started_at = now()`, and nothing in the service surface
can backdate a lead — but a demo where all 500 leads landed in the same minute
makes the week/month filters meaningless. So after each chunk is created through
the services, a single UPDATE on the SAME tenant-bound connection rewrites only
`started_at` / `last_activity_at` / `submitted_at`. It touches no PII, no
ciphertext and no key_version, and it is still RLS-scoped.

CLEANUP — the whole batch is removable with, under a tenant connection bound to
this business:
    DELETE FROM flow_events      WHERE business_id = '<BID>';
    DELETE FROM lead_files       WHERE business_id = '<BID>';
    DELETE FROM leads            WHERE business_id = '<BID>';
    DELETE FROM business_images  WHERE business_id = '<BID>';
    DELETE FROM services         WHERE business_id = '<BID>';
    DELETE FROM bot_settings     WHERE business_id = '<BID>';
    DELETE FROM booking_settings WHERE business_id = '<BID>';
Every lead this script writes ALSO carries the narrower marker
`cache_chat_ref LIKE 'conv:<BID>:ck-demo-%'`, so the leads alone can be dropped
without touching the page/bot config.

Run inside the backend container:
  docker compose --env-file infra/.env -f infra/docker-compose.yml \
    exec -T backend sh -c "cd /app && PYTHONPATH=/app python scripts/seed_chocolate_kingdom.py"

Re-running is safe: the script wipes its own marked rows first.
All customer names/phones below are INVENTED demo values.
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from app.core import crypto
from app.core.clients import create_pg_pool, create_redis
from app.core.config import get_settings
from app.db.session import tenant_connection
from app.models.bot_builder import BotSettings
from app.services import booking as booking_service
from app.services import bot_settings as bot_settings_service
from app.services import business_images as images_storage
from app.services import conversation_state as cs
from app.services import file_storage
from app.services import leads as leads_service

BID = "fab99cce-f844-4fd4-8f95-c5ef2f6eda10"

# Every conversation id this script mints starts with this, so `cache_chat_ref`
# carries a marker narrower than the tenant itself (see the cleanup note above).
MARKER = "ck-demo-"

# Where the pre-sliced artwork sits (mounted into the container by the runner).
# Overridable so the script can run inside the backend container, which runs as
# a non-root user and cannot create a directory at the filesystem root.
ART_DIR = Path(os.environ.get("CK_ART_DIR", "/seed-art-tmp"))

SEED = 20260722  # deterministic: a re-run reproduces the same demo, not a new one


# ============================================================================
# 1. the business page
# ============================================================================

PAGE_FIELDS = {
    "tagline": "סדנאות & חוויות שוקולד — לימי הולדת, לחברות ולכל רגע מתוק",
    "about": (
        "chocolate kingdom הוקמה מתוך אהבה אחת פשוטה: הרגע שבו שוקולד חם נשפך "
        "על השיש והידיים מתחילות ליצור. מאז 2014 אנחנו מארחים במרכז המבקרים שלנו "
        "בנתניה משפחות, כיתות וצוותים שלמים — לסדנאות יצירה, לימי הולדת בלתי "
        "נשכחים, ל־Happy Hour שוקולד במשרד ולחדר הבריחה \"צ׳רלי בממלכת השוקולד\". "
        "כל מה שיוצא מהמטבח שלנו נעשה בעבודת יד, מחומרי גלם בלגיים, ובלי תמציות "
        "או חומרים משמרים. אנחנו מאמינים שסדנה טובה היא לא רק מה שאוכלים בסוף — "
        "אלא מה שזוכרים ממנה שנה אחר כך."
    ),
    "address": "רחוב הרצל 42, אזור התעשייה פולג, נתניה",
    "phone": "09-8654321",
    "whatsapp": "0525557890",
    "instagram_url": "https://www.instagram.com/chocolate.kingdom.il",
    "waze_url": "https://waze.com/ul?q=%D7%94%D7%A8%D7%A6%D7%9C%2042%20%D7%A0%D7%AA%D7%A0%D7%99%D7%94",
}

PAGE_THEME = {
    "primary": "#5B3A22",
    "accent": "#C9A227",
    "background": "#FBF6EF",
    "text": "#2E1B0F",
}

WELCOME_MESSAGE = (
    "ברוכים הבאים לממלכת השוקולד! 🍫 בחרו את החוויה שמתאימה לכם, "
    "ואנחנו כבר מכינים את הסינר."
)

# Sun–Thu a full day split around lunch, Fri a short morning. Keys: "0"=Sun.."6"=Sat.
WORKING_HOURS = {
    "0": [{"s": "09:00", "e": "13:00"}, {"s": "14:00", "e": "18:00"}],
    "1": [{"s": "09:00", "e": "13:00"}, {"s": "14:00", "e": "18:00"}],
    "2": [{"s": "09:00", "e": "13:00"}, {"s": "14:00", "e": "18:00"}],
    "3": [{"s": "09:00", "e": "13:00"}, {"s": "14:00", "e": "19:00"}],
    "4": [{"s": "09:00", "e": "13:00"}, {"s": "14:00", "e": "18:00"}],
    "5": [{"s": "09:00", "e": "13:00"}],
}


# ============================================================================
# 2. the gallery — captions written after LOOKING at each tile
# ============================================================================

GALLERY = [
    ("tile_0.jpg", "הלוגו שלנו על עוגת שוקולד לבן ופנינים"),
    ("tile_1.jpg", "יום הולדת בממלכת השוקולד — סדנת ילדים עם קערות תוספות"),
    ("tile_2.jpg", "Happy Hour לחברות — מזרקת שוקולד ומגדלי פרלינים במשרד"),
    ("tile_3.jpg", "מארזי מתנה ממותגים עם טראפלס ופתק ברכה אישי"),
    ("tile_4.jpg", "צ׳רלי בממלכת השוקולד — חדר בריחה משפחתי"),
    ("tile_5.jpg", "מרכז המבקרים — סיור, הסבר וטעימות"),
    ("tile_6.jpg", "סדנת יצירה ולימוד — זילוף פרלינים בעבודת יד"),
    ("tile_7.jpg", "החנות שלנו — הכניסה לממלכת השוקולד"),
]


# ============================================================================
# 3. services
# ============================================================================

SERVICES = [
    ("סדנת שוקולד ליום הולדת", 90, 1450,
     "עד 20 ילדים · סינר ממותג לכל חוגג · יצירת פרלינים ושוקולד אישי לקחת הביתה."),
    ("Happy Hour שוקולד לחברות", 120, 3200,
     "מזרקת שוקולד, מגדלי פרלינים ופירות, ותחנת יצירה — אצלנו או אצלכם במשרד."),
    ("חדר בריחה: צ׳רלי בממלכת השוקולד", 75, 480,
     "עד 6 משתתפים · חידות בתוך מפעל שוקולד · מתאים מגיל 8 ומעלה."),
    ("סיור וטעימות במרכז המבקרים", 60, 45,
     "סיור מודרך בין שלבי ייצור השוקולד, עם טעימות בכל תחנה."),
    ("סדנת יצירה ולימוד למבוגרים", 150, 280,
     "טמפרטורה, טמפרינג ומילויים — סדנה עמוקה למי שרוצה באמת להבין שוקולד."),
    ("מארז מתנה ממותג — הרכבה אישית", 30, 120,
     "בוחרים פרלינים, בוחרים קופסה, מוסיפים לוגו או ברכה. מוכן ליום העסקים הבא."),
]


# ============================================================================
# 4. the bot — all three flow_types, varied step types, one file step each
# ============================================================================

BOT_PROFILE = {
    "name": "מתוקי — העוזר של ממלכת השוקולד",
    "system_prompt": (
        "אתה מתוקי, העוזר הדיגיטלי של chocolate kingdom — עסק לסדנאות וחוויות "
        "שוקולד בנתניה. אתה חם, סבלני ומחייך, מדבר עברית פשוטה ומזמינה, ומשתמש "
        "באימוג'ים במידה. תפקידך לעזור ללקוחות לבחור בין סדנת יום הולדת, "
        "Happy Hour לחברות, מארזי מתנה ממותגים, חדר הבריחה וסיור במרכז המבקרים, "
        "ולאסוף את הפרטים הדרושים כדי שנחזור אליהם. אל תמציא מחירים, תאריכים או "
        "זמינות שלא נמסרו לך — אם אינך יודע, אמור שנציג יבדוק ויחזור. אם הלקוח "
        "מבקש אדם, או נשמע מוטרד, העבר מיד לנציג אנושי."
    ),
    "tone": "חם, מתוק וסבלני",
    "language": "he",
    "greeting": (
        "שלום וברוכים הבאים לממלכת השוקולד! 🍫👑\n"
        "אני מתוקי, ואשמח לעזור לכם למצוא את החוויה המתוקה שמתאימה בדיוק לכם.\n"
        "מה מעניין אתכם היום?"
    ),
    "escalation_message": (
        "בשמחה! מעביר אתכם לאחד מאיתנו 🙏 מישהו מהצוות יחזור אליכם בהקדם — "
        "בינתיים אפשר להשאיר כאן כל פרט נוסף."
    ),
    "auto_close_minutes": 120,
    "menu_keywords": ["תפריט", "menu", "0", "חזרה", "התחלה"],
}

LEAD_STEPS = {
    "birthday_workshop": {
        "label": "סדנת יום הולדת לילדים",
        "flow_type": "lead",
        "steps": [
            {"key": "שם_מלא", "question": "נעים מאוד! מה השם המלא שלך?",
             "type": "text", "required": True},
            {"key": "טלפון", "question": "מה מספר הטלפון שנחזור אליו?",
             "type": "phone", "required": True,
             "error_message": "לא הצלחתי לזהות מספר טלפון, אפשר לנסות שוב?"},
            {"key": "גיל_החוגג", "question": "בן/בת כמה החוגג/ת?",
             "type": "choice", "required": True,
             "options": ["4-6", "7-9", "10-12", "13+"]},
            {"key": "מספר_ילדים", "question": "כמה ילדים בערך יגיעו?",
             "type": "text", "required": True},
            {"key": "תאריך_מבוקש", "question": "לאיזה תאריך אתם מכוונים?",
             "type": "text", "required": True},
            {"key": "הזמנה_מעוצבת", "question": "יש לכם הזמנה מעוצבת? אפשר לצרף ונתאים את הסינרים 🎨",
             "type": "file", "required": False, "accept": ["image", "pdf"]},
        ],
    },
    "company_event": {
        "label": "Happy Hour ואירועי חברות",
        "flow_type": "lead",
        "steps": [
            {"key": "שם_מלא", "question": "מה השם שלך?", "type": "text", "required": True},
            {"key": "חברה", "question": "מאיזו חברה אתם?", "type": "text", "required": True},
            {"key": "טלפון", "question": "מה הטלפון ליצירת קשר?",
             "type": "phone", "required": True},
            {"key": "אימייל", "question": "לאן לשלוח את הצעת המחיר?",
             "type": "email", "required": True,
             "error_message": "נראה שהכתובת לא תקינה, אפשר שוב?"},
            {"key": "סוג_אירוע", "question": "איזה סוג אירוע אתם מתכננים?",
             "type": "choice", "required": True,
             "options": ["Happy Hour במשרד", "יום גיבוש אצלנו", "סדנה לצוות", "מתנות לחג"]},
            {"key": "מספר_משתתפים", "question": "כמה משתתפים בערך?",
             "type": "text", "required": True},
        ],
    },
    "gift_boxes": {
        "label": "מארזי מתנה ממותגים",
        "flow_type": "lead",
        "steps": [
            {"key": "שם_מלא", "question": "מה השם שלך?", "type": "text", "required": True},
            {"key": "טלפון", "question": "מה הטלפון שלך?", "type": "phone", "required": True},
            {"key": "כמות_מארזים", "question": "כמה מארזים אתם צריכים?",
             "type": "choice", "required": True,
             "options": ["עד 20", "20-50", "50-150", "150+"]},
            {"key": "קובץ_לוגו", "question": "אפשר לצרף את הלוגו למיתוג הקופסאות? 📎",
             "type": "file", "required": False, "accept": ["image", "pdf"]},
            {"key": "הערות", "question": "משהו נוסף שכדאי שנדע?",
             "type": "text", "required": False},
        ],
    },
    "talk_to_human": {
        "label": "דברו עם נציג",
        "flow_type": "human_handoff",
        "steps": [],
    },
    "book_visit": {
        "label": "הזמנת סיור במרכז המבקרים",
        "flow_type": "booking",
        "service_name": "סיור וטעימות במרכז המבקרים",
        "steps": [
            {"key": "שם_מלא", "question": "מה השם המלא שלך?", "type": "text", "required": True},
            {"key": "טלפון", "question": "מה מספר הטלפון?", "type": "phone", "required": True},
            {"key": "מספר_מבקרים", "question": "כמה אנשים יגיעו לסיור?",
             "type": "text", "required": True},
        ],
    },
}

HANDOFF_KEYWORDS = ["נציג", "אדם", "בן אדם", "human", "agent", "לדבר עם מישהו", "תלונה"]


# ============================================================================
# 5. answer vocabulary for the 500 leads
# ============================================================================

FIRST_NAMES = [
    "נועה", "יעל", "שירה", "תמר", "מיכל", "רונית", "אורלי", "הילה", "דנה", "ליאת",
    "מאיה", "אפרת", "סיגל", "ענבל", "קרן", "שני", "אביגיל", "רותם", "גל", "טל",
    "יוסי", "אבי", "רן", "עומר", "איתי", "ניר", "דור", "אלון", "גיא", "עידו",
    "אורי", "יונתן", "אסף", "רועי", "עמית", "שחר", "ליאור", "בר", "נדב", "תומר",
]
LAST_NAMES = [
    "כהן", "לוי", "מזרחי", "פרץ", "ביטון", "דהן", "אברהם", "פרידמן", "שפירא", "אזולאי",
    "גבאי", "אוחיון", "מלכה", "בן דוד", "חדד", "אמסלם", "טל", "שרון", "ברקוביץ", "נחום",
    "רוזנברג", "קפלן", "אדרי", "סבן", "יעקובי", "הראל", "זהבי", "בן שימול", "עמר", "נגר",
]
COMPANIES = [
    "אלביט מערכות", "צ׳ק פוינט", "מובילאיי", "פייבר", "וויקס", "מונדיי", "ריקו ישראל",
    "בנק הפועלים", "שטראוס", "תנובה", "סלקום", "פרטנר", "אמדוקס", "נייס", "פלייטיקה",
    "קבוצת עזריאלי", "מכבי שירותי בריאות", "אל על", "טבע", "רפאל",
]
EMAIL_HOSTS = ["gmail.com", "walla.co.il", "outlook.com", "hotmail.com"]

BIRTHDAY_NOTES = [
    "רוצים משהו בנושא יוניקורן", "החוגגת אלרגית לאגוזים — חשוב מאוד",
    "יש 3 ילדים צמחוניים בקבוצה", "מעדיפים שעות אחר הצהריים",
    "אולי נוסיף גם את חדר הבריחה אחרי", "צריכים חניה לאוטובוס קטן",
]
COMPANY_NOTES = [
    "התקציב הוא עד 250 ש\"ח למשתתף", "האירוע בסוף הרבעון",
    "צריך חשבונית מס עם מספר הזמנה", "חלק מהצוות כשר למהדרין",
    "מחפשים משהו לחנוכה", "רוצים שהאירוע יהיה אצלנו במשרד בת\"א",
]
GIFT_NOTES = [
    "המיתוג צריך להיות בזהב", "צריך את זה עד ה־15 לחודש",
    "רוצים גם פתק ברכה מודפס", "חלק מהנמענים בחו\"ל",
    "מעדיפים מארז בלי אלכוהול", "רוצים לראות דוגמה לפני הזמנה גדולה",
]

DEAL_NOTES = [
    "סגרנו סדנה מלאה — שולם מקדמה 30%.",
    "הזמינו Happy Hour ל־45 איש, חשבונית נשלחה.",
    "לקוח חוזר, סגר שני מועדים ברצף.",
    "סגרו 80 מארזים ממותגים לחג.",
    "שילמו במלואו בטלפון, נשלח אישור ליומן.",
    "סגרו חדר בריחה + סיור כחבילה.",
]
CLOSED_NOTES = [
    "התקציב שלהם היה נמוך מהמינימום שלנו.",
    "בחרו בספק אחר שקרוב יותר אליהם.",
    "התאריך שביקשו היה תפוס ולא היה מועד חלופי.",
    "דחו את האירוע לשנה הבאה, לחזור ברבעון הבא.",
    "לא ענו אחרי שלוש פניות.",
    "התברר שהם מחפשים קייטרינג מלא, לא סדנה.",
]

FLOW_KEYS = ["birthday_workshop", "company_event", "gift_boxes", "book_visit", "talk_to_human"]


def _phone(rng: random.Random) -> str:
    return f"05{rng.choice('02345689')}{rng.randint(1000000, 9999999)}"


def _answers_for(rng: random.Random, flow: str, name: str) -> dict:
    """Realistic Hebrew answers whose KEYS match that flow's own step keys."""
    phone = _phone(rng)
    if flow == "birthday_workshop":
        a = {
            "שם_מלא": name,
            "טלפון": phone,
            "גיל_החוגג": rng.choice(["4-6", "7-9", "10-12", "13+"]),
            "מספר_ילדים": str(rng.randint(8, 25)),
            "תאריך_מבוקש": (
                datetime.now() + timedelta(days=rng.randint(5, 70))
            ).strftime("%d/%m/%Y"),
        }
        if rng.random() < 0.35:
            a["הערות"] = rng.choice(BIRTHDAY_NOTES)
        return a
    if flow == "company_event":
        first = name.split()[0]
        return {
            "שם_מלא": name,
            "חברה": rng.choice(COMPANIES),
            "טלפון": phone,
            "אימייל": f"{_translit(first)}{rng.randint(1, 99)}@{rng.choice(EMAIL_HOSTS)}",
            "סוג_אירוע": rng.choice(
                ["Happy Hour במשרד", "יום גיבוש אצלנו", "סדנה לצוות", "מתנות לחג"]
            ),
            "מספר_משתתפים": str(rng.choice([12, 18, 25, 30, 45, 60, 80, 120])),
            **({"הערות": rng.choice(COMPANY_NOTES)} if rng.random() < 0.4 else {}),
        }
    if flow == "gift_boxes":
        return {
            "שם_מלא": name,
            "טלפון": phone,
            "כמות_מארזים": rng.choice(["עד 20", "20-50", "50-150", "150+"]),
            **({"הערות": rng.choice(GIFT_NOTES)} if rng.random() < 0.5 else {}),
        }
    if flow == "book_visit":
        return {
            "שם_מלא": name,
            "טלפון": phone,
            "מספר_מבקרים": str(rng.randint(2, 40)),
        }
    # talk_to_human — the handoff flow collects nothing, but the runtime still
    # captures whatever the customer volunteered before asking for a person.
    return {"שם_מלא": name, "טלפון": phone}


_TRANSLIT = {
    "א": "a", "ב": "b", "ג": "g", "ד": "d", "ה": "h", "ו": "v", "ז": "z", "ח": "h",
    "ט": "t", "י": "y", "כ": "k", "ך": "k", "ל": "l", "מ": "m", "ם": "m", "נ": "n",
    "ן": "n", "ס": "s", "ע": "a", "פ": "p", "ף": "f", "צ": "tz", "ץ": "tz", "ק": "k",
    "ר": "r", "ש": "sh", "ת": "t",
}


def _translit(hebrew: str) -> str:
    out = "".join(_TRANSLIT.get(ch, "") for ch in hebrew)
    return out or "user"


# ============================================================================
# 6. the 15 live conversations
# ============================================================================

CONVERSATIONS = [
    # --- bot (5): the engine is still driving ---
    ("bot", "birthday_workshop", "מיכל שפירא", [
        ("customer", "היי, אני מחפשת סדנת שוקולד ליום הולדת 8"),
        ("bot", "שלום וברוכה הבאה לממלכת השוקולד! 🍫 אשמח לעזור. מה השם המלא שלך?"),
        ("customer", "מיכל שפירא"),
        ("bot", "נעים מאוד מיכל! מה מספר הטלפון שנחזור אליו?"),
        ("customer", "0526641123"),
        ("bot", "מעולה. בן/בת כמה החוגג/ת? 4-6 / 7-9 / 10-12 / 13+"),
        ("customer", "7-9"),
        ("bot", "כמה ילדים בערך יגיעו?"),
    ]),
    ("bot", "gift_boxes", "אלון גבאי", [
        ("customer", "שלום, אנחנו רוצים מארזי שוקולד ממותגים לעובדים"),
        ("bot", "איזה כיף! 🎁 מה השם שלך?"),
        ("customer", "אלון גבאי"),
        ("bot", "תודה אלון. מה הטלפון שלך?"),
        ("customer", "0543219876"),
        ("bot", "כמה מארזים אתם צריכים? עד 20 / 20-50 / 50-150 / 150+"),
    ]),
    ("bot", "book_visit", "רותם הראל", [
        ("customer", "אפשר להגיע לסיור במרכז המבקרים בשבת?"),
        ("bot", "שלום! 😊 אנחנו פתוחים ראשון עד חמישי, ובשישי עד 13:00. "
                "אשמח לקבוע לכם מועד — מה השם המלא שלך?"),
        ("customer", "רותם הראל"),
        ("bot", "מה מספר הטלפון?"),
        ("customer", "0509988771"),
        ("bot", "כמה אנשים יגיעו לסיור?"),
        ("customer", "אנחנו 12, כיתה ד' של הבת שלי"),
        ("bot", "מקסים! 12 מבקרים. אני שולח לך את המועדים הפנויים 📅"),
    ]),
    ("bot", "company_event", "ענבל נחום", [
        ("customer", "היי, מחפשים משהו מתוק לערב גיבוש של הצוות"),
        ("bot", "יש לנו בדיוק את זה 🍫 מה השם שלך?"),
        ("customer", "ענבל נחום"),
        ("bot", "מאיזו חברה אתם?"),
        ("customer", "מונדיי"),
        ("bot", "מה הטלפון ליצירת קשר?"),
    ]),
    ("bot", "birthday_workshop", "תומר אדרי", [
        ("customer", "כמה עולה סדנה ל-15 ילדים?"),
        ("bot", "סדנת יום הולדת מתחילה ב־1,450 ₪ לעד 20 ילדים, וכוללת סינר "
                "ממותג לכל חוגג 🎉 רוצה שנתפוס לכם תאריך? מה השם המלא שלך?"),
        ("customer", "תומר אדרי"),
        ("bot", "מה מספר הטלפון שנחזור אליו?"),
    ]),

    # --- waiting (5): asked for a person, nobody picked up yet ---
    ("waiting", "talk_to_human", "יעל אזולאי", [
        ("customer", "שלום, אפשר לדבר עם נציג בבקשה?"),
        ("bot", "בשמחה! מעביר אתכם לאחד מאיתנו 🙏 מישהו מהצוות יחזור אליכם בהקדם."),
        ("customer", "יעל אזולאי, 0527334455"),
        ("customer", "זה דחוף, האירוע ביום חמישי"),
    ]),
    ("waiting", "company_event", "ניר קפלן", [
        ("customer", "היי, צריך הצעת מחיר ל-80 עובדים"),
        ("bot", "אשמח לעזור! מה השם שלך?"),
        ("customer", "ניר קפלן"),
        ("bot", "מאיזו חברה אתם?"),
        ("customer", "אמדוקס"),
        ("customer", "בעצם עדיף שאדבר עם נציג, יש לי כמה דרישות מיוחדות"),
        ("bot", "בהחלט, מעביר אתכם לנציג 🙏"),
    ]),
    ("waiting", "birthday_workshop", "שירה בן דוד", [
        ("customer", "הבן שלי אלרגי לאגוזים, אפשר סדנה בלי?"),
        ("bot", "שאלה חשובה — אני מעביר אתכם לנציג שיוכל לענות בדיוק על זה 🙏"),
        ("customer", "תודה, שירה בן דוד 0546112390"),
    ]),
    ("waiting", "gift_boxes", "עמית זהבי", [
        ("customer", "שלחתי לכם מייל לפני שבוע ולא קיבלתי תשובה"),
        ("bot", "מצטער על זה! מעביר אתכם מיד לנציג אנושי 🙏"),
        ("customer", "עמית זהבי, מ-רפאל. מדובר ב-200 מארזים"),
    ]),
    ("waiting", "talk_to_human", "דור סבן", [
        ("customer", "נציג"),
        ("bot", "בשמחה! מעביר אתכם לאחד מאיתנו 🙏"),
        ("customer", "רציתי לבדוק אם אפשר לשנות תאריך של סדנה שכבר הזמנתי"),
    ]),

    # --- human (5): an owner took over ---
    ("human", "company_event", "אורלי מלכה", [
        ("customer", "היי, מתכננים אירוע חנוכה לחברה"),
        ("bot", "איזה כיף! מה השם שלך?"),
        ("customer", "אורלי מלכה, מצ׳ק פוינט"),
        ("bot", "מעביר אתכם לנציג שיבנה לכם הצעה 🙏"),
        ("owner", "היי אורלי, כאן שני מ־chocolate kingdom 👋 שמחה לעזור! "
                  "כמה משתתפים אתם צופים?"),
        ("customer", "בערך 60, אולי 70"),
        ("owner", "מעולה. ל־70 איש אני ממליצה על מזרקת שוקולד + תחנת יצירה. "
                  "שולחת לך הצעה מסודרת למייל תוך שעה 📄"),
        ("customer", "מושלם, תודה רבה!"),
    ]),
    ("human", "birthday_workshop", "הילה אוחיון", [
        ("customer", "רוצה לקבוע יום הולדת ל-12 ילדים"),
        ("bot", "מעולה! מעביר אתכם לנציג 🙏"),
        ("owner", "היי הילה! 😊 יש לנו מקום ביום שישי ה־8 ב־10:00, מתאים?"),
        ("customer", "כן! אפשר גם צילום?"),
        ("owner", "בטח, אנחנו מצלמים את כל הסדנה ושולחים אלבום אחרי 📸"),
    ]),
    ("human", "gift_boxes", "רועי ברקוביץ", [
        ("customer", "צריך 150 מארזים עם לוגו של החברה"),
        ("bot", "מעביר אתכם לנציג שיטפל בזה 🙏"),
        ("owner", "היי רועי, כאן דניאל 👋 שלחת לנו את קובץ הלוגו?"),
        ("customer", "כן, שלחתי עכשיו"),
        ("owner", "קיבלתי, נראה מצוין. מכין הדמיה ושולח היום 🎁"),
    ]),
    ("human", "book_visit", "טל יעקובי", [
        ("customer", "אנחנו גן ילדים, אפשר סיור מותאם לגיל 5?"),
        ("bot", "מעביר אתכם לנציג 🙏"),
        ("owner", "היי טל! בהחלט — יש לנו מסלול מקוצר של 40 דקות לגיל הרך. "
                  "כמה ילדים בגן?"),
        ("customer", "28 ילדים ו-3 גננות"),
        ("owner", "מצוין, נחלק לשתי קבוצות. איזה יום נוח לכם?"),
    ]),
    ("human", "talk_to_human", "אפרת חדד", [
        ("customer", "היי, הייתי אצלכם אתמול והשוקולד היה מדהים 🤩"),
        ("bot", "תודה רבה! מעביר אתכם לנציג 🙏"),
        ("owner", "וואו אפרת, תודה שכתבת! 🥰 נשמח אם תשתפי אצלנו באינסטגרם"),
        ("customer", "בכיף! וגם רציתי לשאול על הסדנה למבוגרים"),
        ("owner", "היא רצה כל יום רביעי ב־19:00, 150 דקות של שוקולד אמיתי 🍫"),
    ]),
]

# A few conversations carry an unread badge (how many the owner hasn't opened).
UNREAD = {0: 2, 5: 4, 7: 1, 8: 3, 9: 2, 12: 1}


# ============================================================================
# the seed
# ============================================================================

async def _wipe(pool, redis) -> None:
    """Remove everything a previous run of THIS script wrote (marked rows only)."""
    async with tenant_connection(pool, BID) as conn:
        await conn.execute(
            "DELETE FROM flow_events WHERE business_id = $1 AND lead_id IN "
            "(SELECT id FROM leads WHERE business_id = $1 AND cache_chat_ref LIKE $2)",
            BID, f"conv:{BID}:{MARKER}%",
        )
        await conn.execute(
            "DELETE FROM leads WHERE business_id = $1 AND cache_chat_ref LIKE $2",
            BID, f"conv:{BID}:{MARKER}%",
        )
        await conn.execute("DELETE FROM lead_files WHERE business_id = $1", BID)
        # Gallery: drop the files from disk too, then the rows.
        rows = await conn.fetch(
            "SELECT storage_path FROM business_images WHERE business_id = $1", BID
        )
        for r in rows:
            try:
                images_storage.delete_image(r["storage_path"])
            except Exception:  # noqa: BLE001 — a missing file is fine
                pass
        await conn.execute("DELETE FROM business_images WHERE business_id = $1", BID)

        # The LOGO has no business_images row (it is just booking_settings.
        # logo_url), so the loop above never sees it — without this, every re-run
        # left the previous logo orphaned on disk.
        old_logo = await conn.fetchval(
            "SELECT logo_url FROM booking_settings WHERE business_id = $1", BID
        )
        if old_logo and old_logo.startswith("/media/"):
            try:
                images_storage.delete_image(old_logo[len("/media/"):])
            except Exception:  # noqa: BLE001 — a missing file is fine
                pass

        await conn.execute("DELETE FROM services WHERE business_id = $1", BID)

    # Live conversations from a previous run.
    for conv_id in await redis.smembers(f"convindex:{BID}"):
        if conv_id.startswith(MARKER):
            await cs.reset_conversation(redis, BID, conv_id)


async def _seed_page_and_images(pool) -> dict:
    """Page fields + working hours + services + the logo and the 8 gallery tiles."""
    out = {}

    # --- the gallery bytes go through the REAL upload service ---
    logo_bytes = (ART_DIR / "logo.png").read_bytes()
    logo_path, logo_mime, logo_size = images_storage.save_image(
        BID, logo_bytes, "image/png"
    )
    out["logo_url"] = f"/media/{logo_path}"

    async with tenant_connection(pool, BID) as conn:
        # Page fields (+ the logo url the service just produced).
        page = await booking_service.update_page(
            conn, BID,
            fields={**PAGE_FIELDS, "logo_url": out["logo_url"]},
            page_theme=PAGE_THEME,
            set_page_theme=True,
        )
        out["slug"] = page["slug"]

        # Working hours + the booking window.
        await booking_service.update_settings(
            conn, BID,
            working_hours=WORKING_HOURS,
            min_notice_minutes=120,
            buffer_minutes=15,
            max_days_ahead=45,
            meet_enabled=False,
            welcome_message=WELCOME_MESSAGE,
        )

        # Services.
        out["services"] = []
        for name, minutes, price, desc in SERVICES:
            svc = await booking_service.create_service(
                conn, BID, name=name, duration_minutes=minutes,
                active=True, description=desc, price=price,
            )
            out["services"].append(svc)

        # Gallery rows for the tiles.
        out["images"] = []
        for order, (fname, caption) in enumerate(GALLERY):
            raw = (ART_DIR / fname).read_bytes()
            path, mime, size = images_storage.save_image(BID, raw, "image/jpeg")
            row = await booking_service.create_image(
                conn, BID, storage_path=path, mime_type=mime,
                size_bytes=size, caption=caption, sort_order=order,
            )
            out["images"].append(row)

    return out


async def _seed_bot(pool) -> dict:
    """Validate the config through the real BotSettings model, then save it."""
    settings = BotSettings(
        lead_steps=LEAD_STEPS,
        bot_profile=BOT_PROFILE,
        handoff_keywords=HANDOFF_KEYWORDS,
        is_published=True,
    )
    return await bot_settings_service.save_settings(pool, BID, settings)


def _upload_lead_file(name: str, raw: bytes, mime: str) -> dict | None:
    """Encrypt + store one customer attachment; return the answer object.

    Returns exactly the shape the bot engine writes into `answers` for a `file`
    step: {"file_id", "mime_type", "name"} (bot-config-contract §2.1).
    """
    file_id = str(uuid.uuid4())
    try:
        storage_key, wrapped_dek, key_version, sha = file_storage.put_encrypted(
            BID, file_id, raw
        )
    except Exception as exc:  # noqa: BLE001 — surfaced by the caller, not swallowed
        print(f"  ! file upload failed ({type(exc).__name__}) — skipping file answers")
        return None
    return {
        "file_id": file_id,
        "mime_type": mime,
        "name": name,
        "_row": (storage_key, wrapped_dek, key_version, sha, mime, len(raw)),
    }


async def _seed_leads(pool, rng: random.Random) -> dict:
    """500 leads across the flows, with a realistic status mix and 90-day spread."""
    # The intended status mix. 485 here + the 15 live-conversation leads seeded
    # afterwards (all of them still 'in_progress') = 500 leads for the tenant.
    plan: list[str] = (
        ["deal"] * 90 + ["closed"] * 70 + ["abandoned"] * 95
        + ["new"] * 145 + ["in_progress"] * 85
    )
    rng.shuffle(plan)

    # Real encrypted attachments a handful of leads will point at. We upload a
    # small pool and hand them out, so the demo has genuine decryptable files
    # without 40 round-trips to the bucket.
    file_pool: list[dict] = []
    for i, (fname, label) in enumerate(
        [("tile_1.jpg", "הזמנה-ליום-הולדת.jpg"), ("tile_3.jpg", "לוגו-החברה.jpg"),
         ("tile_6.jpg", "רעיון-לעיצוב.jpg"), ("tile_4.jpg", "הזמנה-מעוצבת.jpg"),
         ("tile_7.jpg", "מיתוג-קופסאות.jpg"), ("tile_2.jpg", "תמונת-השראה.jpg")]
    ):
        got = _upload_lead_file(label, (ART_DIR / fname).read_bytes(), "image/jpeg")
        if got:
            file_pool.append(got)

    # Write the lead_files rows for the pool (RLS-scoped, exactly like the
    # gateway's upload endpoint does).
    async with tenant_connection(pool, BID) as conn:
        for f in file_pool:
            storage_key, wrapped_dek, key_version, sha, mime, size = f["_row"]
            await conn.execute(
                """
                INSERT INTO lead_files (
                    id, business_id, storage_key, wrapped_dek, key_version,
                    mime_type, file_name, size_bytes, sha256
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                f["file_id"], BID, storage_key, wrapped_dek, key_version,
                mime, crypto.encrypt_pii(f["name"]), size, sha,
            )
    for f in file_pool:
        f.pop("_row", None)

    now = datetime.now(timezone.utc)
    counts: dict[str, int] = {}
    flow_counts: dict[str, int] = {}
    files_attached = 0

    CHUNK = 50
    for chunk_start in range(0, len(plan), CHUNK):
        chunk = plan[chunk_start:chunk_start + CHUNK]
        async with tenant_connection(pool, BID) as conn:
            for offset, status in enumerate(chunk):
                idx = chunk_start + offset
                flow = rng.choices(
                    FLOW_KEYS, weights=[34, 26, 18, 14, 8], k=1
                )[0]
                name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
                answers = _answers_for(rng, flow, name)

                # A file answer on the flows that actually HAVE a file step.
                if file_pool and rng.random() < 0.06:
                    if flow == "birthday_workshop":
                        answers["הזמנה_מעוצבת"] = dict(rng.choice(file_pool))
                        files_attached += 1
                    elif flow == "gift_boxes":
                        answers["קובץ_לוגו"] = dict(rng.choice(file_pool))
                        files_attached += 1

                conv_id = f"{MARKER}lead-{idx:04d}"
                lead_id = await leads_service.create_lead(
                    conn, BID, lead_name=flow, conversation_id=conv_id, is_test=False
                )
                await leads_service.log_event(
                    conn, BID, lead_id, flow, leads_service.EVENT_STARTED,
                    step_index=None, is_test=False,
                )

                if status in ("new", "deal", "closed"):
                    # These all reached the end of the questionnaire.
                    await leads_service.complete_lead(conn, BID, lead_id, answers)
                    await leads_service.log_event(
                        conn, BID, lead_id, flow, leads_service.EVENT_COMPLETED,
                        step_index=len(answers), is_test=False,
                    )
                    if status == "deal":
                        await leads_service.set_lead_status(
                            conn, BID, lead_id, "deal",
                            note=rng.choice(DEAL_NOTES),
                            close_reason=leads_service.CLOSE_REASON_COMPLETED,
                        )
                    elif status == "closed":
                        await leads_service.set_lead_status(
                            conn, BID, lead_id, "closed",
                            note=rng.choice(CLOSED_NOTES),
                            close_reason=leads_service.CLOSE_REASON_ANSWERED,
                        )
                else:
                    # in_progress / abandoned stopped part-way, so only the
                    # answers they got to are stored.
                    keys = list(answers)
                    kept = keys[: max(1, rng.randint(1, len(keys)))]
                    partial = {k: answers[k] for k in kept}
                    await leads_service.update_lead(
                        conn, BID, lead_id, collected=partial,
                        last_step_index=len(partial),
                    )
                    if status == "abandoned":
                        await leads_service.set_lead_status(
                            conn, BID, lead_id, "abandoned",
                            close_reason=leads_service.CLOSE_REASON_ABANDONED,
                        )
                        await leads_service.log_event(
                            conn, BID, lead_id, flow, leads_service.EVENT_ABANDONED,
                            step_index=len(partial), is_test=False,
                        )
                    answers = partial

                if flow == "talk_to_human":
                    await leads_service.log_event(
                        conn, BID, lead_id, flow, leads_service.EVENT_HANDOFF,
                        step_index=None, is_test=False,
                    )

                # --- backdate (see the module docstring for why this is raw) ---
                started = now - timedelta(
                    days=rng.uniform(0, 90), hours=rng.uniform(0, 24)
                )
                if status == "in_progress":
                    # An 'in_progress' lead that has been idle for more than
                    # ABANDONED_AFTER_MINUTES (60) is not in progress — the real
                    # abandoned-sweep flips it to 'abandoned' within the minute,
                    # and closes its Redis conversation. (It did exactly that on
                    # the first seeding run.) So these keep a RECENT last touch,
                    # which is also what "still in progress" honestly means here.
                    last_act = now - timedelta(minutes=rng.randint(2, 50))
                else:
                    last_act = started + timedelta(minutes=rng.randint(4, 60 * 36))
                    if last_act > now:
                        last_act = now - timedelta(minutes=rng.randint(1, 120))
                await conn.execute(
                    """
                    UPDATE leads
                    SET started_at = $3::timestamptz,
                        last_activity_at = $4::timestamptz,
                        submitted_at = CASE
                            WHEN submitted_at IS NULL THEN NULL::timestamptz
                            ELSE $4::timestamptz END
                    WHERE id = $1 AND business_id = $2
                    """,
                    lead_id, BID, started, last_act,
                )
                await conn.execute(
                    "UPDATE flow_events SET created_at = $3 "
                    "WHERE business_id = $2 AND lead_id = $1",
                    lead_id, BID, started,
                )

                counts[status] = counts.get(status, 0) + 1
                flow_counts[flow] = flow_counts.get(flow, 0) + 1

        print(f"  ... {chunk_start + len(chunk)}/{len(plan)} leads")

    return {"counts": counts, "flows": flow_counts, "files": files_attached}


async def _seed_conversations(pool, redis, rng: random.Random) -> list:
    """15 live conversations in Redis, each linked to a lead so the inbox has names."""
    made = []
    for i, (status, flow, name, messages) in enumerate(CONVERSATIONS):
        conv_id = f"{MARKER}wa-{i:02d}"
        await cs.reset_conversation(redis, BID, conv_id)

        answers = _answers_for(rng, flow, name)
        # Keep the name the transcript actually uses.
        answers["שם_מלא"] = name

        async with tenant_connection(pool, BID) as conn:
            lead_id = await leads_service.create_lead(
                conn, BID, lead_name=flow, conversation_id=conv_id, is_test=False
            )
            await leads_service.update_lead(
                conn, BID, lead_id, collected=answers, last_step_index=len(answers)
            )
            await leads_service.log_event(
                conn, BID, lead_id, flow, leads_service.EVENT_STARTED,
                step_index=None, is_test=False,
            )
            if status in ("waiting", "human"):
                await leads_service.log_event(
                    conn, BID, lead_id, flow, leads_service.EVENT_HANDOFF,
                    step_index=None, is_test=False,
                )
            # These are LIVE chats. The lead stays 'in_progress', so its last
            # touch MUST be inside the abandoned-sweep window (60 min) or the
            # sweep abandons it and closes the conversation out from under us —
            # which is precisely what happened on the first seeding run.
            now_ = datetime.now(timezone.utc)
            await conn.execute(
                "UPDATE leads SET started_at = $3::timestamptz, "
                "last_activity_at = $4::timestamptz "
                "WHERE id = $1 AND business_id = $2",
                lead_id, BID,
                now_ - timedelta(hours=rng.uniform(1, 60)),
                now_ - timedelta(minutes=rng.randint(1, 40)),
            )

        # The transcript — ENCRYPTED by conversation_state, never written raw.
        for role, body in messages:
            await cs.append_message(redis, BID, conv_id, role, body)

        await cs.set_status(redis, BID, conv_id, status)

        for _ in range(UNREAD.get(i, 0)):
            await cs.incr_unread(redis, BID, conv_id)

        made.append((conv_id, status, name, len(messages), UNREAD.get(i, 0)))
    return made


async def main() -> None:
    rng = random.Random(SEED)
    s = get_settings()
    pool = await create_pg_pool(s)
    redis = create_redis(s)
    try:
        print("== wiping any previous run of this seed ==")
        await _wipe(pool, redis)

        print("== page, hours, services, gallery ==")
        page = await _seed_page_and_images(pool)
        print(f"  slug     = {page['slug']}")
        print(f"  logo     = {page['logo_url']}")
        print(f"  services = {len(page['services'])}")
        print(f"  images   = {len(page['images'])}")

        print("== bot config ==")
        bot = await _seed_bot(pool)
        print(f"  flows        = {list(bot['lead_steps'])}")
        print(f"  flow_types   = "
              f"{sorted({f['flow_type'] for f in bot['lead_steps'].values()})}")
        print(f"  is_published = {bot['is_published']}")

        print("== 500 leads ==")
        lead_info = await _seed_leads(pool, rng)
        print(f"  statuses = {lead_info['counts']}")
        print(f"  flows    = {lead_info['flows']}")
        print(f"  leads carrying a real file answer = {lead_info['files']}")

        print("== live conversations ==")
        convs = await _seed_conversations(pool, redis, rng)
        for conv_id, status, name, n, unread in convs:
            print(f"  {conv_id:18s} {status:8s} msgs={n:2d} unread={unread} {name}")

        print("\nDone.")
    finally:
        await pool.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
