# 0024 — הקשחת אבטחה לקראת פרודקשן + שער QA

> סטטוס: **done** · תאריך: 2026-07-16 · Owner: Omer
> Commit: `037a924` (merged ב-PR #1, `b57b76e`)
> **הפירוט המלא** יושב ב-[`../security/hardening-report.md`](../security/hardening-report.md)
> ו-[`../security/production-networking.md`](../security/production-networking.md) — כאן רק ההחלטות.

## Context
לפני העלייה לאוויר עשינו מעבר הקשחה אחד, חוצה-מערכת, בענף `chore/security-hardening`.
המסמך הזה מקבע את מה שהוחלט; הדוחות המפורטים לא משוכפלים כאן.

## ההחלטות

### 1. קובץ סודות אחד — `infra/.env`
`infra/.env.local` שונה ל-**`infra/.env`** (אותו תוכן, עדיין git-ignored), וכל ההפניות עודכנו:
compose, `core/config.py`, `run.bat`/`stop.bat`/`Makefile`, כל `tests/*.bat`, ה-agents וה-docs.
נשאר **template אחד** במעקב — `infra/.env.example`; ה-templates הפר-תיקייה נמחקו,
ומפתחות כפולים מתים נוקו.

### 2. תיקון דליפת PII ב-access log (HIGH)
`uvicorn.access` רשם את שורת הבקשה הגולמית **כולל query string** — ובכך דלפו
`code`/`state` של OAuth ו-`cancel_token` של ביטול הזמנה אל תוך הלוגים.
`backend/app/core/request_log.py` מחליף אותו ב-middleware שרושם **שורה אחת מצונזרת**
(method · path בלי query · status · ms), עם מיסוך של path segments שהם טוקנים.
אומת: canary של `code`/`state` לא מופיע באף לוג.

### 3. רשת פרודקשן — reverse proxy הוא הדלת היחידה
`infra/docker-compose.prod.yml` + `infra/Caddyfile`: **Caddy** הוא השירות היחיד עם
פורטים מפורסמים (80/443); postgres/redis/gateway/backend נשארים על הרשת הפנימית.
`frontend/Dockerfile.prod` מגיש build סטטי. הסביבה המקומית (dev) **לא נגעה**.

### 4. תיעוד API כבוי בפרודקשן
`/docs`, `/redoc`, `/openapi.json` מושבתים כאשר `APP_ENV != dev` (ב-`create_app`, `app/main.py`).

### 5. שערי בדיקה (guards) + מטריצת auth
- `test_frontend_secret_guard` — אין סוד בבנדל של ה-frontend.
- `test_log_pii_guard` — אין PII/טוקנים בלוגים.
- `test_port_exposure_guard` — אין שירות מפורסם מלבד ה-proxy.
- `test_e2e_auth_matrix.py` — **12 בדיקות** על session / admin / gateway-token / public-booking.
- עודכנו assertions ישנות ב-`test_m6a.py` / `test_m6b_wall.py` (M6b הוסיף שדות error/conflict).

### 6. Postman ל-CI
`tests/postman/` — collection + environment להרצה ב-**newman**, **בלי סודות במעקב**.
הרצה חיה: **18/18 assertions ירוקות**.

## שאריות (flagged, לא בוצע)
- **לרוטט `GOOGLE_CLIENT_SECRET` ו-`GEMINI_API_KEY`** לפני go-live אמיתי — עדיין פתוח.

## Consequences
- יש עכשיו נתיב פרודקשן מוכן (`docker-compose.prod.yml`) שנוצל בפועל בהחלטה
  [`0025-production-deployment.md`](0025-production-deployment.md).
- כל סוד חדש נכנס למקום אחד בלבד (`infra/.env` + שורה ב-`infra/.env.example`).
