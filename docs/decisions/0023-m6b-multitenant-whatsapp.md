# 0023 — M6b: WhatsApp רב-דיירי (סוקט לכל עסק + מפתחות מוצפנים במסד)

> סטטוס: **done · אומת חי** · תאריך: 2026-07-16 · Owner: Omer
> Commits: `ac28651` (M6b), `6a4b674` (Bad-MAC / logout recovery), `24841be` (follow-ups)
> ממשיך את [`0013-whatsapp-multitenant-and-aws-roadmap.md`](0013-whatsapp-multitenant-and-aws-roadmap.md)
> ואת [`0014-m6a-whatsapp-self-test.md`](0014-m6a-whatsapp-self-test.md).

## הסיפור

עד M6b היה **סוקט Baileys אחד** לכל המערכת, וה-creds ישבו כקבצים לא-מוצפנים ב-`gateway/auth/`
(`gateway_account_id = 'spike'`). זה עבד לעסק אחד בלבד — כלומר לא מוצר.
ב-M6b כל עסק מקבל **סוקט משלו**, וה-creds שלו נשמרים **מוצפנים במסד** במקום על הדיסק.

## מה נבנה

### 1. סוקט אחד לכל עסק
- `gateway/src/manager.js` — מנהל הסשנים: מסנכרן מול ה-backend כל **15 שניות**
  (מתחיל סשנים חדשים, עוצר סשנים שהוסרו).
- `gateway/src/session.js` — מחזור החיים של סוקט בודד: זיהוי self-chat, reconnect עם
  exponential backoff, שליחות מסודרות (serialized) עם rate-limit, ו-logout → relink אוטומטי (QR חדש).
- `gateway/src/socket.js` (הספייק החד-דיירי) **נמחק**.

### 2. ה-creds כ-blob אחד מוצפן ב-DB
- `gateway/src/dbAuthState.js` — ה-auth state של Baileys נשמר כ**מעטפה אחת** (blob),
  בכתיבות debounced, דרך ה-backend. **ה-gateway לא מחזיק שום מפתח הצפנה ושום קובץ.**
- `gateway/src/internalApi.js` — ערוץ הבקרה gateway→backend.
- Backend: `backend/app/api/internal_wa.py` — API פנימי `/internal/wa/*` מאחורי
  `X-Gateway-Token`: רשימת סשנים, load/save של ה-auth_state המוצפן (KEK תכשיט-הכתר,
  טבלת `whatsapp_credentials`), סטטוס per-business, ו-QR.
- הגישה ל-`whatsapp_credentials` היא **רק** דרך ה-pool החדש של `gateway_role`
  (`app.state.gw_pool`) — ל-`app_role` אין שום grant על הטבלה. ה-KEK לעולם לא יוצא מה-backend.

### 3. QR לכל עסק
ה-QR נשמר ב-Redis תחת `wa:qr:{business_id}` עם TTL קצר. **`gateway_account_id = business_id`**
(במקום `'spike'`) — בM6b כל עסק *הוא* החשבון שלו. ה-frontend הפך את זרימת החיבור:
כפתור "התחבר" **קודם** יוצר את הסשן, ואז מופיע ה-QR של אותו עסק.

### 4. השומר: מספר אחד = עסק אחד
כשעסק מדווח "connected", ה-backend בודק `wa_phone_conflict()` לפי **HMAC של הטלפון**
(`whatsapp_connections.phone_hmac`, בלי טקסט גלוי). עסק שני שסורק מספר שכבר מקושר —
**נדחה, מנותק (logout), ורואה שגיאת `phone_conflict`** מפורשת ב-UI.

### 5. חוסן (commit `6a4b674`)
- **Bad-MAC auto-recovery** — זיהוי כשל פענוח (CIPHERTEXT stub) ב-`messages.upsert`,
  וניקוי ה-Signal session **של אותו איש קשר בלבד**, כך שההודעה הבאה שלו מנהלת סשן טרי.
- **getMessage resend cache** — cache חסום-גודל של הודעות יוצאות, כדי לענות לבקשת resend
  של הנמען במקום להחזיר `undefined`.
- **logout (401)** → מחיקת ה-auth המת + restart של הסוקט → QR טרי אוטומטית.
- **stale_handoff_sweep** ב-backend: סוגר יזומה כל שיחה פתוחה ששקטה מעבר לסף (שעה).

### 6. ניקוי דלתות dev
`routes.js` חושף עכשיו רק `/healthz` + `/send-bot` (token-gated, מקבל `business_id`).
הוסרו `/qr`, `/qr.json`, `/info`, `/inbox`, `/send` הלא-מאומתים.

## שינויי DB
- **`0026_whatsapp_multitenant_sessions.sql`** — RLS של תכשיט-הכתר נאכף מחדש על
  `whatsapp_credentials` (`gateway_role` בלבד) + `wa_list_sessions()` SECURITY DEFINER
  (מחזירה **מזהי עסקים בלבד**).
- **`0027_wa_phone_conflict.sql`** — `whatsapp_connections.phone_hmac` + `wa_phone_conflict()` SECURITY DEFINER.

## Contract (API)

| Method | Path | תיאור |
|---|---|---|
| `GET/PUT` | `/internal/wa/*` | ערוץ פנימי לשער (`X-Gateway-Token`): sessions / creds / status / QR |
| `GET` | `/api/whatsapp/status` | סטטוס החיבור של העסק מה-session |
| `GET` | `/api/whatsapp/qr` | ה-QR של העסק (מ-`wa:qr:{business_id}`) |
| `POST` | `/api/whatsapp/link` | "התחל סשן" — יוצר את שורת החיבור שהשער עושה לה poll |
| `POST` | `/send-bot` (gateway) | שליחה יוצאת, עכשיו עם `business_id` |

`send_outbound(business_id, to, text)` — שולח על הסוקט של העסק הנכון (3 ארגומנטים; חתימת M6a.2 עודכנה).

## אימות
`backend/tests/strict/test_m6b_wall.py` — **12 בדיקות, כל שש תכונות ה-WALL ירוקות**:
(a) בידוד תכשיט-הכתר (B לא קורא/מעדכן/מזייף את שורת A), (b) נעילת `app_role`
(`insufficient_privilege` על כל נגיעה), (c) `wa_list_sessions()` חושפת מזהי עסקים בלבד,
(d) `/internal/wa/*` בלי טוקן / עם טוקן שגוי → 401 שטוח, (e) round-trip + הצפנה-במנוחה
(ה-plaintext לא נמצא ב-bytes הגולמיים), (f) בידוד QR per-business.

**אומת חי:** שני עסקים קושרו במקביל עם creds מוצפנים נפרדים; הסשן שרד restart של השער
**בלי סריקה מחדש** (ה-creds נטענו מה-DB); קישור כפול של אותו מספר זוהה ונדחה.

## Consequences
- הדרישה מ-[`0002-multi-tenant-required.md`](0002-multi-tenant-required.md) מתקיימת עכשיו גם בערוץ WhatsApp.
- ה-gateway הפך חסר-מצב על הדיסק — אפשר להרים/להוריד אותו בחופשיות (חשוב לפרודקשן).
- מגבלה מכוונת: מספר WhatsApp אחד יכול לשרת **עסק אחד בלבד**.
