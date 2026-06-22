# 0016 — M12: Back-Office (platform-operator admin panel)

> סטטוס: **מאושר, בבנייה** · תאריך: 2026-06-22 · קודם: 0002 (multi-tenant), 0005 (auth/data), 0014 (M6a).
> מטרה: פאנל **מנהל‑על** ל‑Omer (מפעיל ה‑SaaS) לראות ולנהל את **כל** העסקים יחד — נפרד מה‑dashboard
> הפר‑עסקי (M7). זה **המקום היחיד שחוצה את חומת הטננטים במכוון**, ולכן דלת נעולה נפרדת שאינה מחלישה
> את הבידוד של כולם.

## הסיפור (בן 5)
Omer הוא בעל **הקניון** (Bizz_up). כל עסק = חנות עם מפתח רק לעצמה (זה M7). ל‑Omer יש **חדר בקרה** עם חלון אל
כל החנויות: מי פתח ומתי, כניסה אחרונה, איזה מנוי, וכמה עמוס (הודעות/לידים/הזמנות). ומשם הוא גם **פועל**:
משנה מנוי, או נועל (משהה) חנות. למפתח של חדר הבקרה — רק ל‑Omer יש גישה.

## החלטות נעולות
1. **מנוי = ידני** (Free/Basic/Pro + active/suspended/cancelled), מנוהל מהפאנל. אין סליקה — מתוכנן שיתחבר Stripe בעתיד.
2. **מעקב שימוש מתחיל מעכשיו** — מונים בלבד (אפס תוכן). היסטוריה לא ניתנת לשחזור (הצ'אט אפמרלי ב‑Redis).
3. **v1 מלא עם פעולות** — שינוי מנוי + השהיה/ביטול. **השהיה משתיקה את הבוט בפועל** (לא רק תווית).
4. **התחזות‑לצפייה (impersonate) נדחית** — הכי מסוכן; לא ב‑v1.
5. זהות admin = `ADMIN_EMAILS` (env, fail-closed, בלי ברירת מחדל). **נבדק חי מול האימייל בכל בקשה** — לא נשמר דגל בסשן (env הוא מקור האמת; שינוי תופס בלי re-login).

## חוזה דאטה קפוא (migrations 0015–0017)

### 0015 — plans + subscriptions + businesses.is_active
- `plans(code PK text, name text, price numeric(10,2) def 0, sort_order int, limits jsonb def '{}', created_at)` — קטלוג גלובלי (אין business_id). זריעה: `free`/`basic`/`pro`.
- `subscriptions(business_id uuid PK→businesses ON DELETE CASCADE, plan_code text→plans def 'free', status text def 'active', started_at, current_period_end timestamptz null, updated_at)`.
- `ALTER TABLE businesses ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true`.
- grants: `plans` → `GRANT SELECT TO app_role` (קטלוג לא רגיש, ללא RLS). `subscriptions` → **אין** CRUD ישיר ל‑app_role; ניגשים רק דרך פונקציות ה‑admin (SD). trigger `set_updated_at` על subscriptions.

### 0016 — usage_daily + admin_audit
- `usage_daily(business_id uuid→businesses ON DELETE CASCADE, day date, metric text, count bigint def 0, PRIMARY KEY(business_id,day,metric))`. **RLS ENABLE+FORCE**, policy `p_tenant_isolation` (USING+WITH CHECK `business_id=current_business_id()`). `GRANT SELECT,INSERT,UPDATE TO app_role` — כל עסק מעדכן **את שלו**.
- מטריקות v1: `msg_in` · `msg_out` · `lead` · `booking` · `login`.
- `admin_audit(id uuid PK, admin_user_id text→users ON DELETE SET NULL, admin_email text, action text, target_business_id uuid, detail jsonb def '{}', created_at)`. נכתב **רק** ע"י פונקציית ה‑SD (שרצה כ‑owner) → אין grant ישיר ל‑app_role.

### 0017 — admin SECURITY DEFINER functions (חוצות‑טננט, EXECUTE ל‑app_role בלבד)
כולן `SECURITY DEFINER`, `SET search_path = public, pg_temp`, `REVOKE ALL FROM PUBLIC` + `GRANT EXECUTE TO app_role`. נקראות **אך ורק** מאחורי שער ה‑admin.
- `admin_overview()` → סך עסקים, פעילים/מושהים/מבוטלים, חדשים 7 ימים, סך לידים (לא‑test), הודעות היום/החודש (סכום usage_daily).
- `admin_list_businesses(p_search text, p_limit int, p_offset int)` → טבלה: `business_id, name, owner_email, created_at, last_login_at, plan_code, status, is_active, leads_count, msgs_30d`.
- `admin_business_detail(p_business_id uuid)` → פרופיל עסק יחיד: זהה לעיל + סטטוס חיבור WhatsApp + ספירות.
- `admin_usage_series(p_business_id uuid, p_from date, p_to date)` → טבלה `(day, metric, count)` לגרפים.
- `admin_set_subscription(p_admin_user_id text, p_admin_email text, p_business_id uuid, p_plan_code text, p_status text)` → upsert ל‑subscriptions, **מסנכרן `businesses.is_active`** (`suspended`/`cancelled`→false, `active`→true), כותב `admin_audit`, מחזיר את השורה החדשה.

## חוזה API קפוא — כל `/api/admin/*` מאחורי `current_admin` (session + admin)
| מסלול | פעולה |
|---|---|
| `GET /api/admin/overview` | KPI כלל‑פלטפורמה |
| `GET /api/admin/businesses?search=&limit=&offset=` | רשימת כל העסקים (חיפוש/דפדוף) |
| `GET /api/admin/businesses/{id}` | פרופיל עסק יחיד |
| `GET /api/admin/businesses/{id}/usage?from=&to=` | סדרת שימוש לגרפים (טווח חסום ≤ ~92 ימים) |
| `PATCH /api/admin/businesses/{id}/subscription` | `{plan_code, status}` → קובע מנוי+סטטוס, כותב audit |
| `GET /api/admin/plans` | קטלוג התוכניות (ל‑dropdown) |
| `GET /api/me` (הרחבה) | מוסיף שדה `is_admin: bool` (מחושב חי מול `ADMIN_EMAILS`) |

## הזרימה
1. **login**: ללא שינוי מבני. `/api/me` ו‑`current_admin` מחשבים `is_admin = (email ∈ ADMIN_EMAILS)` בכל בקשה.
2. **שער admin**: `current_admin` → 403 לכל מי שאינו admin, לפני כל קוד.
3. **קריאה**: ה‑endpoint קורא לפונקציית SD המתאימה (חוצה‑טננט) על חיבור app_role רגיל.
4. **כתיבה (מנוי/השהיה)**: `admin_set_subscription(...)` → מעדכן subscriptions + is_active + audit.
5. **אכיפת השהיה**: צינור הבוט (webhook `_run_bot_turn`) בודק `businesses.is_active` יחד עם `is_published` — עסק מושהה **שותק**.
6. **מונה שימוש**: `usage.bump(business_id, metric)` עושה UPSERT +1 ליום הנוכחי, ב‑best-effort (כשל לא שובר זרימה), בנקודות: הודעה נכנסת/יוצאת (webhook), ליד נוצר (leads), הזמנה (booking), login (callback, בתוך tenant_connection).

## אבטחה ובידוד
- `current_admin` = `ADMIN_EMAILS` (env, fail-closed). זה **גבול האמון** היחיד שמגן על פונקציות ה‑SD החוצות‑טננט — חייב להיות הרמטי. אף `business_id` מהלקוח.
- חומת הטננטים של **כל** העסקים נשארת שלמה; שום RLS לא נחלש. ה‑admin הוא שביל נפרד דרך פונקציות SD צרות.
- פונקציות SD ממוקדות, EXECUTE ל‑app_role בלבד, נקראות **רק** מ‑`/api/admin` (כמו ש‑provision_owner נקרא רק מה‑callback).
- כל פעולת admin → `admin_audit` (שרשרת אחריות).
- `usage_daily` = מספרים בלבד, אפס PII; אין PII/סודות בלוג.
- בדיקה: לא‑admin → 403 מכל מסלול admin; הצבירה לא דולפת עסק A דרך עסק B.

## הסוכנים + המטרות

### 🗄️ סוכן 1 — bizzup-data-builder (migrations 0015–0017)
מקבל: 0003/0004/0005/0009 כדפוס. מחזיר: חתימות הטבלאות והפונקציות = חוזה הדאטה.
1. 0015: plans + subscriptions + `businesses.is_active`, grants, seed free/basic/pro, trigger updated_at.
2. 0016: usage_daily (RLS+FORCE+policy+grant SELECT/INSERT/UPDATE ל‑app_role) + admin_audit.
3. 0017: חמש פונקציות ה‑admin SD, REVOKE PUBLIC + GRANT EXECUTE app_role, search_path מקובע.
4. הכל additive/idempotent (IF NOT EXISTS / CREATE OR REPLACE / DROP POLICY IF EXISTS).
5. `admin_set_subscription` מסנכרן is_active וכותב audit באטומיות.

### ⚙️ סוכן 2 — bizzup-backend-builder
מקבל: חוזה הדאטה, deps.py, me.py, dashboard.py, config.py, webhook.py.
1. `config`: `ADMIN_EMAILS` (CSV→set, fail-closed: ריק = אין מנהלים, מותר).
2. `deps`: `current_admin` (session + email∈ADMIN_EMAILS, אחרת 403).
3. `me.py`: `/api/me` + `is_admin`; router חדש `/api/admin` עם `dependencies=[Depends(current_admin)]`, מאונט תחת `/api`.
4. `api/admin.py` + `models/admin.py`: overview/businesses/detail/usage/plans/set-subscription, קוראים לפונקציות SD.
5. `services/usage.py`: `bump(...)` (UPSERT, best-effort) + חיווט ל‑5 הנקודות.
6. אכיפת השהיה: webhook core בודק is_active לצד is_published.
7. business מהשרת בלבד; אין PII/סודות בלוג; מחזיר חוזה מדויק.

### 🎨 סוכן 3 — bizzup-frontend-builder
מקבל: חוזה ה‑API, App.tsx, AuthContext, types.ts, ui kit.
1. `lib/adminClient.ts` + `admin/types.ts`.
2. `is_admin` ב‑auth types + context; פריט ניווט "ניהול" שמופיע **רק** ל‑admin; routes `/admin*` ב‑AuthGate.
3. דפים: AdminHome (KPI), BusinessesList (טבלה+חיפוש+דפדוף), BusinessDetail (פרופיל + שליטה מנוי/סטטוס + גרפי שימוש). RTL עברית, נגיש.

### ✅ סוכן 4 — bizzup-test-runner (QA)
להרים stack, להריץ migrations, לכתוב+להריץ pytest + בדיקות מסופרות: 403 ללא admin, נכונות aggregation, מונים עולים, השהיה משתיקה את הבוט, audit נכתב, אפס דליפת PII; רגרסיה M2–M11/M6a; לסמן STATUS.

### 🛡️ סוכן 5 — security review (במקביל ל‑QA)
לבקר את השטח החוצה‑טננט: שער ה‑admin, גבול האמון של ADMIN_EMAILS, grants, PII/סודות, ה‑audit. מחזיר ממצאים + verdict.

## Workflow
data → backend → frontend (טורי) → QA ∥ security (מקבילי, קוראים בלבד) → אימות+תיקון ב‑main loop → checkpoint + עדכון STATUS/זיכרון.

## תוצאה (2026-06-22)
**נבנה, אומת, ומקומיט.** QA: `test_m12.py` 26/26 + narrated 13/13 + negative-control בידוד פעיל; חבילת strict
מלאה **257 passed**; M2 12/12 (אפס רגרסיה). אבטחה: verdict **SHIP** (0 CRITICAL/HIGH). commits: חצי ה‑backend/data
ב‑`4633c9c` (נדחף ל‑origin, מעורבב עם rebrand דף הנחיתה 0015), ההשלמה ב‑`e304f5f` (לוקאלי, טרם נדחף).

### Security follow-ups (לא חוסמים — לשלב ההקשחה ל‑production / M6b/AWS)
- **MED-1:** `admin_set_subscription` סומך על שער ה‑app בלבד לזהות ה‑admin (כמו `provision_owner`). לשמור שהיא נקראת **רק** מ‑`api/admin.py`; בעתיד לשקול קשירת זהות ה‑admin בצד‑DB (session GUC) במקום ארגומנט.
- **LOW-1:** `business_id` ב‑path מאומת כמחרוזת ≤64; ערך לא‑UUID נדחה רק ב‑cast של Postgres (→404). לשקול אימות UUID בקצה (שים לב: הטסט הנוכחי מצפה ל‑404 על id פגום — שינוי ל‑422 ידרוש עדכון טסט).
- **LOW-2:** ה‑JSON log formatter מקדם כל שדה `extra`; אין דליפה היום, אבל כדאי allow-list אמיתי לפני שיצטברו שדות.
- **LOW-3:** דליי קוסמטי ב‑`admin_overview` — דליי active נספר לפי `businesses.is_active`, suspended/cancelled לפי שורות subscription; עקבי כל עוד `admin_set_subscription` הוא הכותב היחיד.
