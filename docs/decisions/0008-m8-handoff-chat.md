# 0008 — M8: צ'אט חי של מעבר לנציג אנושי (in-app)

> סטטוס: **מאושר, בבנייה** · תאריך: 2026-06-19 · קודם: [0006](0006-redis-live-chat.md) (live chat ברדיס), [0007](0007-m5-m7-build-plan.md).

## ההחלטה
לבנות את כל **מערכת הצ'אט הפנימי** של מעבר‑לנציג בתוך האפליקציה: היסטוריית שיחה מלאה, מסך כתיבה
בסגנון WhatsApp (כולל מקלדת אמוג'ים פשוטה), ומסע סטטוסים מלא — **עכשיו**. השליחה האמיתית לטלפון
הלקוח דרך WhatsApp תידלק עם **M6** (שבוע הבא); ה‑`outbox` הקיים כבר מוכן לכך.

## למה עכשיו
ה‑handoff כבר עובד (הבוט מזהה ושותק), השיחות כבר נשמרות ברדיס עם status, ויש כבר תור `outbox`
ב-`append_reply`. חסר רק: **תמליל מלא**, **מסך צ'אט**, **מסע סטטוסים**, ו**נורת התראה**. הכל בתוך
האפליקציה, ניתן להדגמה דרך "נסה אותי" כצד-הלקוח — בלי טלפון אמיתי.

## מודל הסטטוסים (Redis)
היום: `bot` · `human` · `closed`. מוסיפים `waiting`:

| שלט (UI) | key | מי שולט | בוט מדבר? |
|---|---|---|---|
| בוט עונה | `bot` | הבוט | כן |
| המתנה לנציג (חדש) | `waiting` | אף אחד עדיין | **לא** |
| בשיחה עם נציג | `human` | בעל העסק | **לא** |
| טופל | `closed` | — | לא |

מעברים: לקוח מבקש נציג → `bot`→`waiting` (+ אירוע "ביקש נציג" שמדליק נורה) · בעל העסק לוחץ "לשיחה
עם הלקוח" → `waiting`→`human` · "טופל" → `human`→`closed`.
**הבוט שותק ב-`waiting` וגם ב-`human`** (היום רק `human` — תיקון נדרש ב-`bot_runtime`).

## תמליל (Redis, ephemeral, מבודד לפי business_id)
| מה | key | תוכן |
|---|---|---|
| תמליל מלא | `conv:{business}:{conv}:log` | רשימה של `{role, body, at}`; role ∈ customer/bot/owner; חתוך ל-200 (LTRIM) |
| outbox (קיים) | `conv:{business}:{conv}:outbox` | תשובות הנציג שמחכות (M6 ירוקן) |
| מטא (קיים) | `conv:{business}:{conv}` | status, preview, last_activity |

**חשוב:** גם כשהבוט שותק (status=waiting/human), הודעת הלקוח הנכנסת **כן** נכתבת לתמליל — אחרת בעל
העסק לא יראה הודעות חדשות מהלקוח.

## חוזה ה-API (תחת /api, מאחורי השער הקיים)
| Method | Path | תפקיד |
|---|---|---|
| GET | `/api/conversations/{id}` | "פתח שיחה": `{conversation_id, status, lead, messages[]}` — ליד מקושר + תמליל בקריאה אחת |
| GET | `/api/conversations/{id}/messages` | תמליל בלבד (רענון/פולינג): `{conversation_id, messages[]}` |
| POST | `/api/conversations/{id}/reply` | קיים — נרחיב: כותב גם לתמליל (role=owner) |
| POST | `/api/conversations/{id}/status` | קיים — Literal מורחב ל-`waiting` |

כולם: session-gated · `business_id` מהשרת בלבד · `_assert_owns` על מפתח רדיס · בלי לוג תוכן/PII ·
גבולות גודל על reply/message.

## עשרת ה-Goals
1. `append_message` + `get_messages` ב-`conversation_state` (LTRIM 200, מבודד).
2. `STATUS_WAITING` ברשימת הסטטוסים החוקיים.
3. שתיקה ב-`waiting`+`human` ב-`bot_runtime` (+ כתיבת הודעת לקוח לתמליל גם במסלול השקט).
4. handoff → `waiting` + רישום אירוע "ביקש נציג".
5. כתיבת כל הודעה לתמליל (לקוח+בוט ב-`run_turn`, נציג ב-`append_reply`).
6. `get_lead_by_conversation` + `GET /api/conversations/{id}` ו-`.../messages`.
7. שורת אקורדיון בשיחות: סגור=שלט+preview; פתוח=פרטי ליד + כפתור "לשיחה עם הלקוח".
8. `ChatPanel`: בועות WhatsApp (לקוח שמאל/נציג ימין/בוט עדין), תיבת הקלדה+שליחה, פולינג.
9. נורת התראה בבית (שיחות `waiting`) + כפתורי סטטוס ("לשיחה עם הלקוח"/"טופל").
10. מקלדת אמוג'ים פשוטה (לוח קבוע של אמוג'ים נפוצים, בלי ספרייה כבדה).

## הסוכנים וה-Workflow
בנייה **בטור** (כל סוכן מקבל את החוזה מקודמו) → QA ‖ אבטחה **במקביל** (רק קוראים/בודקים) → אני מאמת
ומתקן בלולאה הראשית עד ירוק → checkpoint.

```
backend-services → backend-api → frontend-chat → frontend-list → (QA ‖ security) → verify → commit
```

- **backend-services** (G1–G5 שכבת שירות): conversation_state + bot_runtime + leads.get_lead_by_conversation.
- **backend-api** (G6 שכבת API): dashboard.py endpoints + models; מחזיר shapes מדויקים.
- **frontend-chat** (G8,G10): ChatPanel + EmojiPicker + chat client.
- **frontend-list** (G7,G9): אקורדיון ConversationsPage + נורת בית + כפתורי סטטוס + wiring.
- **QA** (test-runner): תמליל, מעברי סטטוס, שתיקה ב-waiting, **בידוד A≠B**, רגרסיה M2–M7.
- **security** (security-scanner): בידוד endpoints חדשים, אין PII בלוג, גבולות גודל, אין דליפת תמליל.

## אבטחה ובידוד (ספציפי ל-M8)
- כל endpoint חדש מאחורי `current_business`; `business_id` לעולם לא מהנתיב/גוף.
- כל מפתח רדיס חדש (`:log`) עובר `_assert_owns`; התמליל מבודד לחלוטין בין דיירים.
- גבולות גודל על reply ו-message; בלי תוכן הודעה/PII בלוגים; שגיאות גנריות.

## תלות מפורשת
שליחה אמיתית ללקוח = **M6**. עד אז ההודעה נשמרת בתמליל וב-`outbox`; ההדגמה מתבצעת עם "נסה אותי"
כצד-הלקוח.
