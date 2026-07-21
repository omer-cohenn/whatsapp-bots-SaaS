# חוזה ה-API של העמוד העסקי (M20)

> סטטוס: **סגור** · תאריך: 2026-07-21 · Owner: Omer
> מממש את [`0028-m20-business-page.md`](../decisions/0028-m20-business-page.md) — שלבים 2–5.
> **זה המסמך שסוכני ה-frontend (C ו-D) בונים מולו.** אין צורך לקרוא את ה-Python.

---

## 1. תמונת מצב בשורה אחת

שני משאבים: **הגדרות העמוד** (טקסט, קישורים, ערכת צבעים) שיושבות על `booking_settings`,
ו**גלריית התמונות** — רשומות ב-`business_images`, כשהקבצים עצמם על **דיסק השרת**
ומוגשים סטטית ע"י Caddy. FastAPI לא מגיש תמונות בפרודקשן.

| # | נקודה | גישה |
|---|---|---|
| 1 | `GET /api/booking/page` | בעלים (session) |
| 2 | `PUT /api/booking/page` | בעלים (session) |
| 3 | `POST /api/booking/images` | בעלים (session) · multipart |
| 4 | `PATCH /api/booking/images/{id}` | בעלים (session) |
| 5 | `DELETE /api/booking/images/{id}` | בעלים (session) |
| 6 | `GET /api/book/{slug}/page` | **פומבי** — בלי session |

**הלקוח לעולם לא שולח `business_id`.** בנקודות 1–5 הוא נגזר מה-session בשרת,
ובנקודה 6 מה-`slug`. שליחת `business_id` בגוף בקשה תיפול על 422.

---

## 2. כתובת התמונה — `/media/{storage_path}`

כל רשומת תמונה מחזירה `storage_path` **יחסי**, בפורמט
`{business_id}/{uuid}.{jpg|png|webp}`. ה-URL להצגה נבנה ב-frontend:

```ts
const src = `/media/${image.storage_path}`;
// דוגמה: /media/aaaaaaaa-aaaa-.../3710890f-f581-41e5-aa96-5c4bb88cb702.png
```

* **אותו נתיב בדיוק ב-dev ובפרודקשן.** בפרודקשן Caddy מגיש את הקובץ מהדיסק
  (`infra/Caddyfile`); ב-dev, שבו אין reverse proxy, ה-backend מגיש את אותו
  `/media/*` דרך `StaticFiles` — רק כדי שהגלריה לא תיראה שבורה בפיתוח.
* ה-API **לא** מחזיר URL מלא, במכוון: כך אפשר להחליף דומיין בלי מיגרציית נתונים.
* הקבצים **חסינים לשינוי** — עריכה = מחיקה + העלאה מחדש, ולכן ה-URL נשמר עם
  `Cache-Control: public, max-age=2592000, immutable`. אין צורך ב-cache-buster.
* אין רשימת תיקיות: `/media/{business_id}/` מחזיר 404, לא enumeration.

---

## 3. הצורות (types)

```ts
// שורה אחת בגלריה — כפי שהבעלים רואה אותה
type BusinessImage = {
  id: string;                 // uuid
  storage_path: string;       // "{business_id}/{uuid}.png"  →  /media/{storage_path}
  caption: string | null;     // כיתוב קצר, עד 120 תווים
  sort_order: number;         // סדר תצוגה, 0..10000
  mime_type: string | null;   // "image/jpeg" | "image/png" | "image/webp"
  size_bytes: number | null;
  created_at: string | null;  // ISO-8601 UTC
};

// אותה תמונה כפי שמבקר אנונימי רואה אותה — שלושה שדות בלבד
type PublicBusinessImage = {
  id: string;
  storage_path: string;
  caption: string | null;
};
```

---

## 4. `GET /api/booking/page` — הגדרות העמוד + הגלריה

**תגובה `200`:**

```json
{
  "slug": "Yh3kQ2mBw9Ls",
  "business_name": "Avi Insurance",
  "tagline": "מספרה שכונתית",
  "about": "עובדים מ-2010",
  "address": "הרצל 10 תל אביב",
  "phone": "03-1234567",
  "whatsapp": "972501234567",
  "instagram_url": "https://instagram.com/demo",
  "waze_url": null,
  "logo_url": null,
  "page_theme": { "palette": "ocean" },
  "images": [
    {
      "id": "49714ebc-b9c3-4963-8834-47c1debdc532",
      "storage_path": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/3710890f-....png",
      "caption": "תספורת פייד",
      "sort_order": 0,
      "mime_type": "image/png",
      "size_bytes": 73,
      "created_at": "2026-07-21T08:36:25.559442+00:00"
    }
  ],
  "updated_at": "2026-07-21T08:35:18.869969+00:00"
}
```

* **קריאה ראשונה יוצרת את השורה ואת ה-slug** — תמיד יש קישור פומבי להציג.
* `images` מגיע **בסדר התצוגה**: `sort_order` עולה, ותיקו נשבר לפי `created_at`.
* `business_name` נקרא מטבלת `businesses` ולא נערך כאן.
* `page_theme` הוא אובייקט JSON **חופשי לחלוטין** שה-frontend מגדיר וקורא;
  ה-backend שומר ומחזיר אותו בלי לפרש. `{}` = ברירת המחדל. אפשר לשנות את
  מבנה הערכה בלי שום שינוי ב-backend.
* בלי session → `401`.

---

## 5. `PUT /api/booking/page` — עדכון חלקי

**גוף הבקשה (כל השדות אופציונליים):**

```jsonc
{
  "tagline":       "string | null",   // עד 160
  "about":         "string | null",   // עד 2000
  "address":       "string | null",   // עד 240
  "phone":         "string | null",   // עד 40
  "whatsapp":      "string | null",   // עד 40
  "instagram_url": "string | null",   // עד 500, חייב להתחיל ב-http:// או https://
  "waze_url":      "string | null",   // עד 500, אותו כלל
  "logo_url":      "string | null",   // עד 500, אותו כלל
  "page_theme":    {}                 // אובייקט חופשי; null מאפס ל-{}; ראה למטה
}
```

**התגובה זהה בדיוק ל-`GET /api/booking/page`** (כולל `images`), כך שאפשר לרענן
את כל המסך מתשובת ה-PUT בלי קריאה נוספת.

### 🔑 הכלל היחיד שחייבים להבין כאן

| מה שולחים | מה קורה |
|---|---|
| המפתח **לא נשלח בכלל** | העמודה **לא נגעה** |
| המפתח נשלח עם `null` | העמודה **מתאפסת** |
| המפתח נשלח עם `""` | מנורמל ל-`null` (= מתאפסת) |

זה לא פרט טכני — זו הדרך היחידה **להסיר כפתור מההירו**. כלל המוצר הוא
"שדה ריק ⇒ הכפתור לא מוצג" (decision 0028), ולכן `{"phone": null}` הוא מה
שמוחק את כפתור החיוג. `PUT` ששולח רק `{"about": "..."}` לא נוגע בשום שדה אחר.

**שגיאות:**

| מצב | קוד |
|---|---|
| `instagram_url`/`waze_url`/`logo_url` שאינו `http(s)` (למשל `javascript:`) | `422` |
| שדה שלא ברשימה (למשל `slug`, `business_name`) | `422` — `extra="forbid"` |
| חריגה ממגבלת אורך | `422` |
| בלי session | `401` |

> `slug` ושם העסק **server-owned** ואינם מתקבלים כאן בכלל.
> `javascript:` נחסם כי שלושת הקישורים האלה נרנדרים כ-`href`/`src` בעמוד פומבי.

---

## 6. `POST /api/booking/images` — העלאת תמונה

`multipart/form-data`:

| שדה | סוג | חובה |
|---|---|---|
| `file` | הקובץ | ✔ |
| `caption` | טקסט, עד 120 תווים | ✖ |

```ts
const fd = new FormData();
fd.append("file", file);
fd.append("caption", "תספורת פייד");
await fetch("/api/booking/images", { method: "POST", body: fd, credentials: "include" });
```

**תגובה `201`: אובייקט `BusinessImage` בודד** (לא מעטפת).

* `sort_order` **לא מתקבל בהעלאה** — תמונה חדשה נוחתת תמיד **בסוף** הגלריה
  (`max(sort_order)+1`), והסידור נעשה ב-`PATCH`.
* שם הקובץ שהדפדפן שולח **נזרק לגמרי**. השם על הדיסק הוא `uuid4` שאנחנו
  מייצרים, והסיומת נגזרת מהסוג ש**זוהה מהבייטים**. אין שום דרך להשפיע עליו.

**שגיאות:**

| מצב | קוד | `detail` |
|---|---|---|
| כבר יש 40 תמונות | `422` | `"אפשר להעלות עד 40 תמונות. מחקו תמונה קיימת כדי להוסיף חדשה."` |
| הקובץ גדול מ-5MB | `413` | `"התמונה גדולה מדי (עד 5MB לתמונה)"` |
| לא JPG/PNG/WEBP לפי **התוכן** | `415` | `"אפשר להעלות רק תמונות מסוג JPG, PNG או WEBP"` |
| קובץ ריק | `422` | `"הקובץ ריק"` |
| בלי session | `401` | — |

> **ה-`detail` בעברית ומיועד להצגה ישירה למשתמש.** הוא לעולם לא מכיל טקסט
> שהלקוח שלח (לא שם קובץ, לא כיתוב), ולכן בטוח להציג אותו כמו שהוא.
>
> **תקרת ה-40 נאכפת בשרת**, נספרת ב-DB תחת RLS. בדיקה ב-UI היא נוחות בלבד —
> חסימה ב-frontend לא מונעת מהשרת לדחות, ולהפך.
>
> **הסינון לפי תוכן ולא לפי הצהרה:** `.html` ששונה שמו ל-`photo.png` עם
> `Content-Type: image/png` נדחה ב-415. גם SVG נדחה (יכול לשאת `<script>`),
> וגם GIF ו-PDF. אין הסתמכות על הסיומת או על מה שהדפדפן הצהיר.

---

## 7. `PATCH /api/booking/images/{id}` — כיתוב וסדר

```jsonc
{
  "caption":    "string | null",  // עד 120; null מוחק את הכיתוב
  "sort_order": 0                 // 0..10000
}
```

**תגובה `200`: אובייקט `BusinessImage` מעודכן.**

* אותו כלל השמטה-מול-null כמו ב-`PUT /page`: `caption` שלא נשלח נשאר כמו שהוא,
  `caption: null` מוחק אותו.
* `sort_order` הוא int רגיל — השמטה = לא לגעת.
* **סידור מחדש:** שלחו ערך **ייחודי** לכל תמונה (0,1,2,…). שתי תמונות עם אותו
  `sort_order` יסודרו לפי `created_at`, מה שייראה כמו סידור "שלא נתפס".
  הדרך הנכונה לגרירה היא לשלוח PATCH לכל תמונה שהמיקום שלה השתנה.
* `id` שאינו של העסק הזה → **`404`** (לא 403 — 403 היה מאשר שה-id קיים אצל
  מישהו אחר).

---

## 8. `DELETE /api/booking/images/{id}`

**תגובה `204`, ללא גוף.** מוחק את הרשומה **וגם את הקובץ מהדיסק**.
`id` זר או שכבר נמחק → `404`. הפעולה **בלתי הפיכה** — אין סל מיחזור ואין גיבוי.

---

## 9. `GET /api/book/{slug}/page` — העמוד הפומבי

**בלי session, בלי cookie, בלי `business_id`.** ה-tenant נפתר מה-slug.

**תגובה `200`:**

```json
{
  "business_name": "Avi Insurance",
  "tagline": "מספרה שכונתית",
  "about": "עובדים מ-2010",
  "address": "הרצל 10 תל אביב",
  "phone": null,
  "whatsapp": "972501234567",
  "instagram_url": "https://instagram.com/demo",
  "waze_url": null,
  "logo_url": null,
  "page_theme": { "palette": "ocean" },
  "images": [
    {
      "id": "49714ebc-b9c3-4963-8834-47c1debdc532",
      "storage_path": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/3710890f-....png",
      "caption": "תספורת פייד"
    }
  ]
}
```

* **אלה 11 השדות. אין אחרים.** אין `slug`, אין `updated_at`, אין הגדרות הזמנה,
  אין שעות עבודה, אין מונים, ואין שום מידע על לקוחות. זו רשימה סגורה, ומודל
  נפרד לגמרי מזה של הבעלים — כדי שעמודה חדשה שתתווסף בעתיד לא תדלוף לכאן בטעות.
* `images` בסדר התצוגה; כל תמונה = `id` + `storage_path` + `caption` בלבד.
* slug לא קיים → `404` עם `{"detail": "page not found"}`.
* ה-endpoint הזה **לא מחליף** את `GET /api/book/{slug}/services` — השירותים
  והברכה ממשיכים להגיע משם. העמוד הפומבי קורא לשניהם.

### כלל ארבעת הכפתורים (decision 0028)

```
waze_url      → כפתור Waze
instagram_url → כפתור Instagram
phone         → כפתור חיוג   (tel:)
whatsapp      → כפתור WhatsApp
```

**`null` ⇒ הכפתור לא מרונדר בכלל.** לא מעומעם, לא מושבת — פשוט לא קיים.

---

## 10. מה השתנה בחוזה קיים — ⚠️ שינוי שובר

**`services.image_url` נמחקה.** השדה `image_url` **הוסר** מכל הצורות הבאות:

* `GET /api/services` · `POST /api/services` · `PATCH /api/services/{id}`
* `GET /api/book/{slug}/services`

שליחת `image_url` ב-POST/PATCH של שירות מחזירה עכשיו **422** (`extra="forbid"`).
הגלריה מחליפה את הפיצ'ר. ה-frontend חייב להסיר את השדה מהעורך ומכרטיס השירות
(`ServicesEditor.tsx`, `BookingFlow.tsx`, `appointmentTypes.ts`, `lib/imageResize.ts`).

---

## 11. מגבלות במספרים

| מה | ערך |
|---|---|
| תמונות לעסק | **40** (נאכף בשרת) |
| גודל תמונה | **5 MB** |
| סוגים מותרים | `image/jpeg`, `image/png`, `image/webp` בלבד |
| כיתוב | 120 תווים |
| tagline / about / address | 160 / 2000 / 240 תווים |
| טלפון / WhatsApp | 40 תווים כל אחד |
| קישורים (instagram/waze/logo) | 500 תווים, `http(s)` בלבד |
| `sort_order` | 0–10000 |
