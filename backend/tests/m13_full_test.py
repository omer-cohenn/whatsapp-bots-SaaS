"""
============================================================================
  M13 — חדר הבקרה הופך ללוח מחוונים של בעל ה‑SaaS — בדיקה מלאה, בשפה פשוטה
============================================================================

מה זה הקובץ הזה?
  ב‑M12 בנינו ל‑Omer "חדר בקרה" — חלון אחד שמשקיף על כל העסקים בקניון. ב‑M13
  אנחנו מוסיפים שם לוח‑מחוונים אמיתי של בעל עסק:

      💰 LTV  — כמה כל לקוח‑עסק שווה (מחיר התוכנית × כמה חודשים הוא איתנו) — הערכה.
      💬 הודעות לכל עסק — בסיס לחיוב עתידי.
      🎯 סוגי לידים — פגישה / ליד רגיל / פנייה‑לנציג, בעוגה אחת.
      🤖 פעולות AI  — כמה פעמים ה‑Gemini עבד, ליום ולפי תוכנית.
      📈 מגמות — צילום‑מצב יומי (snapshot) שנצבר ל‑MRR/פעילים/נטישה.

  ובנוסף — טבלת מכירות (CRM ברמת הפלטפורמה): כל עסק הוא כרטיס שנע בעמודות
  חדש → יצרתי‑קשר → מחמם → נסגר/אבד, עם פתקים ותזכורת חזרה. כדי ש‑Omer ידע על מי
  לעבוד עד שמשלם.

  הכלל הקדוש לא נשבר: חדר הבקרה הוא המקום היחיד שחוצים בו את חומת הטננטים — בכוונה.
  לכן יש לו דלת נעולה משלו (רשימת אימיילים של admin), והחצייה קורית רק דרך
  פונקציות "SECURITY DEFINER" צרות. אף עסק רגיל לא יכול לקרוא את טבלאות ה‑CRM
  ישירות, ושום נתון של לקוח‑קצה (טלפון/שם/תשובות) לא דולף לחדר הבקרה.

  כל בדיקה מדפיסה:
      🧪 מה ניסינו
      💡 למה זה חשוב (מה היה משתבש במציאות)
      ✅ / ❌ מה קרה בפועל

  הבדיקה הכי חשובה: עסק רגיל לא יכול לקרוא ישירות את טבלאות ה‑CRM/snapshots —
  ואנחנו גם "שוברים" את החומה בכוונה (negative control) ורואים שהבדיקה תופסת,
  ואז מחזירים הכול למקום.

  להרצה: לחצו פעמיים על tests/test_m13.bat, או ראו HOW‑TO בתחתית.
============================================================================
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from datetime import date

import asyncpg
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from app.db.session import tenant_connection
from app.main import app
from app.services import usage as usage_service
from app.services.auth import SESSION_COOKIE_NAME, _SESSION_KEY_PREFIX

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

# לוח תוצאות.
_passed = 0
_total = 0


# --- עזרי הדפסה ("שפת התינוק" כולה כאן) --------------------------------------

def banner(num: str, title: str) -> None:
    print()
    print("─" * 74)
    print(f"  בדיקה {num}: {title}")
    print("─" * 74)


def explain(what: str, why: str) -> None:
    print(f"  🧪 ניסינו : {what}")
    print(f"  💡 כי     : {why}")


def result(ok: bool, detail: str) -> None:
    global _passed, _total
    _total += 1
    if ok:
        _passed += 1
        print(f"  ✅ טוב    : {detail}")
    else:
        print(f"  ❌ רע     : {detail}   <-- צריך תיקון!")


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


async def main() -> int:  # noqa: C901 — רשימת בדיקות שטוחה וקריאה בכוונה
    print(__doc__)

    app_dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]

    pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=4)
    redis = aioredis.from_url(redis_url, decode_responses=True)
    su = await asyncpg.create_pool(dsn=_superuser_dsn(), min_size=1, max_size=2)

    # פותרים את מזהה ה‑admin האמיתי בשביל ה‑FK של האודיט/פתקים (users.email ייחודי).
    async with su.acquire() as conn:
        admin_user = await conn.fetchval(
            "SELECT id FROM users WHERE email = $1", ADMIN_EMAIL)
        if admin_user is None:
            admin_user = ADMIN_USER_ID_FALLBACK
            await conn.execute(
                "INSERT INTO users (id, email, name) VALUES ($1,$2,'M13 Admin')",
                admin_user, ADMIN_EMAIL)
    admin_user = str(admin_user)

    await _wipe(su)
    print("\n  (הכנה: ניקינו את מצב ה‑CRM/subscriptions/usage של אבי+בלה, "
          "ופתרנו את משתמש ה‑admin)")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:

            # ── בדיקה 1 — הדלת נעולה (בלי כניסה) ─────────────────────────────
            banner("1", "בלי כניסה → כל מסכי האנליטיקה וה‑CRM נעולים (401)")
            explain(
                "קוראים לכל המסלולים החדשים של M13 (אנליטיקה, CRM, פתקים) בלי שום login",
                "חדר הבקרה חוצה את חומת הטננטים. אם היה נגיש בלי login, כל אחד ברשת היה "
                "קורא נתונים של כל העסקים. חייב להיות 401 חלק לפני שום עבודה.")
            routes = [
                "/api/admin/analytics/leads-by-type",
                "/api/admin/analytics/messages",
                "/api/admin/analytics/ai-ops",
                "/api/admin/analytics/by-plan?metric=ai_call",
                "/api/admin/analytics/trends",
                "/api/admin/crm",
                f"/api/admin/businesses/{BIZ_A}/crm/notes",
            ]
            codes = [(await http.get(r)).status_code for r in routes]
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
            codes = [(await http.get(r)).status_code for r in routes]
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
            codes = [(await http.get(r)).status_code for r in routes]
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

            # ── בדיקה 9 — בליעת ai_call (החיווט האמיתי) ─────────────────────
            banner("9", "מונה ה‑ai_call באמת מתעדכן (החיווט של bot‑builder/booking)")
            explain(
                "מריצים את אותו bump_safe(ai_call) שה‑endpoint מריץ אחרי קריאת Gemini, "
                "וקוראים את usage_daily של היום",
                "המספרים בלוח טובים רק אם המונה באמת תופס כל פעולת AI. הקפצה אחת חייבת "
                "לנחות על שורת היום של העסק הנכון.")
            async with su.acquire() as conn:
                before = (await conn.fetchval(
                    "SELECT count FROM usage_daily WHERE business_id=$1 AND "
                    "day=current_date AND metric='ai_call'", BIZ_A)) or 0
            async with tenant_connection(pool, BIZ_A) as conn:
                await usage_service.bump_safe(conn, BIZ_A, usage_service.METRIC_AI_CALL)
            async with su.acquire() as conn:
                after_cnt = await conn.fetchval(
                    "SELECT count FROM usage_daily WHERE business_id=$1 AND "
                    "day=current_date AND metric='ai_call'", BIZ_A)
            result(after_cnt == before + 1,
                   f"ai_call {before}→{after_cnt} (+1) — החיווט תופס")
            await _wipe(su)

            # ── בדיקה 10 — ה‑snapshot נחתם, ואידמפוטנטי ─────────────────────
            banner("10", "כל טעינת overview חותמת snapshot של היום — ואידמפוטנטי")
            explain(
                "קוראים overview פעמיים ובודקים שיש בדיוק שורת snapshot אחת להיום, "
                "ושה‑body מחזיר avg_ltv",
                "אין scheduler, אז ההיסטוריה למגמות נצברת בכל טעינה. אבל שתי טעינות "
                "באותו יום חייבות להשאיר שורה אחת — לא להכפיל את ההיסטוריה.")
            sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
            b1 = (await http.get("/api/admin/overview")).json()
            await http.get("/api/admin/overview")
            await _logout(redis, http, sid)
            async with su.acquire() as conn:
                rows = await conn.fetchval(
                    "SELECT count(*) FROM platform_snapshots WHERE day=current_date")
            snap_ok = rows == 1 and "avg_ltv" in b1 and "total_ltv" in b1
            result(snap_ok,
                   f"שורות snapshot להיום={rows} (אחת), overview כולל avg_ltv "
                   f"({b1.get('avg_ltv')})")

            # ── בדיקה 11 — מגמות: הסדרה מכילה את היום ───────────────────────
            banner("11", "סדרת המגמות (trends) מכילה את ה‑snapshot של היום")
            explain(
                "אחרי שה‑overview חתם את היום, קוראים את סדרת המגמות",
                "גרפי ה‑MRR/פעילים/נטישה ניזונים מה‑snapshots. אחרי חתימה, היום חייב "
                "להופיע בסדרה עם מספרים שתואמים את ה‑overview.")
            sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
            overview = (await http.get("/api/admin/overview")).json()
            trends = (await http.get("/api/admin/analytics/trends")).json()
            await _logout(redis, http, sid)
            today_pt = next((p for p in trends["series"]
                             if p["day"] == date.today().isoformat()), None)
            trends_ok = (today_pt is not None
                         and today_pt["total_businesses"] == overview["total_businesses"]
                         and today_pt["active_count"] == overview["active_count"])
            result(trends_ok,
                   f"היום בסדרה: עסקים={today_pt and today_pt['total_businesses']}, "
                   f"פעילים={today_pt and today_pt['active_count']} — תואם overview")

            # ── בדיקה 12 — CRM: הזזת שלב + שובל אודיט ────────────────────────
            banner("12", "מזיזים עסק בצינור המכירות → השלב נשמר ונכתב אודיט עם זהות ה‑admin")
            explain(
                "כ‑admin מזיזים את אבי לשלב 'warming' עם תזכורת חזרה, ומציצים בלוח "
                "ובאודיט",
                "כל פעולת CRM היא חצייה של החומה — חייבת להשאיר טביעת אצבע: מי (ה‑Google "
                "sub + אימייל האמיתיים), מה (crm_stage), על איזה עסק.")
            await _wipe(su)
            sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
            patch = await http.patch(
                f"/api/admin/businesses/{BIZ_A}/crm",
                json={"stage": "warming", "next_followup": "2026-07-01T09:00:00+00:00"})
            board = (await http.get("/api/admin/crm")).json()
            await _logout(redis, http, sid)
            row = next((c for c in board["businesses"] if c["business_id"] == BIZ_A), None)
            async with su.acquire() as conn:
                audit = await conn.fetchrow(
                    "SELECT admin_user_id, admin_email, action, target_business_id, "
                    "detail FROM admin_audit WHERE target_business_id=$1 "
                    "AND action='crm_stage' ORDER BY created_at DESC LIMIT 1", BIZ_A)
            d = (audit["detail"] if isinstance(audit["detail"], dict)
                 else json.loads(audit["detail"])) if audit else {}
            crm_ok = (
                patch.status_code == 200
                and patch.json()["stage"] == "warming"
                and row is not None and row["stage"] == "warming"
                and audit is not None
                and audit["admin_user_id"] == admin_user
                and audit["admin_email"] == ADMIN_EMAIL
                and audit["action"] == "crm_stage"
                and str(audit["target_business_id"]) == BIZ_A
                and d == {"stage": "warming"})
            result(crm_ok,
                   "אבי עבר ל‑'warming' בלוח; אודיט נחתם עם ה‑admin id+email האמיתיים, "
                   "action=crm_stage, על העסק הנכון")

            # ── בדיקה 13 — פתקי CRM: הלוך‑ושוב + ספירה + קלט שגוי ────────────
            banner("13", "פתק CRM נכתב (201), חוזר חדש‑קודם, וספירת הפתקים עולה")
            explain(
                "כ‑admin מוסיפים שני פתקים, קוראים את היומן, ובודקים את ספירת הפתקים "
                "בלוח; וגם פתק ריק וענק‑לא‑קיים",
                "היומן מאפשר ל‑Omer לזכור מה דובר מול כל לקוח. פתק חייב לחזור חדש‑קודם, "
                "הספירה חייבת לעלות, וקלט שגוי חייב להידחות נקי (422/404).")
            await _wipe(su)
            sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
            board0 = (await http.get("/api/admin/crm")).json()
            base_count = next((c["note_count"] for c in board0["businesses"]
                               if c["business_id"] == BIZ_A), 0)
            r1 = await http.post(f"/api/admin/businesses/{BIZ_A}/crm/notes",
                                 json={"note": "התקשרתי לבעלים; ליד חם"})
            r2 = await http.post(f"/api/admin/businesses/{BIZ_A}/crm/notes",
                                 json={"note": "נגיעה שנייה; שלחתי מחירון"})
            notes = (await http.get(
                f"/api/admin/businesses/{BIZ_A}/crm/notes")).json()["notes"]
            board1 = (await http.get("/api/admin/crm")).json()
            new_count = next((c["note_count"] for c in board1["businesses"]
                              if c["business_id"] == BIZ_A), 0)
            blank = (await http.post(f"/api/admin/businesses/{BIZ_A}/crm/notes",
                                     json={"note": "   "})).status_code
            unknown = (await http.post(f"/api/admin/businesses/{UNKNOWN_BIZ}/crm/notes",
                                       json={"note": "x"})).status_code
            await _logout(redis, http, sid)
            ids = [n["id"] for n in notes]
            notes_ok = (
                r1.status_code == 201 and r2.status_code == 201
                and r1.json()["note_id"] in ids and r2.json()["note_id"] in ids
                and ids.index(r2.json()["note_id"]) < ids.index(r1.json()["note_id"])
                and notes[0]["note"] == "נגיעה שנייה; שלחתי מחירון"
                and notes[0]["admin_email"] == ADMIN_EMAIL
                and new_count == base_count + 2
                and blank == 422 and unknown == 404)
            result(notes_ok,
                   f"שני פתקים נכתבו (201), חזרו חדש‑קודם, ספירה {base_count}→{new_count} "
                   f"(+2); פתק ריק→{blank}, עסק לא‑קיים→{unknown}")
            await _wipe(su)

            # ── בדיקה 14 — בידוד: טבלאות ה‑CRM/snapshots מחוץ לתחום ─────────
            banner("14", "עסק רגיל לא יכול לקרוא ישירות business_crm / crm_notes / snapshots")
            explain(
                "ב‑app role רגיל מנסים לקרוא ישירות את שלוש טבלאות חדר‑הבקרה החדשות; "
                "ואז אבי מנסה לקרוא את שורות ה‑usage של בלה",
                "חציית החומה אפשרית רק דרך פונקציות ה‑SD הצרות. שלוש הטבלאות נותנות "
                "ל‑app role אפס גישה ישירה, ו‑usage עדיין מציית לחומה — אבי לא רואה את בלה.")
            crm_denied = notes_denied = snap_denied = False
            try:
                async with tenant_connection(pool, BIZ_A) as conn:
                    await conn.fetch("SELECT * FROM business_crm")
            except asyncpg.InsufficientPrivilegeError:
                crm_denied = True
            try:
                async with tenant_connection(pool, BIZ_A) as conn:
                    await conn.fetch("SELECT * FROM crm_notes")
            except asyncpg.InsufficientPrivilegeError:
                notes_denied = True
            try:
                async with tenant_connection(pool, BIZ_A) as conn:
                    await conn.fetch("SELECT * FROM platform_snapshots")
            except asyncpg.InsufficientPrivilegeError:
                snap_denied = True
            async with tenant_connection(pool, BIZ_A) as conn:
                b_rows = await conn.fetch(
                    "SELECT * FROM usage_daily WHERE business_id=$1", BIZ_B)
            # הדלת המורשית (פונקציית ה‑SD) עדיין עובדת על conn רגיל.
            async with pool.acquire() as conn:
                crm_list = await conn.fetch("SELECT * FROM admin_crm_list()")
            iso_ok = (crm_denied and notes_denied and snap_denied
                      and b_rows == [] and len(crm_list) >= 2)
            result(iso_ok,
                   f"business_crm denied={crm_denied}, crm_notes denied={notes_denied}, "
                   f"snapshots denied={snap_denied}; אבי רואה {len(b_rows)} משורות בלה; "
                   f"פונקציית ה‑SD עדיין עובדת (הדלת היחידה)")

            # ── בדיקה 15 — NEGATIVE CONTROL: שוברים את החומה, רואים שנתפס ────
            banner("15", "NEGATIVE CONTROL: נותנים grant ידני, רואים שנפתח — ואז מחזירים")
            explain(
                "נותנים ל‑app role GRANT SELECT ישיר על crm_notes, מוודאים שהקריאה "
                "מצליחה (כלומר הבדיקה מסוגלת לתפוס דליפה) — ואז REVOKE ומוודאים שוב חסום",
                "בדיקה טובה חייבת להיות מסוגלת להיכשל. אם נשלול את ה‑grant ושום דבר "
                "לא ישתנה — החומה פתוחה. מוכיחים שהחסימה היא grant אמיתי וניתן‑להסרה, "
                "ומחזירים את הכול.")
            opened = restored = False
            async with su.acquire() as conn:
                await conn.execute("GRANT SELECT ON crm_notes TO app_role")
            try:
                async with tenant_connection(pool, BIZ_A) as conn:
                    leaked = await conn.fetch("SELECT * FROM crm_notes")
                opened = isinstance(leaked, list)  # הדלת נפתחה — אפשר לראות דליפה
            except asyncpg.InsufficientPrivilegeError:
                opened = False
            async with su.acquire() as conn:
                await conn.execute("REVOKE SELECT ON crm_notes FROM app_role")
            try:
                async with tenant_connection(pool, BIZ_A) as conn:
                    await conn.fetch("SELECT * FROM crm_notes")
            except asyncpg.InsufficientPrivilegeError:
                restored = True
            result(opened and restored,
                   "grant ידני → הקריאה הצליחה (הבדיקה מסוגלת לתפוס דליפה); "
                   "REVOKE → חסום שוב (שוחזר)")

            # ── בדיקה 16 — בלי דליפת PII ────────────────────────────────────
            banner("16", "אף תגובת אנליטיקה/CRM לא מחזירה PII של לקוח‑קצה")
            explain(
                "זורעים פנייה‑לנציג + פגישה (כדי שהדליים לא יהיו אפס), וסורקים את כל "
                "מפתחות התגובות מול רשימה אסורה (טלפון/שם/תשובות/טקסט הודעה)",
                "חדר הבקרה מציג זהות + מספרים + הקשר מכירות — לעולם לא תוכן של לקוח‑קצה. "
                "טקסט הפתק של ה‑CRM הוא נתון מכירות של Omer, אבל גם הוא לא דולף החוצה.")
            await _seed_lead(su, BIZ_A, handoff=True)
            await _seed_booking(su, BIZ_A)
            forbidden = {"phone", "client_phone", "contact_name", "client_name",
                         "lead_name", "message", "text", "answers", "client_email",
                         "meet_link"}
            sid = await _login(redis, http, admin_user, ADMIN_EMAIL, BIZ_A)
            lbt = (await http.get(
                "/api/admin/analytics/leads-by-type?period=all")).json()
            msgs = (await http.get("/api/admin/analytics/messages?period=all")).json()
            crm = (await http.get("/api/admin/crm")).json()
            detail = (await http.get(f"/api/admin/businesses/{BIZ_A}")).json()
            await _logout(redis, http, sid)
            leak = False
            if set(lbt.keys()) != {"booking", "lead", "handoff"}:
                leak = True
            for r in msgs["businesses"]:
                if set(r.keys()) & forbidden:
                    leak = True
            for c in crm["businesses"]:
                if set(c.keys()) & forbidden:
                    leak = True
            if set(detail.keys()) & forbidden:
                leak = True
            result(not leak,
                   "כל מפתחות התגובות הם זהות/מספרים/הקשר‑מכירות — אפס מפתח של "
                   "לקוח‑קצה (טלפון/שם/תשובות) דלף")
            await _wipe(su)

    # ── ניקוי סופי ────────────────────────────────────────────────────────────
    await _wipe(su)
    await pool.close()
    await su.close()
    await redis.aclose()

    # ── לוח תוצאות ──────────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    if _passed == _total:
        print(f"  🎉 תוצאה: M13 {_passed}/{_total} בדיקות עברו. לוח המחוונים של בעל "
              "ה‑SaaS אמין, ה‑CRM נעול, וה‑PII לא דולף. 👑")
    else:
        print(f"  🚨 תוצאה: M13 {_passed}/{_total} עברו — {_total - _passed} "
              "נכשלו. אל תשחררו עד שירוק.")
    print("=" * 74)
    return 0 if _passed == _total else 1


# ── איך מריצים ───────────────────────────────────────────────────────────────
#   הכי קל : לחיצה כפולה על  tests/test_m13.bat  (מסדר הכול לבד).
#   ידנית  : מתיקיית השורש, עם הסטאק רץ (run.bat):
#     docker compose --env-file infra/.env.local -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/m13_full_test.py"
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
