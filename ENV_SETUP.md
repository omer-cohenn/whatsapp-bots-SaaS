# ENV_SETUP.md — מה למלא כדי לעבוד עם API אמיתיים (בלי דמה) 🔑

> המדריך הזה מסביר **בדיוק** אילו ערכים צריך למלא בקובץ `infra/.env` כדי שהמערכת תרוץ עם
> שירותים אמיתיים. רוב הערכים אתה **מייצר בעצמך** (סודות אקראיים). רק שניים מגיעים משירות חיצוני
> אמיתי: **Gemini** (ה-AI) ו-**Google OAuth** (התחברות).
>
> **DB ו-Redis אמיתיים ורצים מקומית בתוך Docker** — אין שם שום "דמה", רק צריך לתת להם סיסמאות.
> ה"דמה" היחיד שדורש מפתח חיצוני אמיתי כדי להיעלם = **Gemini + Google OAuth**.

---

## איך מתחילים

1. להעתיק את התבנית:
   ```powershell
   Copy-Item infra/.env.example infra/.env
   ```
   (הקובץ `infra/.env` הוא git-ignored — לעולם לא נכנס ל-git.)
2. למלא בו את הערכים מהטבלה למטה (לייצר את האקראיים עם הגנרטורים).
3. להריץ: דאבל-קליק על `run.bat`.

> ⚠️ `run.bat` מייצר אוטומטית `.env` עם ערכים אקראיים אם הוא חסר — אבל הוא **לא** ממלא את
> המפתחות החיצוניים (Gemini, Google). אותם חייבים למלא ידנית כדי שה-AI וההתחברות יעבדו.

---

## הגנרטורים (להעתקה ישירה)

| מה מייצרים | הפקודה |
|---|---|
| **מפתח Fernet** (להצפנה — `PII_DATA_KEY`, `WA_CRED_KEK`) | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` |
| **טוקן/סוד אקראי** (כל השאר) | `python -c "import secrets;print(secrets.token_urlsafe(32))"` |

(בלי Python מותקן: `openssl rand -base64 32` נותן סוד אקראי טוב לכל מה שאינו Fernet.)

---

## חובה — בלי אלה המערכת לא עולה (fail-closed) ⛔

| משתנה | מה זה | מאיפה משיגים / איך מייצרים |
|---|---|---|
| `GATEWAY_API_TOKEN` | הטוקן המשותף בין הגייטוויי ל-backend (header על כל webhook) | גנרטור טוקן |
| `POSTGRES_USER` / `POSTGRES_DB` | שם המשתמש + שם מסד הנתונים של Postgres המקומי | אתה ממציא (למשל `bizzup` / `bizzup`) |
| `POSTGRES_PASSWORD` | סיסמת ה-superuser של Postgres המקומי (Docker) | גנרטור טוקן |
| `REDIS_PASSWORD` | סיסמת ה-Redis המקומי (Docker) | גנרטור טוקן |
| `APP_DB_PASSWORD` | סיסמת ה-role `app_role` (שדרכו ה-backend מתחבר — כך RLS חל) | גנרטור טוקן |
| `GATEWAY_DB_PASSWORD` | סיסמת ה-role `gateway_role` (גישה רק לטבלת התכשיט) | גנרטור טוקן |
| `PII_DATA_KEY` | מפתח **Fernet** — מצפין PII של לידים (טלפון/שם/תשובות) | גנרטור Fernet |
| `WA_CRED_KEK` | מפתח **Fernet** — ה-KEK של creds הוואטסאפ (תכשיט הכתר) | גנרטור Fernet |
| `PHONE_HMAC_KEY` | מפתח HMAC לחיפוש לפי "טביעת-אצבע" של טלפון | גנרטור טוקן |
| `SESSION_SECRET` | סוד שכבת ה-sessions | גנרטור טוקן |
| `GOOGLE_CLIENT_ID` | מזהה ה-OAuth client של Google (התחברות) | **Google Cloud Console** → APIs & Services → Credentials → OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | הסוד של אותו OAuth client | אותו מסך ב-Google Cloud Console |
| `GOOGLE_REDIRECT_URI` | כתובת ה-callback של ההתחברות | בדב: `http://localhost:5173/auth/callback` — להוסיף אותה ל-"Authorized redirect URIs" ב-Console |
| `GEMINI_API_KEY` | מפתח ה-AI (בונה הבוט + הודעת הפתיחה) — **עכשיו חובה ל-AI אמיתי** | **Google AI Studio** → Get API key (`gemini-3.1-flash-lite`) |

> 🔑 **שני המפתחות החיצוניים האמיתיים** הם `GOOGLE_CLIENT_ID/SECRET` (מ-Google Cloud Console) ו-`GEMINI_API_KEY`
> (מ-Google AI Studio). כל השאר אתה מייצר לבד עם הגנרטורים. כל ה-DB/Redis רצים אמיתיים מקומית ב-Docker.
>
> 🐳 **מה ש-Docker בונה לבד — אתה לא ממלא אותם:** `DATABASE_URL` (מורכב מ-`APP_DB_PASSWORD`+`POSTGRES_DB`),
> `GATEWAY_DATABASE_URL` (מ-`GATEWAY_DB_PASSWORD`), ו-`REDIS_URL` (מ-`REDIS_PASSWORD`). זו הסיבה שהרשימה
> נראית קצרה — אתה ממלא ~15 ערכים, ו-Docker מרכיב מהם את כתובות החיבור המלאות.

---

## אופציונלי — יש ברירת מחדל, אפשר לדלג ⚙️

| משתנה | מה זה | מתי למלא |
|---|---|---|
| `ADMIN_EMAILS` | רשימת אימיילים שמקבלים גישת בק-אופיס מנהל (מופרדים בפסיק). ריק = אין מנהלים (לא fail-closed) | למלא `oyc3333@gmail.com` כדי לראות את לשונית "ניהול" |
| `GOOGLE_CALENDAR_REDIRECT_URI` | callback נפרד לחיבור יומן Google (M11) — אם לא מוגדר, הפיצ'ר כבוי והאפליקציה עדיין עולה | רק אם רוצים סנכרון יומן; בדב: `http://localhost:5173/api/google/callback` (להוסיף ל-Console) |
| `PUBLIC_BASE_URL` | בסיס ה-URL הציבורי (לקישורי תורים/ביטול) | ברירת מחדל מתאימה לדב; לשנות רק בפרודקשן |
| `GATEWAY_BASE_URL` | היכן ה-backend מוצא את הגייטוויי (לשליחת הודעות) | ברירת מחדל = שם השירות ב-Docker; לשנות רק בהרצה לא-רגילה |
| `VITE_BACKEND_URL` | כתובת ה-backend שה-frontend פונה אליה | ברירת מחדל `http://localhost:8000` — בדב לא נוגעים |
| `BACKEND_WEBHOOK_URL` | היכן הגייטוויי שולח הודעות נכנסות | ברירת מחדל = שירות ה-backend ב-Docker |
| `APP_ENV` / `LOG_LEVEL` | סביבת הרצה + רמת לוג | ברירת מחדל `dev` / `INFO` |

---

## הגדרת Google Console + מקורות חיצוניים 🌐

מעבר למשתני הסביבה — יש דברים שצריך **לרשום בקונסולות חיצוניות**, אחרת ההתחברות תיכשל
(`redirect_uri_mismatch`). ⚠️ **לוואטסאפ אין שום webhook לרשום** — אנחנו על Baileys/QR (לא Meta Cloud API),
אז מתחברים בסריקת QR, וה-`/webhook/whatsapp` הוא **פנימי** (gateway→backend, מאובטח ב-`GATEWAY_API_TOKEN`),
לא נחשף לאף שירות חיצוני.

### Google Cloud Console (חובה להתחברות)
**1. OAuth client (Web application) → Authorized redirect URIs:**

| כתובת (בדב) | בשביל | חובה? |
|---|---|---|
| `http://localhost:5173/auth/callback` | התחברות (login) | **חובה** — בלי זה אין כניסה |
| `http://localhost:5173/api/google/callback` | חיבור יומן Google | רק אם משתמשים ביומן |

**2. Authorized JavaScript origins:** `http://localhost:5173`.
**3. OAuth consent screen:** scopes `openid` · `email` · `profile` (התחברות) + `calendar.events` (רק ליומן).
כל עוד האפליקציה במצב **"Testing"** — חובה להוסיף את האימייל שלך כ-**Test user**, אחרת Google חוסם את ההתחברות.
**4. Enable APIs:** להפעיל **"Google Calendar API"** — רק אם משתמשים ביומן (להתחברות רגילה לא צריך).

מ-(1) לוקחים את ה-Client ID + Secret → `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

### Google AI Studio
ליצור API key → `GEMINI_API_KEY`. אין callback / webhook.

### בפרודקשן (בהמשך, עם דומיין אמיתי)
להחליף `localhost` בכתובת ה-`https://` האמיתית **גם** במשתני הסביבה (`GOOGLE_REDIRECT_URI` וכו') **וגם**
ברשימת ה-redirect URIs / origins ב-Console, ולהעביר את ה-consent screen מ-"Testing" ל-"Published".

---

## כללי ברזל 🛡️
- **אסור** ערכי "change-me" / ברירות-מחדל קבועות לסודות — לייצר ערכים טריים בעלי אנטרופיה גבוהה.
- **אסור** למחזר ערכים ישנים מ-`..\last_bo\.env` — הם נחשבים מודלפים.
- התבניות (`.example`) **לא** מכילות סודות אמיתיים. רק `.env` (git-ignored) מחזיק ערכים אמיתיים.
- בפרודקשן הערכים מגיעים מ-AWS Secrets Manager / KMS — לא מקובץ.
