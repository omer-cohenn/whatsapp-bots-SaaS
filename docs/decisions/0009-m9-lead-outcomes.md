# 0009 — M9: תוצאות לידים ואיחוד שיחות

> סטטוס: **מאושר, בבנייה** · תאריך: 2026-06-19 · קודם: [0008](0008-m8-handoff-chat.md) (handoff chat), [0006](0006-redis-live-chat.md).

## ההחלטה
לאחד את ה"תוצאה" של פנייה סביב **הליד** כמקור אמת אחד, לשיחות נציג ולשיחות לידים רגילות כאחד:
- בשיחות נציג: להחליף "טופל" בשני כפתורי תוצאה — **"בוצעה עסקה"** (deal) / **"סגירת פנייה"** (closed).
- בדף הלידים: לשנות "הושלמו"→**"ליד שלם"**, ולהוסיף טאבים **"בוצעה עסקה"** ו**"נסגרו"**; כפתור **צ'אט פנימי** בכל ליד.
- כל **מעבר לנציג** יוצר ליד (מינימלי אם צריך) כדי שכל פנייה תופיע באותם טאבים.

## החלטות שהתקבלו עם Omer
1. כפתור השיחה בכרטיס הליד = **צ'אט פנימי באפליקציה** (ChatPanel), לא wa.me. (כפתור wa.me הקיים נשאר.)
2. **כל handoff יוצר ליד מינימלי תמיד** (גם בלי פרטים) → מאחד לידים ושיחות נציג בדף אחד.

## מה כבר קיים (לא בונים מחדש)
- סטטוסי ליד `deal`/`closed` + `set_lead_status` + `PATCH /api/leads/{id}/status` — [leads.py:49](../../backend/app/services/leads.py), [dashboard.py:109](../../backend/app/api/dashboard.py).
- כפתורי "בוצעה עסקה"/"ליד סגור" בכרטיס הליד — [LeadCard.tsx:134](../../frontend/src/components/dashboard/LeadCard.tsx).
- כפתור wa.me בכרטיס הליד — [LeadCard.tsx:121](../../frontend/src/components/dashboard/LeadCard.tsx).
- `ChatPanel` הפנימי (M8) — [ChatPanel.tsx](../../frontend/src/components/dashboard/ChatPanel.tsx).

## הפערים שצריך לסגור
- `GET /api/leads` **לא** מקבל `deal`/`closed` בסינון ([dashboard.py:69](../../backend/app/api/dashboard.py), `list_leads` _REAL_STATUSES).
- מודל הליד **לא** מחזיר `conversation_id` (נחוץ כדי לפתוח צ'אט פנימי מליד). יש `cache_chat_ref = conv:{biz}:{conv}` — נגזור ממנו.
- שיחת נציג ללא פרטים = אין ליד → לא מופיעה בטאבים. נתקן ע"י יצירת ליד מינימלי ב‑handoff.

## הלוגיקה — תוצאה זורמת דרך הליד
| כפתור (UI) | סטטוס ליד | סטטוס שיחה |
|---|---|---|
| בוצעה עסקה | `deal` | `closed` |
| סגירת פנייה | `closed` | `closed` |

בשיחת נציג הכפתור קורא ל‑`PATCH /api/leads/{lead_id}/status` (deal/closed) **וגם** `POST /api/conversations/{id}/status` (closed) — שני endpoints קיימים, בלי חדש.

## חוזה (שינויי API)
| Method | Path | שינוי |
|---|---|---|
| GET | `/api/leads?status=` | להוסיף `deal`,`closed` לערכים המותרים |
| GET | `/api/leads` (payload) | כל פריט ליד מקבל שדה חדש `conversation_id` (נגזר מ‑`cache_chat_ref`, או null) |

הכל: שער קיים · `business_id` מהשרת · RLS · ללא PII בלוג.

## ה-Goals
1. **backend:** `list_leads` + Literal של `GET /api/leads` מקבלים `deal`+`closed` (הוספה לרשימת הסטטוסים הניתנים לסינון).
2. **backend:** ב‑`bot_runtime`, `handed_off` **תמיד** מבטיח ליד — יוצר ליד מינימלי (`lead_name="פנייה לנציג"`, status in_progress) אם אין פעיל, ומקשר אליו את אירוע ה‑handoff.
3. **backend:** מודל `LeadItem` + `_decrypt_lead_row`/`list_leads` מחזירים `conversation_id` (נגזר מ‑`cache_chat_ref` ע"י הסרת הקידומת `conv:{business_id}:`).
4. **frontend types:** `LeadStatusFilter` += `'deal' | 'closed'`; `Lead` += `conversation_id: string | null`.
5. **LeadsPage:** "הושלמו"→**"ליד שלם"**; טאבים חדשים **"בוצעה עסקה"** (deal) + **"נסגרו"** (closed); התאמת KPI.
6. **LeadCard:** כפתור **"צ'אט באפליקציה"** שפותח את `ChatPanel` עבור `lead.conversation_id` (גם בלי טלפון); ה‑wa.me נשאר.
7. **ConversationCard:** להחליף "טופל" בשני כפתורים — **"בוצעה עסקה"**/**"סגירת פנייה"** — שמסמנים את `detail.lead` (deal/closed) **וגם** סוגרים את השיחה.
8. **QA:** סינון deal/closed; תוצאה בשיחת נציג מסמנת ליד+סוגרת שיחה; handoff יוצר ליד; conversation_id מוחזר; בידוד A≠B; רגרסיה M2–M8.
9. **אבטחה:** הסינון/השדה החדש לא פותחים דליפה; `business_id` מהשרת; אין PII בלוג.

## הסוכנים וה-Workflow
```
backend (טורי) → frontend (טורי) → QA ‖ security (במקביל) → verify בלולאה הראשית → commit
```
- **backend-builder** (G1–G3): leads.py, dashboard.py, models/dashboard.py, bot_runtime.py. מחזיר ערכי הסינון + צורת ה‑LeadItem.
- **frontend-builder** (G4–G7): types, LeadsPage, LeadCard, ConversationCard.
- **test-runner** (G8) + **security-scanner** (G9) — במקביל בסוף.

## אבטחה ובידוד (ספציפי ל-M9)
- הסינון החדש נשאר RLS-scoped; `conversation_id` נגזר משדה שכבר שייך לדייר.
- כפתורי תוצאה משתמשים ב‑`PATCH leads/{id}/status` שכבר מחזיר 404 לליד זר.
- אין PII/סודות בלוג; שגיאות גנריות.

## תלות
אין תלות ב‑M6. הצ'אט הפנימי כבר עובד (M8); השליחה לטלפון עדיין תלויה ב‑M6 (תור outbox מוכן).
