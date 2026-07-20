# docs/ — 📚 התיעוד

כל התיעוד החי של Bizz_up: איפה אנחנו, מה החלטנו ולמה, והמפרט המלא. המפה הכללית של הריפו:
[`../STRUCTURE.md`](../STRUCTURE.md).

## מאיפה מתחילים
**תמיד [`STATUS.md`](STATUS.md) קודם** — הקובץ היחיד של "איפה אנחנו / איך ממשיכים", מתעדכן בכל מיילסטון.

## מה יש כאן
```
docs/
├── STATUS.md       # 📍 "איפה אנחנו / איך ממשיכים" — הקובץ הראשון בכל סשן חדש
├── DEPLOY.md       # 🚀 ספר הפעלה לפרודקשן (Lightsail + Caddy + deploy.sh)
├── decisions/      # החלטות ארכיטקטורה/מוצר (0001…0026) — למה בחרנו מה שבחרנו
├── spec/           # המפרט המלא של ה-MVP
├── system-map/     # מפת המערכת המקורית (last_bo) שעליה התבסס השכתוב
├── progress-reports/  # עדכוני התקדמות למנטור
├── prototype/      # אב-טיפוס HTML של הממשק
├── 00_overview.md  # סקירה כללית
├── bugs.md         # באגים שזוהו במערכת המקורית
├── security/       # דוח ההקשחה + פוסטורת הרשת בפרודקשן
└── security-issues.md  # ממצאי אבטחה מהמערכת המקורית
```

### `decisions/`
כל החלטה בקובץ קטן `NNNN-short-title.md` (פורמט: Context / Decision / Why / Consequences).
מ-`0001` (Baileys/QR) עד `0026` (אייקון המותג). זה ה"למה" מאחורי כל בחירה ארכיטקטונית.
האחרונות: `0023` WhatsApp רב-דיירי · `0024` הקשחת אבטחה · `0025` עלייה לאוויר · `0026` מיתוג.

### `spec/`
`roadmap.md` · `mvp-checklist.md` · `build-guide.md` · `architecture.md` · `data-model.md` ·
`bot-config-contract.md` + `roadmap-parts/` (פירוט לכל תחום: backend/frontend/data/whatsapp/infra/security/devops-aws).

### `system-map/`
המיפוי המפורט של המערכת הישנה (`last_bo` + `qr_wa_scanner`) לפני השכתוב — backend-map, frontend-map,
whatsapp-gateway, database-schema, data-flow, architecture, infrastructure.

## איך עובדים עם זה
- מסמכי Markdown בלבד — לקרוא/לערוך כרגיל.
- מסיימים מיילסטון → לעדכן רשומה ב-`STATUS.md` (בסגנון הרשומות הקיימות) + להוסיף `decisions/NNNN-*.md` אם הייתה החלטה.
