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

  (הקובץ הזה הוא runner דק: לוגיקת 16 הבדיקות יושבת ב‑_m13_story.py, ועזרי
   ה"שפת התינוק" המשותפים ב‑_story.py — אותו פלט בדיוק, רק מסודר יותר.)
============================================================================
"""

from __future__ import annotations

import asyncio
import os

import asyncpg
import redis.asyncio as aioredis
from httpx import ASGITransport, AsyncClient

from _m13_story import _superuser_dsn, _wipe, resolve_admin_user, run_phases
from _m13_story_b import run_phases_b
from _story import Story
from app.main import app


async def main() -> int:
    print(__doc__)

    app_dsn = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]

    pool = await asyncpg.create_pool(dsn=app_dsn, min_size=1, max_size=4)
    redis = aioredis.from_url(redis_url, decode_responses=True)
    su = await asyncpg.create_pool(dsn=_superuser_dsn(), min_size=1, max_size=2)

    # פותרים את מזהה ה‑admin האמיתי בשביל ה‑FK של האודיט/פתקים (users.email ייחודי).
    admin_user = await resolve_admin_user(su)

    await _wipe(su)
    print("\n  (הכנה: ניקינו את מצב ה‑CRM/subscriptions/usage של אבי+בלה, "
          "ופתרנו את משתמש ה‑admin)")

    # לוח התוצאות מוגדר עם הנוסח העברי המדויק של M13.
    story = Story(test_label="בדיקה", try_label="ניסינו ", because_label="כי     ",
                  good_label="טוב    ", bad_label="רע     ", bad_suffix="<-- צריך תיקון!")

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            await run_phases(story, http, redis, su, pool, admin_user)
            await run_phases_b(story, http, redis, su, pool, admin_user)

    # ── ניקוי סופי ────────────────────────────────────────────────────────────
    await _wipe(su)
    await pool.close()
    await su.close()
    await redis.aclose()

    # ── לוח תוצאות ──────────────────────────────────────────────────────────────
    print()
    print("=" * 74)
    if story.passed == story.total:
        print(f"  🎉 תוצאה: M13 {story.passed}/{story.total} בדיקות עברו. לוח המחוונים של בעל "
              "ה‑SaaS אמין, ה‑CRM נעול, וה‑PII לא דולף. 👑")
    else:
        print(f"  🚨 תוצאה: M13 {story.passed}/{story.total} עברו — {story.total - story.passed} "
              "נכשלו. אל תשחררו עד שירוק.")
    print("=" * 74)
    return 0 if story.passed == story.total else 1


# ── איך מריצים ───────────────────────────────────────────────────────────────
#   הכי קל : לחיצה כפולה על  tests/test_m13.bat  (מסדר הכול לבד).
#   ידנית  : מתיקיית השורש, עם הסטאק רץ (run.bat):
#     docker compose --env-file infra/.env -f infra/docker-compose.yml \
#       run --rm backend sh -c "cd /app && PYTHONPATH=/app python tests/narrated/m13_full_test.py"
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
