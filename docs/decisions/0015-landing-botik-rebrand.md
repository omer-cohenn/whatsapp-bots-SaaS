# 0015 — M12: new "בוטיק" landing page + brand rename

> סטטוס: **מאושר, בבנייה** · תאריך: 2026-06-22 · קודם: דף הנחיתה הישן (components/landing/*).
> מחליפים את דף הנחיתה הקיים בדף החדש ש‑Omer בנה ("בוטיק", `landing_page_Botik.jsx`), וממתגים מחדש Bizz_up→בוטיק.

## הסיפור
מבקר נכנס ל‑`/` → רואה את דף "בוטיק" החדש (hero מונפש, נתונים, איך עובד, יכולות, תחומים, מסלולים, FAQ, CTA) →
לוחץ "התחברות"/"התחילו" → `/auth/google` → דשבורד. השם בכל ה‑UI הופך ל"בוטיק".

## החלטות נעולות (Q&A 2026-06-22)
1. **עיצוב = להשאיר 1:1** — ה‑CSS המוטמע של הדף נשמר כמו שהוא (חריג חד‑פעמי מכלל ה‑Tailwind, מבודד לדף).
2. **מותג = "בוטיק" בכל ה‑UI** — אבל רק **טקסט שהמשתמש רואה** (frontend + `<title>` + README). **לא** נוגעים במזהים טכניים: `name: bizz_up` (Docker), שם התיקייה, env, שמות קוד, docs/decisions/CLAUDE.md.
3. **קישורים = כמו היום** — התחברות/התחילו/מסלולים/CTA → `/auth/google`; פוטר → `/terms`,`/privacy`,`/accessibility`.
4. **רכיבים ישנים = למחוק** — 9 קבצי `components/landing/*` (רק `LandingPage.tsx` ייבא אותם).

## היקף (frontend בלבד — אין data/backend)
| קובץ | פעולה |
|---|---|
| `pages/LandingPage.tsx` | מוחלף בדף "בוטיק" (port ל‑.tsx + types, `<style>{CSS}</style>` נשמר 1:1, default export `LandingPage`) |
| `components/landing/{LandingHeader,Hero,StatsStrip,HowItWorks,Features,UseCases,Pricing,Faq,CtaSection}.tsx` | נמחקים |
| `index.html`, `OwnerHeader`, `DashboardLayout`, `SiteFooter`, `LoginPage`, `TermsPage`, `LegalPage`, `AccessibilityPage`, `README.md` | "Bizz_up"→"בוטיק"/"Botik" |
| `App.tsx`, `Home.tsx`, routing | ללא שינוי |

## חיווט הקישורים
- כפתורי התחברות/התחלה/מסלולים/CTA סופי → `<a href="/auth/google">` (ניווט מלא — זה route של ה‑backend).
- פוטר: תנאי שימוש→`/terms`, פרטיות→`/privacy`, נגישות→`/accessibility` (react-router `Link`).

## Goals
1. port → `LandingPage.tsx` (.tsx+types, CSS 1:1). 2. חיווט הקישורים. 3. a11y מינימלי ל‑jsx‑a11y (SVG דקורטיבי `aria-hidden`, אין `href="#"`). 4. מחיקת 9 הרכיבים הישנים. 5. מיתוג "בוטיק" (~10 מקומות + `<title>`). 6. typecheck+lint+build נקי. 7. אימות ויזואלי (preview, desktop+mobile).

## הסוכנים + Workflow
```
frontend (port+חיווט+מיתוג+מחיקה) → [ QA ‖ security ] → אימות ויזואלי בלולאה הראשית → checkpoint + push
```
- **frontend** (bizzup-frontend-builder): כל הבנייה; מחזיר קבצים + build נקי.
- **QA** (bizzup-test-runner): typecheck/lint/build, routes/קישורים, רגרסיה.
- **security** (security-scanner): אין סוד, קישורים פנימיים בטוחים, פונט CDN מודע, אין PII.

## אבטחה
דף שיווקי ציבורי — אין tenant data. אין נגיעה ב‑Docker/env/נתונים. הפונטים מ‑Google CDN (מודע; אפשר self-host בעתיד).

## לא בהיקף
שינוי שם הפרויקט ב‑Docker/תיקייה/env · מיתוג ב‑docs/decisions/CLAUDE.md/gateway browser name · המרת הדף ל‑Tailwind.
