# 0026 — מיתוג בוטיק: אייקון ה-B-robot כסמל האתר

> סטטוס: **done** · תאריך: 2026-07-17 · Owner: Omer
> Commits: `e940443`, `d69b20c`, `0c2e84b`
> ממשיך את [`0015-landing-botik-rebrand.md`](0015-landing-botik-rebrand.md).

## מה נבנה

### 1. אסט אחד לכל המקומות
- `e940443` — לוגו בוטיק חדש שקוף ברזולוציה גבוהה (`frontend/public/botik-logo.png`),
  רקע הוסר לגמרי כולל בתוך האותיות; הלוגואים הישנים (`logo.png`, `logo-on-dark.png`) נמחקו.
  שם קובץ חדש נבחר בכוונה כדי לעקוף את ה-cache של הדפדפן.
- `d69b20c` — סימן ה-**B-robot** חולץ מתוך האמנות (הרכיב המחובר הגדול ביותר, רקע הוסר)
  וקיבל **קו מתאר ירוק** כדי שייקרא בגודל של טאב → `frontend/public/botik-icon.png`,
  ומשמש כ-`favicon` וכ-`apple-touch-icon`.
- `0c2e84b` — האייקון **מחליף את ה-wordmark בכל נקודת מותג**: סרגל הדשבורד,
  hero + footer של דף הנחיתה, עמוד התחברות, ועמוד המשפטי. סימן אחד, עקבי.

### 2. חותמת "דמו" על המחירים
בסקשן המסלולים: חותמת **"דמו"** גדולה, מסובבת ומקווקוות על הכותרת + "המחירים להמחשה בלבד"
בתת-כותרת — כדי שתמחור הדמו לא ייקרא כמחיר אמיתי.
(המודל עצמו מתועד ב-[`0020-pricing-tiers.md`](0020-pricing-tiers.md).)

### 3. brand intro צף וממורכז
בראש דף הנחיתה: האייקון עם "הכירו את בוטיק", **ממורכז**, נכנס ב-float-in איטי
(1.9 שניות) עם התחשבות ב-`prefers-reduced-motion`. כפתור ההתחברות נעוץ לפינה.

## קבצים שהשתנו
`frontend/index.html` · `frontend/public/botik-icon.png` + `botik-logo.png` ·
`components/DashboardLayout.tsx` · `components/landing/{HeroSection,Footer,PricingSection,styles}.ts(x)` ·
`pages/{LoginPage,LegalPage}.tsx`

## לא בהיקף
שינוי שמות טכניים (`bizz_up` ב-Docker/תיקייה/env) — כמו בהחלטה 0015, נשארים כפי שהם.
