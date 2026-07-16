# 0019 — M15: Repo & file-organization cleanup (clean monorepo)

> סטטוס: **אושר (monorepo), ממתין ל‑go לביצוע** · תאריך: 2026-06-23.
> מטרה: סדר ויזואלי מלא בקבצים — **בלי שום שינוי התנהגות בקוד**. בחירה נעולה: **ריפו אחד מסודר**
> (`omer-cohenn/ManBuizz`), 5 תחומים ברורים, READMEs + מפת מבנה + פיצול קבצים ארוכים. לא פיצול לפולירפו.

## הסיפור (בן 5)
ארון אחד עם הכל בפנים — לא קונים ארונות חדשים, רק מדביקים מדבקות ברורות, שמים דף הסבר בכל מגירה, ותולים מפה על הדלת. אותם דברים בדיוק, רק שמוצאים הכל בשנייה.

## ההחלטה: monorepo (לא polyrepo)
מפתח יחיד → ריפו אחד מנצח: commit אטומי חוצה‑שכבות, docker-compose ממשיך לעבוד, חוזים משותפים במקום אחד, תקורה נמוכה, הפיך. הפיצול ל‑5 ריפוז (מה ש‑Omer שקל) נדחה — כבד ומסוכן ליחיד. ה"5 תחומים" ממומשים כ**תיקיות ברורות** בריפו אחד.

## המצב היום (עובדות)
- GitHub: ריפו אחד `omer-cohenn/ManBuizz` (monorepo).
- שורות קוד: backend/app 10,915 · backend/tests 18,039 · frontend/src 14,569 · supabase 2,483 · gateway/src 853 · infra 283 · **סך קוד ≈ 46,973** · docs 8,329.
- אבטחה: `.env`/`.env.*` + `gateway/auth` ב‑gitignore; **אין secret/creds ב‑git** (מאומת).

## אילוץ‑על
**אפס שינוי התנהגות.** הזזת קבצים / פיצול מודולים / README / docs / .gitignore — מותר. עדכון נתיבי import + build config שנובע מהזזה — מכני, לא לוגי. **רשת ביטחון:** חבילת **287 הבדיקות** + frontend build חייבות לעבור זהה אחרי כל שלב.

## תוכנית הסדר
1. `STRUCTURE.md` בשורש — מפת הריפו + 5 התחומים + "מאיפה מתחילים".
2. README בכל תחום: `backend/`, `gateway/`, `frontend/`, `infra/`, `supabase/`, `docs/`.
3. רענון `infra/.env.example` + `.env.example` (כולל `GEMINI_API_KEY`, `ADMIN_EMAILS`) + מסמך "מה למלא ל‑API אמיתי".
4. פיצול הקבצים הארוכים לתת‑מודולים מתועדים (re-export יציב, imports לא נשברים):
   `backend/app/services/booking.py` (1147) · `frontend/src/pages/LandingPage.tsx` (860) · `backend/app/api/admin.py` (776) · `gateway/src/index.js` (646) · `backend/app/services/leads.py` (573) · `frontend/src/pages/WhatsAppPage.tsx` (554).
5. סידור `backend/tests` לתת‑תיקיות ברורות (strict / narrated / isolation) — העברה בלבד.
6. הרצת 287 הבדיקות + build → הוכחת אפס רגרסיה.

## עשרת ה‑Goals
ראה צ'אט (1–10): STRUCTURE.md · READMEs · env refresh + מסמך מילוי · פיצול booking · פיצול admin+leads · פיצול gateway index.js · פיצול LandingPage+WhatsAppPage · סידור tests · 287 ירוק + build · checkpoint + עדכון STATUS/CLAUDE.

## הסוכנים
backend-refactor (booking/admin/leads/tests + READMEs) → frontend-refactor (pages + README) → gateway+infra+docs (index.js + READMEs + STRUCTURE.md + env) → QA (test-runner: 287 + build, אפס רגרסיה). אזורים נפרדים → אפשר מקבילי חלקית; QA אחרון.

## Workflow
refactor באזורים (אפשר מקבילי) → QA מריץ את כל החבילה + build → אימות אצלי שהכל זהה → checkpoint + עדכון STATUS/CLAUDE.

## אבטחה ו‑.env
secrets כבר ב‑gitignore (מאומת). מסמך "מה למלא ל‑API אמיתי" (חובה/אופציונלי + גנרטורים) — ה"דמה" היחיד שצריך מפתח אמיתי כדי להעלים = Gemini + Google OAuth; DB/Redis אמיתיים מקומית ב‑Docker.

## גישת השמות (נעול)
**שומרים את השמות הטכניים** (`api`/`services`/`models`/`core`/`db` — קונבנציה אוניברסלית; לשנותם שובר imports ומבלבל כל מפתח/סוכן). במקום זה **"שלטים בעברית":** `STRUCTURE.md` (מפת כל 5 התחומים, שם‑טכני↔עברית), `README.md` בכל תחום, ושורת הסבר בעברית בראש כל קובץ. כך מבינים במבט — בלי לשבור כלום.

## עדכון כל הדוקס של קלוד
- 🆕 `STRUCTURE.md` (מפה ראשית) · `ENV_SETUP.md` ("מה למלא ל‑API אמיתי") · README ×6 (backend/gateway/frontend/infra/supabase/docs).
- ✏️ `CLAUDE.md` — סעיף "Folder map" מיושן (מציג `whatsapp-gateway/` ותיקיות ריקות) → לעדכן למבנה האמיתי + הפניה ל‑STRUCTURE.md.
- ✏️ `README.md` (שורש) · `docs/STATUS.md` (רשומת M15) · רענון `infra/.env*.example`.

## הסוכנים (8 — במסגרת 6–9 שביקש Omer)
| # | סוכן | המשימה | תלות |
|---|---|---|---|
| A | backend-services | פצל `services/booking.py`→`booking/` + `services/leads.py`→`leads/` (re-export יציב) + שורת‑הסבר עברית בראש קבצי services | — |
| B | backend-api | פצל `api/admin.py`→`api/admin/` (businesses/analytics/crm + __init__ מרכיב router) + שורות‑הסבר ל‑api | — |
| C | backend-tests | סדר ל‑`tests/{strict,narrated,isolation}` + פצל קבצי בדיקה >500 + עדכן conftest + ה‑`.bat` | A,B |
| D | frontend | פצל `LandingPage.tsx`→`components/landing/*` + `WhatsAppPage.tsx`→`components/whatsapp/*` + README + headers | — |
| E | gateway | פצל `gateway/src/index.js`→`socket/webhook/routes` + thin index + README | — |
| F | docs-maps | `STRUCTURE.md` + 6 README + `ENV_SETUP.md` + רענון env + עדכון `CLAUDE.md`/`README.md`/`STATUS.md` | A,B,D,E |
| G | QA | להריץ 287 בדיקות + frontend build + boot של gateway → אפס רגרסיה; לתקן שבירת import | A–F |
| H | security | לוודא שאף secret לא נכנס ל‑git, .gitignore עדיין מכסה, התבניות נקיות | A–F |

## Workflow
פיצולים לפי תחום (A/B/D/E — תיקיות נפרדות) → C (tests, אחרי A/B) → F (docs, אחרי הקוד) → G ∥ H (קוראים בלבד) → אימות אצלי → checkpoint יחיד.
כלל זהב: **אף סוכן לא מקמיט** — אני מקמיט בסוף, אחרי שה‑287 ירוקות.

## תוצאה
(יתמלא אחרי הביצוע: pass counts, אפס רגרסיה, commit.)
