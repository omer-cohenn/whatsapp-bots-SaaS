# 0014 — M6a: WhatsApp self-test (self-chat) — full bot loop over the owner's number

> סטטוס: **מאושר, ממתין ל‑go לבנייה** · תאריך: 2026-06-22 · קודם: 0001 (Baileys), 0013 (M6+AWS roadmap).
> שלב ראשון של M6. מטרה: שכל הבוט יעבוד **באמת** דרך WhatsApp עם **מספר אחד** (של Omer) — איסוף לידים נשמר,
> קביעת פגישה שולחת את קישור ה‑`/book/{slug}` האמיתי, מעבר לנציג — והכל מופיע בדשבורד.

## הסיפור (בן 5)
ה‑gateway מחובר כ"מכשיר מקושר" לוואטסאפ של Omer, אז הוא רואה גם את **"הודעה לעצמי"**. Omer כותב לעצמו "היי" →
ההודעה רצה דרך **כל מנוע הבוט** (כמו לקוח אמיתי) → הבוט עונה לו באותו צ'אט. כך מספר אחד מספיק לבדוק הכל.

## החלטות נעולות (Q&A)
1. יעד = **צ'אט‑עם‑עצמי**. חיבור = **QR**.
2. **נתונים אמיתיים** (`is_test=False`) — לידים/פגישות מופיעים רגיל בדשבורד. ה‑webhook **אוכף `is_published`**:
   הבוט עונה **רק אם הבוט מפורסם** (כמו לקוח אמיתי). → Omer מפרסם את הבוט פעם אחת.

## חוזה קפוא (frozen — מאפשר בנייה מקבילה)
- **payload נכנס** (gateway→webhook): השדות הקיימים + `self_test: bool`, `conversation_id: str` (= jid הצ'אט‑עצמי).
- **תשובת ה‑webhook**: `{ "status": str, "replies": [str, ...] }` (ריק אם לא מפורסם / אין mapping / שתיקה).
- **endpoints (admin, gated /api)**: `GET /api/whatsapp/status` → `{linked, connected, phone, gateway_status}` ·
  `POST /api/whatsapp/link` → רושם business↔gateway_account_id+phone, מחזיר status · `GET /api/whatsapp/qr` → `{status, qr_data_url|null}` (proxy לשער).
- `gateway_account_id` = `'spike'` (קבוע, M6a). `GATEWAY_BASE_URL` פנימי (ברירת מחדל `http://gateway:3000`).

## הזרימה + מניעת לולאה
1. השער מזהה צ'אט‑עצמי: `jidNormalizedUser(remoteJid) === jidNormalizedUser(sock.user.id)`.
2. מסמן `self_test`, שולח ל‑webhook. ה‑backend: resolve business → אם `is_published` → `run_turn(is_test=False, conversation_id)` → מחזיר `{replies}`. אחרת `replies=[]`.
3. השער שולח כל reply חזרה לאותו jid.
4. 🔴 **מניעת לולאה:** תשובת הבוט = "הודעה ממך". השער שומר **סט של message_id ששלח** ומדלג עליהם ב‑`messages.upsert` (דילוג רגיל על `fromMe` נשאר לכל שאר הצ'אטים).

## אבטחה ובידוד
`X-Gateway-Token` נשאר (constant-time, 401 על טוקן שגוי). business מזוהה **בשרת בלבד** דרך `whatsapp_connections`.
טלפון מוצפן. אין טקסט/טלפון/טוקן בלוג. endpoints מאחורי השער + business מהסשן. ⚠️ Baileys לא רשמי — מספר לא קריטי.

## הסוכנים (5) + מטרות (9±2 לכל אחד)

### 🟢 סוכן 1 — gateway (Node) — 9
1. לחשב את ה‑jid העצמי פעם אחת (`jidNormalizedUser(sock.user.id)`).
2. זיהוי צ'אט‑עצמי: `normalize(remoteJid) === normalize(own)`.
3. לטפל בהודעות צ'אט‑עצמי גם כש‑`fromMe` (שאר הצ'אטים — להמשיך לדלג).
4. **מניעת לולאה:** סט של `message_id` שנשלחו (cap ~200) — לדלג על upsert שה‑id שלו בסט.
5. לבנות payload עם `self_test=true` + `conversation_id=remoteJid` + text/type.
6. POST ל‑webhook עם `X-Gateway-Token`; לקרוא את ה‑JSON שחוזר.
7. לשלוח כל reply דרך `sock.sendMessage(remoteJid,{text})` בסדר; לרשום כל id שנשלח בסט.
8. עמידות: טקסט ריק → דלג; שגיאות בלוג בטוח, הסוקט שורד; reconnection ללא שינוי.
9. לא לשבור התנהגות לצ'אטים רגילים (עדיין forward ack-only, בלי self_test).

### ⚙️ סוכן 2 — backend (Python) — 10
1. `models/webhook.py`: + `self_test`, `conversation_id`.
2. `services/whatsapp.py` (חדש): `get_connection_by_account` + `upsert_connection` (whatsapp_connections, טלפון מוצפן, RLS).
3. `models/whatsapp.py` (חדש): status/link shapes.
4. `api/webhook.py`: auth+redacted נשאר; על `self_test` → resolve business → אם מפורסם `run_turn(is_test=False, conversation_id)` אחרת `replies=[]` → להחזיר `{status, replies}`.
5. אכיפת `is_published` (קריאה דרך `bot_settings`) — שתיקה אם לא מפורסם.
6. `api/whatsapp.py` (gated): `GET /status`, `POST /link` (mapping מהסשן + account id + phone מהשער), `GET /qr` (proxy).
7. `config`: `GATEWAY_BASE_URL`; אם צריך — להוסיף לשער `/info` (account id + phone + status) שה‑backend יקרא.
8. למאונט את הראוטר תחת `/api` (me.py).
9. business מהסשן בלבד; tenant_connection; טלפון מוצפן; אין PII/טוקן בלוג.
10. להחזיר את החוזה המדויק.

### 🎨 סוכן 3 — frontend — 8
1. `whatsappClient.ts` (getStatus/link/getQr) + types.
2. פריט ניווט "וואטסאפ" + route `/whatsapp` (AuthGate).
3. `WhatsAppPage`: סטטוס (מחובר + טלפון) או QR+הוראות אם מנותק.
4. כפתור "חבר" → POST link.
5. תזכורת **"פרסמו את הבוט"** + הוראת בדיקה ("שלחו לעצמכם הודעה והבוט יענה").
6. polling לסטטוס; שגיאות ידידותיות.
7. RTL + jsx-a11y + ערכת UI.
8. typecheck/lint/build נקי.

### 🚦 סוכן 4 — QA — 9
1. סטאק+מיגרציות+seed+health. 2. webhook `self_test` מדומה (טוקן + mapping זרוע, בוט מפורסם) → מחזיר replies מ‑run_turn. 3. שיחת ליד מלאה מדומה → **ליד אמיתי נשמר** + מופיע ב‑`/api/leads`. 4. flow פגישה → ה‑reply מכיל קישור `/book/{slug}` אמיתי. 5. בוט **לא מפורסם** → `replies=[]` (שתיקה). 6. account לא ממופה → ack, בלי replies, בלי קריסה. 7. מניעת‑לולאה (לוגיקת השער). 8. בידוד + `X-Gateway-Token` (401). 9. רגרסיה M2–M11.2 + `.bat` + STATUS.

### 🔐 סוכן 5 — security — 6
1. token constant-time + 401. 2. business בשרת בלבד; אין הרצת בוט של דייר אחר. 3. אין PII/טקסט/טלפון/טוקן בלוג (gateway+backend). 4. endpoints gated + business מהסשן; proxy QR לא דולף בין דיירים. 5. טלפון מוצפן at-rest. 6. verdict + findings.

## ה‑Workflow (מקבילי ככל האפשר)
החוזה **קפוא מראש** (למעלה), לכן 3 סוכני הבנייה רצים **במקביל** (קבצים נפרדים: gateway/ · backend/app · frontend/src — אין התנגשות):
```
[ gateway ‖ backend ‖ frontend ]  →  [ QA ‖ security ]  →  אימות בלולאה הראשית → checkpoint
```
החסם היחיד: בנייה לפני בדיקה (QA/security רק קוראים). ממצאים חוזרים לסוכן האחראי עד ירוק.

## אימות
- אוטומטי: בדיקות הסוכן QA (לעיל) + רגרסיה.
- בלולאה הראשית: restart gateway+backend; לוודא שהשער מקושר (אחרת QR בעמוד); לרשום mapping לעסק של Omer; checkpoint.
- ידני (Omer): **לפרסם את הבוט** → לפתוח "הודעה לעצמי" → לשלוח "היי" → הבוט מנהל שיחה, אוסף ליד/שולח קישור פגישה; לראות בדשבורד.

## לא ב‑M6a (→ M6b, 0013)
ריבוי‑סוקטים לכל עסק · מפתחות מוצפנים במסד (כרגע דיסק) · ריקון תורי outbox · קוד 8 תווים · rate‑limit · הסרת כלי dev.
