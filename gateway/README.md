# gateway/ — 💬 וואטסאפ (Node / Baileys)

שירות Node נפרד שמתחבר לוואטסאפ דרך **Baileys** (ספריית QR לא-רשמית) ומעביר הודעות הלוך-ושוב עם
ה-backend על ערוץ יציב ומאומת. הגייטוויי מכיר `accountId`, **אף פעם לא `business_id`** — ה-backend
מתרגם. כל קובץ נושא שורת הסבר בעברית בראשו. המפה המלאה: [`../STRUCTURE.md`](../STRUCTURE.md).

## התיקיות (השלטים)
```
gateway/src/
├── index.js     # 🛗 הרמה — bootstrap דק: טוען config+logger, מקים express, מחווט ראוטים, מדליק סוקט
├── socket.js    # 🔌 חיבור Baileys + הודעות נכנסות — חיבור/חיבור-מחדש, זיהוי צ'אט-עצמי, מניעת לולאה
├── webhook.js   # 📤 שליחה ל-backend + תשובות — מעביר הודעה נכנסת ושולח את התשובות חזרה לצ'אט
├── routes.js    # 🛣️ מסלולי HTTP — /healthz /info /qr /qr.json /send-bot /inbox /send
├── contract.js  # 📜 חוזה הוובהוק הקפוא gateway→backend (ממופה במקום אחד בלבד)
├── config.js    # 🔐 טעינת הגדרות fail-closed (חייב GATEWAY_API_TOKEN)
└── logger.js    # 📝 לוגר pino (בלי טלפון/טקסט/טוקן)
gateway/auth/    # ⚠️ קבצי ה-session של Baileys — git-ignored, לא נכנס ל-git
```

> פוצל מקובץ-יחיד ארוך (`index.js`) ל-socket/webhook/routes בניקיון M15 — בלי שינוי התנהגות.
> `index.js` נשאר bootstrap דק שמחווט את כולם.

## הנתיב (איך הודעה זורמת)
1. לקוח שולח הודעה בוואטסאפ → `socket.js` קולט (`messages.upsert`).
2. `contract.js` ממפה לפורמט הקפוא `{ gateway_account_id, from, push_name, message_id, timestamp, type, text, raw, conversation_id, self_test? }`.
3. `webhook.js` שולח POST ל-`/webhook/whatsapp` עם header `X-Gateway-Token`.
4. ה-backend מריץ את הבוט ומחזיר תשובות → `webhook.js` מקליד אותן חזרה לצ'אט.

## הרצה
חלק מהסטאק: `run.bat` מהשורש מרים אותו עם השאר.
* `GET http://127.0.0.1:3000/qr` — עמוד ה-QR לסריקה (DEV-only).
* `GET /healthz` — בדיקת חיים (בלי QR/סוד).
* `/inbox` · `/send` — כלי דב לראות/לשלוח הודעות (DEV-only — לנעול לפני פרודקשן).

הרצה ישירה:
```bash
cd gateway && npm install
# צריך GATEWAY_API_TOKEN ו-BACKEND_WEBHOOK_URL ב-env
node src/index.js
```

## חוקים (סיכון חסימה ב-Baileys)
- **כותב יחיד לכל session**; ה-creds — היעד: מוצפנים ב-DB (תכשיט הכתר), לא קבצים גלויים.
- ה-QR **נזרם, לא נשמר**; אימות **header-only**; קצב שליחה שמרני.
- אם ה-socket נתקע (Baileys close 428) → `docker restart` לגייטוויי (בלי סריקת QR מחדש).

החלטה: [`../docs/decisions/0001-whatsapp-baileys-canonical.md`](../docs/decisions/0001-whatsapp-baileys-canonical.md) · roadmap: [`../docs/spec/roadmap-parts/whatsapp.md`](../docs/spec/roadmap-parts/whatsapp.md).
