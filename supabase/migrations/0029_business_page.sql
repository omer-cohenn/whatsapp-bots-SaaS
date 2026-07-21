-- ============================================================================
-- 0029_business_page.sql — M20: עמוד עסקי מעוצב (decision 0028)
-- ----------------------------------------------------------------------------
-- מה הקובץ הזה עושה, ולמה:
--
-- (1) מרחיב את `booking_settings` בשדות של "העמוד העסקי" — כותרת משנה, תיאור,
--     כתובת, טלפון, WhatsApp, אינסטגרם, Waze, לוגו, וערכת הצבעים. כל השדות
--     nullable ואדיטיביים בלבד: עסק קיים ממשיך לעבוד בדיוק כמו קודם, ושדה ריק
--     פירושו שהאלמנט פשוט לא מוצג בעמוד (כלל ה-"שדה ריק ⇒ אין כפתור").
--
-- (2) יוצר `business_images` — רשומת מטא-דאטה לכל תמונת גלריה. הבייטים עצמם
--     יושבים על הדיסק של השרת (volume בשם `business_images`, מוגש ע"י Caddy),
--     ולא ב-Postgres ולא ב-R2. הסיבה: תמונות הגלריה הן תוכן שיווקי פומבי, בעוד
--     ש-R2 (`botik-files`) מחזיק קבצי לידים מוצפנים; הרשאת "ציבורי" ב-R2 היא
--     ברמת הדלי ולא התיקייה, כך שפתיחת הדלי הייתה חושפת גם PII של לקוחות.
--
-- (3) מוחק את `services.image_url` (M11.2) — הגלריה מחליפה אותה.
--
-- ---------------------------------------------------------------------------
-- 🔓 חריגה מודעת מכלל ההצפנה של הפרויקט — קראו לפני שמתקנים:
--   `address` / `phone` / `whatsapp` / `instagram_url` / `waze_url` / `logo_url`
--   נשמרים כ-PLAINTEXT ולא דרך encrypt_pii(), בניגוד ל-`bookings.client_phone`
--   ולשאר עמודות ה-🔒 בסכימה. זו לא שכחה: אלה פרטי הקשר של **העסק עצמו**,
--   שכל מטרתם היא להתפרסם בעמוד פומבי לכל מי שיש לו את ה-slug. הצפנת מידע
--   שנועד להתפרסם לא מגנה על אף אחד, ורק מכריחה כל צפייה בעמוד לעבור פענוח
--   בשרת. PII של **לקוח** נשאר מוצפן כתמיד.
-- ---------------------------------------------------------------------------
--
-- IDEMPOTENCY: לרץ המיגרציות אין ledger — הוא מריץ כל קובץ בכל boot מחדש.
-- לכן: ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS /
-- CREATE INDEX IF NOT EXISTS / DROP POLICY IF EXISTS לפני CREATE POLICY /
-- REVOKE+GRANT (אידמפוטנטיים מטבעם) / DROP COLUMN IF EXISTS.
-- ============================================================================

-- ----- (1) booking_settings — שדות העמוד העסקי ------------------------------ --
-- `booking_settings` היא כבר 1:1 עם עסק (PK = business_id) ומחזיקה את ה-slug
-- ואת welcome_message, כך שאין צורך בטבלה חדשה. RLS + grants ל-app_role כבר
-- הוגדרו ב-0009 וחלים אוטומטית על כל עמודה חדשה — אין כאן שינוי אבטחה.
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS tagline       text;  -- שורה קצרה מתחת לשם העסק
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS about         text;  -- פסקת תיאור ארוכה יותר
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS address       text;  -- 🔓 כתובת העסק (פומבי, לא מוצפן)
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS phone         text;  -- 🔓 מפעיל את כפתור החיוג
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS whatsapp      text;  -- 🔓 מפעיל את כפתור ה-WhatsApp
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS instagram_url text;  -- 🔓 קישור פומבי
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS waze_url      text;  -- 🔓 קישור פומבי
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS logo_url      text;  -- הלוגו העגול בראש ההירו
ALTER TABLE booking_settings ADD COLUMN IF NOT EXISTS page_theme    jsonb NOT NULL DEFAULT '{}'::jsonb;  -- פלטה + radius + font

COMMENT ON COLUMN booking_settings.address IS
  'פרטי קשר פומביים של העסק — plaintext במכוון, לא encrypt_pii. ראו כותרת 0029.';
COMMENT ON COLUMN booking_settings.phone IS
  'פרטי קשר פומביים של העסק — plaintext במכוון, לא encrypt_pii. ראו כותרת 0029.';
COMMENT ON COLUMN booking_settings.whatsapp IS
  'פרטי קשר פומביים של העסק — plaintext במכוון, לא encrypt_pii. ראו כותרת 0029.';
COMMENT ON COLUMN booking_settings.page_theme IS
  'ערכת העיצוב הנבחרת של העמוד (פלטת צבעים, רדיוס, פונט). {} = ברירת המחדל.';

-- ----- (2) business_images — רשומה אחת לכל תמונת גלריה ---------------------- --
-- `storage_path` הוא נתיב יחסי בלבד בתוך ה-volume: {business_id}/{uuid}.{ext}.
-- שם הקובץ נוצר תמיד אצלנו (uuid) והסיומת נגזרת מהסוג שזוהה מהתוכן — לעולם לא
-- משם שהדפדפן שלח. זה מה שסוגר path traversal ו-.html מחופש לתמונה.
-- ON DELETE CASCADE מוחק את הרשומה כשעסק נמחק, אבל **לא** את הקובץ מהדיסק —
-- מסלול המחיקה באפליקציה אחראי למחוק את התיקייה (חוב ידוע, ראו decision 0028).
CREATE TABLE IF NOT EXISTS business_images (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id  uuid NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
  storage_path text NOT NULL,                        -- {business_id}/{uuid}.{ext} — יחסי ל-volume
  caption      text,                                 -- כיתוב קצר של הבעלים ("סדנת שוקולד")
  sort_order   int  NOT NULL DEFAULT 0,              -- סדר התצוגה בגלריה
  mime_type    text NOT NULL,                        -- הסוג שזוהה מהתוכן, לא המוצהר
  size_bytes   bigint NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE business_images IS
  'מטא-דאטה של תמונות הגלריה הפומבית. הבייטים על דיסק השרת (volume business_images), לא ב-DB ולא ב-R2. תוכן שיווקי פומבי — לא מוצפן במכוון.';

-- שליפת הגלריה של עסק לפי סדר התצוגה — המסלול היחיד שקוראים בו את הטבלה.
CREATE INDEX IF NOT EXISTS ix_business_images_business_sort
  ON business_images (business_id, sort_order);

-- ----- (3) RLS — חומת ה-tenant (סגנון הבית: ENABLE + FORCE + policy) -------- --
-- FORCE גורם ל-RLS לחול גם על בעל הטבלה (הגנה לעומק). רץ המיגרציות הוא superuser
-- ולכן עוקף RLS — כך הקובץ הזה בכלל מצליח לרוץ; האפליקציה מתחברת כ-app_role,
-- שם ה-policy חיה ו-`current_business_id()` מגיע מ-`SET app.business_id`.
ALTER TABLE business_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_images FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS p_tenant_isolation ON business_images;
CREATE POLICY p_tenant_isolation ON business_images
  USING (business_id = current_business_id())        -- קריאה: רק התמונות שלי
  WITH CHECK (business_id = current_business_id());  -- כתיבה: רק לתוך ה-tenant שלי

-- ----- (4) Grants — app_role בלבד ------------------------------------------- --
-- אפס הרשאות ל-gateway_role, במכוון: ה-gateway של WhatsApp לא קורא ולא כותב
-- תמונות גלריה. כל מסלולי התמונות (בעלים + העמוד הפומבי) רצים על app.state.pg_pool
-- כ-app_role. REVOKE ALL קודם, כדי שהקובץ יהיה אידמפוטנטי וגם יתקן הרשאה שנוספה
-- בטעות מחוץ למיגרציות.
REVOKE ALL ON business_images FROM app_role, gateway_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON business_images TO app_role;

-- ----- (5) מחיקת services.image_url — במכוון ובלתי הפיך ---------------------- --
-- זו העמודה של M11.2 (0012_service_image.sql) שהחזיקה data: URL מלא של תמונת
-- שירות. הגלריה של M20 מחליפה את הפיצ'ר; החלטת Omer, 2026-07-21 (decision 0028).
-- ⚠️ DROP COLUMN מוחק את התוכן לצמיתות — אין כאן גיבוי ואין דרך חזרה. זה מכוון.
-- IF EXISTS כדי שהריצה השנייה ואילך תהיה no-op שקט.
ALTER TABLE services DROP COLUMN IF EXISTS image_url;
