"""M13 narrated story — seeding helpers + test phases 1–8 (Hebrew narration).

This module is NOT run directly. The thin runner m13_full_test.py opens the
pools + the app lifespan/client, then calls run_phases(...) here (phases 1–8) and
run_phases_b(...) in _m13_story_b.py (phases 9–16). Splitting the phases out of
the runner keeps each file under 500 lines WITHOUT changing a single byte of
printed output (the narration goes through the shared Story from _story.py,
configured with M13's exact Hebrew wording).

Privileged seeding/verification of the zero-grant control-room tables uses the
superuser pool (su) — the app role only ever reaches them through the SD funcs.
Everything is wiped between phases. Nothing prints a secret or end-customer PII.
"""

from __future__ import annotations

import json
import os
from datetime import date

import asyncpg
import secrets

from app.db.session import tenant_connection
from app.services import usage as usage_service
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX
import time

# שני העסקים המדומים (מזהים קבועים מ‑supabase/seed.sql).
BIZ_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # Avi Insurance (PUBLISHED)
BIZ_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"  # Bella Barber  (DRAFT)
UNKNOWN_BIZ = "cccccccc-cccc-cccc-cccc-cccccccccccc"  # עסק שלא קיים

# בעל הקניון (admin). ADMIN_EMAILS ב‑infra/.env.local כולל את האימייל הזה.
ADMIN_EMAIL = "oyc3333@gmail.com"
ADMIN_USER_ID_FALLBACK = "google-sub-m13-admin"
# בעל עסק רגיל — לא ברשימת ה‑admin.
AVI_USER = "google-sub-avi"
NONADMIN_EMAIL = "avi@example.com"

PRICE_PRO = 149.0  # מחיר תוכנית "pro" (migration 0015)


# --- עזרי סשן + זריעה ---------------------------------------------------------

async def _login(redis, http, user_id: str, email: str, business_id: str) -> str:
    sid = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id, "email": email, "name": user_id, "picture": "",
        "business_id": business_id, "business_name": "x",
        "created_at": int(time.time()),
    }
    await redis.set(f"{_SESSION_KEY_PREFIX}{sid}", json.dumps(payload), ex=3600)
    http.cookies.set(SESSION_COOKIE_NAME, sid)
    return sid


async def _logout(redis, http, sid: str) -> None:
    await redis.delete(f"{_SESSION_KEY_PREFIX}{sid}")
    http.cookies.clear()


def _superuser_dsn() -> str:
    """בונה DSN של superuser מ‑POSTGRES_* (קיים בקונטיינר ה‑backend). משמש רק
    כדי לזרוע/לאפס/להציץ בטבלאות חדר‑הבקרה שה‑app role לא יכול לקרוא."""
    return (f"postgresql://{os.environ['POSTGRES_USER']}:"
            f"{os.environ['POSTGRES_PASSWORD']}@postgres:5432/"
            f"{os.environ['POSTGRES_DB']}")


async def _wipe(su) -> None:
    """מנקה את כל מה שזרענו ל‑M13 בשני העסקים — slate נקי לכל בדיקה."""
    async with su.acquire() as conn:
        ids = [BIZ_A, BIZ_B]
        await conn.execute("DELETE FROM crm_notes WHERE business_id = ANY($1::uuid[])", ids)
        await conn.execute("DELETE FROM business_crm WHERE business_id = ANY($1::uuid[])", ids)
        await conn.execute(
            "DELETE FROM admin_audit WHERE target_business_id = ANY($1::uuid[])", ids)
        await conn.execute("DELETE FROM subscriptions WHERE business_id = ANY($1::uuid[])", ids)
        await conn.execute(
            "DELETE FROM flow_events WHERE business_id = ANY($1::uuid[]) "
            "AND flow_key = 'm13-test'", ids)
        await conn.execute(
            "DELETE FROM bookings WHERE business_id = ANY($1::uuid[]) "
            "AND cancel_token LIKE 'm13-%'", ids)
        await conn.execute(
            "DELETE FROM leads WHERE business_id = ANY($1::uuid[]) "
            "AND lead_name IN ('m13-lead', 'פנייה לנציג')", ids)
        await conn.execute(
            "DELETE FROM usage_daily WHERE business_id = ANY($1::uuid[]) "
            "AND day = current_date "
            "AND metric IN ('msg_in','msg_out','ai_call','lead','booking')", ids)
        await conn.execute(
            "UPDATE businesses SET is_active = true WHERE id = ANY($1::uuid[])", ids)


async def _set_sub(su, business_id: str, plan: str, status_value: str,
                   months_ago: int = 0) -> None:
    is_active = status_value == "active"
    async with su.acquire() as conn:
        await conn.execute(
            "INSERT INTO subscriptions (business_id, plan_code, status, started_at) "
            "VALUES ($1,$2,$3, now() - ($4 || ' months')::interval) "
            "ON CONFLICT ON CONSTRAINT subscriptions_pkey DO UPDATE "
            "SET plan_code=EXCLUDED.plan_code, status=EXCLUDED.status, "
            "started_at=EXCLUDED.started_at",
            business_id, plan, status_value, str(months_ago))
        await conn.execute(
            "UPDATE businesses SET is_active=$2 WHERE id=$1", business_id, is_active)


async def _seed_lead(su, business_id: str, *, handoff: bool) -> None:
    async with su.acquire() as conn:
        lead_id = await conn.fetchval(
            "INSERT INTO leads (business_id, lead_name, status, is_test, started_at) "
            "VALUES ($1,$2,'new',false, now()) RETURNING id",
            business_id, "פנייה לנציג" if handoff else "m13-lead")
        if handoff:
            await conn.execute(
                "INSERT INTO flow_events (business_id, lead_id, flow_key, event, "
                "is_test, created_at) VALUES ($1,$2,'m13-test','handed_off',false, now())",
                business_id, lead_id)


async def _seed_booking(su, business_id: str) -> None:
    async with su.acquire() as conn:
        await conn.execute(
            "INSERT INTO bookings (business_id, scheduled_at, duration_minutes, "
            "status, cancel_token, is_test, created_at) "
            "VALUES ($1, now()+interval '1 day', 30, 'pending', $2, false, now())",
            business_id, f"m13-{secrets.token_hex(6)}")


async def _bump(pool, business_id: str, metric: str, n: int) -> None:
    async with tenant_connection(pool, business_id) as conn:
        await usage_service.bump(conn, business_id, metric, n)


async def resolve_admin_user(su) -> str:
    """פותרים את מזהה ה‑admin האמיתי בשביל ה‑FK של האודיט/פתקים (users.email ייחודי)."""
    async with su.acquire() as conn:
        admin_user = await conn.fetchval(
            "SELECT id FROM users WHERE email = $1", ADMIN_EMAIL)
        if admin_user is None:
            admin_user = ADMIN_USER_ID_FALLBACK
            await conn.execute(
                "INSERT INTO users (id, email, name) VALUES ($1,$2,'M13 Admin')",
                admin_user, ADMIN_EMAIL)
    return str(admin_user)


# ── רשימת המסלולים החדשים של M13 (משותפת לבדיקות 1–3) ─────────────────────────
ROUTES = [
    "/api/admin/analytics/leads-by-type",
    "/api/admin/analytics/messages",
    "/api/admin/analytics/ai-ops",
    "/api/admin/analytics/by-plan?metric=ai_call",
    "/api/admin/analytics/trends",
    "/api/admin/crm",
    f"/api/admin/businesses/{BIZ_A}/crm/notes",
]


async def run_phases(story, http, redis, su, pool, admin_user) -> None:
    """מריץ את כל 16 הבדיקות בסדר, על אותו client/lifespan, ומעדכן את ה‑Story."""
    banner, explain, result = story.banner, story.explain, story.result

    # ── בדיקה 1 — הדלת נעולה (בלי כניסה) ─────────────────────────────
    banner("1", "בלי כניסה → כל מסכי האנליטיקה וה‑CRM נעולים (401)")
    explain(
        "קוראים לכל המסלולים החדשים של M13 (אנליטיקה, CRM, פתקים) בלי שום login",
        "חדר הבקרה חוצה את חומת הטננטים. אם היה נגיש בלי login, כל אחד ברשת היה "
        "קורא נתונים של כל העסקים. חייב להיות 401 חלק לפני שום עבודה.")
    codes = [(await http.get(r)).status_code for r in ROUTES]
    patch_c = (await http.patch(
        f"/api/admin/businesses/{BIZ_A}/crm", json={"stage": "won"})).status_code
    post_c = (await http.post(
        f"/api/admin/businesses/{BIZ_A}/crm/notes", json={"note": "x"})).status_code
    result(all(c == 401 for c in codes) and patch_c == 401 and post_c == 401,
           f"קריאות בלי login → {codes}, PATCH={patch_c}, POST={post_c} "
           f"(הכול 401 — נעול)")

    # ── בדיקה 2 — בעל עסק רגיל הוא לא בעל הקניון (403) ───────────────
    banner("2", "בעל עסק רגיל נכנס → חדר הבקרה אומר 403")
    explain(
        "מתחברים כאבי (בעל עסק רגיל, לא ברשימת ה‑admin) ופותחים כל מסך M13",
        "בעל עסק מנהל את העסק שלו — לעולם לא את הקניון. דלת ה‑admin בודקת את "
        "האימייל מול הרשימה LIVE בכל בקשה, אז אבי חייב לקבל 403 בכל מקום.")
    sid = await _login(redis, http, AVI_USER, NONADMIN_EMAIL, BIZ_A)
    codes = [(await http.get(r)).status_code for r in ROUTES]
    patch_c = (await http.patch(
        f"/api/admin/businesses/{BIZ_A}/crm", json={"stage": "won"})).status_code
    post_c = (await http.post(
        f"/api/admin/businesses/{BIZ_A}/crm/notes", json={"note": "x"})).status_code
    await _logout(redis, http, sid)
    result(all(c == 403 for c in codes) and patch_c == 403 and post_c == 403,
           f"בעל עסק רגיל → קריאות {codes}, PATCH={patch_c}, POST={post_c} "
           f"(הכול 403 — לא בעל הקניון)")

    # ── בדיקה 3 — ה‑admin נכנס לכל המסכים (200) ──────────────────────
    banner("3", "Omer (admin) נכנס → 200 בכל מסכי האנליטיקה וה‑CRM")
    explain(
        "מתחברים כ‑Omer (אימייל ברשימת ה‑admin) ופותחים כל מסך קריאה של M13",
        "בעל הקניון חייב להיכנס. אם הדלת חוסמת גם אותו — אין לוח מחוונים בכלל.")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    codes = [(await http.get(r)).status_code for r in ROUTES]
    await _logout(redis, http, sid)
    result(all(c == 200 for c in codes),
           f"ה‑admin קורא {codes} (הכול 200)")

    # ── בדיקה 4 — עוגת סוגי הלידים מסתדרת עם המספרים האמיתיים ────────
    banner("4", "עוגת סוגי הלידים (פגישה/ליד/נציג) מתחברת לאמת ב‑DB")
    explain(
        "זורעים לאבי 2 לידים רגילים + 1 פנייה‑לנציג + 1 פגישה, ומשווים את העוגה "
        "לפני ואחרי",
        "המספרים בלוח חייבים לשקף את המציאות. אנחנו משנים כמות ידועה ובודקים "
        "שכל דלי זז בדיוק בכמות הזו — בלי דליפות בין הקטגוריות.")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    base = (await http.get(
        "/api/admin/analytics/leads-by-type?period=all&plan=all")).json()
    await _seed_lead(su, BIZ_A, handoff=False)
    await _seed_lead(su, BIZ_A, handoff=False)
    await _seed_lead(su, BIZ_A, handoff=True)
    await _seed_booking(su, BIZ_A)
    after = (await http.get(
        "/api/admin/analytics/leads-by-type?period=all&plan=all")).json()
    await _logout(redis, http, sid)
    buckets_ok = (
        after["lead"] == base["lead"] + 2
        and after["handoff"] == base["handoff"] + 1
        and after["booking"] == base["booking"] + 1)
    result(buckets_ok,
           f"ליד {base['lead']}→{after['lead']} (+2), "
           f"נציג {base['handoff']}→{after['handoff']} (+1), "
           f"פגישה {base['booking']}→{after['booking']} (+1) — הכול מסתדר")
    await _wipe(su)

    # ── בדיקה 5 — תצוגת ההודעות‑לחיוב מתחברת למונים ─────────────────
    banner("5", "ההודעות לכל עסק (בסיס לחיוב) סופרות נכון")
    explain(
        "מקפיצים לאבי 5 הודעות נכנסות ו‑3 יוצאות, וקוראים את תצוגת החיוב",
        "החיוב העתידי יישען על המספרים האלה. הם חייבים לזוז בדיוק כמו המונה, "
        "ו‑total חייב להיות in+out.")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    base = (await http.get("/api/admin/analytics/messages?period=all")).json()
    base_a = next((r for r in base["businesses"] if r["business_id"] == BIZ_A),
                  {"msg_in": 0, "msg_out": 0, "total": 0})
    await _bump(pool, BIZ_A, usage_service.METRIC_MSG_IN, 5)
    await _bump(pool, BIZ_A, usage_service.METRIC_MSG_OUT, 3)
    after = (await http.get("/api/admin/analytics/messages?period=all")).json()
    after_a = next((r for r in after["businesses"] if r["business_id"] == BIZ_A), None)
    await _logout(redis, http, sid)
    msgs_ok = (
        after_a is not None
        and after_a["msg_in"] == base_a["msg_in"] + 5
        and after_a["msg_out"] == base_a["msg_out"] + 3
        and after_a["total"] == base_a["total"] + 8
        and after_a["total"] == after_a["msg_in"] + after_a["msg_out"])
    result(msgs_ok,
           f"נכנסות {base_a['msg_in']}→{after_a['msg_in']} (+5), "
           f"יוצאות {base_a['msg_out']}→{after_a['msg_out']} (+3), "
           f"total={after_a['total']} (=in+out)")
    await _wipe(su)

    # ── בדיקה 6 — פילוח לפי תוכנית מקבץ נכון ─────────────────────────
    banner("6", "פילוח מטריקה לפי תוכנית (free/basic/pro) מקבץ נכון")
    explain(
        "אבי=pro, בלה=basic; מקפיצים מטריקת 'lead' לכל אחד ובודקים שכל ערך נחת "
        "מתחת לתוכנית הנכונה",
        "הפילוח לפי תוכנית עוזר ל‑Omer להבין איזו תוכנית מייצרת ערך. ערך של עסק "
        "pro לא יכול להיספר בטעות תחת basic.")
    await _set_sub(su, BIZ_A, "pro", "active")
    await _set_sub(su, BIZ_B, "basic", "active")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)

    def _val(body, plan):
        return next((r["value"] for r in body["rows"] if r["plan_code"] == plan), 0)

    base = (await http.get(
        "/api/admin/analytics/by-plan?metric=lead&period=all")).json()
    base_pro, base_basic = _val(base, "pro"), _val(base, "basic")
    await _bump(pool, BIZ_A, usage_service.METRIC_LEAD, 4)
    await _bump(pool, BIZ_B, usage_service.METRIC_LEAD, 7)
    after = (await http.get(
        "/api/admin/analytics/by-plan?metric=lead&period=all")).json()
    await _logout(redis, http, sid)
    byplan_ok = (_val(after, "pro") == base_pro + 4
                 and _val(after, "basic") == base_basic + 7)
    result(byplan_ok,
           f"pro {base_pro}→{_val(after, 'pro')} (+4), "
           f"basic {base_basic}→{_val(after, 'basic')} (+7) — קובץ נכון")
    await _wipe(su)

    # ── בדיקה 7 — פעולות ה‑AI ליום מצטברות נכון ─────────────────────
    banner("7", "סדרת פעולות ה‑AI ליום (ai_call) מצטברת על פני כל העסקים")
    explain(
        "מקפיצים ai_call לאבי (+2) ולבלה (+3), וקוראים את הסדרה היומית",
        "כל קריאת Gemini מוצלחת נספרת. הנקודה של היום צריכה לגדול בדיוק בסכום "
        "מכל העסקים (2+3=5).")
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)

    def _today(body):
        return next((p["count"] for p in body["series"]
                     if p["day"] == date.today().isoformat()), 0)

    base = (await http.get("/api/admin/analytics/ai-ops")).json()
    base_today = _today(base)
    await _bump(pool, BIZ_A, usage_service.METRIC_AI_CALL, 2)
    await _bump(pool, BIZ_B, usage_service.METRIC_AI_CALL, 3)
    after = (await http.get("/api/admin/analytics/ai-ops")).json()
    bad_date = (await http.get(
        "/api/admin/analytics/ai-ops?from=nope")).status_code
    await _logout(redis, http, sid)
    aiops_ok = _today(after) == base_today + 5 and bad_date == 422
    result(aiops_ok,
           f"ai_call היום {base_today}→{_today(after)} (+5); "
           f"תאריך שבור → {bad_date} (422)")
    await _wipe(su)

    # ── בדיקה 8 — ה‑LTV (הערכה): מחיר × ותק ─────────────────────────
    banner("8", "LTV (הערכה) = מחיר תוכנית × ותק; free → 0")
    explain(
        "אבי=pro שהתחיל לפני 3 חודשים → 149×3=447; בלה ללא מנוי → 0. גם בודקים "
        "ש‑avg/total ב‑overview מתחברים לפונקציית הסיכום",
        "ה‑LTV הוא ההערכה כמה כל לקוח שווה. הוא חייב להיות מחיר התוכנית × חודשי "
        "ותק, ו‑free שווה 0 — אחרת ההחלטות של Omer יישענו על מספר שגוי.")
    await _set_sub(su, BIZ_A, "pro", "active", months_ago=3)
    sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
    a = (await http.get(f"/api/admin/businesses/{BIZ_A}")).json()
    b = (await http.get(f"/api/admin/businesses/{BIZ_B}")).json()
    overview = (await http.get("/api/admin/overview")).json()
    await _logout(redis, http, sid)
    async with pool.acquire() as conn:
        summ = await conn.fetchrow("SELECT * FROM admin_ltv_summary()")
    ltv_ok = (
        abs(a["ltv_estimate"] - PRICE_PRO * 3) < 0.01
        and b["ltv_estimate"] == 0
        and a["crm"]["stage"] == "new"
        and abs(overview["total_ltv"] - float(summ["total_ltv"])) < 0.01
        and abs(overview["avg_ltv"] - float(summ["avg_ltv"])) < 0.01)
    result(ltv_ok,
           f"אבי(pro, 3 ח') LTV={a['ltv_estimate']} (=149×3), בלה(free)="
           f"{b['ltv_estimate']}; overview total_ltv={overview['total_ltv']} "
           f"תואם את הסיכום")
    await _wipe(su)
