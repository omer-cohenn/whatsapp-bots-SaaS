# 0010 — M10: צ'אט תמיד-זמין (TTL לפי סטטוס) + הערת תוצאה חובה

> סטטוס: **מאושר, בבנייה** · תאריך: 2026-06-19 · קודם: [0009](0009-m9-lead-outcomes.md), [0008](0008-m8-handoff-chat.md), [0006](0006-redis-live-chat.md).

## ההחלטה
שלושה שינויים סביב הצ'אט הפנימי:
1. **התמליל לא ייעלם כשצריך אותו** — נשאר ב‑Redis (לא Postgres), אבל ה‑TTL נקבע לפי סטטוס השיחה.
2. **כפתור שיחה אחד — פנימי בלבד.** מסירים את כפתור וואטסאפ-ווב החיצוני מכרטיס הליד.
3. **הערת תוצאה חובה** בסגירת פנייה / ביצוע עסקה — נשמרת מוצפנת על הליד.

## החלטות שהתקבלו עם Omer
1. **לא** עוברים ל‑Postgres לתמליל. נשארים ב‑Redis עם **TTL לפי סטטוס** (Omer: "אם ביקשו נציג לשמור ברדיס עד שיענה נציג"). הרחבה: גם `human` נשאר קבוע, ו‑`closed` נשמר 30 יום.
2. הפתק (`outcome_note`) = **חובה** בסגירה/עסקה (אי אפשר לסגור בלי לכתוב משפט).

## מדיניות ה-TTL (conversation_state)
| סטטוס | TTL ב-Redis | למה |
|---|---|---|
| `bot` | 60 דק' מתגלגל (כמו היום) | שיחת בוט פעילה; אם נשתקה — נקייה |
| `waiting` | **PERSIST (ללא תפוגה)** | ביקשו נציג — לא לאבד עד שמישהו עונה |
| `human` | **PERSIST (ללא תפוגה)** | נציג מטפל כרגע |
| `closed` | 30 יום | נסגר — עדיין נצפה, ואז ניקוי אוטומטי |

⚠️ קריטי: היום `append_message` שם תמיד 60 דק' — זה ידרוס PERSIST. לכן ה‑TTL ייקבע במקום מרכזי
(`_apply_ttl(status)`) וגם `set_status` וגם `append_message` יקראו לו לפי הסטטוס הנוכחי.

## מה כבר קיים (לא בונים מחדש)
- תמליל ב‑Redis + סטטוסים — [conversation_state.py](../../backend/app/services/conversation_state.py).
- `set_lead_status` + `PATCH /api/leads/{id}/status` + סטטוסי deal/closed — [leads.py](../../backend/app/services/leads.py), [dashboard.py:109](../../backend/app/api/dashboard.py).
- כפתורי תוצאה בשיחות (M9) ב‑[ConversationCard.tsx](../../frontend/src/components/dashboard/ConversationCard.tsx) ובלידים ב‑[LeadCard.tsx](../../frontend/src/components/dashboard/LeadCard.tsx); הצפנה ב‑[crypto.py](../../backend/app/core/crypto.py).

## הפערים
- `append_message` דורס TTL → צריך מדיניות מרכזית.
- אין עמודת `outcome_note` בטבלת `leads` → מיגרציה.
- כפתור wa.me חיצוני קיים ב‑LeadCard → להסיר.
- כשהתמליל ריק (פג, או ליד ישן) → המסך ריק → צריך נפילה‑רכה (סיכום מהפרטים).

## חוזה (API / data)
| מה | שינוי | שמירה |
|---|---|---|
| `leads.outcome_note` (🔒) | עמודה חדשה (ciphertext) | מיגרציה `0007` |
| `PATCH /api/leads/{id}/status` | גוף: `{status, note?}` (note → outcome_note מוצפן) | endpoint קיים |
| `LeadItem` | + `outcome_note: string \| null` (מפוענח לבעלים) | — |

הכל: שער קיים · `business_id` מהשרת · RLS · בלי PII בלוג.

## ה-Goals
1. **data:** מיגרציה `0007` — `ALTER TABLE leads ADD COLUMN IF NOT EXISTS outcome_note text;` (grants כבר מכסים).
2. **backend:** `_apply_ttl(redis, biz, conv, status)` מרכזי ב‑conversation_state; `set_status` ו‑`append_message` קוראים לו (PERSIST ל‑waiting/human, 60דק' ל‑bot, 30יום ל‑closed) על conv-key + `:log` + index.
3. **backend:** `set_lead_status(..., note=None)` מצפין ל‑`outcome_note`; `LeadStatusRequest` += `note`; ה‑PATCH מעביר note.
4. **backend:** `LeadItem` += `outcome_note` (מפוענח); `list_leads`/`_decrypt_lead_row`/`get_lead_by_conversation` מחזירים אותו.
5. **frontend:** להסיר את כפתור wa.me החיצוני ב‑LeadCard; להשאיר כפתור צ'אט פנימי אחד (בולט).
6. **frontend:** נפילה-רכה בצ'אט — כשאין הודעות, להציג סיכום מ‑`lead.answers` ("פרטים שנאספו") במקום ריק.
7. **frontend:** חלונית פתק **חובה** בסגירה/עסקה (ConversationCard + LeadCard) — טקסט נדרש; שולח `{status, note}`; מציג את הפתק על הכרטיס.
8. **seeder:** `seed_m8_demo.py` — שהשיחות הדמה (waiting/human) יהיו PERSIST; closed עם 30 יום.
9. **QA + security + docs.**

## הסוכנים (5) וה-Workflow
```
data → backend → frontend → QA ‖ security → verify בלולאה הראשית → commit
```
- **data-builder** (G1): מיגרציה 0007 (עמודה אחת).
- **backend-builder** (G2–G4): conversation_state TTL, set_lead_status+note, LeadItem.
- **frontend-builder** (G5–G7): כפתור יחיד, נפילה-רכה, חלונית פתק חובה.
- **test-runner** (G8–G9) + **security-scanner** — במקביל בסוף.
טורי כי backend צריך את העמודה, frontend צריך את ה‑API; QA+אבטחה רק בודקים.

## אבטחה ובידוד (ספציפי ל-M10)
- `outcome_note` מוצפן במנוחה (עלול להכיל פרטי עסקה); מפוענח רק לבעלים, לעולם לא בלוג.
- שינויי ה‑TTL לא נוגעים בבידוד — כל המפתחות נשארים business-prefixed + `_assert_owns`.
- `business_id` מהשרת בלבד.

## תלות וסיכון
אין תלות ב‑M6. סיכון מודע: שיחות `closed`/`waiting` נשמרות ב‑Redis לאורך זמן → צמיחת זיכרון מתונה
(בודד/MVP — זניח; ניקוי אגרסיבי יותר אפשר בעתיד). לידים ישנים שהתמליל שלהם כבר פג מקבלים סיכום-נפילה-רכה.
