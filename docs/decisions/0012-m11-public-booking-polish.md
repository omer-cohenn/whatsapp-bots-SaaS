# 0012 — M11.1: דף הזמנה ציבורי בעיצוב הפרוטוטייפ

> סטטוס: **מאושר, בבנייה** · תאריך: 2026-06-21 · קודם: 0011 (M11 booking). תוכנית מלאה ב‑plan file (אושר ע"י Omer).

## ההחלטה
לבנות מחדש את דף ההזמנה הציבורי לפי הפרוטוטייפ שאושר (`docs/prototype/bizzup-prototype.html` + סקיצת React),
ולהוסיף לכל שירות **תיאור** ו**מחיר** (אופציונלי), ולעסק **הודעת פתיחה** שניתן לנסח עם **AI** ולראות בתצוגה
מקדימה חיה בהגדרות.

## החלטות נעולות (Q&A)
1. **בלי תמונה** כרגע (אין אחסון קבצים) — כרטיס שירות = כותרת + תיאור (+מחיר). תמונות בהמשך.
2. **מחיר אופציונלי** (₪). ריק → מוצג **"ללא עלות"**.
3. **welcome_message** לכל עסק (ידני/AI), מוצג בראש הדף.
4. **תצוגה מקדימה חיה** בהגדרות (אותו קומפוננטת BookingFlow עם טיוטה).

## דאטה (מיגרציה 0011)
- `ALTER TABLE services ADD COLUMN IF NOT EXISTS description text;`
- `ALTER TABLE services ADD COLUMN IF NOT EXISTS price int;` (nullable; ₪; ≥0)
- `ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS welcome_message text;`
(אדיטיבי/אידמפוטנטי; RLS+grants הקיימים מכסים עמודות חדשות.)

## API (שינויים)
- `/api/services[/{id}]` (GET/POST/PATCH) + `description`,`price`.
- `/api/booking/settings` (GET/PUT) + `welcome_message`.
- `GET /api/book/{slug}/services` → לכל שירות `description`,`price` + `welcome_message` ברמת התשובה.
- **חדש** `GET /api/book/{slug}/availability?service_id&from&to` → `{dates:[YYYY-MM-DD]}` (ימים עם ≥1 משבצת; טווח חסום ≤62 יום).
- **חדש** `POST /api/booking/welcome/generate` (gated) → `{message}` (Gemini `gemini-3.1-flash-lite`, validate‑at‑use 503/502).

## פרונט
`BookingFlow` חדש (לפי הפרוטוטייפ): hero+welcome, כרטיסי שירות (כותרת/תיאור/מחיר|"ללא עלות", בלי תמונה),
לוח חודשי מותאם עם נקודות זמינות (מ‑availability), בחירת שעה, סיכום, אישור. `PublicBookingPage` עוטף עם
נתונים אמיתיים; ההגדרות מריצות אותו כ‑preview. `ServicesEditor` + תיאור/מחיר. `BookingSettingsPanel` +
"הודעת פתיחה" (textarea + "נסח עם AI") + תצוגה מקדימה. שימוש ב‑Icon הקיים (בלי lucide).

## אבטחה
AI gated + GEMINI לא בלוג + שגיאות גנריות; public availability slug‑verified + טווח חסום; description/price/
welcome_message חסומי‑אורך/טווח; בלי שינוי בבידוד.

## סוכנים/Workflow
data → backend → frontend → (QA ‖ security) → אימות בלולאה הראשית → checkpoint.
