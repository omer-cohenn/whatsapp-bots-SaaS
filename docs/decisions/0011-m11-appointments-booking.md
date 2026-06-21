# 0011 — M11: מערכת קביעת תורים ופגישות (Appointments & Booking)

> סטטוס: **מאושר, בבנייה** · תאריך: 2026-06-21 · קודם: 0004 (MVP scope), 0006 (Redis live-chat), 0009/0010.
> התוכנית המלאה (גואלים לכל סוכן + workflow עם שערים) אושרה ע"י Omer ושמורה ב‑plan file.

## ההחלטה
לבנות מערכת קביעת תורים אמיתית — מתקנת את 3 החטאים של last_bo: **B7** (השיחה לא באמת מזמינה), **C4**
(IDOR בין‑עסקי), **M5** (PII גלוי). הכל במיילסטון אחד.

## החלטות נעולות (Q&A עם Omer)
1. **דף הזמנה ציבורי** (הבוט שולח קישור; הלקוח בוחר בדף אינטרנט).
2. **אזור זמן קבוע `Asia/Jerusalem`** (zoneinfo, בלי pytz).
3. **כמה שירותים לעסק**, לכל שירות משך משלו.
4. **שעות פעילות מפוצלות** — לכל יום רשימת טווחים.
5. **כולל הכל:** חוקי זמינות (min_notice/buffer/max_days_ahead) · ביטול/שינוי ע"י הלקוח · תזכורות/אישורים בוואטסאפ (תור `outbox`, נשלח עם M6).
6. **Google Calendar אופציונלי**: יצירת/עדכון/מחיקת אירועים ביומן בעל העסק + הלקוח כמשתתף לפי מייל. **בלי free/busy**.
7. **Google Meet = מתג גלובלי לעסק**.
8. **איחוד עם הליד** (כמו M9/M10): הזמנה יוצרת/מקשרת ליד.

## דאטה (מיגרציות 0008 טבלאות + 0009 RLS/grants)
- `booking_settings` (timezone, working_hours jsonb=יום→רשימת {s,e}, min_notice_minutes, buffer_minutes, max_days_ahead, meet_enabled, slug ייחודי לא‑נחיש).
- `services` (name, duration_minutes, active).
- `bookings` (service_id, lead_id, client_name/phone/email🔒, scheduled_at UTC, duration_minutes, status, notes🔒, google_event_id, meet_link, cancel_token, is_test, key_version).
- `google_credentials` (business_id PK, refresh_token🔒 KEK, scope, connected_email).
- כל הטבלאות: RLS FORCE + p_tenant_isolation + grants ל‑app_role; PII מוצפן באפליקציה.

## API
- admin (תחת /api, session): `/api/booking/settings`, `/api/services[/{id}]`, `/api/bookings[/{id}]`, `/api/google/{connect,callback,disconnect}`.
- ציבורי (ללא session): `GET /api/book/{slug}/services|slots`, `POST /api/book/{slug}`, `POST /api/book/{slug}/{cancel|reschedule}/{cancel_token}`.

## ספריות
- בקאנד: `google-auth`, `google-auth-oauthlib`, `google-api-python-client`, `zoneinfo` (stdlib).
- פרונט: `react-day-picker`.

## אבטחה (M11)
- PII לקוח מוצפן (תיקון M5); refresh_token מוצפן KEK; C4 בבדיקות הבידוד; נתיב ציבורי עם slug‑verify + ולידציה + rate‑limit + מניעת כפילות + cancel_token לא‑נחיש; אין סודות/PII/טוקן בלוג.

## תלות
- M6 (וואטסאפ) לא מחובר → שליחת קישור/אישורים/תזכורות בתור `outbox`, נדלקת עם M6.
- Google: מפתחות CLIENT_ID/SECRET קיימים (מה‑login); דרוש להוסיף scope `calendar.events` + redirect URI לקולבק היומן ב‑Google Console. עד אז — אינטגרציה נבנית אמיתית, נבדקת עם mock.

## סוכנים + Workflow
6 סוכנים: data → backend-core → google(זמני) → frontend → (QA ‖ security). שערי‑בדיקה G1–G5; QA+אבטחה
"בודקים סוכן ומחזירים לתיקון" עד ירוק. פירוט מלא (גואלים לכל סוכן) ב‑plan file.
